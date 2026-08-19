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


class VisualTranscriptionOutput(BaseModel):
    """Draft visual transcription produced by ``LlamaCppQwen38VisionProvider``.

    Key invariants
    --------------
    * ``needs_review`` is always ``True`` — this is a draft, never a final
      record.
    * ``draft_text`` contains verbatim Markdown/LaTeX transcribed from the
      image.  It must not contain grading verdicts or corrections.
    * ``image_sha256`` is a 64-character lowercase hex string recorded for
      audit purposes.  Raw student image bytes are never logged elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    draft_text: str = Field(
        min_length=1,
        description="Verbatim transcription of the handwritten student answer in Markdown/LaTeX.",
    )
    uncertain_glyphs: list[UncertainGlyph] = Field(
        default_factory=list,
        description="Glyphs the model could not determine unambiguously.",
    )
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
    def blank_or_irrelevant_may_have_empty_draft(self) -> VisualTranscriptionOutput:
        if (self.is_blank or self.is_irrelevant) and len(self.draft_text.strip()) == 0:
            raise ValueError(
                "draft_text must have at least one character even for blank/irrelevant answers "
                "(use a sentinel such as '[blank]' or '[irrelevant]')"
            )
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
