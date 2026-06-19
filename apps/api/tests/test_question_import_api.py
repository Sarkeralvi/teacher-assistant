from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz
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
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    QuestionImportJob,
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
    QuestionImportJob,
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


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_teacher(client: TestClient, name: str = "Teacher") -> dict[str, Any]:
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": f"qimport-{uuid4().hex}@example.com",
            "password": "question-import-pass",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_assessment(client: TestClient) -> dict[str, Any]:
    teacher = create_teacher(client)
    token = str(teacher["access_token"])
    user = teacher["user"]
    assert isinstance(user, dict)
    headers = auth_headers(token)
    course_response = client.post(
        "/courses",
        headers=headers,
        json={"teacher_id": user["id"], "code": "PHY101", "title": "Physics"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=headers,
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "20.00"},
    )
    assert assessment_response.status_code == 201
    return {"assessment": assessment_response.json(), "headers": headers, "teacher": user}


def make_question_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=420, height=220)
    page.insert_text((20, 40), "Q1. Define velocity. [5 marks]")
    page.insert_text((20, 80), "Question 2: Explain acceleration. (3)")
    page.insert_text((20, 120), "3) State Newton's first law. 2 marks")
    doc.save(path)
    doc.close()


def make_png(path: Path) -> None:
    Image.new("RGB", (80, 40), color="white").save(path, format="PNG")


def test_question_import_rejects_unauthenticated_request(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    paper_path = tmp_path / "question-paper.pdf"
    make_question_pdf(paper_path)

    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            files={"file": ("question-paper.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 401


def test_question_import_rejects_authenticated_non_owner(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    other_teacher = create_teacher(client, name="Other Teacher")
    other_headers = auth_headers(str(other_teacher["access_token"]))
    paper_path = tmp_path / "question-paper.pdf"
    make_question_pdf(paper_path)

    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=other_headers,
            files={"file": ("question-paper.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 404


def test_owner_unsupported_question_import_provider_preserves_provider_error(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    image_path = tmp_path / "paper.png"
    make_png(image_path)

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            data={"provider": "gpt-5.5"},
            files={"file": ("paper.png", file_obj, "image/png")},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Unsupported question import provider: gpt-5.5"


def test_upload_question_paper_creates_import_job_and_drafts(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    paper_path = tmp_path / "question-paper.pdf"
    make_question_pdf(paper_path)

    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            files={"file": ("question-paper.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 201
    job = response.json()
    assert job["assessment_id"] == assessment["id"]
    assert job["status"] == "drafted"
    assert job["provider"] == "mock"
    assert job["original_filename"] == "question-paper.pdf"
    assert not job["file_path"].startswith("/")
    assert ".." not in job["file_path"]
    assert len(job["draft_questions"]) == 3
    assert job["draft_questions"][0] == {
        "draft_id": "draft-1",
        "question_no": "1",
        "question_text": "Define velocity.",
        "model_answer": None,
        "total_marks": "5.00",
        "confidence": "0.80",
        "source_page": 1,
        "source_text_excerpt": "Q1. Define velocity. [5 marks]",
        "needs_review": True,
    }

    detail = client.get(f"/question-imports/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["draft_questions"] == job["draft_questions"]


def test_drafts_are_not_saved_until_selected_drafts_are_accepted(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    paper_path = tmp_path / "question-paper.pdf"
    make_question_pdf(paper_path)
    with paper_path.open("rb") as file_obj:
        job_response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            files={"file": ("question-paper.pdf", file_obj, "application/pdf")},
        )
    assert job_response.status_code == 201
    job = job_response.json()

    assert client.get(f"/assessments/{assessment['id']}/questions").json() == []

    accept_response = client.post(
        f"/question-imports/{job['id']}/accept",
        json={
            "draft_questions": [
                {
                    "draft_id": "draft-1",
                    "question_no": "1A",
                    "question_text": "Edited velocity question",
                    "model_answer": "Rate of displacement change.",
                    "total_marks": "6.00",
                },
                {
                    "draft_id": "draft-3",
                    "question_no": "3",
                    "question_text": "State Newton's first law.",
                    "model_answer": None,
                    "total_marks": "2.00",
                },
            ]
        },
    )

    assert accept_response.status_code == 201
    accepted = accept_response.json()
    assert accepted["created_count"] == 2
    assert len(accepted["questions"]) == 2
    assert accepted["questions"][0]["question_no"] == "1A"
    assert accepted["questions"][0]["question_text"] == "Edited velocity question"
    assert accepted["questions"][0]["model_answer"] == "Rate of displacement change."
    assert accepted["questions"][0]["total_marks"] == "6.00"

    listed = client.get(f"/assessments/{assessment['id']}/questions").json()
    assert [question["question_no"] for question in listed] == ["1A", "3"]
    detail = client.get(f"/question-imports/{job['id']}").json()
    assert detail["status"] == "accepted"


def test_question_import_validation_errors(client: TestClient, tmp_path: Path) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    missing = client.post(
        "/assessments/999999/question-imports",
        headers=headers,
        files={"file": ("question-paper.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert missing.status_code == 404

    unsupported = client.post(
        f"/assessments/{assessment['id']}/question-imports",
        headers=headers,
        files={"file": ("question-paper.txt", b"Q1 text", "text/plain")},
    )
    assert unsupported.status_code == 415

    image_path = tmp_path / "paper.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        image_response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            files={"file": ("paper.png", file_obj, "image/png")},
        )
    assert image_response.status_code == 201
    assert image_response.json()["draft_questions"][0]["needs_review"] is True

    unknown_job = client.get("/question-imports/999999")
    assert unknown_job.status_code == 404


def test_question_import_does_not_expose_sensitive_or_call_codex(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    paper_path = tmp_path / "question-paper.pdf"
    make_question_pdf(paper_path)
    with paper_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            files={"file": ("question-paper.pdf", file_obj, "application/pdf")},
        )

    body = response.text.lower()
    assert response.status_code == 201
    assert "password_hash" not in body
    assert "raw_response_json" not in body
    assert response.json()["provider"] == "mock"


def test_real_codex_provider_request_rejected_when_not_enabled(
    client: TestClient, tmp_path: Path
) -> None:
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    image_path = tmp_path / "paper.png"
    make_png(image_path)

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            data={"provider": "codex_cli_question_extractor"},
            files={"file": ("paper.png", file_obj, "image/png")},
        )

    assert response.status_code == 403
    assert "explicitly enabled" in response.json()["detail"]


def test_image_upload_routed_to_enabled_codex_provider_with_warnings(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import question_imports
    from app.schemas import DraftQuestion
    from app.services.question_import_extractor import QuestionExtractionResult

    class FakeCodexExtractor:
        provider = "codex_cli_question_extractor"

        def extract(self, file_path: Path, content_type: str) -> QuestionExtractionResult:
            assert file_path.is_file()
            assert content_type == "image/png"
            return QuestionExtractionResult(
                draft_questions=[
                    DraftQuestion(
                        draft_id="draft-1",
                        question_no="1",
                        question_text="Synthetic image question",
                        model_answer=None,
                        total_marks="5.00",
                        confidence="0.90",
                        source_page=1,
                        source_text_excerpt="Q1. Synthetic image question [5 marks]",
                        needs_review=True,
                    )
                ],
                warnings=["fake codex warning"],
            )

    def fake_build_question_extractor(*, settings, requested_provider=None):
        assert settings.codex_question_extraction_enabled is True
        assert requested_provider == "codex_cli_question_extractor"
        return FakeCodexExtractor()

    monkeypatch.setenv("CODEX_QUESTION_EXTRACTION_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(question_imports, "build_question_extractor", fake_build_question_extractor)
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    image_path = tmp_path / "paper.png"
    make_png(image_path)

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            data={"provider": "codex_cli_question_extractor"},
            files={"file": ("paper.png", file_obj, "image/png")},
        )

    assert response.status_code == 201
    job = response.json()
    assert job["provider"] == "codex_cli_question_extractor"
    assert job["provider_warnings"] == ["fake codex warning"]
    assert len(job["draft_questions"]) == 1
    assert job["draft_questions"][0]["needs_review"] is True
    assert client.get(f"/assessments/{assessment['id']}/questions").json() == []


def test_provider_failure_stores_actionable_job_error(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import question_imports
    from app.services.question_import_extractor import CodexQuestionExtractionError

    class FailingCodexExtractor:
        provider = "codex_cli_question_extractor"

        def extract(self, file_path: Path, content_type: str):
            raise CodexQuestionExtractionError(
                "Codex question extraction output schema validation failed; "
                "top-level keys: questions, warnings; questions count=0; "
                "validation errors: questions: too_short - List should have at least 1 item"
            )

    def fake_build_question_extractor(*, settings, requested_provider=None):
        assert requested_provider == "codex_cli_question_extractor"
        return FailingCodexExtractor()

    monkeypatch.setenv("CODEX_QUESTION_EXTRACTION_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(question_imports, "build_question_extractor", fake_build_question_extractor)
    owned = create_assessment(client)
    assessment = owned["assessment"]
    headers = owned["headers"]
    image_path = tmp_path / "paper.png"
    make_png(image_path)

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/question-imports",
            headers=headers,
            data={"provider": "codex_cli_question_extractor"},
            files={"file": ("paper.png", file_obj, "image/png")},
        )

    assert response.status_code == 502
    assert "questions count=0" in response.json()["detail"]

    with SessionLocal() as db:
        job = db.query(QuestionImportJob).filter_by(assessment_id=assessment["id"]).one()
        assert job.status == "failed"
        assert "questions count=0" in str(job.error)
        assert job.provider_warnings == [job.error]
