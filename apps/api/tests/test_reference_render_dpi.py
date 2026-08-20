from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.services.local_reference_extraction import (
    DEFAULT_RENDER_DPI,
    LocalReferenceExtractionError,
    LocalReferenceExtractor,
)

# A4 in PDF points.
A4_WIDTH_PT = 595
A4_HEIGHT_PT = 842


def _a4_pdf(path: Path, pages: int = 1) -> Path:
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
        page.insert_text((72, 144), "P(B|L) = 7/12", fontsize=24)
    document.save(path)
    document.close()
    return path


def _size(png_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png_bytes)) as image:
        return image.size


def test_pages_render_at_the_requested_dpi(tmp_path: Path) -> None:
    pdf = _a4_pdf(tmp_path / "reference.pdf")

    rendered = LocalReferenceExtractor().render_pages(pdf, "application/pdf")

    assert len(rendered) == 1
    width, height = _size(rendered[0][1])
    expected_width = A4_WIDTH_PT * DEFAULT_RENDER_DPI / 72
    assert width == pytest.approx(expected_width, rel=0.02)
    assert height > width


def test_the_default_no_longer_downsamples_the_source_scans(tmp_path: Path) -> None:
    """The old fixed Matrix(2, 2) rendered 144 DPI regardless of the source.

    The real reference scans are 146-320 DPI, so that threw away roughly half
    the linear resolution on the handwritten rubric and the typeset solution -
    the two hardest pages to read.
    """
    pdf = _a4_pdf(tmp_path / "reference.pdf")

    default_width, _ = _size(
        LocalReferenceExtractor().render_pages(pdf, "application/pdf")[0][1]
    )
    legacy_width, _ = _size(
        LocalReferenceExtractor().render_pages(pdf, "application/pdf", target_dpi=144)[0][1]
    )

    assert default_width > legacy_width
    assert default_width / legacy_width == pytest.approx(DEFAULT_RENDER_DPI / 144, rel=0.05)


def test_oversized_pages_are_bounded_rather_than_rendered_unbounded(tmp_path: Path) -> None:
    pdf = _a4_pdf(tmp_path / "reference.pdf")

    rendered = LocalReferenceExtractor().render_pages(
        pdf, "application/pdf", target_dpi=4000, max_side_px=1200
    )

    width, height = _size(rendered[0][1])
    assert max(width, height) <= 1200


def test_every_page_is_rendered_in_order(tmp_path: Path) -> None:
    pdf = _a4_pdf(tmp_path / "reference.pdf", pages=3)

    rendered = LocalReferenceExtractor().render_pages(pdf, "application/pdf")

    assert [page_no for page_no, _bytes, _mime in rendered] == [1, 2, 3]
    assert all(mime == "image/png" for _no, _bytes, mime in rendered)


def test_a_nonsense_dpi_is_refused(tmp_path: Path) -> None:
    pdf = _a4_pdf(tmp_path / "reference.pdf")

    with pytest.raises(LocalReferenceExtractionError, match="DPI must be positive"):
        LocalReferenceExtractor().render_pages(pdf, "application/pdf", target_dpi=0)
