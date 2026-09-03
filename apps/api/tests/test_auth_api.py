import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.auth import _b64encode
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


def signed_token(payload: object) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        (
            _b64encode(json.dumps(header, separators=(",", ":")).encode()),
            _b64encode(json.dumps(payload, separators=(",", ":")).encode()),
        )
    )
    signature = hmac.new(
        get_settings().jwt_secret_key.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


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


def test_public_registration_cannot_self_assign_admin_role(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/auth/register",
        json={
            "name": "Untrusted Admin",
            "email": "untrusted-admin@example.com",
            "password": "correct horse battery",
            "role": "admin",
        },
    )

    assert response.status_code == 422
    assert db_session.scalars(select(User)).all() == []


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


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"sub": [], "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
    ],
)
def test_signed_malformed_token_claims_return_401_not_server_error(
    client: TestClient, payload: object
) -> None:
    response = client.get("/auth/me", headers=auth_header(signed_token(payload)))

    assert response.status_code == 401


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


def test_user_endpoints_do_not_enumerate_other_teachers(client: TestClient) -> None:
    first = register(client, "first-teacher@example.com")
    second = register(client, "second-teacher@example.com")
    first_headers = auth_header(str(first["access_token"]))
    first_id = int(first["user"]["id"])
    second_id = int(second["user"]["id"])

    listing = client.get("/users", headers=first_headers)
    assert listing.status_code == 200
    assert [user["id"] for user in listing.json()] == [first_id]

    own = client.get(f"/users/{first_id}", headers=first_headers)
    assert own.status_code == 200
    assert own.json()["email"] == "first-teacher@example.com"

    other = client.get(f"/users/{second_id}", headers=first_headers)
    assert other.status_code == 404
