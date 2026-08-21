from __future__ import annotations

import io
from decimal import Decimal

from PIL import Image, ImageDraw

from packages.ocr.coverage import measure_uncovered_ink


def _page(marks: list[tuple[int, int, int, int]], size: tuple[int, int] = (800, 1000)) -> bytes:
    """A white page with black rectangles standing in for handwriting."""
    image = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(image)
    for box in marks:
        draw.rectangle(box, fill=0)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_blank_page_is_reported_as_blank_not_as_unassigned() -> None:
    # Calling an empty page "unassigned content" would train a teacher to
    # ignore the warning that matters.
    coverage = measure_uncovered_ink(_page([]), [])

    assert coverage is not None
    assert coverage.is_blank is True
    assert coverage.ratio == Decimal("0")


def test_ink_fully_inside_a_mapped_region_is_covered() -> None:
    coverage = measure_uncovered_ink(_page([(100, 100, 300, 200)]), [(50, 50, 400, 300)])

    assert coverage is not None
    assert coverage.is_blank is False
    assert coverage.ratio < Decimal("0.01")


def test_an_answer_the_mapper_missed_is_detected() -> None:
    """The case this exists for.

    One answer is boxed, a second is not. The missed one has no region, so no
    per-region check can see it; only ink-versus-coverage can.
    """
    page = _page([(100, 100, 300, 200), (100, 600, 300, 700)])

    coverage = measure_uncovered_ink(page, [(50, 50, 400, 300)])

    assert coverage is not None
    # Both marks are the same size, so about half the ink is unaccounted for.
    assert coverage.ratio > Decimal("0.4")


def test_no_regions_at_all_means_all_ink_is_unassigned() -> None:
    coverage = measure_uncovered_ink(_page([(100, 100, 300, 200)]), [])

    assert coverage is not None
    assert coverage.ratio == Decimal("1")


def test_boxes_are_scaled_when_they_came_from_a_different_render_size() -> None:
    # Boxes recorded against a 1600x2000 render must still line up with an
    # 800x1000 image, or coverage would silently mismatch and report every
    # page as full of unassigned ink.
    page = _page([(100, 100, 300, 200)])

    coverage = measure_uncovered_ink(
        page, [(100, 100, 600, 400)], image_width=1600, image_height=2000
    )

    assert coverage is not None
    assert coverage.ratio < Decimal("0.01")


def test_unreadable_image_bytes_report_unknown_rather_than_zero() -> None:
    # None means "could not tell", which a caller must treat differently from
    # "no uncovered ink" - reporting zero would hide a missed answer.
    assert measure_uncovered_ink(b"not an image", []) is None
