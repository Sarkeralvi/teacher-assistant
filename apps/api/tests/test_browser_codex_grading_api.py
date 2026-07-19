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
from tests.test_grading_api import codex_api_output, strict_rubric

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
    monkeypatch.setenv("BRAIN_PROVIDER", "mock")
    monkeypatch.delenv("CODEX_BROWSER_GRADING_ENABLED", raising=False)
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def register_teacher(
    client: TestClient, email: str = "browser-codex@example.com"
) -> tuple[int, str]:
    response = client.post(
        "/auth/register",
        json={"name": "Browser Codex Teacher", "email": email, "password": "secret123"},
    )
    assert response.status_code == 201
    payload = response.json()
    return int(payload["user"]["id"]), str(payload["access_token"])


def create_owned_answer_region(client: TestClient, tmp_path: Path) -> dict[str, object]:
    teacher_id, token = register_teacher(client)
    course_response = client.post(
        "/courses",
        json={"teacher_id": teacher_id, "code": "COD101", "title": "Codex Smoke"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        json={
            "question_no": "1",
            "question_text": "Explain.",
            "model_answer": "A complete answer explains the concept.",
            "total_marks": "5.00",
        },
    )
    assert question_response.status_code == 201
    rubric_response = client.post(
        f"/questions/{question_response.json()['id']}/rubrics",
        json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
    )
    assert rubric_response.status_code == 201
    image_path = tmp_path / "answer.png"
    Image.new("RGB", (100, 80), color="white").save(image_path, format="PNG")
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            data={"student_identifier": "S-001"},
            files={"file": ("answer.png", file_obj, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
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
            "manual_answer_text": "Student explanation captured for grading.",
            "full_answer_confirmed": True,
        },
    )
    assert region_response.status_code == 201
    return {"teacher_id": teacher_id, "token": token, "region": region_response.json()}


def test_browser_codex_endpoint_requires_auth(client: TestClient, tmp_path: Path) -> None:
    region = create_owned_answer_region(client, tmp_path)["region"]

    response = client.post(f"/answer-regions/{region['id']}/grade-codex-dev")

    assert response.status_code == 401


def test_browser_codex_endpoint_rejects_when_env_flag_disabled(
    client: TestClient, tmp_path: Path
) -> None:
    data = create_owned_answer_region(client, tmp_path)

    response = client.post(
        f"/answer-regions/{data['region']['id']}/grade-codex-dev",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert response.status_code == 403
    assert "Codex browser grading is unavailable" in response.text
    assert "host-backend Codex dev mode" in response.text


def test_browser_codex_endpoint_grades_one_region_and_never_finalizes(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"
        calls: list[dict[str, object]] = []

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def grade(self, **kwargs: object):
            self.calls.append(kwargs)
            return codex_api_output()

    data = create_owned_answer_region(client, tmp_path)
    monkeypatch.setenv("CODEX_BROWSER_GRADING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.grading_service.CodexCliProvider", FakeCodexCliProvider)

    response = client.post(
        f"/answer-regions/{data['region']['id']}/grade-codex-dev",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["job"]["status"] == "succeeded"
    suggestion = payload["suggestion"]
    assert suggestion["answer_region_id"] == data["region"]["id"]
    assert suggestion["model_provider"] == "codex_cli"
    assert suggestion["needs_review"] is True
    assert "raw_response_json" not in suggestion
    assert "teacher_review_required" in suggestion["review_flags"]
    assert "codex_cli_provider" in suggestion["review_flags"]
    assert len(FakeCodexCliProvider.calls) == 1
    db_session.expire_all()
    assert db_session.scalars(select(GradeSuggestion)).one().model_provider == "codex_cli"
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_browser_codex_endpoint_returns_clear_error_when_cli_unavailable(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"

        def __init__(self, **kwargs: object) -> None:
            pass

        def grade(self, **kwargs: object):
            raise RuntimeError("codex command not found: codex")

    data = create_owned_answer_region(client, tmp_path)
    monkeypatch.setenv("CODEX_BROWSER_GRADING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.grading_service.CodexCliProvider", MissingCodexCliProvider)

    response = client.post(
        f"/answer-regions/{data['region']['id']}/grade-codex-dev",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert response.status_code == 503
    assert "Codex CLI is not available in this backend runtime" in response.text
    assert "Use host-backend Codex dev mode" in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_browser_codex_endpoint_sanitizes_provider_errors(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"

        def __init__(self, **kwargs: object) -> None:
            pass

        def grade(self, **kwargs: object):
            raise RuntimeError("Codex failed with sk-secret-value")

    data = create_owned_answer_region(client, tmp_path)
    monkeypatch.setenv("CODEX_BROWSER_GRADING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.services.grading_service.CodexCliProvider", FailingCodexCliProvider)

    response = client.post(
        f"/answer-regions/{data['region']['id']}/grade-codex-dev",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert response.status_code == 502
    assert "sk-secret-value" not in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert job.error is not None
    assert "sk-secret-value" not in job.error
