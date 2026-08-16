from __future__ import annotations

import io

from PIL import Image, ImageDraw

from app.services.local_ocr_client import OcrBlock
from app.services.ocr_rescue_service import (
    OcrRescueService,
    _looks_like_answer_header,
    _pp_geometry_candidate,
    group_ocr_blocks_into_bands,
)


def test_fraction_components_merge_into_one_band() -> None:
    blocks = [
        {"bbox": [100, 20, 150, 38], "text": "7"},
        {"bbox": [90, 40, 160, 44], "text": "—"},
        {"bbox": [100, 47, 150, 66], "text": "12"},
        {"bbox": [210, 125, 300, 150], "text": "next line"},
    ]

    bands = group_ocr_blocks_into_bands(blocks, max_bands=6)

    assert len(bands) == 2
    assert bands[0][1] <= 20
    assert bands[0][3] >= 66


def test_band_order_and_six_band_ceiling_are_deterministic() -> None:
    blocks = [
        {"bbox": [20, index * 50, 160, index * 50 + 20], "text": str(index)}
        for index in reversed(range(9))
    ]

    first = group_ocr_blocks_into_bands(blocks, max_bands=6)
    second = group_ocr_blocks_into_bands(list(reversed(blocks)), max_bands=6)

    assert first == second
    assert len(first) == 6
    assert [box[1] for box in first] == sorted(box[1] for box in first)


def test_rescue_preprocessing_removes_red_and_preserves_thin_black_bar() -> None:
    source = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(source)
    draw.line((30, 35, 170, 35), fill="black", width=1)
    draw.line((30, 70, 170, 70), fill=(220, 20, 20), width=5)
    raw = io.BytesIO()
    source.save(raw, format="PNG")
    service = object.__new__(OcrRescueService)

    processed = service._preprocess(raw.getvalue(), alternate=False)

    with Image.open(io.BytesIO(processed)) as image:
        scale = image.width / source.width
        black_y = round(35 * scale)
        red_y = round(70 * scale)
        x = round(100 * scale)
        assert image.getpixel((x, black_y)) < 150
        assert image.getpixel((x, red_y)) > 225


def test_answer_headers_are_excluded_without_removing_student_math() -> None:
    assert _looks_like_answer_header("Answer no: 01") is True
    assert _looks_like_answer_header("01(a)") is True
    assert _looks_like_answer_header("01(@)") is True
    assert _looks_like_answer_header("P(x)=7/12") is False


def test_ppocr_stacked_glyphs_become_image_geometry_fraction() -> None:
    blocks = [
        OcrBlock(page=1, order=1, label="text", text="X", bbox=[50, 10, 80, 35]),
        OcrBlock(page=1, order=2, label="text", text="10", bbox=[45, 50, 85, 78]),
    ]

    assert _pp_geometry_candidate(blocks) == r"$\frac{X}{10}$"
