from __future__ import annotations

import io

from PIL import Image, ImageDraw

from app.services.local_ocr_client import OcrBlock
from app.services.ocr_rescue_service import (
    OcrRescueService,
    _looks_like_answer_header,
    _looks_like_top_compact_header,
    _pp_geometry_candidate,
    add_missing_projection_bands,
    align_formula_context_rows,
    detect_uncovered_ink_bands,
    fraction_component_ensemble_candidates,
    group_ocr_blocks_into_bands,
    merge_contextual_probability_bands,
    probability_symbol_ensemble_candidates,
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


def test_aligned_probability_rows_do_not_collapse_into_one_fraction() -> None:
    blocks = [
        {"bbox": [100, y, 280, y + 30], "text": text}
        for y, text in zip(
            (20, 70, 120, 170),
            ("P(D)=0.3", "P(W)=0.3", "P(B)=0.4", "P(L|D)=0.03"),
            strict=True,
        )
    ]

    bands = group_ocr_blocks_into_bands(blocks, max_bands=6)

    assert len(bands) == 4


def test_page_rule_projection_is_discarded_and_formula_sliver_is_merged() -> None:
    bands = [[80, 100, 900, 500], [200, 700, 700, 820]]
    projections = [
        [40, 500, 760, 522],  # touching denominator/fraction fragment
        [0, 650, 1000, 676],  # printed full-width page rule
    ]

    result = add_missing_projection_bands(bands, projections, max_bands=6)

    assert result == [[40, 100, 900, 522], [200, 700, 700, 820]]


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
    assert _looks_like_top_compact_header("010", top=20, cutoff=100) is True
    assert _looks_like_top_compact_header("010", top=120, cutoff=100) is False
    assert _looks_like_top_compact_header("0.10", top=20, cutoff=100) is False


def test_ppocr_stacked_glyphs_become_image_geometry_fraction() -> None:
    blocks = [
        OcrBlock(page=1, order=1, label="text", text="X", bbox=[50, 10, 80, 35]),
        OcrBlock(page=1, order=2, label="text", text="10", bbox=[45, 50, 85, 78]),
    ]

    assert _pp_geometry_candidate(blocks) == r"$\frac{X}{10}$"


def test_fraction_component_ensemble_never_uses_arithmetic() -> None:
    candidates = fraction_component_ensemble_candidates(
        r"$\frac{X}{10}$", r"$$ \frac{7}{6} $$"
    )

    assert r"$\frac{7}{10}$" in candidates
    assert r"$\frac{X}{6}$" in candidates
    assert len(candidates) == 3


def test_probability_symbol_ensemble_surfaces_bounded_teacher_choices() -> None:
    candidates = probability_symbol_ensemble_candidates(
        "Odds in favour of Y = 9:11",
        r"$$ P(y)=\frac{y}{20};P(y)=\frac{11}{20} $$",
    )

    assert any(r"P(y)=\frac{9}{20}" in candidate for candidate in candidates)
    assert any(r"P(\overline{y})=\frac{11}{20}" in candidate for candidate in candidates)


def test_whole_formula_rows_align_one_extra_row_to_first_band() -> None:
    rows = align_formula_context_rows(
        r"$$ \begin{align*}a\\&b\\&c\\&d\\&e\end{align*} $$",
        band_count=4,
    )

    assert rows == ["$$ a \\\\ b $$", "$$ c $$", "$$ d $$", "$$ e $$"]


def test_de_morgan_visual_alternative_is_never_auto_selected() -> None:
    candidates = probability_symbol_ensemble_candidates(
        "(ii) P(xny)=P(xuy)",
        r"$$ (i) P(\bar{x}\cap\bar{y})=P(\bar{x}\cup\bar{y}) $$",
    )

    assert any(
        r"(ii) P(\bar{x}\cap\bar{y})=P(\overline{x\cupy})" in candidate
        for candidate in candidates
    )


def test_ink_projection_adds_a_line_ppocr_missed() -> None:
    image = Image.new("L", (300, 180), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 24, 260, 38), fill=0)
    draw.rectangle((20, 117, 260, 133), fill=0)

    boxes = detect_uncovered_ink_bands(
        image,
        covered_boxes=[[10, 20, 270, 45]],
    )

    assert len(boxes) == 1
    assert boxes[0][1] < 125 < boxes[0][3]


def test_odds_context_merges_with_probability_line() -> None:
    blocks = [
        OcrBlock(
            page=1,
            order=1,
            label="text",
            text="odds in favour of X = 7:5",
            bbox=[20, 20, 250, 50],
        ),
        OcrBlock(
            page=1,
            order=2,
            label="text",
            text="P(X)=7/12 and P(X)=5/12",
            bbox=[20, 70, 280, 100],
        ),
    ]

    merged = merge_contextual_probability_bands(
        [[10, 10, 290, 60], [10, 60, 290, 110]], blocks
    )

    assert merged == [[10, 10, 290, 110]]
