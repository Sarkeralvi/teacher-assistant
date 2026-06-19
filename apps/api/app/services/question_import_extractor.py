from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import fitz
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings, get_settings
from app.schemas import DraftQuestion

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
_REQUIRED_EXEC_FLAGS = ("--output-last-message", "--cd", "--sandbox")
_IMAGE_FLAGS = ("--image", "-i")
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")
_MAX_CAPTURE_CHARS = 4000
_JSON_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL
)
_TEXT_PREVIEW_CHARS = 3000


class CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., CompletedProcessLike]
Which = Callable[[str], str | None]


class CodexQuestionExtractionError(RuntimeError):
    """Raised when question extraction provider setup or execution fails safely."""


@dataclass(frozen=True)
class QuestionExtractionResult:
    draft_questions: list[DraftQuestion]
    warnings: list[str]


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
                        "Review uploaded question paper and enter extracted question text."
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


class CodexExtractedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(min_length=1, max_length=32)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_page: int = Field(ge=1)
    source_text_excerpt: str = Field(min_length=1)
    needs_review: bool = True

    @field_validator("needs_review")
    @classmethod
    def must_require_teacher_review(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("needs_review must be true")
        return value


class CodexExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[CodexExtractedQuestion] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class CodexQuestionExtractor:
    provider = CODEX_QUESTION_PROVIDER

    def __init__(
        self,
        *,
        command: str = "codex",
        model_name: str = "",
        timeout_seconds: float = 300.0,
        sandbox: str = "read-only",
        use_json: bool = True,
        output_last_message: bool = True,
        image_input_enabled: bool = False,
        skip_git_repo_check: bool = False,
        workdir: str = "/home/newton/teacher-assistant",
        which: Which = shutil.which,
        runner: Runner = subprocess.run,
    ) -> None:
        self.command = command or "codex"
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox or "read-only"
        self.use_json = use_json
        self.output_last_message = output_last_message
        self.image_input_enabled = image_input_enabled
        self.skip_git_repo_check = skip_git_repo_check
        self.workdir = workdir or "/home/newton/teacher-assistant"
        self._which = which
        self._runner = runner
        self._help_text: str | None = None

    def extract(self, file_path: Path, content_type: str) -> QuestionExtractionResult:
        self._preflight()
        with tempfile.TemporaryDirectory(prefix="ta-codex-question-import-") as tmp_dir:
            output_file = Path(tmp_dir) / "last-message.json"
            command = self._build_command(
                output_file=output_file,
                file_path=file_path,
                content_type=content_type,
            )
            prompt = self._build_prompt(file_path=file_path, content_type=content_type)
            try:
                completed = self._runner(
                    command,
                    cwd=self.workdir,
                    capture_output=True,
                    text=True,
                    input=prompt,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexQuestionExtractionError(
                    f"Codex question extraction timed out after {self.timeout_seconds:g}s"
                ) from exc
            if completed.returncode != 0:
                detail = self._sanitize((completed.stderr or completed.stdout or "").strip())
                raise CodexQuestionExtractionError(
                    f"Codex question extraction exited with status {completed.returncode}: "
                    f"{detail[:_MAX_CAPTURE_CHARS]}"
                )
            payload = self._read_json_output(output_file)
        try:
            validated = CodexExtractionPayload.model_validate(payload)
        except ValidationError as exc:
            raise CodexQuestionExtractionError(
                self._schema_error_detail(payload, exc)
            ) from exc
        drafts = [
            DraftQuestion(
                draft_id=f"draft-{index}",
                question_no=question.question_no,
                question_text=question.question_text,
                model_answer=question.model_answer,
                total_marks=question.total_marks,
                confidence=question.confidence,
                source_page=question.source_page,
                source_text_excerpt=question.source_text_excerpt[:500],
                needs_review=True,
            )
            for index, question in enumerate(validated.questions, start=1)
        ]
        return QuestionExtractionResult(draft_questions=drafts, warnings=validated.warnings)

    def _preflight(self) -> None:
        if self._which(self.command) is None:
            raise CodexQuestionExtractionError(f"codex command not found: {self.command}")
        version = self._run_preflight_command([self.command, "--version"], "codex --version")
        if not version.strip():
            raise CodexQuestionExtractionError("codex --version returned no output")
        help_text = self._run_preflight_command(
            [self.command, "exec", "--help"], "codex exec --help"
        )
        self._help_text = help_text
        for flag in _REQUIRED_EXEC_FLAGS:
            if flag not in help_text:
                raise CodexQuestionExtractionError(
                    f"Codex CLI exec does not support required flag {flag}"
                )
        if self.output_last_message is False:
            raise CodexQuestionExtractionError(
                "Codex question extractor requires --output-last-message"
            )
        if self.skip_git_repo_check and "--skip-git-repo-check" not in help_text:
            raise CodexQuestionExtractionError(
                "Codex CLI exec does not support required flag --skip-git-repo-check"
            )
        if self.image_input_enabled and not self._supported_image_flag():
            raise CodexQuestionExtractionError(
                "Codex CLI image input is not supported by this installed version."
            )
        if self.sandbox == "danger-full-access":
            raise CodexQuestionExtractionError(
                "Codex question extractor refuses danger-full-access sandbox"
            )

    def _run_preflight_command(self, command: list[str], label: str) -> str:
        try:
            completed = self._runner(
                command,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=min(self.timeout_seconds, 30),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexQuestionExtractionError(f"{label} timed out") from exc
        if completed.returncode != 0:
            detail = self._sanitize((completed.stderr or completed.stdout or "").strip())
            raise CodexQuestionExtractionError(f"{label} failed: {detail[:_MAX_CAPTURE_CHARS]}")
        return completed.stdout or completed.stderr or ""

    def _build_command(self, *, output_file: Path, file_path: Path, content_type: str) -> list[str]:
        command = [
            self.command,
            "exec",
            "--cd",
            self.workdir,
            "--sandbox",
            self.sandbox,
            "--output-last-message",
            str(output_file),
        ]
        if self.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if self.use_json and self._help_text and "--json" in self._help_text:
            command.append("--json")
        if self.model_name:
            command.extend(["--model", self.model_name])
        if self.image_input_enabled and content_type in _IMAGE_CONTENT_TYPES:
            image_flag = self._supported_image_flag()
            if image_flag is None:
                raise CodexQuestionExtractionError(
                    "Codex CLI image input is not supported by this installed version."
                )
            command.extend([image_flag, str(file_path)])
        return command

    def _supported_image_flag(self) -> str | None:
        help_text = self._help_text or ""
        for flag in _IMAGE_FLAGS:
            if flag in help_text:
                return flag
        return None

    def _read_json_output(self, output_file: Path) -> dict[str, Any]:
        if not output_file.is_file():
            raise CodexQuestionExtractionError("Codex CLI did not write --output-last-message file")
        text = output_file.read_text(encoding="utf-8")
        if not text.strip():
            raise CodexQuestionExtractionError("Codex CLI --output-last-message file was empty")
        json_text = self._strip_markdown_json_fence(text)
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise CodexQuestionExtractionError(
                "Codex CLI output-last-message did not contain exact valid JSON; "
                f"preview={self._sanitize(text.strip())[:500]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise CodexQuestionExtractionError(
                f"Codex CLI JSON output must be an object; got {type(payload).__name__}"
            )
        return payload

    @staticmethod
    def _strip_markdown_json_fence(text: str) -> str:
        match = _JSON_FENCE_PATTERN.match(text)
        if match:
            return match.group("body").strip()
        return text

    def _schema_error_detail(self, payload: dict[str, Any], exc: ValidationError) -> str:
        error_summaries = []
        for error in exc.errors()[:5]:
            location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
            error_summaries.append(f"{location}: {error.get('type')} - {error.get('msg')}")
        keys = ", ".join(sorted(payload.keys())) or "<none>"
        questions = payload.get("questions")
        question_shape = (
            f"questions type={type(questions).__name__}"
            if not isinstance(questions, list)
            else f"questions count={len(questions)}"
        )
        return (
            "Codex question extraction output schema validation failed; "
            f"top-level keys: {keys}; {question_shape}; "
            f"validation errors: {'; '.join(error_summaries)}"
        )

    def _build_prompt(self, *, file_path: Path, content_type: str) -> str:
        image_note = (
            "The uploaded image is attached through the Codex CLI image flag."
            if self.image_input_enabled and content_type in _IMAGE_CONTENT_TYPES
            else (
                "No image bytes are attached. If you cannot access/read the file, "
                "return no invented content and add a warning."
            )
        )
        text_preview = self._uploaded_text_preview(file_path=file_path, content_type=content_type)
        return f"""You are extracting teacher-reviewed draft questions for Teacher Assistant.
Return ONLY valid JSON. Do not write markdown or prose outside JSON.
Do not modify files. Do not ask for approval.
This is draft extraction only; teacher review is mandatory.
Every extracted question MUST set needs_review=true.
If unsure, keep needs_review=true, lower confidence, and add a warning.

Uploaded file path: {file_path}
Uploaded content type: {content_type}
{image_note}

{text_preview}

Detect question numbers and separate questions. Detect simple marks when visible.
Do not create final Questions. Produce only this JSON schema:
{{
  "questions": [
    {{
      "question_no": "1",
      "question_text": "Differentiate y = x^2.",
      "model_answer": null,
      "total_marks": 5,
      "confidence": 0.8,
      "source_page": 1,
      "source_text_excerpt": "Q1. Differentiate y = x^2. [5 marks]",
      "needs_review": true
    }}
  ],
  "warnings": []
}}
"""

    def _uploaded_text_preview(self, *, file_path: Path, content_type: str) -> str:
        if content_type != "application/pdf":
            return "Extracted text preview from uploaded file: unavailable for this content type."
        try:
            lines = extract_text_lines(file_path, content_type)
        except Exception:
            return (
                "Extracted text preview from uploaded file: unavailable; "
                "PDF text extraction failed."
            )
        if not lines:
            return "Extracted text preview from uploaded file: unavailable; no embedded text found."
        rendered = "\n".join(f"page {page}: {line}" for page, line in lines)
        return (
            "Extracted text preview from uploaded file:\n"
            f"{rendered[:_TEXT_PREVIEW_CHARS]}"
        )

    @staticmethod
    def _sanitize(message: str) -> str:
        without_keys = _API_KEY_PATTERN.sub("[REDACTED]", message)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", without_keys)


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
                "Real Codex question extraction must be explicitly enabled."
            )
        return CodexQuestionExtractor(
            command=resolved_settings.codex_cli_command,
            model_name=resolved_settings.codex_cli_model,
            timeout_seconds=resolved_settings.codex_cli_timeout_seconds,
            sandbox=resolved_settings.codex_cli_sandbox,
            use_json=resolved_settings.codex_cli_use_json,
            output_last_message=resolved_settings.codex_cli_output_last_message,
            image_input_enabled=resolved_settings.codex_cli_image_input_enabled,
            skip_git_repo_check=resolved_settings.codex_cli_skip_git_repo_check,
            workdir=resolved_settings.codex_cli_workdir,
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
