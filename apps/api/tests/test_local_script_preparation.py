from __future__ import annotations

import io
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
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
from app.services.local_ocr_client import LocalOcrResult
from app.services.local_script_preparation import (
    LocalScriptPreparationService,
    PreparedSegment,
    _apply_adjacent_continuation_boundary_fallback,
    _cleaned_whole_image,
    build_teacher_transcription_choices,
)
from app.services.storage import LocalStorage


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

    def switch(self, phase: str) -> None:
        self.events.append(phase)


class FakeOcrClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        self.events.append("ocr")
        self.calls.append(kwargs)
        return LocalOcrResult.model_validate(
            {
                "request_id": kwargs["request_id"],
                "mode": kwargs["mode"],
                "text": "1(a) The force is 10 N.",
                "normalized_text": "1(a) The force is 10 N.",
                "markdown": "1(a) The force is 10 N.",
                "blocks": [
                    {
                        "page": 1,
                        "order": 1,
                        "label": "text",
                        "text": "1(a) The force is 10 N.",
                        "bbox": [20, 30, 240, 90],
                    }
                ],
                "warnings": [],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "gpu:0",
                "latency_ms": 5,
            }
        )


class FakeQwenAdapter:
    def __init__(self, events: list[str], question_id: int) -> None:
        self.events = events
        self.question_id = question_id
        self.pages: list[dict[str, Any]] = []
        self.questions: list[dict[str, Any]] = []
        self.preparation_inputs: list[dict[str, Any]] = []

    def verify_available_model(self) -> None:
        self.events.append("verify_qwen")

    def map_submission_answers_from_ocr_pages(
        self, *, pages: list[dict[str, Any]], questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.events.append("map_qwen")
        self.pages = pages
        self.questions = questions
        return {
            "mappings": [
                {
                    "question_id": self.question_id,
                    "question_no": "1(a)",
                    "status": "mapped",
                    "block_references": [{"page_no": 1, "block_orders": [1]}],
                    "confidence": "0.91",
                    "warnings": [],
                    "needs_review": True,
                }
            ],
            "warnings": [],
            "usage": {"total_tokens": 50},
        }

    def prepare_student_answers_from_ocr_candidates(
        self, *, answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.events.append("prepare_qwen")
        self.preparation_inputs = answers
        return {
            "answers": [
                {
                    "question_id": self.question_id,
                    "question_no": "1(a)",
                    "status": "prepared",
                    "prepared_text": "The force is 10 N.",
                    "confidence": "0.90",
                    "uncertainties": [],
                    "source_candidate_ids": [
                        answers[0]["ocr_candidates"][0]["id"]
                    ],
                    "needs_review": True,
                }
            ],
            "warnings": [],
            "usage": {"total_tokens": 40},
        }


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
        # The helper adds a 32-pixel border around the original image.
        assert cleaned.getpixel((32 + 30, 32 + 10)) == 0
        assert cleaned.getpixel((32 + 30, 32 + 28)) == 255


def test_teacher_choices_add_focused_and_arithmetic_context_readings() -> None:
    prepared = (
        "Working line\n"
        r"$= \frac{7/12 \times 0.5}{5/12} = \frac{x}{10}$"
    )
    choices = build_teacher_transcription_choices(
        prepared_text=prepared,
        qwen_alternatives=[],
        ocr_candidates=[
            {
                "kind": "focused_final_formula",
                "text": r"$= \frac{7/12 \times 0.5}{5/12} = \frac{x}{10}$",
            }
        ],
    )

    assert any(r"\frac{7}{10}" in choice["text"] for choice in choices)
    assert any(
        choice["source"] == "arithmetic_consistency_suggestion"
        for choice in choices
    )
    assert all(len(choice["sha256"]) == 64 for choice in choices)


def test_teacher_choices_ignore_unrelated_focused_gibberish() -> None:
    choices = build_teacher_transcription_choices(
        prepared_text="Prob. of failure = 0.5.\nAlice conducts the 1st inspection.",
        qwen_alternatives=[],
        ocr_candidates=[
            {
                "kind": "focused_final_formula",
                "text": r"$$ \textcircled{4}0\quad\textcircled{4}i $$",
            }
        ],
    )

    assert choices == []

    numeric_gibberish = build_teacher_transcription_choices(
        prepared_text=r"Working\n= \frac{28}{67}",
        qwen_alternatives=[],
        ocr_candidates=[
            {
                "kind": "focused_final_formula",
                "text": r"=\frac{2\sqrt{8}}{67}\sqrt{400}",
            }
        ],
    )
    assert numeric_gibberish == []

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


def test_full_page_ocr_then_qwen_creates_unconfirmed_draft_mapping(
    db_session: Session,
) -> None:
    teacher = User(
        name="Teacher",
        email="script-preparation@example.com",
        password_hash="unused",
        role="teacher",
    )
    course = Course(teacher=teacher, code="PHY", title="Physics")
    assessment = Assessment(
        course=course,
        title="Pilot",
        assessment_type="exam",
        total_marks=Decimal("5"),
    )
    extraction = ExtractionRun(
        assessment=assessment,
        artifact_file_path="reference.pdf",
        original_filename="reference.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="local_paddle_qwen",
        status="succeeded",
        blockers=[],
    )
    question = Question(
        assessment=assessment,
        question_no="1(a)",
        question_text="Calculate the force.",
        model_answer="The force is 10 N.",
        total_marks=Decimal("5"),
    )
    rubric = Rubric(
        question=question,
        version=1,
        is_active=True,
        rubric_json={
            "total_marks": "5",
            "criteria": [{"id": "answer", "name": "Answer", "max_marks": "5"}],
        },
    )
    node = QuestionNode(
        assessment=assessment,
        extraction_run=extraction,
        question_number="1(a)",
        label="1(a)",
        text="Calculate the force.",
        marks=Decimal("5"),
        node_type="subquestion",
        source_page=1,
        confidence=Decimal("0.9"),
        teacher_confirmed=True,
    )
    submission = Submission(
        assessment=assessment,
        student_identifier="student-1",
        status="ready",
    )
    db_session.add_all(
        [teacher, course, assessment, extraction, question, rubric, node, submission]
    )
    db_session.flush()

    storage = LocalStorage()
    stored_page = storage.page_image_path(submission.id, 1)
    Image.new("RGB", (400, 300), "white").save(stored_page.absolute_path)
    page = SubmissionPage(
        submission=submission,
        page_no=1,
        image_path=stored_page.relative_path,
    )
    db_session.add(page)
    db_session.commit()
    db_session.refresh(submission)

    events: list[str] = []
    ocr = FakeOcrClient(events)
    qwen = FakeQwenAdapter(events, question.id)
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_SCRIPT_PREPARATION_ENABLED=True,
        LOCAL_OCR_ENABLED=True,
        LOCAL_QWEN_ENABLED=True,
        LOCAL_QWEN_API_KEY="local-test-key",
        LOCAL_QWEN_MODEL="qwen3.6-35b-a3b-q4km",
    )
    mappings = LocalScriptPreparationService(
        db_session,
        settings=settings,
        storage=storage,
        ocr_client=ocr,
        qwen_adapter=qwen,  # type: ignore[arg-type]
        phase_manager=RecordingPhaseManager(events),  # type: ignore[arg-type]
    ).prepare(
        submission=submission,
        teacher=teacher,
        expected_model="qwen3.6-35b-a3b-q4km",
        replace_existing=True,
        maximum_ocr_calls=4,
    )

    assert events == [
        "OcrGpu",
        "ocr",
        "Qwen",
        "verify_qwen",
        "map_qwen",
        "OcrGpu",
        "ocr",
        "ocr",
        "ocr",
        "Qwen",
        "verify_qwen",
        "prepare_qwen",
    ]
    assert len(ocr.calls) == 4
    assert ocr.calls[0]["mode"] == "document"
    assert ocr.calls[1]["mode"] == "answer_region"
    assert ocr.calls[2]["mode"] == "answer_region"
    assert ocr.calls[2]["prompt_label"] == "ocr"
    assert ocr.calls[3]["mode"] == "answer_region"
    assert ocr.calls[3]["prompt_label"] == "formula"
    assert qwen.questions[0]["model_answer"] == "The force is 10 N."
    assert qwen.questions[0]["rubric"]["criteria"][0]["id"] == "answer"
    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.mapping_status == "mapped"
    assert mapping.teacher_confirmed is False
    assert mapping.answer_region is not None
    assert mapping.answer_region.manual_answer_text is None
    assert mapping.answer_region.full_answer_confirmed is False
    assert all(segment.confirmed is False for segment in mapping.answer_region.segments)
    assert mapping.source_reference["ocr_draft_text"] == "1(a) The force is 10 N."
    assert mapping.source_reference["model_prepared_answer_text"] == "The force is 10 N."
    assert qwen.preparation_inputs[0]["question_text"] == "Calculate the force."
    assert "model_answer" not in qwen.preparation_inputs[0]
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.event_type == "submission_script_draft_prepared")
    ).one()
    assert "ocr_draft_text" not in str(audit.payload_json)
    assert audit.payload_json["ocr_call_count"] == 4
    assert audit.payload_json["qwen_call_count"] == 2
