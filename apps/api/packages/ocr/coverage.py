"""Detect ink that no region accounts for.

The safety net for content a reader missed entirely. A line that was never
detected has no confidence score to be low and no region to escalate, so no
per-line or per-region check can see it -- only comparing where ink IS against
where regions were placed.

This deliberately measures geometry, not text. Recognition on handwriting is
unreliable (94.7% of lines wrong in the bake-off), but *detecting that ink
exists* is a far easier problem, so this stays useful exactly where reading
does not.
"""

from __future__ import annotations

import io
from decimal import Decimal

# Pixels at or below this luminance count as ink. Scans carry grey paper and
# JPEG noise well above pure black, so a mid-grey cut is more robust than a
# strict one.
INK_LUMINANCE_MAX = 128
# Coverage is a ratio, so full resolution buys nothing and costs a lot.
ANALYSIS_MAX_SIDE = 1000


class InkCoverage:
    """Ink totals for one page, and how much of it fell outside known regions."""

    def __init__(self, ink_pixels: int, uncovered_pixels: int) -> None:
        self.ink_pixels = ink_pixels
        self.uncovered_pixels = uncovered_pixels

    @property
    def ratio(self) -> Decimal:
        if self.ink_pixels == 0:
            return Decimal("0")
        return (Decimal(self.uncovered_pixels) / Decimal(self.ink_pixels)).quantize(
            Decimal("0.000001")
        )

    @property
    def is_blank(self) -> bool:
        return self.ink_pixels == 0


def measure_uncovered_ink(
    image_bytes: bytes,
    boxes: list[tuple[float, float, float, float]],
    *,
    image_width: int | None = None,
    image_height: int | None = None,
) -> InkCoverage | None:
    """Fraction of ink pixels lying outside every supplied box.

    ``boxes`` are in the coordinate space of the ORIGINAL image; pass
    ``image_width``/``image_height`` when the boxes came from a differently
    sized render than ``image_bytes``, so they can be scaled correctly rather
    than silently mismatching.

    Returns ``None`` when the image cannot be read, so a callers can treat
    "unknown" differently from "no uncovered ink".
    """
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover - both are hard dependencies
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source_width, source_height = source.size
            grey = source.convert("L")
            grey.thumbnail((ANALYSIS_MAX_SIDE, ANALYSIS_MAX_SIDE))
            analysis = np.asarray(grey)
    except Exception:
        return None

    if analysis.size == 0 or source_width == 0 or source_height == 0:
        return None

    reference_width = image_width or source_width
    reference_height = image_height or source_height
    height, width = analysis.shape[:2]
    scale_x = width / reference_width
    scale_y = height / reference_height

    ink_mask = analysis <= INK_LUMINANCE_MAX
    ink_pixels = int(ink_mask.sum())
    if ink_pixels == 0:
        return InkCoverage(ink_pixels=0, uncovered_pixels=0)

    # Paint covered areas, then count ink outside them. Vectorised: a per-pixel
    # Python loop over a 1000x1000 page against dozens of boxes is tens of
    # millions of operations and made this unusable per page.
    covered = np.zeros_like(ink_mask, dtype=bool)
    for x1, y1, x2, y2 in boxes:
        left = max(int(min(x1, x2) * scale_x), 0)
        right = min(int(max(x1, x2) * scale_x) + 1, width)
        top = max(int(min(y1, y2) * scale_y), 0)
        bottom = min(int(max(y1, y2) * scale_y) + 1, height)
        if right <= left or bottom <= top:
            continue
        covered[top:bottom, left:right] = True

    uncovered_pixels = int((ink_mask & ~covered).sum())
    return InkCoverage(ink_pixels=ink_pixels, uncovered_pixels=uncovered_pixels)
