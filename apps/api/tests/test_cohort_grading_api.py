from collections.abc import Iterator
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


class FakeQueue:
    """Never enqueue into the shared dev Redis the worker consumes from.
    Tests run the job function directly, exercising the same worker path.
    """

    def enqueue(self, *args: object, **kwargs: object) -> None:
        return None


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


@pytest.fixture()
def client(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    monkeypatch.setattr("app.api.routes.grading.get_default_queue", lambda: FakeQueue())
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
    client: TestClient, tmp_path: Path, *, student_count: int, ready: bool = True
) -> dict[str, object]:
    """Register a teacher, one question with a rubric, and `student_count`
    submissions each with a confirmed answer region for that question.
    """
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
    client.post(
        f"/questions/{question['id']}/rubrics",
        headers=headers,
        json={"version": 1, "is_active": True, "rubric_json": strict_rubric()},
    )
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
                "manual_answer_text": "Explained well." if ready else "",
                "full_answer_confirmed": ready,
            },
        ).json()
        region_ids.append(region["id"])
    return {
        "headers": headers,
        "assessment_id": assessment["id"],
        "question_id": question["id"],
        "region_ids": region_ids,
    }


def test_grade_cohort_dispatches_one_job_per_ready_region(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=3)

    response = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort",
        headers=data["headers"],
    )

    assert response.status_code == 202
    body = response.json()
    assert body["total_regions"] == 3
    assert body["queued_count"] == 3
    assert body["skipped"] == []
    assert body["refused"] == []
    job_ids = [job["id"] for job in body["queued_jobs"]]
    assert len(job_ids) == 3
    for job in body["queued_jobs"]:
        assert job["status"] == "queued"

    # Workers would run these; run directly for a deterministic assertion.
    for job_id in job_ids:
        run_grade_answer_region_job(job_id)

    db_session.expire_all()
    suggestions = db_session.scalars(
        select(GradeSuggestion).where(GradeSuggestion.question_id == data["question_id"])
    ).all()
    assert len(suggestions) == 3
    assert all(s.rubric_id is not None for s in suggestions)


def test_grade_cohort_skips_already_graded_and_refuses_unready(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=2)
    # Grade the whole cohort once.
    first = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort",
        headers=data["headers"],
    ).json()
    for job in first["queued_jobs"]:
        run_grade_answer_region_job(job["id"])

    # Add a third, unready region (no manual answer text / not confirmed).
    image = tmp_path / "late.png"
    _png(image)
    with image.open("rb") as file_obj:
        submission = client.post(
            f"/assessments/{data['assessment_id']}/submissions/upload",
            headers=data["headers"],
            data={"student_identifier": "S-LATE"},
            files={"file": ("a.png", file_obj, "image/png")},
        ).json()
    page_id = submission["pages"][0]["id"]
    client.post(
        f"/submission-pages/{page_id}/answer-regions",
        headers=data["headers"],
        json={"question_id": data["question_id"], "x": 1, "y": 2, "width": 20, "height": 25},
    )

    second = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort",
        headers=data["headers"],
    ).json()

    assert second["total_regions"] == 3
    assert second["queued_count"] == 0
    assert len(second["skipped"]) == 2  # the two already-graded regions
    assert len(second["refused"]) == 1  # the unready one
    assert "not ready" in second["refused"][0]["reason"].lower()


def test_cohort_summary_flags_outlier(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = build_cohort(client, tmp_path, student_count=4)
    dispatch = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort",
        headers=data["headers"],
    ).json()
    for job in dispatch["queued_jobs"]:
        run_grade_answer_region_job(job["id"])

    # Mock provider gives every region 0; rewrite three to a cohort of 8 and
    # leave one at 0 so it stands out as a low-score outlier.
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
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/cohort-grades",
        headers=data["headers"],
    )

    assert response.status_code == 200
    summary = response.json()
    assert summary["graded_region_count"] == 4
    assert summary["distribution"]["count"] == 4
    assert summary["flagged_region_count"] >= 1
    flagged = [item for item in summary["items"] if item["outlier_flags"]]
    assert any("low_score_vs_cohort" in item["outlier_flags"] for item in flagged)
    # Flag-only: the flagged suggestion's score is unchanged.
    outlier_region_id = suggestions[3].answer_region_id
    outlier = next(
        item for item in summary["items"] if item["answer_region_id"] == outlier_region_id
    )
    assert Decimal(str(outlier["score"])) == Decimal("0.00")


def test_grade_cohort_requires_owner(client: TestClient, tmp_path: Path) -> None:
    data = build_cohort(client, tmp_path, student_count=1)
    intruder = client.post(
        "/auth/register",
        json={"name": "Intruder", "email": "cohort-intruder@example.com", "password": "pw123456"},
    ).json()
    intruder_headers = {"Authorization": f"Bearer {intruder['access_token']}"}

    unauth = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort"
    )
    assert unauth.status_code == 401

    forbidden = client.post(
        f"/assessments/{data['assessment_id']}/questions/{data['question_id']}/grade-cohort",
        headers=intruder_headers,
    )
    assert forbidden.status_code == 404
