from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import fitz
from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.schemas import DraftQuestion
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

QUESTION_PATTERN = re.compile(
    r"^\s*(?:Q\.?\s*|Question\s+)?(?P<number>\d+)[\.)\:]?\s*(?P<text>.*)$",
    re.IGNORECASE,
)
MARK_PATTERNS = (
    re.compile(r"\[(?P<marks>\d+(?:\.\d+)?)\s*marks?\]", re.IGNORECASE),
    re.compile(r"\((?P<marks>\d+(?:\.\d+)?)\)", re.IGNORECASE),
    re.compile(r"(?P<marks>\d+(?:\.\d+)?)\s*marks?\b", re.IGNORECASE),
)
CODEX_QUESTION_PROVIDER = "codex_cli_question_extractor"
MOCK_QUESTION_PROVIDER = "mock"
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")
_MAX_CAPTURE_CHARS = 4000
_JSON_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL
)
_TEXT_PREVIEW_CHARS = 3000


@dataclass(frozen=True)
class QuestionExtractionResult:
    draft_questions: list[DraftQuestion]
    warnings: list[str]

class CodexQuestionExtractionError(RuntimeError):
    pass


class QuestionExtractor(Protocol):
    provider: str

    def extract(self, file_path: Path, content_type: str) -> QuestionExtractionResult: ...

class MockQuestionExtractor:
    provider = MOCK_QUESTION_PROVIDER

    def extract(self, file_path: Path, content_type: str) -> QuestionExtractionResult:
        source_lines = extract_text_lines(file_path, content_type)
        drafts: list[DraftQuestion] = []
        for page_no, line in source_lines:
            match = QUESTION_PATTERN.match(line)
            if not match:
                continue
            question_text, marks = extract_marks(match.group("text").strip())
            question_text = question_text.strip(" -:")
            if not question_text:
                question_text = line.strip()
            drafts.append(
                DraftQuestion(
                    draft_id=f"draft-{len(drafts) + 1}",
                    question_no=match.group("number"),
                    question_text=question_text,
                    model_answer=None,
                    total_marks=marks,
                    confidence=Decimal("0.80") if marks is not None else Decimal("0.65"),
                    source_page=page_no,
                    source_text_excerpt=line.strip()[:500],
                    needs_review=True,
                )
            )
        if drafts:
            return QuestionExtractionResult(draft_questions=drafts, warnings=[])
        fallback_excerpt = source_lines[0][1].strip()[:500] if source_lines else file_path.name
        warnings = []
        if content_type in _IMAGE_CONTENT_TYPES:
            warnings.append(
                "Default mock/simple extraction does not understand image content. "
                "Real Codex extraction must be explicitly enabled."
            )
        return QuestionExtractionResult(
            draft_questions=[
                DraftQuestion(
                    draft_id="draft-1",
                    question_no="1",
                    question_text=(
                        "Review uploaded question paper and enter extracted "
                        "question text."
                    ),
                    model_answer=None,
                    total_marks=None,
                    confidence=Decimal("0.20"),
                    source_page=1,
                    source_text_excerpt=fallback_excerpt,
                    needs_review=True,
                )
            ],
            warnings=warnings,
        )

class CodexQuestionExtractor(QuestionExtractor):
    provider = "codex_cli_question_extractor"

    def __init__(
        self,
        *,
        command: str = "codex",
        model_name: str | None = None,
        which=None,
        runner=None,
        workdir: str | None = None,
        timeout_seconds: float = 300.0,
        sandbox: str = "read-only",
        image_input_enabled: bool = False,
        skip_git_repo_check: bool = False,
        **kwargs: object,
    ) -> None:
        self.command = command
        self.model_name = model_name
        self.which = which or (lambda cmd: cmd)
        self.runner = runner
        self.workdir = workdir
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox
        self.image_input_enabled = image_input_enabled
        self.skip_git_repo_check = skip_git_repo_check

    def extract(self, file_path: Path, content_type: str) -> QuestionExtractionResult:
        if self.runner is None:
            try:
                adapter = BrainAdapter.from_settings(get_settings())
            except BrainProviderConfigurationError as e:
                raise HTTPException(
                    status_code=503, detail=f"AI provider unavailable: {e}"
                ) from e
            try:
                ai_result = adapter.extract_questions_from_document(str(file_path))
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=422, detail=f"AI returned malformed JSON: {e}"
                ) from e
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except NotImplementedError as e:
                raise HTTPException(status_code=503, detail=str(e)) from e
            except Exception as e:
                raise HTTPException(
                    status_code=503, detail=f"AI provider unavailable: {e}"
                ) from e
            if not ai_result.get("questions"):
                raise HTTPException(
                    status_code=422,
                    detail="AI extracted zero questions. Check the PDF quality or page content.",
                )
            return _normalize_provider_result(ai_result)

        pdf_text = "\n".join(line for _page, line in extract_text_lines(file_path, content_type))
        preview = pdf_text[:_TEXT_PREVIEW_CHARS]
        output_path = Path(file_path).with_suffix(".codex.json")
        command = [self.command, "exec", "--output-last-message", str(output_path)]
        if self.model_name:
            command += ["--model", self.model_name]
        help_text = getattr(self.runner([self.command, "exec", "--help"]), "stdout", "")
        if self.skip_git_repo_check and "--skip-git-repo-check" in help_text:
            command.append("--skip-git-repo-check")
        image_supported = "--image" in help_text
        if self.image_input_enabled and content_type in _IMAGE_CONTENT_TYPES and image_supported:
            command += ["--image", str(file_path)]
        prompt = (
            "Extracted text preview from uploaded file:\n\n"
            f"{preview}\n\n"
            "Return ONLY valid JSON with keys questions and warnings."
        )
        try:
            result = self.runner(
                command,
                input=prompt,
                cwd=self.workdir,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexQuestionExtractionError("Codex question extraction timed out") from exc
        if getattr(result, "returncode", 0) != 0:
            message = _sanitize_codex_error(
                getattr(result, "stderr", "")
                or getattr(result, "stdout", "")
                or "Codex extraction failed"
            )
            raise CodexQuestionExtractionError(message)
        raw = output_path.read_text(encoding="utf-8")
        try:
            parsed = _parse_codex_json(raw)
        except ValueError as e:
            raise CodexQuestionExtractionError(str(e)) from e
        return _normalize_codex_result(parsed)


class ProviderQuestionExtractor(CodexQuestionExtractor):
    pass



def _sanitize_codex_error(message: str) -> str:
    sanitized = _API_KEY_PATTERN.sub("[REDACTED]", message)
    sanitized = _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", sanitized)
    return sanitized[:_MAX_CAPTURE_CHARS]


def _parse_codex_json(raw: str) -> dict[str, object]:
    text = raw.strip()
    fenced = _JSON_FENCE_PATTERN.match(text)
    if fenced:
        text = fenced.group("body").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex output must be valid JSON; preview={text[:120]}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            "Codex output schema validation failed: top-level keys: questions, warnings"
        )
    return parsed


def _normalize_provider_result(parsed: dict[str, object]) -> QuestionExtractionResult:
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions:
        raise CodexQuestionExtractionError(
            "Codex output schema validation failed: questions too_short; "
            "top-level keys: questions, warnings"
        )
    converted = []
    for i, q in enumerate(questions, start=1):
        if isinstance(q, dict):
            converted.append(
                {
                    "question_no": q.get("question_no") or q.get("question_number") or str(i),
                    "question_text": q.get("question_text", ""),
                    "model_answer": q.get("model_answer"),
                    "total_marks": q.get("total_marks") or q.get("marks"),
                    "confidence": q.get("confidence", 0.8),
                    "source_page": q.get("source_page", 1),
                    "source_text_excerpt": (
                        q.get("source_text_excerpt") or q.get("question_text", "")
                    ),
                    "needs_review": q.get("needs_review", True),
                }
            )
    return _normalize_codex_result({"questions": converted, "warnings": parsed.get("warnings", [])})


def _normalize_codex_result(parsed: dict[str, object]) -> QuestionExtractionResult:
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions:
        raise CodexQuestionExtractionError(
            "Codex output schema validation failed: questions too_short; "
            "top-level keys: questions, warnings"
        )
    drafts: list[DraftQuestion] = []
    required = {
        "question_no",
        "question_text",
        "total_marks",
        "confidence",
        "source_page",
        "source_text_excerpt",
        "needs_review",
    }
    for i, q in enumerate(questions, start=1):
        if not isinstance(q, dict) or not required.issubset(q.keys()):
            raise CodexQuestionExtractionError("Codex output schema validation failed")
        drafts.append(
            DraftQuestion(
                draft_id=f"draft-{i}",
                question_no=str(q.get("question_no", i)),
                question_text=str(q.get("question_text", "")),
                model_answer=q.get("model_answer"),
                total_marks=q.get("total_marks"),
                confidence=Decimal(str(q.get("confidence", "0.80"))),
                source_page=q.get("source_page"),
                source_text_excerpt=str(q.get("source_text_excerpt", "")),
                needs_review=bool(q.get("needs_review", True)),
            )
        )
    return QuestionExtractionResult(
        draft_questions=drafts, warnings=list(parsed.get("warnings", []))
    )


def build_question_extractor(
    *, settings: Settings | None = None, requested_provider: str | None = None
) -> QuestionExtractor:
    resolved_settings = settings or get_settings()
    provider = (
        requested_provider
        or resolved_settings.question_import_provider
        or MOCK_QUESTION_PROVIDER
    ).strip()
    if provider in {"", MOCK_QUESTION_PROVIDER, "deterministic"}:
        return MockQuestionExtractor()
    if provider == CODEX_QUESTION_PROVIDER:
        if not resolved_settings.codex_question_extraction_enabled:
            raise CodexQuestionExtractionError(
                "Codex question extraction must be explicitly enabled"
            )
        return CodexQuestionExtractor(
            command=resolved_settings.codex_cli_command,
            model_name=resolved_settings.codex_cli_model,
            timeout_seconds=resolved_settings.codex_cli_timeout_seconds,
            sandbox=resolved_settings.codex_cli_sandbox,
            workdir=resolved_settings.codex_cli_workdir,
            image_input_enabled=resolved_settings.codex_cli_image_input_enabled,
            skip_git_repo_check=resolved_settings.codex_cli_skip_git_repo_check,
        )
    if provider == "local_paddle_qwen":
        raise CodexQuestionExtractionError(
            "local_paddle_qwen provider has been removed. "
            "Visual question import will be provided by Qwen3.8."
        )
    raise CodexQuestionExtractionError(f"Unsupported question import provider: {provider}")

def extract_text_lines(file_path: Path, content_type: str) -> list[tuple[int, str]]:
    if content_type == "application/pdf":
        return extract_pdf_lines(file_path)
    return []


def extract_pdf_lines(file_path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document, start=1):
            for raw_line in page.get_text("text").splitlines():
                line = raw_line.strip()
                if line:
                    lines.append((index, line))
    return lines


def extract_marks(text: str) -> tuple[str, Decimal | None]:
    for pattern in MARK_PATTERNS:
        match = pattern.search(text)
        if match:
            marks = Decimal(match.group("marks")).quantize(Decimal("0.01"))
            cleaned = (text[: match.start()] + text[match.end() :]).strip()
            return cleaned, marks
    return text, None
