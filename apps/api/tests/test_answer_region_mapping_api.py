from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegionMapping,
    Assessment,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionMapping,
    SubmissionPage,
    Submission,
    Rubric,
    QuestionNode,
    Question,
    GradingRun,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    command.upgrade(config, "head")

    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
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
    client: TestClient, email_prefix: str = "mapping"
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


def create_question(client: TestClient, assessment_id: int, question_no: str) -> dict[str, object]:
    response = client.post(
        f"/assessments/{assessment_id}/questions",
        json={
            "question_no": question_no,
            "question_text": f"Explain {question_no}",
            "model_answer": f"Model answer {question_no}",
            "total_marks": "5.00",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_active_rubric(client: TestClient, question_id: int) -> dict[str, object]:
    response = client.post(
        f"/questions/{question_id}/rubrics",
        json={
            "version": 1,
            "rubric_json": {
                "total_marks": "5.00",
                "criteria": [
                    {
                        "id": "accuracy",
                        "name": "Accuracy",
                        "description": "Accurate answer",
                        "max_marks": "5.00",
                    }
                ],
            },
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_grading_run(client: TestClient, assessment_id: int, token: str) -> dict[str, object]:
    response = client.post(
        f"/assessments/{assessment_id}/grading-runs/custom",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()


def make_text_pdf(path: Path, page_texts: list[str]) -> None:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(path)
    doc.close()


def upload_submission_pdf(
    client: TestClient,
    assessment_id: int,
    pdf_path: Path,
    token: str,
    student_identifier: str = "S-001",
) -> dict[str, object]:
    with pdf_path.open("rb") as file_obj:
        response = client.post(
            f"/assessments/{assessment_id}/submissions/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"student_identifier": student_identifier, "student_name": "Student One"},
            files={"file": (pdf_path.name, file_obj, "application/pdf")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def seed_confirmed_question_nodes(db: Session, assessment_id: int) -> list[QuestionNode]:
    extraction_run = ExtractionRun(
        assessment_id=assessment_id,
        artifact_file_path="artifacts/mock-question-paper.pdf",
        original_filename="mock-question-paper.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="mock",
        status="succeeded",
        normalized_output={},
        blockers=[],
    )
    db.add(extraction_run)
    db.flush()

    nodes = [
        QuestionNode(
            assessment_id=assessment_id,
            extraction_run_id=extraction_run.id,
            node_type="subquestion",
            question_number="Q1(a)",
            parent_question_number="Q1",
            label="Q1(a)",
            text="Part a",
            marks=5,
            source_page=1,
            teacher_confirmed=True,
        ),
        QuestionNode(
            assessment_id=assessment_id,
            extraction_run_id=extraction_run.id,
            node_type="subquestion",
            question_number="Q1(b)",
            parent_question_number="Q1",
            label="Q1(b)",
            text="Part b",
            marks=5,
            source_page=1,
            teacher_confirmed=True,
        ),
    ]
    db.add_all(nodes)
    db.commit()
    for node in nodes:
        db.refresh(node)
    return nodes


def test_text_script_mapping_maps_q1a_and_q1b_without_creating_grading_records(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-success")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    create_question(client, int(assessment["id"]), "Q1(a)")
    create_question(client, int(assessment["id"]), "Q1(b)")
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))

    pdf_path = tmp_path / "script.pdf"
    make_text_pdf(pdf_path, ["Student Script\nQ1(a) answer text here\nQ1(b) answer text here"])
    submission = upload_submission_pdf(client, int(assessment["id"]), pdf_path, token)

    response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapped_count"] == 2
    assert body["uncertain_count"] == 0
    assert body["blocked_count"] == 0
    assert {item["question_node_id"] for item in body["mappings"]} == {
        node.id for node in db_session.scalars(select(QuestionNode)).all()
    }
    assert all(item["answer_region_id"] is not None for item in body["mappings"])
    assert all(item["mapping_status"] == "mapped" for item in body["mappings"])

    assert db_session.scalar(select(func.count(GradeSuggestion.id))) == 0
    assert db_session.scalar(select(func.count(FinalGrade.id))) == 0
    assert db_session.scalar(select(func.count(GradingJob.id))) == 0


def test_ambiguous_mapping_creates_uncertain_blocker(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-uncertain")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    create_question(client, int(assessment["id"]), "Q1(a)")
    create_question(client, int(assessment["id"]), "Q1(b)")
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))

    pdf_path = tmp_path / "ambiguous.pdf"
    make_text_pdf(pdf_path, ["Q1(a) first\nQ1(a) second\nQ1(b) unique"])
    submission = upload_submission_pdf(client, int(assessment["id"]), pdf_path, token, "S-002")

    response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert response.status_code == 200, response.text
    mappings = response.json()["mappings"]
    q1a = next(
        item
        for item in mappings
        if item["source_reference"] and "Q1(a)" in str(item["source_reference"])
    )
    assert q1a["mapping_status"] == "uncertain"
    assert "Multiple visible label matches" in (q1a["blocker_reason"] or "")


def test_teacher_correction_and_confirmation_persist(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-correct")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    create_question(client, int(assessment["id"]), "Q1(a)")
    create_question(client, int(assessment["id"]), "Q1(b)")
    nodes = seed_confirmed_question_nodes(db_session, int(assessment["id"]))

    pdf_path = tmp_path / "partial.pdf"
    make_text_pdf(pdf_path, ["Q1(a) present only"])
    submission = upload_submission_pdf(client, int(assessment["id"]), pdf_path, token, "S-003")

    run_response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert run_response.status_code == 200, run_response.text
    mappings = run_response.json()["mappings"]
    blocked = next(item for item in mappings if item["mapping_status"] == "blocked")
    page_id = int(submission["pages"][0]["id"])
    update_response = client.patch(
        f"/question-node-mappings/{blocked['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "question_node_id": nodes[1].id,
            "page_id": page_id,
            "x": "24",
            "y": "200",
            "width": "500",
            "height": "180",
            "manual_answer_text": "Teacher-corrected Q1(b) text",
            "confidence": "1.0",
            "mapping_status": "mapped",
            "blocker_reason": None,
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["mapping_status"] == "mapped"
    assert updated["answer_region_id"] is not None
    assert updated["answer_region"]["manual_answer_text"] == "Teacher-corrected Q1(b) text"

    confirm_response = client.post(
        f"/question-node-mappings/{blocked['id']}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"teacher_confirmed": True},
    )
    assert confirm_response.status_code == 200, confirm_response.text
    confirmed = confirm_response.json()
    assert confirmed["mapping_status"] == "teacher_confirmed"
    assert confirmed["teacher_confirmed"] is True


def test_workflow_state_blocks_unconfirmed_or_uncertain_mappings(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-ready")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]))
    question_a = create_question(client, int(assessment["id"]), "Q1(a)")
    question_b = create_question(client, int(assessment["id"]), "Q1(b)")
    create_active_rubric(client, int(question_a["id"]))
    create_active_rubric(client, int(question_b["id"]))
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))
    grading_run = create_grading_run(client, int(assessment["id"]), token)

    pdf_path = tmp_path / "ready.pdf"
    make_text_pdf(pdf_path, ["Q1(a) duplicate\nQ1(a) duplicate again\nQ1(b) unique"])
    submission = upload_submission_pdf(client, int(assessment["id"]), pdf_path, token, "S-004")
    run_response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert run_response.status_code == 200

    detail = client.get(
        f"/grading-runs/{grading_run['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert detail.status_code == 200
    workflow_state = detail.json()["workflow_state"]
    assert workflow_state["mappings_ready"] is False
    assert workflow_state["uncertain_mapping_count"] >= 1
    assert any("mapping" in blocker.lower() for blocker in workflow_state["blockers"])
