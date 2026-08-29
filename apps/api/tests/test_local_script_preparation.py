from __future__ import annotations

import io
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import delete
from sqlalchemy.orm import Session

from alembic import command
from app.db.session import SessionLocal
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    Question,
    QuestionNode,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.services.local_script_preparation import (
    PreparedSegment,
    _apply_adjacent_continuation_boundary_fallback,
    _cleaned_whole_image,
    _find_low_ink_page_boundary,
    _stabilize_visual_page_regions,
)
from packages.brain.schemas_qwen38 import VisualPageRegion


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(api_root / "alembic.ini")), "head")
    db = SessionLocal()
    cleanup_models = (
        AuditLog,
        AnswerRegionMapping,
        AnswerRegionSegment,
        AnswerRegion,
        SubmissionPage,
        Submission,
        Rubric,
        QuestionNode,
        Question,
        ExtractionRun,
        Assessment,
        Course,
        User,
    )
    try:
        for model in cleanup_models:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in cleanup_models:
            db.execute(delete(model))
        db.commit()
        db.close()


class RecordingPhaseManager:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def switch(self, phase: str, *, lease_holder_id: str) -> None:
        assert lease_holder_id
        self.events.append(phase)



def test_cleaned_whole_image_removes_red_marker_but_preserves_black_ink(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "marked-answer.png"
    source = Image.new("RGB", (80, 40), "white")
    draw = ImageDraw.Draw(source)
    draw.line((8, 10, 70, 10), fill=(20, 20, 20), width=5)
    draw.line((8, 28, 70, 28), fill=(190, 45, 45), width=5)
    source.save(source_path)

    with Image.open(io.BytesIO(_cleaned_whole_image(source_path))) as cleaned:
        # The helper adds a border and scales the full image for thin-stroke OCR.
        scale = cleaned.width / (source.width + 64)
        black_point = (round((32 + 30) * scale), round((32 + 10) * scale))
        red_point = (round((32 + 30) * scale), round((32 + 28) * scale))
        assert cleaned.getpixel(black_point) < 64
        assert cleaned.getpixel(red_point) > 245


def test_visual_region_hardening_preserves_full_width_shared_setup_and_final_line(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "single-answer.png"
    page = Image.new("RGB", (1200, 1700), "white")
    draw = ImageDraw.Draw(page)
    draw.text((80, 180), "shared givens", fill="black")
    draw.text((700, 1550), "right-side final result", fill="black")
    page.save(page_path)
    region = VisualPageRegion(
        question_label="1(b)(i)",
        bbox=[70, 650, 910, 940],
        continues_from_previous=False,
        continues_to_next=False,
        confidence=Decimal("0.9"),
        warnings=[],
    )

    [stabilized] = _stabilize_visual_page_regions(
        regions=[region],
        image_path=page_path,
        page_id=4,
        page_no=3,
        page_width=page.width,
        page_height=page.height,
    )

    assert stabilized.segment.x == 0
    assert stabilized.segment.width == page.width
    assert stabilized.segment.y == 0
    assert stabilized.segment.y + stabilized.segment.height == page.height
    warnings = " ".join(stabilized.warnings)
    assert "shared givens" in warnings
    assert "full page width" in warnings
    assert "page bottom" in warnings


def test_visual_region_hardening_keeps_a_suspicious_low_continuation_anchor(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "continuation-and-next-part.png"
    Image.new("RGB", (1000, 1000), "white").save(page_path)
    region = VisualPageRegion(
        question_label="1(a)(i)",
        bbox=[100, 350, 900, 700],
        continues_from_previous=True,
        continues_to_next=False,
        confidence=Decimal("0.7"),
        warnings=[],
    )

    [stabilized] = _stabilize_visual_page_regions(
        regions=[region],
        image_path=page_path,
        page_id=2,
        page_no=2,
        page_width=1000,
        page_height=1000,
    )

    # The adjacent-question fallback needs this unassigned top strip to remain
    # visible; blindly extending every alleged continuation would hide it.
    assert stabilized.segment.y > 0


def test_low_ink_boundary_uses_white_gap_without_luminance_overflow(
    tmp_path: Path,
) -> None:
    page_path = tmp_path / "white-gap.png"
    page = Image.new("RGB", (600, 1000), "white")
    draw = ImageDraw.Draw(page)
    # The rough model anchors meet inside this dark answer line. The server
    # must move the separator to the first nearby white rows below it.
    draw.rectangle((20, 380, 580, 425), fill="black")
    page.save(page_path)

    boundary = _find_low_ink_page_boundary(
        image_path=page_path,
        previous_bottom=390,
        next_top=410,
        page_height=page.height,
    )

    assert 426 <= boundary <= 445


def test_adjacent_blank_after_multi_page_answer_gets_uncertain_shared_boundary() -> None:
    first = {
        "question_id": 1,
        "status": "mapped",
        "confidence": "0.8",
        "warnings": [],
    }
    second = {
        "question_id": 2,
        "status": "not_found",
        "confidence": "0.8",
        "warnings": [],
    }
    page_one = PreparedSegment(1, 1, Decimal("0"), Decimal("0"), Decimal("10"), Decimal("10"), [1])
    page_two = PreparedSegment(
        2,
        2,
        Decimal("0"),
        Decimal("50"),
        Decimal("10"),
        Decimal("10"),
        [1],
    )
    prepared = [(first, [page_one, page_two], "first"), (second, [], "")]

    _apply_adjacent_continuation_boundary_fallback(
        prepared,
        {(2, 1): {"text": "end of (i) and visible work for (ii)"}},
        {2: (2, 100, 200)},
    )

    assert prepared[1][0]["status"] == "uncertain"
    assert prepared[1][1] == [page_two]
    assert prepared[1][2] == "end of (i) and visible work for (ii)"
    assert prepared[0][1][-1].block_orders == []
    assert prepared[0][1][-1].height == Decimal("50")
    assert page_two not in prepared[0][1]
    assert "continuation_boundary_inferred_requires_teacher_review" in (
        prepared[1][0]["warnings"]
    )

