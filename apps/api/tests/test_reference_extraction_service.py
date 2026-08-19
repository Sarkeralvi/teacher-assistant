from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import (
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    RubricExtractionCriterion,
    User,
)
from app.services.reference_extraction_service import (
    ReferenceExtractionError,
    ReferenceExtractionService,
)


class FakePhaseManager:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def switch(self, phase: str) -> None:
        self.phases.append(phase)


class FakeExtractor:
    def __init__(self) -> None:
        self.qwen_calls = 0

    def render_pages(self, file_path: Path, _content_type: str):
        return [(1, f"rendered {file_path.stem}".encode(), "image/png")]

    def extract_reference_bundle(self, documents):
        self.qwen_calls += 1
        assert set(documents) == {"QUESTION", "SOLUTION", "RUBRIC"}
        return {
            "questions": [
                {
                    "question_number": "1(a)",
                    "parent_question_number": "1",
                    "node_type": "subquestion",
                    "question_text": "Calculate the probability.",
                    "model_answer": "Private worked answer from the solution.",
                    "marks": "5.00",
                    "source_question_pages": [1],
                    "source_solution_pages": [1],
                    "source_text_excerpt": "Calculate the probability.",
                    "confidence": "0.90",
                    "criteria": [
                        {
                            "criterion_label": "Method",
                            "description": "Uses the correct probability method.",
                            "max_marks": "3.00",
                            "confidence": "0.90",
                            "source_rubric_pages": [1],
                            "blocker": None,
                        },
                        {
                            "criterion_label": "Answer",
                            "description": "Obtains the correct answer.",
                            "max_marks": "2.00",
                            "confidence": "0.90",
                            "source_rubric_pages": [1],
                            "blocker": None,
                        },
                    ],
                    "blockers": [],
                    "needs_review": True,
                }
            ],
            "warnings": [],
            "usage": {"total_tokens": 100},
        }


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    cleanup = (
        AuditLog,
        FinalGrade,
        GradeSuggestion,
        Rubric,
        Question,
        RubricExtractionCriterion,
        QuestionNode,
        GradingRun,
        ExtractionRun,
        Assessment,
        Course,
        User,
    )
    try:
        for model in cleanup:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in cleanup:
            db.execute(delete(model))
        db.commit()
        db.close()


def seed_run(db: Session, storage_root: Path) -> GradingRun:
    teacher = User(
        name="Teacher",
        email="reference-service@example.test",
        password_hash="not-used",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code="MATH", title="Math")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Assessment",
        assessment_type="exam",
        total_marks="5.00",
        status="draft",
    )
    db.add(assessment)
    db.flush()
    material_dir = storage_root / "uploads" / "grading_runs" / "1"
    material_dir.mkdir(parents=True)
    paths = {}
    for name in ("question", "solution", "rubric"):
        path = material_dir / f"{name}.pdf"
        path.write_bytes(f"%PDF-1.4 {name}".encode())
        paths[name] = path.relative_to(storage_root).as_posix()
    run = GradingRun(
        assessment_id=assessment.id,
        created_by_teacher_id=teacher.id,
        mode="custom_controlled",
        status="materials_uploaded",
        marking_policy="general",
        question_pdf_path=paths["question"],
        solution_pdf_path=paths["solution"],
        rubric_pdf_path=paths["rubric"],
        question_pdf_name="question.pdf",
        solution_pdf_name="solution.pdf",
        rubric_pdf_name="rubric.pdf",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def enabled_settings(storage_root: Path) -> Settings:
    return Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN38_ENABLED=True,
        LOCAL_QWEN38_API_KEY="key-local-test",
        LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=True,
        LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
        LOCAL_STORAGE_ROOT=str(storage_root),
        UPLOADS_DIR=str(storage_root / "uploads"),
        ARTIFACTS_DIR=str(storage_root / "artifacts"),
    )


def test_reference_bundle_runs_with_qwen38_visual_extraction(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    extractor = FakeExtractor()
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=phases,
        extractor_factory=lambda: extractor,
    )

    queued = service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )
    assert queued["status"] == "queued"
    service.run(run.id)

    db_session.expire_all()
    run = db_session.get(GradingRun, run.id)
    assert run is not None
    assert run.reference_extraction_status == "succeeded"
    assert run.reference_ocr_call_count == 3
    assert run.reference_qwen_call_count == 1
    assert extractor.qwen_calls == 1


def test_reference_bundle_detects_material_tampering_before_any_model_call(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    extractor = FakeExtractor()
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=phases,
        extractor_factory=lambda: extractor,
    )
    service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )
    (storage_root / run.question_pdf_path).write_bytes(b"changed")

    service.run(run.id)

    db_session.expire_all()
    run = db_session.get(GradingRun, run.id)
    assert run is not None
    assert run.reference_extraction_status == "failed"
    assert "changed after teacher authorization" in (run.reference_extraction_error or "")
    assert run.reference_ocr_call_count == 0
    assert run.reference_qwen_call_count == 0
    assert phases.phases == []
    assert extractor.qwen_calls == 0


def test_reference_bundle_kill_switch_and_model_alias_are_enforced(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    settings = enabled_settings(storage_root)
    settings.local_reference_extraction_enabled = False
    service = ReferenceExtractionService(
        db_session,
        settings=settings,
        phase_manager=FakePhaseManager(),
        extractor_factory=FakeExtractor,
    )

    with pytest.raises(ReferenceExtractionError, match="disabled"):
        service.create(
            run,
            teacher_id=run.created_by_teacher_id,
            expected_model="qwen3.8-27b-q4km",
        )

    settings.local_reference_extraction_enabled = True
    with pytest.raises(ReferenceExtractionError, match="model alias"):
        service.create(
            run,
            teacher_id=run.created_by_teacher_id,
            expected_model="wrong-model",
        )
