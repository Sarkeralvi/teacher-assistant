from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    Assessment,
    Course,
    ExtractionRun,
    QuestionNode,
    RubricExtractionCriterion,
    User,
)

CLEANUP_MODELS = (
    QuestionNode,
    RubricExtractionCriterion,
    ExtractionRun,
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


@pytest.fixture()
def assessment(client: TestClient) -> dict[str, object]:
    user_response = client.post(
        "/users", json={"name": "Teacher", "email": f"extract-{uuid4().hex}@example.com"}
    )
    assert user_response.status_code == 201
    course_response = client.post(
        "/courses",
        json={"teacher_id": user_response.json()["id"], "code": "PHY101", "title": "Physics"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "20.00"},
    )
    assert assessment_response.status_code == 201
    return assessment_response.json()


QUESTION_TEXT = (
    "Q1. Answer the following. [10 marks]\n"
    "Q1(a). What is 2 + 2? [4 marks]\n"
    "Q1(b). Explain why addition is useful. [6 marks]\n"
)
RUBRIC_TEXT = (
    "Q1(a): Correct answer 4 marks.\n"
    "Q1(b): Clear explanation 6 marks.\n"
)


def make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=420, height=240)
    y = 40
    for line in text.splitlines():
        page.insert_text((20, y), line)
        y += 30
    doc.save(path)
    doc.close()


def test_provider_disabled_blocks_extraction_run(
    client: TestClient,
    assessment: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_EXTRACTION_ENABLED", "false")
    monkeypatch.setenv("CODEX_EXTRACTION_PROVIDER", "host_bridge_codex")
    get_settings.cache_clear()
    paper_path = tmp_path / "paper.pdf"
    make_pdf(paper_path, QUESTION_TEXT)

    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/extraction-runs",
            data={"extraction_type": "question_paper", "provider": "host_bridge_codex"},
            files={"file": ("paper.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "disabled"
    assert payload["status"] == "blocked"
    assert "disabled" in payload["blockers"][0].lower()


def test_mock_question_extraction_run_stores_raw_and_normalized_output(
    client: TestClient,
    assessment: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("CODEX_EXTRACTION_PROVIDER", "mock")
    get_settings.cache_clear()
    paper_path = tmp_path / "paper.pdf"
    make_pdf(paper_path, QUESTION_TEXT)

    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/extraction-runs",
            data={"extraction_type": "question_paper", "provider": "mock"},
            files={"file": ("paper.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "mock"
    assert payload["status"] == "succeeded"
    assert payload["raw_output"]
    assert payload["normalized_output"]
    assert payload["normalized_output"]["question_nodes"][0]["question_number"] == "Q1"

    nodes = client.get(f"/assessments/{assessment['id']}/question-nodes")
    assert nodes.status_code == 200
    numbers = [node["question_number"] for node in nodes.json()]
    assert numbers == ["Q1", "Q1(a)", "Q1(b)"]


def test_mock_rubric_extraction_run_stores_linked_criteria(
    client: TestClient,
    assessment: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("CODEX_EXTRACTION_PROVIDER", "mock")
    get_settings.cache_clear()
    rubric_path = tmp_path / "rubric.pdf"
    make_pdf(rubric_path, RUBRIC_TEXT)

    with rubric_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/extraction-runs",
            data={"extraction_type": "rubric", "provider": "mock"},
            files={"file": ("rubric.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "succeeded"
    assert payload["normalized_output"]["criteria"][0]["question_number"] == "Q1(a)"

    criteria = client.get(f"/assessments/{assessment['id']}/rubric-extraction-criteria")
    assert criteria.status_code == 200
    assert [item["question_number"] for item in criteria.json()] == ["Q1(a)", "Q1(b)"]
