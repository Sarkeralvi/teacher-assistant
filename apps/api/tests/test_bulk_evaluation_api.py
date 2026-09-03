from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.routes import bulk_evaluations as bulk_routes
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
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
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.final_grade_service import FinalGradeService

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


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    del db_session
    return TestClient(app)


@pytest.fixture()
def qwen38_policy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("BRAIN_ALLOW_REAL_PROVIDERS", "true")
    monkeypatch.setenv("LOCAL_QWEN38_ENABLED", "true")
    monkeypatch.setenv("LOCAL_QWEN38_API_KEY", "key-local-test")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _teacher_and_run(client: TestClient, label: str) -> tuple[dict[str, object], dict[str, object]]:
    registration = client.post(
        "/auth/register",
        json={
            "name": label,
            "email": f"bulk-{label.casefold()}-{uuid4().hex}@example.invalid",
            "password": "BulkTeacherPassword-123!",
        },
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    course = client.post(
        "/courses",
        headers=_headers(token),
        json={"code": f"BULK-{uuid4().hex[:6]}", "title": "Bulk API test"},
    )
    assert course.status_code == 201
    assessment = client.post(
        f"/courses/{course.json()['id']}/assessments",
        headers=_headers(token),
        json={"title": "Bulk API test", "assessment_type": "quiz", "total_marks": "1"},
    )
    assert assessment.status_code == 201
    run = client.post(
        f"/assessments/{assessment.json()['id']}/grading-runs/custom",
        headers=_headers(token),
        json={"marking_policy": "general"},
    )
    assert run.status_code == 201
    return (
        {"token": token, "user": registration.json()["user"], "assessment": assessment.json()},
        run.json(),
    )


def _fake_create(self: object, **kwargs: object) -> BulkEvaluationRun:
    db = self.db
    grading_run = kwargs["grading_run"]
    teacher = kwargs["teacher"]
    assessment_id = int(kwargs["assessment_id"])
    run = BulkEvaluationRun(
        assessment_id=assessment_id,
        grading_run_id=grading_run.id,
        created_by_teacher_id=teacher.id,
        provider="llama_cpp_qwen38",
        model_name=str(kwargs["expected_model"]),
        marking_policy="general",
        policy_version="bulk-supervised-qwen38-v1",
        reference_bundle_sha256="a" * 64,
        archive_sha256="b" * 64,
        import_manifest={"submission_ids": []},
        status="queued",
        stage="mapping",
        authorized_call_limit=int(kwargs["maximum_provider_calls"]),
        started_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _multipart(run_id: int) -> dict[str, str]:
    return {
        "grading_run_id": str(run_id),
        "provider": "llama_cpp_qwen38",
        "expected_model": "qwen3.8-27b-q4km",
        "marking_policy": "general",
        "maximum_provider_calls": "4",
        "local_only_confirmed": "true",
        "strict_auto_pass_confirmed": "true",
        "draft_only_confirmed": "true",
    }


def test_bulk_create_requires_explicit_authorization(client: TestClient) -> None:
    teacher, run = _teacher_and_run(client, "Authorization")
    data = _multipart(int(run["id"]))
    data["draft_only_confirmed"] = "false"

    response = client.post(
        f"/assessments/{teacher['assessment']['id']}/bulk-evaluation-runs",
        headers=_headers(str(teacher["token"])),
        data=data,
        files={"file": ("scripts.zip", b"not-read", "application/zip")},
    )

    assert response.status_code == 422
    assert "draft-only authorization" in response.json()["detail"]


def test_bulk_cloud_provider_requires_explicit_data_boundary_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher, run = _teacher_and_run(client, "CloudBoundary")
    monkeypatch.setenv("BRAIN_ALLOW_REAL_PROVIDERS", "true")
    monkeypatch.setenv("BRAIN_API_KEY", "test-only-gemini-key")
    monkeypatch.setenv("BRAIN_MODEL", "gemini-test-model")
    get_settings.cache_clear()
    data = _multipart(int(run["id"]))
    data.update(
        {
            "provider": "gemini",
            "expected_model": "gemini-test-model",
            "local_only_confirmed": "false",
            "provider_data_boundary_confirmed": "false",
        }
    )

    try:
        response = client.post(
            f"/assessments/{teacher['assessment']['id']}/bulk-evaluation-runs",
            headers=_headers(str(teacher["token"])),
            data=data,
            files={"file": ("scripts.zip", b"not-transferred", "application/zip")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert "Cloud provider data transfer" in response.json()["detail"]


def test_bulk_create_enqueues_only_its_own_run_and_hides_it_from_other_teachers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    qwen38_policy: None,
) -> None:
    del qwen38_policy
    teacher, grading_run = _teacher_and_run(client, "Owner")
    intruder, _ = _teacher_and_run(client, "Intruder")
    enqueued: list[int] = []
    monkeypatch.setattr(bulk_routes.BulkEvaluationService, "create_from_zip", _fake_create)
    monkeypatch.setattr(
        bulk_routes,
        "_enqueue",
        lambda run_id, _provider: enqueued.append(run_id),
    )

    response = client.post(
        f"/assessments/{teacher['assessment']['id']}/bulk-evaluation-runs",
        headers=_headers(str(teacher["token"])),
        data=_multipart(int(grading_run["id"])),
        files={"file": ("scripts.zip", b"synthetic", "application/zip")},
    )

    assert response.status_code == 202
    run_id = response.json()["id"]
    assert enqueued == [run_id]
    assert client.get(
        f"/bulk-evaluation-runs/{run_id}", headers=_headers(str(intruder["token"]))
    ).status_code == 404
    assert client.get(
        f"/bulk-evaluation-runs/{run_id}", headers=_headers(str(teacher["token"]))
    ).status_code == 200


def test_bulk_enqueue_failure_pauses_only_the_newly_created_run(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    qwen38_policy: None,
) -> None:
    del qwen38_policy
    teacher, grading_run = _teacher_and_run(client, "QueueFailure")
    other_teacher, other_grading_run = _teacher_and_run(client, "Unrelated")
    unrelated_grading_run = db_session.get(GradingRun, int(other_grading_run["id"]))
    assert unrelated_grading_run is not None
    other = _fake_create(
        type("Service", (), {"db": db_session})(),
        assessment_id=int(other_teacher["assessment"]["id"]),
        grading_run=unrelated_grading_run,
        teacher=unrelated_grading_run.created_by_teacher,
        expected_model="qwen3.8-27b-q4km",
        marking_policy="general",
        maximum_provider_calls=4,
    )
    monkeypatch.setattr(bulk_routes.BulkEvaluationService, "create_from_zip", _fake_create)

    def fail_enqueue(_run_id: int, _provider: str) -> None:
        raise RuntimeError("RQ down")

    monkeypatch.setattr(bulk_routes, "_enqueue", fail_enqueue)

    response = client.post(
        f"/assessments/{teacher['assessment']['id']}/bulk-evaluation-runs",
        headers=_headers(str(teacher["token"])),
        data=_multipart(int(grading_run["id"])),
        files={"file": ("scripts.zip", b"synthetic", "application/zip")},
    )

    assert response.status_code == 503
    assert db_session.get(BulkEvaluationRun, other.id).status == "queued"
    newest = db_session.scalar(
        select(BulkEvaluationRun)
        .where(BulkEvaluationRun.assessment_id == int(teacher["assessment"]["id"]))
        .order_by(BulkEvaluationRun.id.desc())
    )
    assert newest is not None and newest.status == "paused"


def test_bulk_approval_never_overwrites_a_separately_finalized_draft(
    client: TestClient, db_session: Session
) -> None:
    teacher, grading_run_payload = _teacher_and_run(client, "ManualDecision")
    teacher_id = int(teacher["user"]["id"])
    assessment_id = int(teacher["assessment"]["id"])
    grading_run = db_session.get(GradingRun, int(grading_run_payload["id"]))
    assert grading_run is not None

    question = Question(
        assessment_id=assessment_id,
        question_no="1",
        question_text="Synthetic question",
        model_answer="Synthetic model answer",
        total_marks=Decimal("10.00"),
    )
    submission = Submission(
        assessment_id=assessment_id,
        student_identifier="SYN-001",
        student_name="Synthetic Student",
        status="uploaded",
    )
    db_session.add_all((question, submission))
    db_session.flush()
    page = SubmissionPage(
        submission_id=submission.id,
        page_no=1,
        image_path="artifacts/pages/synthetic.png",
    )
    db_session.add(page)
    db_session.flush()
    region = AnswerRegion(
        submission_id=submission.id,
        question_id=question.id,
        page_id=page.id,
        x=Decimal("1.00"),
        y=Decimal("1.00"),
        width=Decimal("10.00"),
        height=Decimal("10.00"),
        image_path="artifacts/answer_regions/synthetic.png",
    )
    db_session.add(region)
    db_session.flush()
    grading_job = GradingJob(answer_region_id=region.id, status="completed")
    db_session.add(grading_job)
    db_session.flush()
    suggestion = GradeSuggestion(
        grading_job_id=grading_job.id,
        answer_region_id=region.id,
        question_id=question.id,
        model_provider="mock",
        model_name="mock-grader-v1",
        prompt_version="test",
        marking_policy="general",
        raw_response_json={"synthetic": True},
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
        confidence=Decimal("0.9000"),
        needs_review=True,
    )
    db_session.add(suggestion)
    db_session.flush()
    run = BulkEvaluationRun(
        assessment_id=assessment_id,
        grading_run_id=grading_run.id,
        created_by_teacher_id=teacher_id,
        provider="mock",
        model_name="mock-grader-v1",
        marking_policy="general",
        policy_version="bulk-supervised-test",
        reference_bundle_sha256="a" * 64,
        archive_sha256="b" * 64,
        import_manifest={"submission_ids": [submission.id]},
        status="review_ready",
        stage="review",
        authorized_call_limit=1,
        started_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.flush()
    item = BulkEvaluationItem(
        run_id=run.id,
        submission_id=submission.id,
        question_id=question.id,
        answer_region_id=region.id,
        grade_suggestion_id=suggestion.id,
        status="graded",
        stage="review",
        evidence_snapshot_sha256="c" * 64,
        rubric_snapshot_sha256="d" * 64,
    )
    db_session.add(item)
    db_session.commit()

    service = BulkEvaluationService(db_session, storage=object())
    original_snapshot = service.review_snapshot_hash(run)
    final_grade, created = FinalGradeService(db_session).edit_suggestion(
        suggestion.id,
        teacher_id=teacher_id,
        final_score=Decimal("3.00"),
        teacher_comment="Teacher corrected this synthetic draft",
    )
    assert created is True
    db_session.refresh(item)
    assert item.final_grade_id == final_grade.id

    with pytest.raises(BulkEvaluationError, match="Clean draft set changed"):
        service.approve_clean(
            run,
            suggestion_ids=[suggestion.id],
            review_snapshot_sha256=original_snapshot,
            teacher_id=teacher_id,
        )

    db_session.refresh(final_grade)
    assert final_grade.approval_status == "edited"
    assert final_grade.final_score == Decimal("3.00")
