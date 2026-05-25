from collections.abc import Iterator
from pathlib import Path

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
    Question,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)

CLEANUP_MODELS = (
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


def create_assessment(client: TestClient) -> dict[str, object]:
    user_response = client.post("/users", json={"name": "Teacher", "email": "upload@example.com"})
    assert user_response.status_code == 201
    course_response = client.post(
        "/courses",
        json={"teacher_id": user_response.json()["id"], "code": "BIO101", "title": "Biology"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "20.00"},
    )
    assert assessment_response.status_code == 201
    return assessment_response.json()


def make_png(path: Path) -> None:
    Image.new("RGB", (32, 24), color="white").save(path, format="PNG")


def make_pdf(path: Path, pages: int = 2) -> None:
    doc = fitz.open()
    for page_no in range(1, pages + 1):
        page = doc.new_page(width=120, height=80)
        page.insert_text((10, 30), f"Page {page_no}")
    doc.save(path)
    doc.close()


def test_upload_image_creates_submission_and_one_page(client: TestClient, tmp_path: Path) -> None:
    assessment = create_assessment(client)
    image_path = tmp_path / "answer.png"
    make_png(image_path)

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-001", "student_name": "Student One"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )

    assert response.status_code == 201
    submission = response.json()
    assert submission["assessment_id"] == assessment["id"]
    assert submission["student_identifier"] == "S-001"
    assert submission["student_name"] == "Student One"
    assert submission["status"] == "uploaded"
    assert len(submission["pages"]) == 1
    page = submission["pages"][0]
    assert page["page_no"] == 1
    assert page["quality_score"] is None
    assert not page["image_path"].startswith("/")
    assert ".." not in page["image_path"]

    detail = client.get(f"/submissions/{submission['id']}")
    assert detail.status_code == 200
    assert detail.json()["pages"] == submission["pages"]

    image_response = client.get(f"/submission-pages/{page['id']}/image")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.content.startswith(b"\x89PNG")

    listed = client.get(f"/assessments/{assessment['id']}/submissions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [submission["id"]]


def test_upload_pdf_extracts_page_images(client: TestClient, tmp_path: Path) -> None:
    assessment = create_assessment(client)
    pdf_path = tmp_path / "answers.pdf"
    make_pdf(pdf_path, pages=2)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-002"},
            files={"file": ("answers.pdf", file_obj, "application/pdf")},
        )

    assert response.status_code == 201
    submission = response.json()
    assert len(submission["pages"]) == 2
    assert [page["page_no"] for page in submission["pages"]] == [1, 2]
    assert all(page["image_path"].endswith(".png") for page in submission["pages"])
    assert all(not page["image_path"].startswith("/") for page in submission["pages"])


def test_upload_validation_errors(client: TestClient, tmp_path: Path) -> None:
    image_path = tmp_path / "answer.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        missing_assessment = client.post(
            "/assessments/999999/submissions/upload",
            data={"student_identifier": "S-404"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert missing_assessment.status_code == 404

    assessment = create_assessment(client)
    text_path = tmp_path / "answer.txt"
    text_path.write_text("not supported", encoding="utf-8")
    with text_path.open("rb") as file_obj:
        unsupported = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-415"},
            files={"file": ("answer.txt", file_obj, "text/plain")},
        )
    assert unsupported.status_code == 415

    assert client.get("/submissions/999999").status_code == 404
