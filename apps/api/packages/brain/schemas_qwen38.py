"""Output schemas for the Qwen3.8 visual transcription provider.

These types are separate from the Qwen3.6 grading schemas in
``llama_cpp_qwen_provider`` to keep the two providers independently evolvable.
Both providers share the application-level ``GradeSuggestionOutput`` schema for
grading output.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FINAL_INTENT_PROMPT_VERSION = "qwen38-final-intent-structured-v2"


class UncertainGlyph(BaseModel):
    """A character or symbol whose identity the model cannot determine with
    confidence.  At least two alternatives must be supplied."""

    model_config = ConfigDict(extra="forbid")

    position_hint: str = Field(
        min_length=1,
        max_length=200,
        description="Free-text description of where in the transcription the glyph appears.",
    )
    alternatives: list[str] = Field(
        min_length=2,
        max_length=6,
        description="Ordered list of plausible alternatives (most-likely first).",
    )

    @model_validator(mode="after")
    def alternatives_must_be_unique(self) -> UncertainGlyph:
        if len(self.alternatives) != len(set(self.alternatives)):
            raise ValueError("alternatives must be unique")
        return self


class EditingMark(BaseModel):
    """One image-grounded cancellation/correction event without copied answer text."""

    model_config = ConfigDict(extra="forbid")

    page_index: int = Field(ge=1)
    bbox: list[int] = Field(min_length=4, max_length=4)
    status: Literal["cancelled", "replacement", "uncertain_correction"]
    position_hint: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def bbox_is_normalized_box(self) -> EditingMark:
        x1, y1, x2, y2 = self.bbox
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
            raise ValueError("editing bbox must be normalized [x1,y1,x2,y2]")
        return self


class VisualTranscriptionOutput(BaseModel):
    """Draft visual transcription produced by ``LlamaCppQwen38VisionProvider``.

    Key invariants
    --------------
    * ``needs_review`` is always ``True`` — this is a draft, never a final
      record.
    * ``draft_text`` contains final-intent Markdown/LaTeX transcribed from the
      image. Deliberately cancelled work is excluded, but surviving student
      mistakes are preserved and never mathematically repaired.
    * ``image_sha256`` is a 64-character lowercase hex string recorded for
      audit purposes.  Raw student image bytes are never logged elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    draft_text: str = Field(
        description=(
            "Verbatim transcription of the handwritten student answer in Markdown/LaTeX. "
            "It is an empty string only when is_blank is true."
        ),
    )
    uncertain_glyphs: list[UncertainGlyph] = Field(
        default_factory=list,
        description="Glyphs the model could not determine unambiguously.",
    )
    editing_marks: list[EditingMark] = Field(default_factory=list)
    cancellation_detected: bool = False
    replacement_detected: bool = False
    uncertain_correction_detected: bool = False
    is_blank: bool = Field(
        description="True if the answer region contains no student writing.",
    )
    is_irrelevant: bool = Field(
        description="True if the writing is clearly not an answer to the question.",
    )
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True] = True
    model_provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    image_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="SHA256 hex digest of the image bytes sent to the model.",
    )
    latency_ms: int = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def blank_contract_is_exact(self) -> VisualTranscriptionOutput:
        if self.is_blank and self.draft_text.strip():
            raise ValueError("blank visual transcriptions must use an empty draft_text")
        if not self.is_blank and not self.draft_text.strip():
            raise ValueError("nonblank visual transcriptions require draft_text")
        statuses = {mark.status for mark in self.editing_marks}
        expected = {
            "cancelled": self.cancellation_detected,
            "replacement": self.replacement_detected,
            "uncertain_correction": self.uncertain_correction_detected,
        }
        if any((status in statuses) != enabled for status, enabled in expected.items()):
            raise ValueError("editing-analysis flags must match editing_marks")
        if self.uncertain_correction_detected and "[unclear correction]" not in self.draft_text:
            raise ValueError("uncertain correction must remain explicit in draft_text")
        return self


class VisualPageRegion(BaseModel):
    """A complete visible answer segment on one rendered script page."""

    model_config = ConfigDict(extra="forbid")

    question_label: str = Field(min_length=1, max_length=128)
    bbox: list[int] = Field(min_length=4, max_length=4)
    continues_from_previous: bool = False
    continues_to_next: bool = False
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bbox_is_normalized_box(self) -> VisualPageRegion:
        x1, y1, x2, y2 = self.bbox
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
            raise ValueError("bbox must be normalized [x1, y1, x2, y2]")
        return self


class VisualPageMappingOutput(BaseModel):
    """Draft page layout from the visual model; always requires teacher review."""

    model_config = ConfigDict(extra="forbid")

    regions: list[VisualPageRegion]
    needs_review: Literal[True] = True
