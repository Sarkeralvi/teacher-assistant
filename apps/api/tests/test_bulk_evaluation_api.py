from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
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
        {"token": token, "assessment": assessment.json()},
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
