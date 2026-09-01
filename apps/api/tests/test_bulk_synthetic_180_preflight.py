from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    BulkEvaluationItem,
    BulkEvaluationRun,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import BulkEvaluationRunRead
from app.services.bulk_evaluation_service import BulkEvaluationService
from app.services.storage import LocalStorage
from packages.brain.capabilities import BrainExecutionLocation
from packages.evaluation.bulk_synthetic_180 import (
    SYNTHETIC_ITEM_COUNT,
    SYNTHETIC_PAGE_COUNT,
    SYNTHETIC_PAGE_READ_CALL_LIMIT,
    SYNTHETIC_SUBMISSION_COUNT,
    build_synthetic_bulk_archive,
)

_CLEANUP = (
    AuditLog,
    BulkEvaluationItem,
    BulkEvaluationRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionOcrRun,
    AnswerRegionMapping,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    QuestionNode,
    ExtractionRun,
    Question,
    GradingRun,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(api_root / "alembic.ini")), "head")
    db = SessionLocal()
    try:
        for model in _CLEANUP:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in _CLEANUP:
            db.execute(delete(model))
        db.commit()
        db.close()


def test_bulk_180_settings_accept_exact_bounds_and_reject_larger_values() -> None:
    exact = Settings(
        _env_file=None,
        BULK_MAX_SUBMISSIONS=180,
        BULK_MAX_PAGES=720,
        BULK_MAX_PROVIDER_CALLS=1800,
    )

    assert exact.bulk_max_submissions == 180
    assert exact.bulk_max_pages == 720
    assert exact.bulk_max_provider_calls == SYNTHETIC_PAGE_READ_CALL_LIMIT

    with pytest.raises(ValidationError):
        Settings(_env_file=None, BULK_MAX_SUBMISSIONS=181)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, BULK_MAX_PAGES=721)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, BULK_MAX_PROVIDER_CALLS=2001)


def test_synthetic_180_preflight_ingests_every_item_into_read_without_provider_calls(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The complete 180-script archive is imported but never dispatched.

    This is deliberately an ingest-only proof. The mocked policy is used only
    to freeze the creation-time page-read branch; ``run_next`` is never called,
    so no visual or grading provider work can occur.
    """

    storage_root = tmp_path / "storage"
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("UPLOADS_DIR", str(storage_root / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(storage_root / "artifacts"))
    get_settings.cache_clear()
    try:
        corpus = build_synthetic_bulk_archive(
            tmp_path / "synthetic-180.zip",
            page_size=(480, 640),
        )
        teacher, assessment, grading_run = _seed_synthetic_references(
            db_session,
            corpus.questions,
        )
        settings = Settings(
            _env_file=None,
            LOCAL_STORAGE_ROOT=str(storage_root),
            UPLOADS_DIR=str(storage_root / "uploads"),
            ARTIFACTS_DIR=str(storage_root / "artifacts"),
            BULK_MAX_SUBMISSIONS=SYNTHETIC_SUBMISSION_COUNT,
            BULK_MAX_PAGES=SYNTHETIC_PAGE_COUNT,
            BULK_MAX_PROVIDER_CALLS=SYNTHETIC_PAGE_READ_CALL_LIMIT,
        )
        service = BulkEvaluationService(
            db_session,
            settings=settings,
            storage=LocalStorage(),
        )
        policy = SimpleNamespace(
            provider="mock",
            model="qwen3.8-27b-q4km",
            page_read_enabled=True,
            location=BrainExecutionLocation.LOCAL,
        )
        monkeypatch.setattr(service, "_assert_enabled", lambda *_args, **_kwargs: policy)

        with corpus.archive_path.open("rb") as source:
            run = service.create_from_zip(
                assessment_id=assessment.id,
                grading_run=grading_run,
                teacher=teacher,
                upload=UploadFile(filename="synthetic-180.zip", file=BytesIO(source.read())),
                expected_model="qwen3.8-27b-q4km",
                marking_policy="general",
                maximum_provider_calls=SYNTHETIC_PAGE_READ_CALL_LIMIT,
                provider="mock",
            )

        assert run.total_submissions == SYNTHETIC_SUBMISSION_COUNT
        assert run.total_pages == SYNTHETIC_PAGE_COUNT
        assert run.total_items == SYNTHETIC_ITEM_COUNT
        assert run.calls_used == 0
        assert run.authorized_call_limit == SYNTHETIC_PAGE_READ_CALL_LIMIT
        assert run.import_manifest["visual_evidence_path"] == "page_read"
        assert len(run.items) == SYNTHETIC_ITEM_COUNT
        assert {item.status for item in run.items} == {"pending"}
        assert {item.stage for item in run.items} == {"read"}
        assert {item.stage for item in BulkEvaluationRunRead.model_validate(run).items} == {"read"}
        assert db_session.scalar(select(func.count(SubmissionPage.id))) == SYNTHETIC_PAGE_COUNT
        assert db_session.scalar(select(func.count(FinalGrade.id))) == 0

    finally:
        get_settings.cache_clear()


def _seed_synthetic_references(
    db: Session,
    questions: tuple[object, ...],
) -> tuple[User, Assessment, GradingRun]:
    teacher = User(
        name="Synthetic Preflight Teacher",
        email="synthetic-preflight@example.invalid",
        password_hash="synthetic-only",
        role="teacher",
    )
    course = Course(teacher=teacher, code="SYN180", title="Synthetic Bulk Preflight")
    assessment = Assessment(
        course=course,
        title="Synthetic 180-script assessment",
        assessment_type="synthetic",
        total_marks=Decimal("24"),
        status="ready",
    )
    grading_run = GradingRun(
        assessment=assessment,
        created_by_teacher=teacher,
        mode="bulk_supervised",
        status="grading_ready",
        marking_policy="general",
        questions_confirmed_at=datetime.now(UTC),
        rubrics_confirmed_at=datetime.now(UTC),
    )
    db.add_all([teacher, course, assessment, grading_run])
    db.flush()
    for specification in questions:
        question = Question(
            assessment_id=assessment.id,
            question_no=specification.question_no,
            question_text=specification.question_text,
            model_answer=specification.model_answer,
            total_marks=Decimal(specification.total_marks),
        )
        db.add(question)
        db.flush()
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                rubric_json=specification.rubric_json,
                is_active=True,
            )
        )
    db.commit()
    return teacher, assessment, grading_run
