"""Shapes a tier-1 OCR engine produces, independent of which engine it is.

Kept close to the surviving ``OcrBlockRead`` schema so a reading can be
persisted without a translation layer, and deliberately not modelled on any one
engine's output so swapping engines does not ripple through the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in pixels of the rendered page."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(self.x2 - self.x1, 0.0)

    @property
    def height(self) -> float:
        return max(self.y2 - self.y1, 0.0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def overlaps_horizontally(self, other: BoundingBox) -> bool:
        return self.x1 < other.x2 and other.x1 < self.x2

    def vertical_gap_to(self, other: BoundingBox) -> float:
        if self.y2 <= other.y1:
            return other.y1 - self.y2
        if other.y2 <= self.y1:
            return self.y1 - other.y2
        return 0.0

    def merged_with(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            x1=min(self.x1, other.x1),
            y1=min(self.y1, other.y1),
            x2=max(self.x2, other.x2),
            y2=max(self.y2, other.y2),
        )

    def padded(self, margin: float) -> BoundingBox:
        return BoundingBox(
            x1=self.x1 - margin,
            y1=self.y1 - margin,
            x2=self.x2 + margin,
            y2=self.y2 + margin,
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass(frozen=True)
class OcrLine:
    """One recognized line.

    ``confidence`` is the engine's own decoding statistic where it reports one.
    It is ``None`` for engines that do not, which callers must handle rather
    than defaulting to a number the engine never produced.
    """

    text: str
    confidence: Decimal | None = None
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class OcrPageReading:
    """One engine's reading of one rendered page, with its provenance."""

    engine: str
    lines: list[OcrLine]
    render_dpi: int
    page_image_sha256: str
    page_width: int
    page_height: int
    engine_version: str | None = None
    engine_model_sha256: str | None = None
    latency_ms: int | None = None
    # Fraction of ink pixels not inside any detected box. The strongest
    # available signal that the detector missed content outright, which no
    # per-line confidence can express because the missed line has no entry.
    uncovered_ink_ratio: Decimal | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def confidences(self) -> list[Decimal]:
        return [line.confidence for line in self.lines if line.confidence is not None]


class TierOneOcrEngine(Protocol):
    """What the pipeline requires of a tier-1 engine, and nothing more.

    Stated as a Protocol so the engine is chosen by measurement rather than by
    import: any reader that returns lines with geometry satisfies this, whether
    it is a CTC recognizer reporting per-line scores or a vision-language model
    reporting none. Callers must therefore treat ``OcrLine.confidence`` as
    genuinely optional.
    """

    def read_page(
        self,
        image_bytes: bytes,
        *,
        render_dpi: int,
        page_width: int,
        page_height: int,
    ) -> OcrPageReading: ...
