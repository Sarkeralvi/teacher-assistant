from collections.abc import Iterator
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

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
def client(db_session: Session) -> TestClient:
    return TestClient(app)


def valid_rubric_json(total_marks: int = 5) -> dict[str, object]:
    return {
        "total_marks": total_marks,
        "criteria": [
            {
                "id": "concept",
                "name": "Core concept",
                "description": "Identifies the correct principle or idea.",
                "max_marks": 2,
            },
            {
                "id": "method",
                "name": "Method and reasoning",
                "description": "Shows correct step-by-step reasoning.",
                "max_marks": total_marks - 2,
            },
        ],
    }


def register_teacher(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "name": "Teacher One",
            "email": f"rubric-teacher-{uuid4().hex}@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_question(
    client: TestClient, total_marks: str = "5.00"
) -> tuple[dict[str, object], dict[str, str]]:
    headers = register_teacher(client)
    course_response = client.post(
        "/courses", headers=headers, json={"code": "RUB101", "title": "Rubrics"}
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=headers,
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "10.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        headers=headers,
        json={
            "question_no": "1",
            "question_text": "Explain the method.",
            "total_marks": total_marks,
        },
    )
    assert question_response.status_code == 201
    return question_response.json(), headers


def post_rubric(
    client: TestClient,
    question_id: int,
    rubric_json: object,
    headers: dict[str, str],
    *,
    version: int = 1,
    is_active: bool = True,
):
    return client.post(
        f"/questions/{question_id}/rubrics",
        headers=headers,
        json={"version": version, "rubric_json": rubric_json, "is_active": is_active},
    )


def assert_validation_error(response, expected_text: str) -> None:
    assert response.status_code == 422
    assert expected_text in response.text


def test_accepts_valid_rubric_schema(client: TestClient) -> None:
    question, headers = create_question(client)

    response = post_rubric(client, int(question["id"]), valid_rubric_json(), headers)

    assert response.status_code == 201
    assert response.json()["rubric_json"] == valid_rubric_json()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.pop("total_marks"), "total_marks is required"),
        (lambda data: data.pop("criteria"), "criteria is required"),
        (lambda data: data.update({"criteria": []}), "criteria must be a non-empty array"),
        (
            lambda data: data.update(
                {
                    "criteria": [
                        data["criteria"][0],
                        {**data["criteria"][1], "id": data["criteria"][0]["id"]},
                    ]
                }
            ),
            "criterion.id must be unique within the rubric",
        ),
        (
            lambda data: data["criteria"][0].update({"max_marks": 0}),
            "criterion.max_marks must be positive",
        ),
        (
            lambda data: data.update({"total_marks": 6}),
            "Sum of criterion.max_marks must equal rubric_json.total_marks",
        ),
        (
            lambda data: data["criteria"][1].update({"depends_on": ["missing"]}),
            "criterion.depends_on references an unknown criterion ID",
        ),
        (
            lambda data: data["criteria"][0].update({"depends_on": ["concept"]}),
            "criterion cannot depend on itself",
        ),
        (
            lambda data: (
                data["criteria"][0].update({"depends_on": ["method"]}),
                data["criteria"][1].update({"depends_on": ["concept"]}),
            ),
            "criterion dependencies must not contain a cycle",
        ),
    ],
)
def test_rejects_invalid_rubric_schema_payloads(client: TestClient, mutate, message: str) -> None:
    question, headers = create_question(client)
    rubric_json = deepcopy(valid_rubric_json())
    mutate(rubric_json)

    response = post_rubric(client, int(question["id"]), rubric_json, headers)

    assert_validation_error(response, message)


def test_rejects_rubric_total_marks_mismatch_with_question(client: TestClient) -> None:
    question, headers = create_question(client, total_marks="4.00")

    response = post_rubric(client, int(question["id"]), valid_rubric_json(total_marks=5), headers)

    assert_validation_error(response, "rubric_json.total_marks must match question.total_marks")


def test_rejects_second_active_rubric_but_allows_inactive_rubric(client: TestClient) -> None:
    question, headers = create_question(client)
    first_active = post_rubric(
        client, int(question["id"]), valid_rubric_json(), headers, version=1, is_active=True
    )
    assert first_active.status_code == 201

    second_active = post_rubric(
        client, int(question["id"]), valid_rubric_json(), headers, version=2, is_active=True
    )
    assert second_active.status_code == 409
    assert "already has an active rubric" in second_active.text

    inactive = post_rubric(
        client, int(question["id"]), valid_rubric_json(), headers, version=2, is_active=False
    )
    assert inactive.status_code == 201
    assert inactive.json()["is_active"] is False
