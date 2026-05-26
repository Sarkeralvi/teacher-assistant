from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    Assessment,
    AuditLog,
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
    AuditLog,
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


def create_region_and_suggestion(client: TestClient, tmp_path: Path) -> dict[str, object]:
    email = f"review-{len(list(tmp_path.glob('*.png')))}@example.com"
    user_response = client.post("/users", json={"name": "Teacher", "email": email})
    assert user_response.status_code == 201
    teacher = user_response.json()
    course_response = client.post(
        "/courses",
        json={"teacher_id": teacher["id"], "code": "REV101", "title": "Review"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    assessment = assessment_response.json()
    question_response = client.post(
        f"/assessments/{assessment['id']}/questions",
        json={"question_no": "1", "question_text": "Explain.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    question = question_response.json()
    rubric_response = client.post(
        f"/questions/{question['id']}/rubrics",
        json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
    )
    assert rubric_response.status_code == 201

    image_path = tmp_path / f"review-source-{len(list(tmp_path.glob('*.png')))}.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-001", "student_name": "Student One"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    submission = submission_response.json()
    page = submission["pages"][0]
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 2, "width": 20, "height": 25},
    )
    assert region_response.status_code == 201
    region = region_response.json()
    grade_response = client.post(f"/answer-regions/{region['id']}/grade")
    assert grade_response.status_code == 201
    suggestion = grade_response.json()["suggestion"]
    return {
        "teacher": teacher,
        "assessment": assessment,
        "question": question,
        "submission": submission,
        "region": region,
        "suggestion": suggestion,
    }


def test_approve_grade_suggestion_creates_final_grade(client: TestClient, tmp_path: Path) -> None:
    data = create_region_and_suggestion(client, tmp_path)

    response = client.post(
        f"/grade-suggestions/{data['suggestion']['id']}/approve",
        json={
            "teacher_id": data["teacher"]["id"],
            "teacher_comment": "Approved after review.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["answer_region_id"] == data["region"]["id"]
    assert payload["suggestion_id"] == data["suggestion"]["id"]
    assert payload["teacher_id"] == data["teacher"]["id"]
    assert payload["final_score"] == data["suggestion"]["score"]
    assert payload["approval_status"] == "approved"
    assert payload["teacher_comment"] == "Approved after review."
    assert "password_hash" not in payload


def test_edit_grade_suggestion_creates_final_grade_with_teacher_score(
    client: TestClient, tmp_path: Path
) -> None:
    data = create_region_and_suggestion(client, tmp_path)

    response = client.post(
        f"/grade-suggestions/{data['suggestion']['id']}/edit",
        json={
            "teacher_id": data["teacher"]["id"],
            "final_score": "4.00",
            "teacher_comment": "Adjusted after inspecting work.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["final_score"] == "4.00"
    assert payload["approval_status"] == "edited"
    assert payload["teacher_comment"] == "Adjusted after inspecting work."


def test_reject_grade_suggestion_creates_rejected_final_grade(
    client: TestClient, tmp_path: Path
) -> None:
    data = create_region_and_suggestion(client, tmp_path)

    response = client.post(
        f"/grade-suggestions/{data['suggestion']['id']}/reject",
        json={
            "teacher_id": data["teacher"]["id"],
            "teacher_comment": "Suggestion is not usable.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["final_score"] == "0.00"
    assert payload["approval_status"] == "rejected"
    assert payload["teacher_comment"] == "Suggestion is not usable."


def test_finalize_validation_failures(client: TestClient, tmp_path: Path) -> None:
    data = create_region_and_suggestion(client, tmp_path)
    suggestion_id = data["suggestion"]["id"]

    too_high = client.post(
        f"/grade-suggestions/{suggestion_id}/edit",
        json={
            "teacher_id": data["teacher"]["id"],
            "final_score": "6.00",
        },
    )
    assert too_high.status_code == 422
    assert "max_score" in too_high.text

    missing_teacher = client.post(
        f"/grade-suggestions/{suggestion_id}/approve",
        json={"teacher_id": 999999},
    )
    assert missing_teacher.status_code == 404

    missing_suggestion = client.post(
        "/grade-suggestions/999999/approve",
        json={"teacher_id": data["teacher"]["id"]},
    )
    assert missing_suggestion.status_code == 404


def test_get_final_grade_and_review_queue_states(client: TestClient, tmp_path: Path) -> None:
    data = create_region_and_suggestion(client, tmp_path)
    assessment_id = data["assessment"]["id"]
    region_id = data["region"]["id"]

    before_final = client.get(f"/assessments/{assessment_id}/review-queue")
    assert before_final.status_code == 200
    queue = before_final.json()
    assert len(queue) == 1
    assert queue[0]["review_status"] == "suggested"
    assert queue[0]["latest_grade_suggestion"]["model_provider"] == "mock"
    assert queue[0]["final_grade"] is None
    assert queue[0]["submission"]["student_identifier"] == "S-001"

    not_found = client.get(f"/answer-regions/{region_id}/final-grade")
    assert not_found.status_code == 404

    finalize = client.post(
        f"/grade-suggestions/{data['suggestion']['id']}/approve",
        json={"teacher_id": data["teacher"]["id"]},
    )
    assert finalize.status_code == 201

    final_grade = client.get(f"/answer-regions/{region_id}/final-grade")
    assert final_grade.status_code == 200
    assert final_grade.json()["id"] == finalize.json()["id"]

    after_final = client.get(f"/assessments/{assessment_id}/review-queue")
    assert after_final.status_code == 200
    assert after_final.json()[0]["review_status"] == "finalized"


def test_review_queue_includes_ungraded_regions(client: TestClient, tmp_path: Path) -> None:
    data = create_region_and_suggestion(client, tmp_path)
    assessment_id = data["assessment"]["id"]
    page_id = data["submission"]["pages"][0]["id"]
    question_id = data["question"]["id"]
    second_region = client.post(
        f"/submission-pages/{page_id}/answer-regions",
        json={"question_id": question_id, "x": 30, "y": 2, "width": 20, "height": 25},
    )
    assert second_region.status_code == 201

    queue = client.get(f"/assessments/{assessment_id}/review-queue")

    assert queue.status_code == 200
    by_region = {item["answer_region"]["id"]: item for item in queue.json()}
    assert by_region[data["region"]["id"]]["review_status"] == "suggested"
    assert by_region[second_region.json()["id"]]["review_status"] == "ungraded"


def test_teacher_actions_replace_existing_current_final_grade(
    client: TestClient, tmp_path: Path
) -> None:
    data = create_region_and_suggestion(client, tmp_path)
    suggestion_id = data["suggestion"]["id"]
    first = client.post(
        f"/grade-suggestions/{suggestion_id}/approve",
        json={"teacher_id": data["teacher"]["id"]},
    )
    assert first.status_code == 201

    second = client.post(
        f"/grade-suggestions/{suggestion_id}/edit",
        json={
            "teacher_id": data["teacher"]["id"],
            "final_score": "3.00",
        },
    )

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["final_score"] == "3.00"


def test_teacher_review_action_writes_audit_log(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_region_and_suggestion(client, tmp_path)

    response = client.post(
        f"/grade-suggestions/{data['suggestion']['id']}/approve",
        json={"teacher_id": data["teacher"]["id"]},
    )

    assert response.status_code == 201
    logs = db_session.query(AuditLog).filter(AuditLog.event_type == "final_grade.approved").all()
    assert len(logs) == 1
    assert logs[0].actor_id == data["teacher"]["id"]
    assert logs[0].entity_type == "final_grade"
