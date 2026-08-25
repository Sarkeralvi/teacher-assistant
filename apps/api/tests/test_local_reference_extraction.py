from pathlib import Path

import pytest
from PIL import Image

from app.services.local_reference_extraction import (
    LocalReferenceExtractionError,
    LocalReferenceExtractor,
)


def make_image(path: Path) -> None:
    Image.new("RGB", (80, 60), "white").save(path, format="PNG")


def test_legacy_direct_ocr_entry_point_is_disabled(tmp_path: Path) -> None:
    image_path = tmp_path / "question.png"
    make_image(image_path)
    extractor = LocalReferenceExtractor()

    with pytest.raises(LocalReferenceExtractionError, match="leased PaddleOCR reference workflow"):
        extractor.ocr_pages(image_path, "image/png")
