from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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
def client(db_session: Session) -> TestClient:
    return TestClient(app)


def register(client: TestClient, email: str = "auth-teacher@example.com") -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={"name": "Auth Teacher", "email": email, "password": "correct horse battery"},
    )
    assert response.status_code == 201
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_user_with_hashed_password_and_never_exposes_hash(
    client: TestClient, db_session: Session
) -> None:
    payload = register(client)

    assert payload["user"]["email"] == "auth-teacher@example.com"
    assert payload["user"]["role"] == "teacher"
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert "password_hash" not in payload
    assert "password_hash" not in payload["user"]

    user = db_session.scalars(select(User).where(User.email == "auth-teacher@example.com")).one()
    assert user.password_hash != "correct horse battery"
    assert user.password_hash.startswith("pbkdf2_sha256$")


def test_login_succeeds_with_correct_password_and_me_returns_current_user(
    client: TestClient,
) -> None:
    register(client)

    login = client.post(
        "/auth/login",
        json={"email": "auth-teacher@example.com", "password": "correct horse battery"},
    )

    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/auth/me", headers=auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "auth-teacher@example.com"
    assert "password_hash" not in me.json()


def test_login_fails_with_wrong_password(client: TestClient) -> None:
    register(client)

    response = client.post(
        "/auth/login",
        json={"email": "auth-teacher@example.com", "password": "wrong"},
    )

    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_missing_or_invalid_token_returns_401_for_auth_me(client: TestClient) -> None:
    missing = client.get("/auth/me")
    invalid = client.get("/auth/me", headers=auth_header("not-a-valid-token"))

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_course_creation_uses_authenticated_teacher_without_raw_teacher_id(
    client: TestClient,
) -> None:
    auth = register(client)
    token = str(auth["access_token"])

    missing_token = client.post("/courses", json={"code": "AUTH101", "title": "Auth Course"})
    assert missing_token.status_code == 401

    response = client.post(
        "/courses",
        headers=auth_header(token),
        json={"code": "AUTH101", "title": "Auth Course"},
    )

    assert response.status_code == 201
    assert response.json()["teacher_id"] == auth["user"]["id"]


def test_invalid_token_returns_401_for_auth_aware_course_creation(client: TestClient) -> None:
    response = client.post(
        "/courses",
        headers=auth_header("bad-token"),
        json={"code": "AUTH401", "title": "Auth Course"},
    )

    assert response.status_code == 401
