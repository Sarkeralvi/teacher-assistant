from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    BatchEvidencePrepRun,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingDispatchItem,
    GradingDispatchRun,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    GradingRun,
    Question,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.worker.jobs import run_grading_dispatch_job
from packages.brain.adapter import BrainAdapter
from packages.brain.mock_provider import MockBrainProvider

CLEANUP_MODELS = (
    AuditLog,
    FinalGrade,
    GradeSuggestion,
    GradingDispatchItem,
    GradingDispatchRun,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    BatchEvidencePrepRun,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    Question,
    GradingRun,
    Assessment,
    Course,
    User,
)


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def enqueue(self, function: object, *args: object, **kwargs: object) -> None:
        self.enqueued.append((function, args, kwargs))


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()


@pytest.fixture()
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture()
def client(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_queue: FakeQueue,
) -> Iterator[TestClient]:
    del db_session
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    monkeypatch.setenv("BRAIN_PROVIDER", "mock")
    monkeypatch.setenv("COHORT_MODEL_GRADING_ENABLED", "true")
    monkeypatch.setenv("COHORT_MAX_PROVIDER_CALLS", "25")
    monkeypatch.setattr("app.api.routes.grading.get_default_queue", lambda: fake_queue)
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def strict_rubric() -> dict[str, object]:
    return {
        "total_marks": "10.00",
        "criteria": [
            {"id": "c1", "name": "Concept", "description": "d", "max_marks": "10.00"},
        ],
    }


def _png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (100, 80), color="white").save(path, format="PNG")


def build_cohort(
    client: TestClient,
    tmp_path: Path,
    *,
    student_count: int,
    marking_policy: str = "general",
) -> dict[str, object]:
    reg = client.post(
        "/auth/register",
        json={
            "name": "Cohort Teacher",
            "email": f"cohort-{tmp_path.name}@example.com",
            "password": "cohort-password",
        },
    ).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    course = client.post(
        "/courses", headers=headers, json={"code": "COH101", "title": "Cohort"}
    ).json()
    assessment = client.post(
        f"/courses/{course['id']}/assessments",
        headers=headers,
        json={"title": "Exam", "assessment_type": "exam", "total_marks": "10.00"},
    ).json()
    grading_run_response = client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers=headers,
        json={"marking_policy": marking_policy},
    )
    assert grading_run_response.status_code == 201
    grading_run = grading_run_response.json()
    question = client.post(
        f"/assessments/{assessment['id']}/questions",
        headers=headers,
        json={
            "question_no": "1",
            "question_text": "Explain.",
            "model_answer": "Explained.",
            "total_marks": "10.00",
        },
    ).json()
    rubric = client.post(
        f"/questions/{question['id']}/rubrics",
        headers=headers,
        json={"version": 1, "is_active": True, "rubric_json": strict_rubric()},
    ).json()
    region_ids: list[int] = []
    for index in range(student_count):
        image = tmp_path / f"s{index}.png"
        _png(image)
        with image.open("rb") as file_obj:
            submission = client.post(
                f"/assessments/{assessment['id']}/submissions/upload",
                headers=headers,
                data={"student_identifier": f"S-{index:03d}"},
                files={"file": ("a.png", file_obj, "image/png")},
            ).json()
        page_id = submission["pages"][0]["id"]
        region = client.post(
            f"/submission-pages/{page_id}/answer-regions",
            headers=headers,
            json={
                "question_id": question["id"],
                "x": 1,
                "y": 2,
                "width": 20,
                "height": 25,
                "manual_answer_text": "Explained well.",
            },
        ).json()
        confirmed = client.patch(
            f"/answer-regions/{region['id']}/full-answer-confirmation",
            headers=headers,
            json={"full_answer_confirmed": True, "manual_answer_text": "Explained well."},
        )
        assert confirmed.status_code == 200
        region = confirmed.json()
        region_ids.append(region["id"])
    queue_response = client.post(
        f"/assessments/{assessment['id']}/grading-queue-runs",
        headers=headers,
        json={},
    )
    assert queue_response.status_code == 201
    queue_run = queue_response.json()
    assert queue_run["queued_item_count"] == student_count
    return {
        "headers": headers,
        "teacher_id": reg["user"]["id"],
        "assessment_id": assessment["id"],
        "question_id": question["id"],
        "rubric_id": rubric["id"],
        "grading_run_id": grading_run["id"],
        "queue_run_id": queue_run["id"],
        "region_ids": region_ids,
    }


def dispatch_payload(data: dict[str, object], *, call_limit: int = 25) -> dict[str, object]:
    return {
        "queue_run_id": data["queue_run_id"],
        "grading_run_id": data["grading_run_id"],
        "provider": "mock",
        "expected_model": "mock-grader-v1",
        "call_limit": call_limit,
        "draft_only_confirmed": True,
    }


def dispatch_url(data: dict[str, object]) -> str:
    return (
        f"/assessments/{data['assessment_id']}/questions/"
        f"{data['question_id']}/grade-cohort"
    )


def test_safe_dispatch_requires_explicit_contract_and_runs_sequential_drafts(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    fake_queue: FakeQueue,
) -> None:
    data = build_cohort(client, tmp_path, student_count=3, marking_policy="tough")

    bodyless = client.post(dispatch_url(data), headers=data["headers"])
    assert bodyless.status_code == 422
    preflight = client.post(
        f"{dispatch_url(data)}/preflight",
        headers=data["headers"],
        json=dispatch_payload(data),
    )
    assert preflight.status_code == 200
    assert preflight.json()["selected_call_count"] == 3
    response = client.post(
        dispatch_url(data),
        headers=data["headers"],
        json=dispatch_payload(data),
    )

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert run["selected_count"] == 3
    assert run["pending_count"] == 3
    assert run["marking_policy"] == "tough"
    assert all(item["status"] == "pending" for item in run["items"])
    assert len(fake_queue.enqueued) == 1
    assert fake_queue.enqueued[0][2] == {}

    run_grading_dispatch_job(run["id"])

    db_session.expire_all()
    finished = db_session.get(GradingDispatchRun, run["id"])
    assert finished is not None
    assert finished.status == "completed"
    assert finished.succeeded_count == 3
    assert finished.calls_started == 3
    suggestions = db_session.scalars(
        select(GradeSuggestion).where(GradeSuggestion.question_id == data["question_id"])
    ).all()
    assert len(suggestions) == 3
    assert all(suggestion.marking_policy == "tough" for suggestion in suggestions)
    assert all(suggestion.rubric_id == data["rubric_id"] for suggestion in suggestions)
    assert all(suggestion.needs_review is True for suggestion in suggestions)
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_dispatch_cap_duplicate_prevention_and_stale_evidence(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=3)
    first = client.post(
        dispatch_url(data),
        headers=data["headers"],
        json=dispatch_payload(data, call_limit=2),
    )
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["selected_count"] == 2
    assert first_body["pending_count"] == 2
    assert first_body["skipped_count"] == 1

    duplicate = client.post(
        dispatch_url(data),
        headers=data["headers"],
        json=dispatch_payload(data),
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["selected_count"] == 1
    assert duplicate.json()["refused_count"] == 2
    active_jobs = db_session.scalars(
        select(GradingJob).where(GradingJob.status.in_(["queued", "running"]))
    ).all()
    assert len(active_jobs) == 3
    assert len({job.answer_region_id for job in active_jobs}) == 3

    changed_region_id = data["region_ids"][2]
    changed = client.patch(
        f"/answer-regions/{changed_region_id}/corrections/full-answer-confirmation",
        headers=data["headers"],
        json={
            "full_answer_confirmed": True,
            "packet_status": "complete",
            "manual_answer_text": "Teacher changed this evidence after queue creation.",
        },
    )
    assert changed.status_code == 200
    preflight = client.post(
        f"{dispatch_url(data)}/preflight",
        headers=data["headers"],
        json=dispatch_payload(data),
    ).json()
    assert preflight["stale_count"] >= 1


def test_dispatch_refuses_model_mismatch_and_server_cap(
    client: TestClient, tmp_path: Path
) -> None:
    data = build_cohort(client, tmp_path, student_count=1)
    mismatch = dispatch_payload(data)
    mismatch["expected_model"] = "wrong-model"
    response = client.post(dispatch_url(data), headers=data["headers"], json=mismatch)
    assert response.status_code == 409
    assert "Expected model" in response.text

    over_cap = dispatch_payload(data)
    over_cap["call_limit"] = 26
    over_cap_response = client.post(
        dispatch_url(data), headers=data["headers"], json=over_cap
    )
    assert over_cap_response.status_code == 422


def test_stop_and_resume_only_runs_never_started_items(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=2)
    run = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()

    stopped = client.post(
        f"/grading-dispatch-runs/{run['id']}/stop", headers=data["headers"]
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["calls_started"] == 0

    resumed = client.post(
        f"/grading-dispatch-runs/{run['id']}/resume", headers=data["headers"]
    )
    assert resumed.status_code == 202
    assert resumed.json()["status"] == "queued"
    run_grading_dispatch_job(run["id"])

    db_session.expire_all()
    finished = db_session.get(GradingDispatchRun, run["id"])
    assert finished is not None
    assert finished.status == "completed"
    assert finished.succeeded_count == 2


def test_rubric_change_is_refused_immediately_before_provider_call(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=1)
    run = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()
    rubric = db_session.get(Rubric, data["rubric_id"])
    assert rubric is not None
    rubric.rubric_json = {
        "total_marks": "10.00",
        "criteria": [
            {"id": "changed", "name": "Changed", "description": "d", "max_marks": "10.00"}
        ],
    }
    db_session.commit()

    run_grading_dispatch_job(run["id"])

    db_session.expire_all()
    finished = db_session.get(GradingDispatchRun, run["id"])
    assert finished is not None
    assert finished.status == "completed"
    assert finished.refused_count == 1
    assert finished.calls_started == 0
    assert db_session.scalars(select(GradeSuggestion)).all() == []


def test_dispatch_stops_on_first_provider_failure_without_retry(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = build_cohort(client, tmp_path, student_count=3)

    class FailingProvider(MockBrainProvider):
        calls = 0

        def grade(self, **kwargs: object) -> object:
            del kwargs
            type(self).calls += 1
            raise RuntimeError("synthetic provider failure")

    adapter = BrainAdapter(FailingProvider())

    def fake_for_provider(
        cls: type[BrainAdapter], settings: object, requested_provider: str
    ) -> BrainAdapter:
        del cls, settings
        assert requested_provider == "mock"
        return adapter

    monkeypatch.setattr(BrainAdapter, "for_provider", classmethod(fake_for_provider))
    run = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()

    run_grading_dispatch_job(run["id"])

    db_session.expire_all()
    finished = db_session.get(GradingDispatchRun, run["id"])
    assert finished is not None
    assert finished.status == "failed"
    assert finished.calls_started == 1
    assert finished.failed_count == 1
    assert FailingProvider.calls == 1
    items = db_session.scalars(
        select(GradingDispatchItem)
        .where(GradingDispatchItem.dispatch_run_id == run["id"])
        .order_by(GradingDispatchItem.id)
    ).all()
    assert [item.attempt_count for item in items] == [1, 0, 0]
    assert [item.status for item in items] == ["failed", "pending", "pending"]
    assert db_session.scalars(select(GradeSuggestion)).all() == []


def test_stale_worker_call_becomes_uncertain_and_is_never_resumed(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=2)
    run_body = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()
    run = db_session.get(GradingDispatchRun, run_body["id"])
    assert run is not None
    first_item = db_session.scalars(
        select(GradingDispatchItem)
        .where(GradingDispatchItem.dispatch_run_id == run.id)
        .order_by(GradingDispatchItem.id)
    ).first()
    assert first_item is not None
    run.status = "running"
    run.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
    first_item.status = "running"
    first_item.attempt_count = 1
    job = db_session.get(GradingJob, first_item.grading_job_id)
    assert job is not None
    job.status = "running"
    db_session.commit()

    read = client.get(
        f"/grading-dispatch-runs/{run.id}", headers=data["headers"]
    )

    assert read.status_code == 200
    reconciled = read.json()
    assert reconciled["status"] == "failed"
    assert reconciled["uncertain_count"] == 1
    resumed = client.post(
        f"/grading-dispatch-runs/{run.id}/resume", headers=data["headers"]
    )
    assert resumed.status_code == 202
    uncertain = next(item for item in resumed.json()["items"] if item["id"] == first_item.id)
    assert uncertain["status"] == "uncertain"
    assert uncertain["attempt_count"] == 1


def test_dispatch_ownership_and_audit_payload_privacy(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=1)
    assert client.post(dispatch_url(data), json=dispatch_payload(data)).status_code == 401
    intruder = client.post(
        "/auth/register",
        json={
            "name": "Intruder",
            "email": "cohort-intruder@example.com",
            "password": "pw123456",
        },
    ).json()
    intruder_headers = {"Authorization": f"Bearer {intruder['access_token']}"}
    assert (
        client.post(
            dispatch_url(data), headers=intruder_headers, json=dispatch_payload(data)
        ).status_code
        == 404
    )

    run = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()
    run_grading_dispatch_job(run["id"])
    payloads = db_session.scalars(
        select(AuditLog.payload_json).where(
            AuditLog.entity_type == "grading_dispatch_run"
        )
    ).all()
    assert payloads
    audit_text = str(payloads)
    assert "Explained well" not in audit_text
    assert "student_identifier" not in audit_text


def test_cohort_summary_flags_outlier(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=4)
    run = client.post(
        dispatch_url(data), headers=data["headers"], json=dispatch_payload(data)
    ).json()
    run_grading_dispatch_job(run["id"])

    suggestions = db_session.scalars(
        select(GradeSuggestion)
        .where(GradeSuggestion.question_id == data["question_id"])
        .order_by(GradeSuggestion.id)
    ).all()
    for suggestion in suggestions[:3]:
        suggestion.score = Decimal("8.00")
    suggestions[3].score = Decimal("0.00")
    db_session.commit()

    response = client.get(
        f"/assessments/{data['assessment_id']}/questions/"
        f"{data['question_id']}/cohort-grades",
        headers=data["headers"],
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["graded_region_count"] == 4
    assert summary["flagged_region_count"] >= 1
    assert any("low_score_vs_cohort" in item["outlier_flags"] for item in summary["items"])
