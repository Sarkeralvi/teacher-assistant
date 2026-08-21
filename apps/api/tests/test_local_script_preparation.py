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
)


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

