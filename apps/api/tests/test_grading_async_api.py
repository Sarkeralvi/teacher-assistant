from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    AnswerRegionSegment,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.worker.jobs import run_grade_answer_region_job
from tests.test_grading_api import create_answer_region_with_optional_rubric

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    Question,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()


class FakeQueue:
    """Stands in for the real RQ queue so tests never enqueue jobs into the
    shared dev Redis instance the actual worker container consumes from.
    Each test drives run_grade_answer_region_job directly instead, which
    exercises the identical worker-side code path.
    """

    def enqueue(self, *args: object, **kwargs: object) -> None:
        return None


@pytest.fixture()
def client(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    monkeypatch.setattr(
        "app.api.routes.grading.get_default_queue", lambda: FakeQueue()
    )
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def test_async_grade_enqueues_queued_job_and_worker_completes_it(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(
        f"/answer-regions/{region['id']}/grade-async", headers=region["_auth_headers"]
    )

    assert response.status_code == 202
    job = response.json()
    assert job["answer_region_id"] == region["id"]
    assert job["status"] == "queued"

    # No worker is running in the test process; the job stays queued until
    # one picks it up. Run the job function directly here to prove it does
    # the same work run_queued_job/_grade_region does synchronously.
    run_grade_answer_region_job(job["id"])

    db_session.expire_all()
    finished_job = db_session.get(GradingJob, job["id"])
    assert finished_job is not None
    assert finished_job.status == "succeeded"
    suggestion = db_session.scalars(
        select(GradeSuggestion).where(GradeSuggestion.grading_job_id == job["id"])
    ).one()
    assert suggestion.model_provider == "mock"

    detail = client.get(f"/grading-jobs/{job['id']}", headers=region["_auth_headers"])
    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded"


def test_async_grade_requires_auth_and_ownership(client: TestClient, tmp_path: Path) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    unauthenticated = client.post(f"/answer-regions/{region['id']}/grade-async")
    assert unauthenticated.status_code == 401

    missing = client.post(
        "/answer-regions/999999/grade-async", headers=region["_auth_headers"]
    )
    assert missing.status_code == 404


def test_async_grade_rejects_when_not_ready(client: TestClient, tmp_path: Path) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path, create_rubric=False)

    response = client.post(
        f"/answer-regions/{region['id']}/grade-async", headers=region["_auth_headers"]
    )

    assert response.status_code == 400
    assert "active rubric" in response.text


def test_async_grade_queue_failure_marks_the_durable_job_failed(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    class FailingQueue:
        def enqueue(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic queue outage")

    monkeypatch.setattr("app.api.routes.grading.get_default_queue", lambda: FailingQueue())
    response = client.post(
        f"/answer-regions/{region['id']}/grade-async", headers=region["_auth_headers"]
    )

    assert response.status_code == 503
    job = db_session.scalars(
        select(GradingJob).where(GradingJob.answer_region_id == region["id"])
    ).one()
    assert job.status == "failed"
    assert job.error == "Grading worker could not be enqueued"
    assert db_session.scalars(select(GradeSuggestion)).all() == []


def test_worker_job_is_idempotent_on_retry_after_success(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    response = client.post(
        f"/answer-regions/{region['id']}/grade-async", headers=region["_auth_headers"]
    )
    job_id = response.json()["id"]

    run_grade_answer_region_job(job_id)
    run_grade_answer_region_job(job_id)  # simulate an RQ retry firing anyway

    db_session.expire_all()
    suggestions = db_session.scalars(
        select(GradeSuggestion).where(GradeSuggestion.grading_job_id == job_id)
    ).all()
    assert len(suggestions) == 1
