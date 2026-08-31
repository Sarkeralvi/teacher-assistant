from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.brain.llama_cpp_qwen_provider import QwenReferenceBundlePayload
from packages.brain.schemas_qwen38 import (
    EditingMark,
    UncertainGlyph,
    VisualPageMappingOutput,
    VisualTranscriptionOutput,
)


@dataclass(frozen=True)
class UniversalVisionCompletion:
    payload: dict[str, Any]
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class _VisualTranscriptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_text: str
    uncertain_glyphs: list[UncertainGlyph] = Field(default_factory=list)
    editing_marks: list[EditingMark] = Field(default_factory=list)
    cancellation_detected: bool = False
    replacement_detected: bool = False
    uncertain_correction_detected: bool = False
    requires_thinking_repair: bool = False
    is_blank: bool
    is_irrelevant: bool = False
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = True


_QUESTION_EXTRACTION_PROMPT = """
Extract every gradable question and sub-question from the supplied exam-paper pages.
Return JSON only with keys questions and warnings. Each question needs question_number,
question_text, marks, and sub_questions. Preserve printed numbering exactly. Use marks=0
and add a warning when a mark is unreadable. Never solve or grade anything.
""".strip()

_RUBRIC_EXTRACTION_PROMPT = """
Extract every marking criterion from the supplied rubric pages. Return JSON only with keys
criteria and warnings. Each criterion needs question_number, criterion_text, max_marks, and
sub_criteria. Preserve printed numbering exactly. Never invent missing marks or grade work.
""".strip()


class UniversalVisionProviderMixin:
    """Provider-neutral visual contracts backed by one structured multimodal call.

    Concrete transports implement ``_complete_structured_vision``. Workflow services
    consume the validated application schemas and never need to know whether the
    transport is Gemini, OpenAI-compatible, local, or cloud.
    """

    provider_name: str
    model_name: str

    def _complete_structured_vision(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
        schema_name: str,
        max_tokens: int | None = None,
    ) -> UniversalVisionCompletion:
        raise NotImplementedError

    def extract_questions_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        completion = self._complete_structured_vision(
            prompt=_QUESTION_EXTRACTION_PROMPT,
            images=_pdf_images(pdf_path),
            response_model=None,
            schema_name="question_pdf_extraction",
        )
        if not isinstance(completion.payload.get("questions"), list):
            raise ValueError("Provider response is missing extracted questions")
        return completion.payload

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        completion = self._complete_structured_vision(
            prompt=_RUBRIC_EXTRACTION_PROMPT,
            images=_pdf_images(pdf_path),
            response_model=None,
            schema_name="rubric_pdf_extraction",
        )
        if not isinstance(completion.payload.get("criteria"), list):
            raise ValueError("Provider response is missing rubric criteria")
        return completion.payload

    def map_page_answer_regions(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        question_labels: list[str],
        question_references: list[dict[str, Any]] | None = None,
        open_continuations: list[str] | None = None,
        boundary_verification: bool = False,
    ) -> VisualPageMappingOutput:
        if not question_labels:
            raise ValueError("Finalized question labels are required for visual mapping")
        references = [
            {
                "question_no": str(item.get("question_no") or "").strip(),
                "question_text": str(item.get("question_text") or "").strip(),
            }
            for item in (question_references or [])
            if str(item.get("question_no") or "").strip()
        ]
        prompt = (
            "Map visible student answer segments on this complete script page only to the "
            "supplied finalized labels. Return at most one normalized [x1,y1,x2,y2] union "
            "box per label, using the full writable width and ending immediately before the "
            "next visible part heading. Preserve wrong, partial, crossed-out, and irrelevant "
            "work as physical answer evidence. Do not transcribe, solve, or grade. Set all "
            "results for teacher review. A continuation and a new labeled part on one page "
            "must be separate regions. When uncertain, widen the box and add a warning. "
            + (
                "This is a boundary-verification pass: explicitly find every intervening "
                "part and never merge neighboring parts. "
                if boundary_verification
                else ""
            )
            + "\nFINALIZED LABELS: "
            + json.dumps(question_labels, ensure_ascii=False)
            + "\nFINALIZED QUESTIONS (identity only): "
            + json.dumps(references, ensure_ascii=False)
            + "\nOPEN CONTINUATIONS: "
            + json.dumps(open_continuations or [], ensure_ascii=False)
            + "\nReturn JSON matching this schema exactly: "
            + json.dumps(VisualPageMappingOutput.model_json_schema(), ensure_ascii=False)
        )
        completion = self._complete_structured_vision(
            prompt=prompt,
            images=[(image_bytes, mime_type)],
            response_model=VisualPageMappingOutput,
            schema_name="visual_page_mapping",
        )
        return VisualPageMappingOutput.model_validate(completion.payload)

    def transcribe_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        return self.transcribe_images(
            images=[(image_bytes, mime_type)],
            label=label,
            max_tokens=max_tokens,
        )

    def transcribe_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        prompt = (
            "Transcribe only the visible student writing in these ordered answer-region "
            "images. Preserve every coherent line, mathematical symbol, mistake, crossing "
            "out, and replacement. Never solve, correct, summarize, grade, or use outside "
            "knowledge. Use Markdown/LaTeX. Mark unresolved glyphs explicitly and describe "
            "visible editing marks with normalized page-indexed boxes. An actually empty "
            "region has is_blank=true and an empty draft_text. Every result needs teacher "
            f"review. Canonical label for navigation only: {label}. Return JSON matching: "
            + json.dumps(_VisualTranscriptionDraft.model_json_schema(), ensure_ascii=False)
        )
        return self._transcription_completion(
            prompt=prompt,
            images=images,
            schema_name="visual_transcription",
            max_tokens=max_tokens,
        )

    def repair_transcription_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        rejected_transcript: str,
        source_editing_marks: list[dict[str, Any]] | None = None,
    ) -> VisualTranscriptionOutput:
        prompt = (
            "Reinspect these ordered answer images because a prior evidence transcript was "
            "uncertain. Return a fresh visual transcription, not an edit based on mathematical "
            "correctness. Preserve student mistakes and resolve only what the pixels support. "
            "Keep unresolved writing explicit. Every cancellation or replacement decision "
            "needs a normalized image box and teacher review.\nPRIOR DRAFT:\n"
            + rejected_transcript
            + "\nPRIOR EDIT LOCATIONS:\n"
            + json.dumps(source_editing_marks or [], ensure_ascii=False)
            + "\nReturn JSON matching: "
            + json.dumps(_VisualTranscriptionDraft.model_json_schema(), ensure_ascii=False)
        )
        return self._transcription_completion(
            prompt=prompt,
            images=images,
            schema_name="visual_transcription_repair",
            max_tokens=None,
        )

    def _transcription_completion(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        schema_name: str,
        max_tokens: int | None,
    ) -> VisualTranscriptionOutput:
        if not images:
            raise ValueError("Visual transcription requires at least one image")
        completion = self._complete_structured_vision(
            prompt=prompt,
            images=images,
            response_model=_VisualTranscriptionDraft,
            schema_name=schema_name,
            max_tokens=max_tokens,
        )
        draft = _VisualTranscriptionDraft.model_validate(completion.payload)
        image_hash = hashlib.sha256(b"".join(item[0] for item in images)).hexdigest()
        return VisualTranscriptionOutput.model_validate(
            {
                **draft.model_dump(mode="json"),
                "needs_review": True,
                "model_provider": self.provider_name,
                "model_name": self.model_name,
                "image_sha256": image_hash,
                "latency_ms": completion.latency_ms,
                "prompt_tokens": completion.prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "provider_calls_used": 1,
            }
        )

    def extract_reference_bundle_from_images(
        self,
        *,
        documents: dict[str, list[tuple[bytes, str, int]]],
    ) -> dict[str, Any]:
        images: list[tuple[bytes, str]] = []
        manifest: list[str] = []
        for document_name in ("QUESTION", "SOLUTION", "RUBRIC"):
            for image_bytes, mime_type, page_no in documents.get(document_name, []):
                manifest.append(f"image {len(images) + 1}: {document_name} page {page_no}")
                images.append((image_bytes, mime_type))
        if not images:
            raise ValueError("Reference extraction requires rendered reference pages")
        prompt = (
            "Build one teacher-reviewable reference bundle from the question paper, solution, "
            "and rubric images. Correlate only canonical gradable leaf questions. Preserve "
            "numbering and cite source page numbers. Copy the supplied model answer; never "
            "invent one. Rubric criteria and marks must reconcile exactly. Missing or unclear "
            "evidence must be a blocker, never a guess. Never grade student work.\nIMAGE ORDER:\n"
            + "\n".join(manifest)
            + "\nReturn JSON matching this schema exactly: "
            + json.dumps(QwenReferenceBundlePayload.model_json_schema(), ensure_ascii=False)
        )
        completion = self._complete_structured_vision(
            prompt=prompt,
            images=images,
            response_model=QwenReferenceBundlePayload,
            schema_name="visual_reference_bundle",
        )
        result = QwenReferenceBundlePayload.model_validate(completion.payload).model_dump(
            mode="json"
        )
        result["usage"] = {
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
        }
        return result


def _pdf_images(pdf_path: str) -> list[tuple[bytes, str]]:
    import fitz

    images: list[tuple[bytes, str]] = []
    with fitz.open(pdf_path) as document:
        for page in document:
            images.append((page.get_pixmap(dpi=150).tobytes("jpeg"), "image/jpeg"))
    if not images:
        raise ValueError("Uploaded PDF has no pages")
    return images
