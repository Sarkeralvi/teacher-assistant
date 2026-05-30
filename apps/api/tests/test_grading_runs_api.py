from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
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
    GradingRun,
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
    GradingRun,
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


def register_teacher(
    client: TestClient, email_prefix: str = "run"
) -> tuple[dict[str, object], str]:
    response = client.post(
        "/auth/register",
        json={
            "name": "Teacher",
            "email": f"{email_prefix}-{uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["user"], body["access_token"]


def create_assessment_for_teacher(client: TestClient, teacher_id: int) -> dict[str, object]:
    course_response = client.post(
        "/courses",
        json={"teacher_id": teacher_id, "code": "MATH101", "title": "Math"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Midterm", "assessment_type": "exam", "total_marks": "50.00"},
    )
    assert assessment_response.status_code == 201
    return assessment_response.json()


def test_create_and_list_custom_grading_run_requires_auth_and_assessment_scope(
    client: TestClient,
) -> None:
    teacher, token = register_teacher(client)
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))

    unauthenticated = client.post(f"/assessments/{assessment['id']}/grading-runs/custom")
    assert unauthenticated.status_code == 401

    response = client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers={"Authorization": f"Bearer {token}"},
        json={"notes": "Teacher will provide solution and rubric PDFs."},
    )

    assert response.status_code == 201
    run = response.json()
    assert run["assessment_id"] == assessment["id"]
    assert run["created_by_teacher_id"] == teacher["id"]
    assert run["mode"] == "custom_controlled"
    assert run["status"] == "draft"
    assert run["notes"] == "Teacher will provide solution and rubric PDFs."
    assert run["question_pdf_path"] is None
    assert run["solution_pdf_path"] is None
    assert run["rubric_pdf_path"] is None

    listed = client.get(
        f"/assessments/{assessment['id']}/grading-runs",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert [item["id"] for item in listed] == [run["id"]]

    detail = client.get(
        f"/grading-runs/{run['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == run["id"]



def test_create_custom_grading_run_missing_assessment_returns_404(client: TestClient) -> None:
    _, token = register_teacher(client)

    response = client.post(
        "/assessments/999999/grading-runs/custom",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_upload_materials_stores_safe_relative_pdf_paths_and_updates_status(
    client: TestClient,
) -> None:
    teacher, token = register_teacher(client)
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    run_response = client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers={"Authorization": f"Bearer {token}"},
    )
    run_id = run_response.json()["id"]

    response = client.post(
        f"/grading-runs/{run_id}/materials",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "question_pdf": ("question.pdf", b"%PDF-1.4\n%question", "application/pdf"),
            "solution_pdf": ("solution.pdf", b"%PDF-1.4\n%solution", "application/pdf"),
            "rubric_pdf": ("rubric.pdf", b"%PDF-1.4\n%rubric", "application/pdf"),
        },
    )

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "materials_uploaded"
    for field in ("question_pdf_path", "solution_pdf_path", "rubric_pdf_path"):
        value = run[field]
        assert isinstance(value, str)
        assert value.endswith(".pdf")
        assert not value.startswith("/")
        assert ".." not in Path(value).parts
        stored_path = Path(get_settings().local_storage_root) / value
        assert stored_path.exists()


def test_material_upload_rejects_non_pdf_and_wrong_teacher(client: TestClient) -> None:
    owner, owner_token = register_teacher(client, "owner")
    assessment = create_assessment_for_teacher(client, int(owner["id"]))
    run = client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    _, other_token = register_teacher(client, "other")

    wrong_teacher = client.post(
        f"/grading-runs/{run['id']}/materials",
        headers={"Authorization": f"Bearer {other_token}"},
        files={"question_pdf": ("question.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert wrong_teacher.status_code == 404

    unsupported = client.post(
        f"/grading-runs/{run['id']}/materials",
        headers={"Authorization": f"Bearer {owner_token}"},
        files={"question_pdf": ("question.txt", b"not a pdf", "text/plain")},
    )
    assert unsupported.status_code == 415

    traversal_name = client.post(
        f"/grading-runs/{run['id']}/materials",
        headers={"Authorization": f"Bearer {owner_token}"},
        files={"question_pdf": ("../../question.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert traversal_name.status_code == 200
    assert ".." not in Path(traversal_name.json()["question_pdf_path"]).parts


def test_status_update_allows_controlled_workflow_statuses(client: TestClient) -> None:
    teacher, token = register_teacher(client)
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    run = client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    response = client.patch(
        f"/grading-runs/{run['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "questions_ready", "notes": "Questions and rubrics confirmed."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "questions_ready"
    assert response.json()["notes"] == "Questions and rubrics confirmed."

    invalid = client.patch(
        f"/grading-runs/{run['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "fully_automated"},
    )
    assert invalid.status_code == 422
