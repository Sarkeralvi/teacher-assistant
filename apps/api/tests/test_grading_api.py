from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
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

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
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


@pytest.fixture()
def client(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def make_png(path: Path, size: tuple[int, int] = (100, 80)) -> None:
    Image.new("RGB", size, color="white").save(path, format="PNG")


def strict_rubric() -> dict[str, object]:
    return {
        "total_marks": "5.00",
        "criteria": [
            {
                "id": "concept",
                "name": "Core concept",
                "description": "Identifies the correct principle or idea.",
                "max_marks": "3.00",
            },
            {
                "id": "clarity",
                "name": "Clarity",
                "description": "Explains the answer clearly.",
                "max_marks": "2.00",
            },
        ],
    }


def create_answer_region_with_optional_rubric(
    client: TestClient, tmp_path: Path, *, create_rubric: bool = True
) -> dict[str, object]:
    email = f"grade-{len(list(tmp_path.glob('*.png')))}@example.com"
    user_response = client.post("/users", json={"name": "Teacher", "email": email})
    assert user_response.status_code == 201
    course_response = client.post(
        "/courses",
        json={"teacher_id": user_response.json()["id"], "code": "GRD101", "title": "Grading"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        json={"question_no": "1", "question_text": "Explain.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    if create_rubric:
        rubric_response = client.post(
            f"/questions/{question_response.json()['id']}/rubrics",
            json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
        )
        assert rubric_response.status_code == 201

    image_path = tmp_path / f"grading-source-{len(list(tmp_path.glob('*.png')))}.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            data={"student_identifier": "S-001"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={
            "question_id": question_response.json()["id"],
            "x": 1,
            "y": 2,
            "width": 20,
            "height": 25,
        },
    )
    assert region_response.status_code == 201
    return region_response.json()


def test_grade_answer_region_creates_job_and_mock_suggestion(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 201
    payload = response.json()
    assert payload["job"]["answer_region_id"] == region["id"]
    assert payload["job"]["status"] == "succeeded"
    suggestion = payload["suggestion"]
    assert suggestion["answer_region_id"] == region["id"]
    assert suggestion["model_provider"] == "mock"
    assert suggestion["model_name"] == "mock-grader-v1"
    assert suggestion["score"] == "0.00"
    assert suggestion["max_score"] == "5.00"
    assert suggestion["confidence"] == "0.0000"
    assert suggestion["needs_review"] is True
    assert (
        suggestion["feedback"]
        == "This is a mock grading suggestion for pipeline validation only."
    )
    raw = suggestion["raw_response_json"]
    assert raw["review_flags"] == ["mock_provider", "teacher_review_required"]
    assert [item["criterion_id"] for item in raw["rubric_breakdown"]] == ["concept", "clarity"]

    db_session.expire_all()
    assert db_session.scalars(select(GradingJob)).one().status == "succeeded"
    assert db_session.scalars(select(GradeSuggestion)).one().model_provider == "mock"


def test_grade_answer_region_failure_cases(client: TestClient, tmp_path: Path) -> None:
    missing_region = client.post("/answer-regions/999999/grade")
    assert missing_region.status_code == 404

    no_rubric_region = create_answer_region_with_optional_rubric(
        client, tmp_path, create_rubric=False
    )
    no_rubric = client.post(f"/answer-regions/{no_rubric_region['id']}/grade")
    assert no_rubric.status_code == 400
    assert "active rubric" in no_rubric.text


def test_grade_suggestion_and_job_read_endpoints(client: TestClient, tmp_path: Path) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    grade_response = client.post(f"/answer-regions/{region['id']}/grade")
    assert grade_response.status_code == 201
    created = grade_response.json()

    list_response = client.get(f"/answer-regions/{region['id']}/grade-suggestions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [created["suggestion"]["id"]]

    suggestion_response = client.get(f"/grade-suggestions/{created['suggestion']['id']}")
    assert suggestion_response.status_code == 200
    assert suggestion_response.json()["id"] == created["suggestion"]["id"]

    job_response = client.get(f"/grading-jobs/{created['job']['id']}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"

def test_grade_answer_region_marks_job_failed_on_provider_error(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter:
        def grade_answer_region(self, **_: object) -> object:
            raise RuntimeError("provider failed with key sk-secret-value")

    class FailingBrainAdapterFactory:
        @classmethod
        def from_settings(cls, settings: object) -> FailingAdapter:
            return FailingAdapter()

    region = create_answer_region_with_optional_rubric(client, tmp_path)
    monkeypatch.setattr("app.services.grading_service.BrainAdapter", FailingBrainAdapterFactory)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 502
    assert "provider failed" in response.text
    assert "sk-secret-value" not in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert job.error is not None
    assert "sk-secret-value" not in job.error
