from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.routes import answer_regions as answer_regions_route
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    Question,
    Submission,
    SubmissionPage,
    User,
)
from packages.brain.answer_region_suggestion_codex_provider import (
    CodexAnswerRegionSuggestionProvider,
)


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in (
            SubmissionPage,
            Submission,
            Question,
            Assessment,
            Course,
            FinalGrade,
            GradeSuggestion,
            AnswerRegion,
            User,
        ):
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in (
            SubmissionPage,
            Submission,
            Question,
            Assessment,
            Course,
            FinalGrade,
            GradeSuggestion,
            AnswerRegion,
            User,
        ):
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


def make_png(path: Path, size: tuple[int, int] = (320, 240)) -> None:
    Image.new("RGB", size, color="white").save(path, format="PNG")


def create_uploaded_page(
    client: TestClient, tmp_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    image_path = tmp_path / f"answer-{len(list(tmp_path.glob('answer-*.png')))}.png"
    email = f"codex-{image_path.stem}@example.com"
    auth_response = client.post(
        "/auth/register",
        json={"name": "Teacher", "email": email, "password": "codex-password"},
    )
    assert auth_response.status_code == 201
    auth = auth_response.json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    course_response = client.post(
        "/courses",
        headers=headers,
        json={"code": "COD101", "title": "Codex"},
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
        json={"question_no": "1", "question_text": "Answer this.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            headers=headers,
            data={"student_identifier": "COD-001"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]
    return question_response.json(), page


def make_runner(mode: str, *, question_id: int | None = None, question_no: str = "1"):
    def runner(command, **kwargs):
        if command[:2] == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex 1.0.0\n")
        if command[:3] == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(
                stdout="--output-last-message --cd --sandbox --json --image -i\n"
            )
        output_path = Path(command[command.index("--output-last-message") + 1])
        if mode == "valid":
            payload = {
                "provider_warnings": ["Low confidence around handwritten margin note."],
                "suggestions": [
                    {
                        "question_id": question_id,
                        "question_no": question_no,
                        "x": 48,
                        "y": 64,
                        "width": 180,
                        "height": 96,
                        "confidence": 0.87,
                        "notes": "Likely the answer spans the mid-page paragraph.",
                        "warnings": ["Margin note nearby."],
                        "needs_review": True,
                    }
                ],
            }
            output_path.write_text(json.dumps(payload), encoding="utf-8")
            return FakeCompletedProcess(stdout="")
        if mode == "invalid_json":
            output_path.write_text("{not-valid-json", encoding="utf-8")
            return FakeCompletedProcess(stdout="")
        if mode == "error_with_secret":
            return FakeCompletedProcess(
                returncode=1,
                stderr="codex failed with sk-SECRET-123 and data:image/png;base64,AAAA",
            )
        raise AssertionError(f"Unhandled fake Codex mode: {mode}")

    return runner


def make_enabled_settings() -> Settings:
    settings = Settings()
    settings.answer_region_suggestion_provider = "codex_cli_answer_region_suggester"
    settings.codex_answer_region_suggestions_enabled = True
    settings.codex_cli_command = "codex"
    settings.codex_cli_image_input_enabled = True
    settings.codex_cli_output_last_message = True
    settings.codex_cli_sandbox = "read-only"
    settings.codex_cli_workdir = "/home/newton/teacher-assistant"
    return settings


def test_codex_answer_region_suggestions_require_explicit_enable_flag(
    client: TestClient, tmp_path: Path
) -> None:
    _question, page = create_uploaded_page(client, tmp_path)

    response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "codex_cli_answer_region_suggester"},
    )

    assert response.status_code == 403
    assert "disabled" in response.text.lower()


def test_codex_answer_region_suggestions_return_drafts_and_wait_for_accept(
    client: TestClient, tmp_path: Path, db_session: Session, monkeypatch
) -> None:
    question, page = create_uploaded_page(client, tmp_path)
    settings = make_enabled_settings()
    question_id = int(cast(int, question["id"]))
    question_no = str(cast(str, question["question_no"]))
    provider = CodexAnswerRegionSuggestionProvider(
        command="codex",
        image_input_enabled=True,
        workdir="/home/newton/teacher-assistant",
        runner=make_runner("valid", question_id=question_id, question_no=question_no),
        which=lambda _command: "/usr/bin/codex",
    )
    monkeypatch.setattr(answer_regions_route, "get_settings", lambda: settings)
    monkeypatch.setattr(
        answer_regions_route,
        "get_codex_answer_region_suggestion_provider",
        lambda _settings: provider,
    )

    response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "codex_cli_answer_region_suggester", "question_ids": [question["id"]]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "codex_cli_answer_region_suggester"
    assert body["source"] == "codex_cli_answer_region_suggester"
    assert body["needs_review"] is True
    assert body["provider_warnings"] == ["Low confidence around handwritten margin note."]
    assert body["suggestions"]
    suggestion = body["suggestions"][0]
    assert suggestion["needs_review"] is True
    assert suggestion["needs_teacher_confirmation"] is True
    assert suggestion["suggested_question_id"] == question["id"]
    assert suggestion["suggested_question_no"] == question["question_no"]
    assert suggestion["provider"] == "codex_cli_answer_region_suggester"
    assert suggestion["source"] == "codex_cli_answer_region_suggester"
    assert suggestion["warnings"] == ["Margin note nearby."]
    assert suggestion["confidence"] == "0.87"

    assert db_session.query(AnswerRegion).count() == 0
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0

    accepted_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={
            "question_id": suggestion["suggested_question_id"],
            "x": suggestion["x"],
            "y": suggestion["y"],
            "width": suggestion["width"],
            "height": suggestion["height"],
        },
    )
    assert accepted_response.status_code == 201
    assert db_session.query(AnswerRegion).count() == 1
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0


def test_codex_answer_region_suggestions_fail_cleanly_on_invalid_json(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    _question, page = create_uploaded_page(client, tmp_path)
    settings = make_enabled_settings()
    provider = CodexAnswerRegionSuggestionProvider(
        command="codex",
        image_input_enabled=True,
        workdir="/home/newton/teacher-assistant",
        runner=make_runner("invalid_json"),
        which=lambda _command: "/usr/bin/codex",
    )
    monkeypatch.setattr(answer_regions_route, "get_settings", lambda: settings)
    monkeypatch.setattr(
        answer_regions_route,
        "get_codex_answer_region_suggestion_provider",
        lambda _settings: provider,
    )

    response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "codex_cli_answer_region_suggester"},
    )

    assert response.status_code == 502
    assert "did not contain exact valid JSON" in response.text
    assert "sk-SECRET" not in response.text


def test_codex_answer_region_suggestions_sanitize_provider_errors(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    _question, page = create_uploaded_page(client, tmp_path)
    settings = make_enabled_settings()
    provider = CodexAnswerRegionSuggestionProvider(
        command="codex",
        image_input_enabled=True,
        workdir="/home/newton/teacher-assistant",
        runner=make_runner("error_with_secret"),
        which=lambda _command: "/usr/bin/codex",
    )
    monkeypatch.setattr(answer_regions_route, "get_settings", lambda: settings)
    monkeypatch.setattr(
        answer_regions_route,
        "get_codex_answer_region_suggestion_provider",
        lambda _settings: provider,
    )

    response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "codex_cli_answer_region_suggester"},
    )

    assert response.status_code == 502
    assert "Codex answer-region suggestion provider failed" in response.text
    assert "sk-SECRET-123" not in response.text
    assert "data:image/png;base64" not in response.text
