from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import fitz
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import ExtractionRun, QuestionNode, RubricExtractionCriterion
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

QUESTION_PAPER_EXTRACTION_TYPE = "question_paper"
RUBRIC_EXTRACTION_TYPE = "rubric"

MOCK_EXTRACTION_PROVIDER = "mock"
DISABLED_EXTRACTION_PROVIDER = "disabled"

_NODE_TYPES = {"question", "subquestion", "instruction"}
_ALLOWED_PROVIDERS = {
    MOCK_EXTRACTION_PROVIDER,
    DISABLED_EXTRACTION_PROVIDER,
}
_ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
}
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_MAX_CAPTURE_CHARS = 4000


class DocumentExtractionError(RuntimeError):
    pass


class BridgeUnavailableError(DocumentExtractionError):
    pass


class QuestionNodePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1, max_length=64)
    parent_question_number: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    node_type: Literal["question", "subquestion", "instruction"]
    source_page: int | None = Field(default=None, ge=1)
    source_reference: dict[str, Any] | None = None
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    teacher_confirmed: bool = False


class RubricCriterionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_number: str | None = Field(default=None, max_length=64)
    criterion_label: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    max_marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))

class QuestionPaperExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_nodes: list[QuestionNodePayload] = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)


class RubricExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[RubricCriterionPayload] = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractionProviderResult:
    raw_output: str
    normalized_output: dict[str, Any]
    blockers: list[str]


class DocumentExtractor:
    provider: str

    def extract(
        self, file_path: Path, extraction_type: str, content_type: str
    ) -> ExtractionProviderResult:
        raise NotImplementedError


class DisabledDocumentExtractor(DocumentExtractor):
    provider = DISABLED_EXTRACTION_PROVIDER

    def extract(
        self, file_path: Path, extraction_type: str, content_type: str
    ) -> ExtractionProviderResult:
        raise BridgeUnavailableError(
            "Experimental real extraction is disabled. "
            "Set CODEX_EXTRACTION_ENABLED=true and choose a provider."
        )


class MockDocumentExtractor(DocumentExtractor):
    provider = MOCK_EXTRACTION_PROVIDER

    def extract(
        self, file_path: Path, extraction_type: str, content_type: str
    ) -> ExtractionProviderResult:
        if extraction_type == QUESTION_PAPER_EXTRACTION_TYPE:
            payload = _build_mock_question_payload(file_path, content_type)
        elif extraction_type == RUBRIC_EXTRACTION_TYPE:
            payload = _build_mock_rubric_payload(file_path, content_type)
        else:
            raise DocumentExtractionError(f"Unsupported extraction type: {extraction_type}")
        return ExtractionProviderResult(
            raw_output=json.dumps(payload, indent=2),
            normalized_output=payload,
            blockers=payload.get("blockers", []),
        )


class ProviderDocumentExtractor(DocumentExtractor):
    provider = "gemini"

    def extract(
        self, file_path: Path, extraction_type: str, content_type: str
    ) -> ExtractionProviderResult:
        try:
            adapter = BrainAdapter.from_settings(get_settings())
        except BrainProviderConfigurationError as e:
            raise HTTPException(status_code=503, detail=f"AI provider unavailable: {e}") from e
        pdf_path = str(file_path)
        try:
            if extraction_type == QUESTION_PAPER_EXTRACTION_TYPE:
                ai_result = adapter.extract_questions_from_document(pdf_path)
                result_key = "questions"
                zero_detail = (
                    "AI extracted zero questions. Check the PDF quality or page content."
                )
            elif extraction_type == RUBRIC_EXTRACTION_TYPE:
                ai_result = adapter.extract_rubric_from_document(pdf_path)
                result_key = "criteria"
                zero_detail = (
                    "AI extracted zero rubric criteria. Check the PDF quality or "
                    "page content."
                )
            else:
                raise DocumentExtractionError(f"Unsupported extraction type: {extraction_type}")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=422, detail=f"AI returned malformed JSON: {e}") from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except NotImplementedError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except DocumentExtractionError:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"AI provider unavailable: {e}") from e
        if not ai_result.get(result_key):
            raise HTTPException(status_code=422, detail=zero_detail)
        return ExtractionProviderResult(
            raw_output=json.dumps(ai_result),
            normalized_output=ai_result,
            blockers=ai_result.get("warnings", []),
        )


class HostBridgeCodexDocumentExtractor(DocumentExtractor):
    provider = "host_bridge_codex"

    def __init__(
        self,
        *,
        bridge_command: str = "",
        timeout_seconds: float = 300.0,
        runner=None,
    ) -> None:
        self.bridge_command = bridge_command
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run

    def extract(
        self, file_path: Path, extraction_type: str, content_type: str
    ) -> ExtractionProviderResult:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output:
            output_path = Path(output.name)
        command = shlex.split(self.bridge_command) if self.bridge_command else []
        command += [
            "--input-file",
            str(file_path),
            "--output-file",
            str(output_path),
            "--extraction-type",
            extraction_type,
            "--content-type",
            content_type,
        ]
        result = self.runner(command, timeout=self.timeout_seconds)
        if getattr(result, "returncode", 0) != 0:
            raise DocumentExtractionError("Document extraction bridge failed")
        try:
            raw_output = output_path.read_text(encoding="utf-8")
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise DocumentExtractionError(
                "Document extraction bridge returned malformed JSON"
            ) from exc
        normalized = validate_normalized_output(extraction_type, payload)
        return ExtractionProviderResult(
            raw_output=raw_output,
            normalized_output=normalized,
            blockers=normalized.get("blockers", []),
        )


def allowed_extraction_content_types() -> dict[str, str]:
    return dict(_ALLOWED_CONTENT_TYPES)


def build_document_extractor(
    *, settings: Settings | None = None, requested_provider: str | None = None
) -> DocumentExtractor:
    resolved_settings = settings or get_settings()
    provider = (
        requested_provider
        or resolved_settings.codex_extraction_provider
        or DISABLED_EXTRACTION_PROVIDER
    ).strip()
    if provider == MOCK_EXTRACTION_PROVIDER:
        return MockDocumentExtractor()
    if provider == DISABLED_EXTRACTION_PROVIDER:
        return DisabledDocumentExtractor()
    if provider == "host_bridge_codex":
        if not resolved_settings.codex_extraction_enabled:
            return DisabledDocumentExtractor()
        return HostBridgeCodexDocumentExtractor(
            bridge_command=resolved_settings.codex_extraction_bridge_command,
            timeout_seconds=resolved_settings.codex_cli_timeout_seconds,
        )
    if provider == "gemini":
        return ProviderDocumentExtractor()
    raise DocumentExtractionError(f"Unsupported extraction provider: {provider}")


def validate_normalized_output(extraction_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if extraction_type == QUESTION_PAPER_EXTRACTION_TYPE:
        return QuestionPaperExtractionPayload.model_validate(payload).model_dump(mode="json")
    if extraction_type == RUBRIC_EXTRACTION_TYPE:
        return RubricExtractionPayload.model_validate(payload).model_dump(mode="json")
    raise DocumentExtractionError(f"Unsupported extraction type: {extraction_type}")


def apply_extraction_result(
    db: Session, run: ExtractionRun, result: ExtractionProviderResult
) -> ExtractionRun:
    normalized_output = validate_normalized_output(run.extraction_type, result.normalized_output)
    run.raw_output = result.raw_output
    run.normalized_output = normalized_output
    run.blockers = [str(blocker) for blocker in result.blockers]
    run.error = None
    run.status = "succeeded"
    db.query(QuestionNode).filter(QuestionNode.extraction_run_id == run.id).delete()
    db.query(RubricExtractionCriterion).filter(
        RubricExtractionCriterion.extraction_run_id == run.id
    ).delete()
    if run.extraction_type == QUESTION_PAPER_EXTRACTION_TYPE:
        for node in normalized_output["question_nodes"]:
            db.add(
                QuestionNode(
                    assessment_id=run.assessment_id,
                    extraction_run_id=run.id,
                    question_number=node["question_number"],
                    parent_question_number=node.get("parent_question_number"),
                    label=node["label"],
                    text=node["text"],
                    marks=node.get("marks"),
                    node_type=node["node_type"],
                    source_page=node.get("source_page"),
                    source_reference=node.get("source_reference"),
                    confidence=node.get("confidence"),
                    teacher_confirmed=bool(node.get("teacher_confirmed", False)),
                )
            )
    else:
        for criterion in normalized_output["criteria"]:
            db.add(
                RubricExtractionCriterion(
                    assessment_id=run.assessment_id,
                    extraction_run_id=run.id,
                    question_number=criterion.get("question_number"),
                    criterion_label=criterion["criterion_label"],
                    description=criterion["description"],
                    max_marks=criterion.get("max_marks"),
                    confidence=criterion.get("confidence"),
                    blocker=criterion.get("blocker"),
                    teacher_confirmed=bool(criterion.get("teacher_confirmed", False)),
                )
            )
    db.flush()
    return run


def mark_extraction_run_blocked(run: ExtractionRun, message: str) -> ExtractionRun:
    run.status = "blocked"
    run.error = None
    run.blockers = [message]
    return run


def mark_extraction_run_failed(run: ExtractionRun, message: str) -> ExtractionRun:
    run.status = "failed"
    run.error = message
    run.blockers = []
    return run




def _build_mock_question_payload(file_path: Path, content_type: str) -> dict[str, Any]:
    lines = _extract_text_lines(file_path, content_type)
    nodes: list[dict[str, Any]] = []
    for page_no, line in lines:
        match = re.match(
            r"^(?P<label>Q\d+(?:\([a-zA-Z0-9]+\))?)\.?(?:\s+|\s*:\s*)(?P<text>.+)$",
            line,
        )
        if not match:
            continue
        label = match.group("label")
        text = match.group("text").strip()
        marks = None
        marks_match = re.search(r"\[(?P<marks>\d+(?:\.\d+)?)\s*marks?\]", text, re.IGNORECASE)
        if marks_match:
            marks = Decimal(marks_match.group("marks")).quantize(Decimal("0.01"))
            text = (text[: marks_match.start()] + text[marks_match.end() :]).strip()
        parent = None
        node_type = "question"
        if "(" in label and label.endswith(")"):
            node_type = "subquestion"
            parent = label.split("(", 1)[0]
        nodes.append(
            {
                "question_number": label,
                "parent_question_number": parent,
                "label": label,
                "text": text,
                "marks": str(marks) if marks is not None else None,
                "node_type": node_type,
                "source_page": page_no,
                "source_reference": {"source_text_excerpt": line[:500]},
                "confidence": "0.80" if marks is not None else "0.65",
                "teacher_confirmed": False,
            }
        )
    if not nodes:
        nodes.append(
            {
                "question_number": "Q1",
                "parent_question_number": None,
                "label": "Q1",
                "text": (
                    "Review uploaded document and confirm extracted question structure "
                    "manually."
                ),
                "marks": None,
                "node_type": "instruction",
                "source_page": 1,
                "source_reference": {"source_text_excerpt": file_path.name},
                "confidence": "0.20",
                "teacher_confirmed": False,
            }
        )
    return {"question_nodes": nodes, "blockers": []}


def _build_mock_rubric_payload(file_path: Path, content_type: str) -> dict[str, Any]:
    lines = _extract_text_lines(file_path, content_type)
    criteria: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^(?P<label>Q\d+(?:\([a-zA-Z0-9]+\))?)\s*[:.-]\s*(?P<text>.+?)\s+(?P<marks>\d+(?:\.\d+)?)\s*marks?\.?$",
        re.IGNORECASE,
    )
    for _page_no, line in lines:
        match = pattern.match(line)
        if not match:
            continue
        criteria.append(
            {
                "question_number": match.group("label"),
                "criterion_label": match.group("label"),
                "description": match.group("text").strip(),
                "max_marks": str(Decimal(match.group("marks")).quantize(Decimal("0.01"))),
                "confidence": "0.80",
                "blocker": None,
                "teacher_confirmed": False,
            }
        )
    if not criteria:
        criteria.append(
            {
                "question_number": None,
                "criterion_label": "teacher-review-required",
                "description": (
                    "Rubric extraction could not confidently link criteria. "
                    "Teacher confirmation required."
                ),
                "max_marks": None,
                "confidence": "0.20",
                "blocker": "Teacher confirmation required",
                "teacher_confirmed": False,
            }
        )
    blockers = [item["blocker"] for item in criteria if item.get("blocker")]
    return {"criteria": criteria, "blockers": blockers}


def _extract_text_lines(file_path: Path, content_type: str) -> list[tuple[int, str]]:
    if content_type == "text/plain":
        return [
            (1, line.strip())
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if content_type == "application/pdf":
        lines: list[tuple[int, str]] = []
        with fitz.open(file_path) as document:
            for page_index, page in enumerate(document, start=1):
                for raw_line in page.get_text("text").splitlines():
                    line = raw_line.strip()
                    if line:
                        lines.append((page_index, line))
        return lines
    return []


def _sanitize(message: str) -> str:
    return _API_KEY_PATTERN.sub("[REDACTED]", message)
