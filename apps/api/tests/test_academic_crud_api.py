from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models import Assessment, Course, Question, Rubric, User


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in (Rubric, Question, Assessment, Course, User):
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in (Rubric, Question, Assessment, Course, User):
            db.execute(delete(model))
        db.commit()
        db.close()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    return TestClient(app)


def create_user(client: TestClient, email: str = "teacher@example.com") -> dict[str, object]:
    response = client.post("/users", json={"name": "Teacher One", "email": email})
    assert response.status_code == 201
    return response.json()


def create_course(client: TestClient, teacher_id: int) -> dict[str, object]:
    response = client.post(
        "/courses",
        json={
            "teacher_id": teacher_id,
            "code": "MATH101",
            "title": "Calculus I",
            "department": "Mathematics",
            "semester": "Spring 2026",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_assessment(client: TestClient, course_id: int) -> dict[str, object]:
    response = client.post(
        f"/courses/{course_id}/assessments",
        json={
            "title": "Midterm",
            "assessment_type": "exam",
            "total_marks": "40.00",
            "status": "draft",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_question(client: TestClient, assessment_id: int) -> dict[str, object]:
    response = client.post(
        f"/assessments/{assessment_id}/questions",
        json={
            "question_no": "1(a)",
            "question_text": "Differentiate x^2.",
            "model_answer": "2x",
            "total_marks": "5.00",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_user_response_excludes_password_hash(client: TestClient) -> None:
    user = create_user(client)

    assert user["id"] > 0
    assert user["name"] == "Teacher One"
    assert user["email"] == "teacher@example.com"
    assert user["role"] == "teacher"
    assert "created_at" in user
    assert "updated_at" in user
    assert "password_hash" not in user


def test_course_crud_and_invalid_teacher(client: TestClient) -> None:
    invalid = client.post(
        "/courses",
        json={"teacher_id": 999999, "code": "BAD101", "title": "Bad Course"},
    )
    assert invalid.status_code == 404

    user = create_user(client)
    course = create_course(client, int(user["id"]))

    assert course["teacher_id"] == user["id"]
    assert course["code"] == "MATH101"

    list_response = client.get("/courses")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [course["id"]]

    get_response = client.get(f"/courses/{course['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Calculus I"

    patch_response = client.patch(f"/courses/{course['id']}", json={"title": "Calculus IA"})
    assert patch_response.status_code == 200
    assert patch_response.json()["title"] == "Calculus IA"

    delete_response = client.delete(f"/courses/{course['id']}")
    assert delete_response.status_code == 204
    assert client.get(f"/courses/{course['id']}").status_code == 404


def test_create_academic_workflow_and_rubric_json_round_trip(client: TestClient) -> None:
    user = create_user(client)
    course = create_course(client, int(user["id"]))
    assessment = create_assessment(client, int(course["id"]))
    question = create_question(client, int(assessment["id"]))

    assert Decimal(assessment["total_marks"]) == Decimal("40.00")
    assert Decimal(question["total_marks"]) == Decimal("5.00")

    rubric_json = {
        "criteria": [
            {"name": "Derivative", "marks": "5.00", "description": "Correct derivative"}
        ]
    }
    rubric_response = client.post(
        f"/questions/{question['id']}/rubrics",
        json={"version": 1, "rubric_json": rubric_json, "is_active": True},
    )
    assert rubric_response.status_code == 201
    rubric = rubric_response.json()
    assert rubric["question_id"] == question["id"]
    assert rubric["rubric_json"] == rubric_json
    assert rubric["is_active"] is True

    list_response = client.get(f"/questions/{question['id']}/rubrics")
    assert list_response.status_code == 200
    assert list_response.json()[0]["rubric_json"] == rubric_json


def test_missing_parent_and_resource_404s(client: TestClient) -> None:
    assert client.get("/courses/999999").status_code == 404
    assert client.get("/assessments/999999").status_code == 404
    assert client.get("/questions/999999").status_code == 404
    assert client.get("/rubrics/999999").status_code == 404

    assessment_response = client.post(
        "/courses/999999/assessments",
        json={"title": "Missing", "assessment_type": "exam", "total_marks": "10.00"},
    )
    assert assessment_response.status_code == 404

    question_response = client.post(
        "/assessments/999999/questions",
        json={"question_no": "1", "question_text": "Missing", "total_marks": "5.00"},
    )
    assert question_response.status_code == 404

    rubric_response = client.post(
        "/questions/999999/rubrics",
        json={"version": 1, "rubric_json": {"criteria": []}},
    )
    assert rubric_response.status_code == 404


def test_reject_non_object_rubric_json_and_second_active_rubric(client: TestClient) -> None:
    user = create_user(client)
    course = create_course(client, int(user["id"]))
    assessment = create_assessment(client, int(course["id"]))
    question = create_question(client, int(assessment["id"]))

    invalid_json = client.post(
        f"/questions/{question['id']}/rubrics",
        json={"version": 1, "rubric_json": ["not", "an", "object"]},
    )
    assert invalid_json.status_code == 422

    first_active = client.post(
        f"/questions/{question['id']}/rubrics",
        json={"version": 1, "rubric_json": {"criteria": []}, "is_active": True},
    )
    assert first_active.status_code == 201

    second_active = client.post(
        f"/questions/{question['id']}/rubrics",
        json={"version": 2, "rubric_json": {"criteria": []}, "is_active": True},
    )
    assert second_active.status_code == 409
