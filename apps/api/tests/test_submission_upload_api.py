from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.routes import submissions as submission_routes
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


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_assessment(client: TestClient) -> dict[str, object]:
    auth_response = client.post(
        "/auth/register",
        json={
            "name": "Teacher",
            "email": f"upload-{uuid4().hex}@example.com",
            "password": "UploadPassword-123!",
        },
    )
    assert auth_response.status_code == 201
    token = auth_response.json()["access_token"]
    course_response = client.post(
        "/courses",
        headers=auth_header(token),
        json={"code": "BIO101", "title": "Biology"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=auth_header(token),
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "20.00"},
    )
    assert assessment_response.status_code == 201
    assessment = assessment_response.json()
    assessment["auth_headers"] = auth_header(token)
    return assessment


def make_png(path: Path) -> None:
    Image.new("RGB", (32, 24), color="white").save(path, format="PNG")


def make_jpeg(path: Path) -> None:
    Image.new("RGB", (32, 24), color="white").save(path, format="JPEG")


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
            headers=assessment["auth_headers"],
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

    detail = client.get(f"/submissions/{submission['id']}", headers=assessment["auth_headers"])
    assert detail.status_code == 200
    assert detail.json()["pages"] == submission["pages"]

    image_response = client.get(
        f"/submission-pages/{page['id']}/image",
        headers=assessment["auth_headers"],
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.content.startswith(b"\x89PNG")

    listed = client.get(
        f"/assessments/{assessment['id']}/submissions",
        headers=assessment["auth_headers"],
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [submission["id"]]


def test_upload_jpg_and_jpeg_images_create_single_page(client: TestClient, tmp_path: Path) -> None:
    assessment = create_assessment(client)
    for suffix, student_identifier in (("jpg", "S-JPG"), ("jpeg", "S-JPEG")):
        image_path = tmp_path / f"answer.{suffix}"
        make_jpeg(image_path)

        with image_path.open("rb") as file_obj:
            response = client.post(
                f"/assessments/{assessment['id']}/submissions/upload",
                headers=assessment["auth_headers"],
                data={"student_identifier": student_identifier},
                files={"file": (f"answer.{suffix}", file_obj, "image/jpeg")},
            )

        assert response.status_code == 201
        submission = response.json()
        assert submission["student_identifier"] == student_identifier
        assert len(submission["pages"]) == 1
        page_response = client.get(
            f"/submission-pages/{submission['pages'][0]['id']}/image",
            headers=assessment["auth_headers"],
        )
        assert page_response.status_code == 200
        assert page_response.headers["content-type"] == "image/png"


def test_upload_pdf_extracts_page_images(client: TestClient, tmp_path: Path) -> None:
    assessment = create_assessment(client)
    pdf_path = tmp_path / "answers.pdf"
    make_pdf(pdf_path, pages=2)

    with pdf_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            headers=assessment["auth_headers"],
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
    assessment = create_assessment(client)
    image_path = tmp_path / "answer.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        missing_assessment = client.post(
            "/assessments/999999/submissions/upload",
            headers=assessment["auth_headers"],
            data={"student_identifier": "S-404"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert missing_assessment.status_code == 404

    text_path = tmp_path / "answer.txt"
    text_path.write_text("not supported", encoding="utf-8")
    with text_path.open("rb") as file_obj:
        unsupported = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            headers=assessment["auth_headers"],
            data={"student_identifier": "S-415"},
            files={"file": ("answer.txt", file_obj, "text/plain")},
        )
    assert unsupported.status_code == 415

    assert client.get("/submissions/999999", headers=assessment["auth_headers"]).status_code == 404


def test_delete_submission_removes_existing_submission_and_related_rows(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    assessment = create_assessment(client)
    question_response = client.post(
        f"/assessments/{assessment['id']}/questions",
        headers=assessment["auth_headers"],
        json={"question_no": "1", "question_text": "Explain.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    image_path = tmp_path / "delete-me.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        upload_response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            headers=assessment["auth_headers"],
            data={"student_identifier": "S-DEL"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert upload_response.status_code == 201
    submission = upload_response.json()
    page_id = submission["pages"][0]["id"]
    region_response = client.post(
        f"/submission-pages/{page_id}/answer-regions",
        headers=assessment["auth_headers"],
        json={
            "question_id": question_response.json()["id"],
            "x": 1,
            "y": 2,
            "width": 20,
            "height": 20,
        },
    )
    assert region_response.status_code == 201

    response = client.delete(
        f"/assessments/{assessment['id']}/submissions/{submission['id']}",
        headers=assessment["auth_headers"],
    )

    assert response.status_code == 204
    assert (
        client.get(
            f"/submissions/{submission['id']}", headers=assessment["auth_headers"]
        ).status_code
        == 404
    )
    assert client.get(
        f"/submission-pages/{page_id}/image", headers=assessment["auth_headers"]
    ).status_code == 404
    assert db_session.get(Submission, submission["id"]) is None
    assert db_session.get(SubmissionPage, page_id) is None
    assert db_session.get(AnswerRegion, region_response.json()["id"]) is None


def test_delete_submission_missing_or_wrong_assessment_returns_404(
    client: TestClient, tmp_path: Path
) -> None:
    assessment = create_assessment(client)
    other_assessment = create_assessment(client)
    image_path = tmp_path / "wrong-assessment.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        upload_response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            headers=assessment["auth_headers"],
            data={"student_identifier": "S-WRONG"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert upload_response.status_code == 201

    assert (
        client.delete(
            f"/assessments/{assessment['id']}/submissions/999999",
            headers=assessment["auth_headers"],
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/assessments/{other_assessment['id']}/submissions/{upload_response.json()['id']}",
            headers=other_assessment["auth_headers"],
        ).status_code
        == 404
    )


def test_delete_submission_ignores_unsafe_stored_paths(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    assessment = create_assessment(client)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("keep me", encoding="utf-8")
    submission = Submission(
        assessment_id=assessment["id"],
        student_identifier="S-TRAVERSAL",
        status="uploaded",
    )
    db_session.add(submission)
    db_session.flush()
    page = SubmissionPage(
        submission_id=submission.id,
        page_no=1,
        image_path="../outside.txt",
    )
    db_session.add(page)
    db_session.commit()
    submission_id = submission.id

    response = client.delete(
        f"/assessments/{assessment['id']}/submissions/{submission_id}",
        headers=assessment["auth_headers"],
    )

    assert response.status_code == 204
    assert outside_file.read_text(encoding="utf-8") == "keep me"
    db_session.expire_all()
    assert db_session.get(Submission, submission_id) is None


def make_zip(path: Path, entries: dict[str, bytes]) -> None:
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def read_png_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_upload_zip_creates_multiple_submissions_and_pages(
    client: TestClient, tmp_path: Path
) -> None:
    assessment = create_assessment(client)
    png_path = tmp_path / "student_003.png"
    jpg_path = tmp_path / "student_004.jpg"
    pdf_path = tmp_path / "student_001.pdf"
    make_png(png_path)
    make_jpeg(jpg_path)
    make_pdf(pdf_path, pages=2)
    zip_path = tmp_path / "scripts.zip"
    make_zip(
        zip_path,
        {
            "student_001.pdf": pdf_path.read_bytes(),
            "student_003.png": png_path.read_bytes(),
            "student_004.jpg": jpg_path.read_bytes(),
        },
    )

    with zip_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload-zip",
            headers=assessment["auth_headers"],
            data={"student_identifier_strategy": "basename"},
            files={"file": ("scripts.zip", file_obj, "application/zip")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["assessment_id"] == assessment["id"]
    assert body["requested_file_count"] == 3
    assert body["imported_count"] == 3
    assert body["skipped_count"] == 0
    assert body["failed_count"] == 0
    assert body["errors"] == []
    assert [item["student_identifier"] for item in body["submissions_created"]] == [
        "student_001",
        "student_003",
        "student_004",
    ]
    assert [len(item["pages"]) for item in body["submissions_created"]] == [2, 1, 1]
    for submission in body["submissions_created"]:
        for page in submission["pages"]:
            assert not page["image_path"].startswith("/")
            assert ".." not in page["image_path"]
            image_response = client.get(
        f"/submission-pages/{page['id']}/image",
        headers=assessment["auth_headers"],
    )
            assert image_response.status_code == 200
            assert image_response.content.startswith(b"\x89PNG")

    listed = client.get(
        f"/assessments/{assessment['id']}/submissions",
        headers=assessment["auth_headers"],
    )
    assert listed.status_code == 200
    assert [item["student_identifier"] for item in listed.json()] == [
        "student_001",
        "student_003",
        "student_004",
    ]


def test_upload_zip_supports_generated_sequential_identifiers(
    client: TestClient, tmp_path: Path
) -> None:
    assessment = create_assessment(client)
    image_path = tmp_path / "answer.png"
    make_png(image_path)
    zip_path = tmp_path / "scripts.zip"
    make_zip(zip_path, {"alpha.png": image_path.read_bytes(), "beta.png": image_path.read_bytes()})

    with zip_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload-zip",
            headers=assessment["auth_headers"],
            data={"student_identifier_strategy": "sequential", "student_name_prefix": "Student"},
            files={"file": ("scripts.zip", file_obj, "application/zip")},
        )

    assert response.status_code == 201
    submissions = response.json()["submissions_created"]
    assert [item["student_identifier"] for item in submissions] == ["S-001", "S-002"]
    assert [item["student_name"] for item in submissions] == ["Student 001", "Student 002"]


def test_upload_zip_reports_unsupported_and_path_traversal_without_extracting(
    client: TestClient, tmp_path: Path
) -> None:
    assessment = create_assessment(client)
    image_path = tmp_path / "valid.png"
    make_png(image_path)
    outside_marker = tmp_path / "escape.png"
    zip_path = tmp_path / "mixed.zip"
    make_zip(
        zip_path,
        {
            "valid.png": image_path.read_bytes(),
            "notes.txt": b"unsupported",
            "../escape.png": b"should not extract",
            "/abs.png": b"absolute path",
        },
    )

    with zip_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload-zip",
            headers=assessment["auth_headers"],
            files={"file": ("mixed.zip", file_obj, "application/zip")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["requested_file_count"] == 4
    assert body["imported_count"] == 1
    assert body["skipped_count"] == 1
    assert body["failed_count"] == 2
    assert any("Unsupported file type" in warning for warning in body["warnings"])
    assert any("Unsafe ZIP path" in error for error in body["errors"])
    assert not outside_marker.exists()


def test_upload_zip_invalid_zip_and_missing_assessment_errors(
    client: TestClient, tmp_path: Path
) -> None:
    assessment = create_assessment(client)
    invalid_zip = tmp_path / "invalid.zip"
    invalid_zip.write_bytes(b"not a zip")
    with invalid_zip.open("rb") as file_obj:
        response = client.post(
            "/assessments/999999/submissions/upload-zip",
            headers=assessment["auth_headers"],
            files={"file": ("invalid.zip", file_obj, "application/zip")},
        )
    assert response.status_code == 404

    with invalid_zip.open("rb") as file_obj:
        invalid = client.post(
            f"/assessments/{assessment['id']}/submissions/upload-zip",
            headers=assessment["auth_headers"],
            files={"file": ("invalid.zip", file_obj, "application/zip")},
        )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Uploaded file is not a valid ZIP archive"


def test_upload_failure_cleans_uncommitted_submission_artifacts(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = create_assessment(client)
    image_path = tmp_path / "answer.png"
    make_png(image_path)

    def fail_extraction(**_kwargs: object) -> list[str]:
        raise RuntimeError("synthetic extraction failure")

    monkeypatch.setattr(submission_routes, "extract_page_images", fail_extraction)
    with image_path.open("rb") as file_obj:
        with pytest.raises(RuntimeError, match="synthetic extraction failure"):
            client.post(
                f"/assessments/{assessment['id']}/submissions/upload",
                headers=assessment["auth_headers"],
                data={"student_identifier": "S-cleanup"},
                files={"file": ("answer.png", file_obj, "image/png")},
            )

    db_session.expire_all()
    assert db_session.query(Submission).count() == 0
    assert list((tmp_path / "storage" / "uploads" / "submissions").glob("*")) == []
    assert list((tmp_path / "storage" / "artifacts" / "pages").glob("*")) == []


def test_upload_zip_rejects_excessive_total_uncompressed_size(
    client: TestClient, tmp_path: Path, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    assessment = create_assessment(client)
    image_path = tmp_path / "answer.png"
    make_png(image_path)
    zip_path = tmp_path / "oversized-total.zip"
    make_zip(
        zip_path,
        {"one.png": image_path.read_bytes(), "two.png": image_path.read_bytes()},
    )
    monkeypatch.setattr(submission_routes, "MAX_ZIP_UNCOMPRESSED_BYTES", 100)

    with zip_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload-zip",
            headers=assessment["auth_headers"],
            files={"file": ("oversized-total.zip", file_obj, "application/zip")},
        )

    assert response.status_code == 413
    assert "uncompressed size" in response.json()["detail"]
    assert db_session.query(Submission).count() == 0
