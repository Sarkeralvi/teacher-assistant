from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

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
    GradingRun,
    Question,
    QuestionImportJob,
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


def register_teacher(client: TestClient, prefix: str) -> tuple[dict[str, object], str]:
    response = client.post(
        "/auth/register",
        json={
            "name": f"{prefix} Teacher",
            "email": f"{prefix}-{uuid4().hex}@example.test",
            "password": "PrivacyBaseline-123!",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["user"], body["access_token"]


def create_owned_assessment(client: TestClient, token: str) -> dict[str, object]:
    course_response = client.post(
        "/courses",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "PRIV101", "title": "Privacy Baseline"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Synthetic exam", "assessment_type": "exam", "total_marks": "10.00"},
    )
    assert assessment_response.status_code == 201
    return assessment_response.json()


def write_storage_file(root: Path, relative_path: str, content: bytes = b"synthetic") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def seed_sensitive_assessment_graph(
    db: Session, assessment_id: int, teacher_id: int, storage_root: Path
) -> dict[str, object]:
    question = Question(
        assessment_id=assessment_id,
        question_no="1",
        question_text="Synthetic question",
        model_answer="Synthetic model answer",
        total_marks=Decimal("10.00"),
    )
    db.add(question)
    db.flush()
    db.add(
        Rubric(
            question_id=question.id,
            version=1,
            is_active=True,
            rubric_json={"total_marks": 10, "criteria": []},
        )
    )

    submission = Submission(
        assessment_id=assessment_id,
        student_identifier="SYN-001",
        student_name="Synthetic Student",
        status="ready",
    )
    db.add(submission)
    db.flush()

    upload_path = f"uploads/submissions/{submission.id}/original-synthetic.png"
    page_path = f"artifacts/pages/submission_{submission.id}/page_0001.png"
    region_path = f"artifacts/answer_regions/submission_{submission.id}/region_synthetic.png"
    for relative_path in (upload_path, page_path, region_path):
        write_storage_file(storage_root, relative_path)

    page = SubmissionPage(submission_id=submission.id, page_no=1, image_path=page_path)
    db.add(page)
    db.flush()

    region = AnswerRegion(
        submission_id=submission.id,
        question_id=question.id,
        page_id=page.id,
        x=Decimal("1.00"),
        y=Decimal("1.00"),
        width=Decimal("10.00"),
        height=Decimal("10.00"),
        image_path=region_path,
    )
    db.add(region)
    db.flush()

    grading_job = GradingJob(answer_region_id=region.id, status="completed")
    db.add(grading_job)
    db.flush()

    suggestion = GradeSuggestion(
        grading_job_id=grading_job.id,
        answer_region_id=region.id,
        question_id=question.id,
        model_provider="mock",
        model_name="mock-grader-v1",
        prompt_version="test",
        marking_policy="general",
        raw_response_json={"synthetic": True},
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
        confidence=Decimal("0.9000"),
        needs_review=True,
        feedback="Synthetic feedback",
    )
    db.add(suggestion)
    db.flush()

    final_grade = FinalGrade(
        answer_region_id=region.id,
        teacher_id=teacher_id,
        suggestion_id=suggestion.id,
        final_score=Decimal("8.00"),
        approval_status="approved",
    )
    db.add(final_grade)

    grading_run = GradingRun(
        assessment_id=assessment_id,
        created_by_teacher_id=teacher_id,
        mode="custom_controlled",
        status="review_ready",
        marking_policy="general",
        question_pdf_path=f"uploads/grading_runs/{assessment_id}/question.pdf",
        solution_pdf_path=f"uploads/grading_runs/{assessment_id}/solution.pdf",
        rubric_pdf_path=f"uploads/grading_runs/{assessment_id}/rubric.pdf",
    )
    db.add(grading_run)
    for relative_path in (
        grading_run.question_pdf_path,
        grading_run.solution_pdf_path,
        grading_run.rubric_pdf_path,
    ):
        assert relative_path is not None
        write_storage_file(storage_root, relative_path, b"%PDF-1.4 synthetic")

    question_import_path = f"uploads/question_imports/{assessment_id}/question-paper.pdf"
    write_storage_file(storage_root, question_import_path, b"%PDF-1.4 synthetic")
    db.add(
        QuestionImportJob(
            assessment_id=assessment_id,
            status="uploaded",
            original_filename="question-paper.pdf",
            content_type="application/pdf",
            file_path=question_import_path,
            provider="mock",
            draft_questions=[],
            provider_warnings=[],
        )
    )
    db.commit()

    return {
        "question_id": question.id,
        "submission_id": submission.id,
        "page_id": page.id,
        "answer_region_id": region.id,
        "suggestion_id": suggestion.id,
        "final_grade_id": final_grade.id,
        "stored_paths": [upload_path, page_path, region_path, question_import_path],
    }


def count_rows(db: Session, model: type[object]) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_teacher_can_delete_own_assessment_test_data_and_files(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "privacy-owner")
    assessment = create_owned_assessment(client, token)
    storage_root = tmp_path / "storage"
    seeded = seed_sensitive_assessment_graph(
        db_session, int(assessment["id"]), int(teacher["id"]), storage_root
    )

    before_final_grade_count = count_rows(db_session, FinalGrade)
    assert before_final_grade_count == 1
    assert all((storage_root / path).exists() for path in seeded["stored_paths"])

    response = client.delete(
        f"/assessments/{assessment['id']}/test-data",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assessment_id"] == assessment["id"]
    assert body["submissions_deleted"] == 1
    assert body["answer_regions_deleted"] == 1
    assert body["grade_suggestions_deleted"] == 1
    assert body["grading_runs_deleted"] == 1
    assert body["question_imports_deleted"] == 1
    assert body["file_delete_error_count"] == 0
    assert not any(str(storage_root) in str(value) for value in body.values())

    for model in (
        Submission,
        SubmissionPage,
        AnswerRegion,
        GradeSuggestion,
        GradingJob,
        FinalGrade,
        GradingRun,
        QuestionImportJob,
        Rubric,
        Question,
    ):
        assert count_rows(db_session, model) == 0
    assert count_rows(db_session, Assessment) == 1
    assert count_rows(db_session, FinalGrade) == 0
    assert not any((storage_root / path).exists() for path in seeded["stored_paths"])


def test_other_teacher_cannot_delete_assessment_test_data(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    owner, owner_token = register_teacher(client, "privacy-owner")
    _other, other_token = register_teacher(client, "privacy-other")
    assessment = create_owned_assessment(client, owner_token)
    storage_root = tmp_path / "storage"
    seed_sensitive_assessment_graph(
        db_session, int(assessment["id"]), int(owner["id"]), storage_root
    )

    response = client.delete(
        f"/assessments/{assessment['id']}/test-data",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Assessment not found"}
    assert count_rows(db_session, Submission) == 1
    assert count_rows(db_session, FinalGrade) == 1


def test_assessment_test_data_delete_requires_authentication(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "privacy-auth")
    assessment = create_owned_assessment(client, token)
    seed_sensitive_assessment_graph(
        db_session, int(assessment["id"]), int(teacher["id"]), tmp_path / "storage"
    )

    response = client.delete(f"/assessments/{assessment['id']}/test-data")

    assert response.status_code == 401
    assert count_rows(db_session, Submission) == 1
    assert count_rows(db_session, FinalGrade) == 1



def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_submission_privacy_graph(
    db: Session, assessment_id: int, storage_root: Path
) -> dict[str, object]:
    question = Question(
        assessment_id=assessment_id,
        question_no="P1",
        question_text="Synthetic privacy question",
        model_answer="Synthetic model answer",
        total_marks=Decimal("5.00"),
    )
    db.add(question)
    db.flush()

    submission = Submission(
        assessment_id=assessment_id,
        student_identifier="SYN-PRIV",
        student_name="Synthetic Privacy Student",
        status="uploaded",
    )
    db.add(submission)
    db.flush()

    upload_path = f"uploads/submissions/{submission.id}/original-synthetic.png"
    page_path = f"artifacts/pages/submission_{submission.id}/page_0001.png"
    region_path = f"artifacts/answer_regions/submission_{submission.id}/region_synthetic.png"
    context_path = f"artifacts/grading_context/submission_{submission.id}/context_synthetic.png"
    for relative_path in (upload_path, page_path, region_path, context_path):
        write_storage_file(storage_root, relative_path)

    page = SubmissionPage(submission_id=submission.id, page_no=1, image_path=page_path)
    db.add(page)
    db.flush()

    region = AnswerRegion(
        submission_id=submission.id,
        question_id=question.id,
        page_id=page.id,
        x=Decimal("1.00"),
        y=Decimal("1.00"),
        width=Decimal("10.00"),
        height=Decimal("10.00"),
        image_path=region_path,
    )
    db.add(region)
    db.commit()

    return {
        "question_id": question.id,
        "submission_id": submission.id,
        "page_id": page.id,
        "answer_region_id": region.id,
        "stored_paths": [upload_path, page_path, region_path, context_path],
    }


def test_teacher_cannot_access_or_delete_another_teachers_submission_or_page(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    owner, owner_token = register_teacher(client, "submission-owner")
    _other, other_token = register_teacher(client, "submission-other")
    assessment = create_owned_assessment(client, owner_token)
    seeded = seed_submission_privacy_graph(
        db_session, int(assessment["id"]), tmp_path / "storage"
    )

    assert client.get(
        f"/submissions/{seeded['submission_id']}", headers=auth_header(other_token)
    ).status_code == 404
    assert client.get(
        f"/submission-pages/{seeded['page_id']}/image", headers=auth_header(other_token)
    ).status_code == 404
    delete_response = client.delete(
        f"/assessments/{assessment['id']}/submissions/{seeded['submission_id']}",
        headers=auth_header(other_token),
    )

    assert delete_response.status_code == 404
    assert count_rows(db_session, Submission) == 1
    assert count_rows(db_session, SubmissionPage) == 1
    assert count_rows(db_session, AnswerRegion) == 1
    assert owner["id"] != _other["id"]


def test_authorized_teacher_deletes_submission_artifacts_and_audit_log(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "submission-delete")
    assessment = create_owned_assessment(client, token)
    storage_root = tmp_path / "storage"
    seeded = seed_submission_privacy_graph(db_session, int(assessment["id"]), storage_root)
    assert all((storage_root / path).exists() for path in seeded["stored_paths"])

    response = client.delete(
        f"/assessments/{assessment['id']}/submissions/{seeded['submission_id']}",
        headers=auth_header(token),
    )

    assert response.status_code == 204
    assert count_rows(db_session, Submission) == 0
    assert count_rows(db_session, SubmissionPage) == 0
    assert count_rows(db_session, AnswerRegion) == 0
    assert not any((storage_root / path).exists() for path in seeded["stored_paths"])
    audit = db_session.scalar(select(AuditLog).where(AuditLog.event_type == "submission.deleted"))
    assert audit is not None
    assert audit.actor_id == teacher["id"]
    assert audit.actor_type == "teacher"
    assert audit.entity_type == "submission"
    assert audit.entity_id == seeded["submission_id"]
    assert audit.payload_json["assessment_id"] == assessment["id"]


def test_submission_upload_requires_authentication(
    client: TestClient, tmp_path: Path
) -> None:
    _teacher, token = register_teacher(client, "upload-auth")
    assessment = create_owned_assessment(client, token)
    image_path = tmp_path / "answer.png"
    write_storage_file(tmp_path, "answer.png", b"not-used")
    from PIL import Image
    Image.new("RGB", (32, 24), color="white").save(image_path, format="PNG")

    with image_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-UNAUTH"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )

    assert response.status_code == 401
