import hashlib
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
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
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
from app.services.local_ocr_client import LocalOcrResult

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionOcrRun,
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


class FakePaddleClient:
    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict[str, object]:
        return {
            "status": "ready",
            "model": "PaddleOCR-VL-1.6",
            "layout_model": "PP-DocLayoutV3",
        }

    def ocr_image(self, **_kwargs: object) -> LocalOcrResult:
        self.calls += 1
        return LocalOcrResult.model_validate(
            {
                "request_id": f"fake-{self.calls}",
                "mode": "answer_region",
                "text": "P(X)=7/12",
                "normalized_text": "P(X)=7/12",
                "markdown": "$P(X)=7/12$",
                "blocks": [
                    {
                        "page": 1,
                        "order": 1,
                        "label": "formula",
                        "text": "P(X)=7/12",
                        "bbox": [0, 0, 50, 20],
                    }
                ],
                "warnings": [],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "gpu:0",
                "latency_ms": 10,
            }
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


def create_assessment_for_teacher(
    client: TestClient, teacher_id: int, token: str
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"}
    course_response = client.post(
        "/courses",
        headers=headers,
        json={"teacher_id": teacher_id, "code": "MATH101", "title": "Math"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=headers,
        json={"title": "Midterm", "assessment_type": "exam", "total_marks": "50.00"},
    )
    assert assessment_response.status_code == 201
    return assessment_response.json()


def create_question(
    client: TestClient, assessment_id: int, question_no: str, token: str
) -> dict[str, object]:
    response = client.post(
        f"/assessments/{assessment_id}/questions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "question_no": question_no,
            "question_text": f"Explain {question_no}",
            "model_answer": f"Model answer {question_no}",
            "total_marks": "5.00",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_active_rubric(client: TestClient, question_id: int, token: str) -> dict[str, object]:
    response = client.post(
        f"/questions/{question_id}/rubrics",
        headers={"Authorization": f"Bearer {token}"},
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
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    create_question(client, int(assessment["id"]), "Q1(b)", token)
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


def test_mapping_run_returns_empty_when_no_confirmed_question_nodes_exist(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-empty")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    create_question(client, int(assessment["id"]), "Q1(b)", token)

    pdf_path = tmp_path / "script.pdf"
    make_text_pdf(pdf_path, ["Q1(a) answer only"])
    submission = upload_submission_pdf(client, int(assessment["id"]), pdf_path, token)

    response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapped_count"] == 0
    assert body["blocked_count"] == 0
    assert body["uncertain_count"] == 0


def test_ambiguous_mapping_creates_uncertain_blocker(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-uncertain")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    create_question(client, int(assessment["id"]), "Q1(b)", token)
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
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    create_question(client, int(assessment["id"]), "Q1(b)", token)
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


def test_hybrid_mapping_confirmation_cannot_accept_transcription_text(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-local-choice")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    create_question(client, int(assessment["id"]), "Q1(b)", token)
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))
    pdf_path = tmp_path / "choice.pdf"
    make_text_pdf(pdf_path, ["Q1(a) answer text here\nQ1(b) answer text here"])
    submission = upload_submission_pdf(
        client, int(assessment["id"]), pdf_path, token, "S-CHOICE"
    )
    run_response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    mapping_id = int(run_response.json()["mappings"][0]["id"])
    primary = "The final result is x/10."
    alternative = "The final result is 7/10."
    primary_hash = hashlib.sha256(primary.encode()).hexdigest()
    alternative_hash = hashlib.sha256(alternative.encode()).hexdigest()
    mapping = db_session.get(AnswerRegionMapping, mapping_id)
    assert mapping is not None
    mapping.provider = "local_paddle_qwen"
    mapping.source_reference = {
        "model_prepared_answer_text": primary,
        "model_prepared_answer_text_sha256": primary_hash,
        "model_prepared_answer_alternatives": [
            {"text": alternative, "sha256": alternative_hash}
        ],
    }
    db_session.commit()

    stale = client.post(
        f"/question-node-mappings/{mapping_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "teacher_confirmed": True,
            "accept_model_prepared_text": True,
            "selected_prepared_text_sha256": "0" * 64,
        },
    )
    assert stale.status_code == 400

    rejected_text = client.post(
        f"/question-node-mappings/{mapping_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "teacher_confirmed": True,
            "accept_model_prepared_text": True,
            "selected_prepared_text_sha256": alternative_hash,
        },
    )
    assert rejected_text.status_code == 400

    confirmed = client.post(
        f"/question-node-mappings/{mapping_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"teacher_confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["teacher_confirmed"] is True
    assert body["answer_region"]["manual_answer_text"] in {None, ""}


def test_qwen38_mapping_confirmation_confirms_every_ordered_image_segment(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-qwen38-segments")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))
    pdf_path = tmp_path / "qwen38-segments.pdf"
    make_text_pdf(pdf_path, ["Q1(a) first page", "continued answer on page two"])
    submission = upload_submission_pdf(
        client, int(assessment["id"]), pdf_path, token, "S-QWEN38-SEGMENTS"
    )
    run_response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert run_response.status_code == 200, run_response.text
    mapping_payload = next(
        item for item in run_response.json()["mappings"] if item["answer_region_id"] is not None
    )
    mapping = db_session.get(AnswerRegionMapping, int(mapping_payload["id"]))
    assert mapping is not None
    assert mapping.answer_region is not None
    region = mapping.answer_region
    first_segment = region.segments[0]
    first_segment.confirmed = False
    second_page = submission["pages"][1]
    region.segments.append(
        AnswerRegionSegment(
            submission_page_id=int(second_page["id"]),
            order_index=2,
            x=first_segment.x,
            y=first_segment.y,
            width=first_segment.width,
            height=first_segment.height,
            image_path=first_segment.image_path,
            source="suggestion",
            confirmed=False,
            is_primary=False,
        )
    )
    mapping.provider = "llama_cpp_qwen38"
    mapping.mapping_status = "uncertain"
    db_session.commit()

    confirm_response = client.post(
        f"/question-node-mappings/{mapping.id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"teacher_confirmed": True},
    )

    assert confirm_response.status_code == 200, confirm_response.text
    confirmed_segments = confirm_response.json()["answer_region"]["segments"]
    assert [segment["order_index"] for segment in confirmed_segments] == [1, 2]
    assert all(segment["confirmed"] is True for segment in confirmed_segments)
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.event_type == "answer_region_mapping_geometry_confirmed",
            AuditLog.entity_id == mapping.id,
        )
    )
    assert audit is not None
    assert audit.payload_json["segment_count"] == 2


def test_direct_paddle_draft_is_hash_confirmed_and_never_finalizes_grade(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher, token = register_teacher(client, "paddle-evidence")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    create_question(client, int(assessment["id"]), "Q1(a)", token)
    seed_confirmed_question_nodes(db_session, int(assessment["id"]))
    pdf_path = tmp_path / "paddle-evidence.pdf"
    make_text_pdf(pdf_path, ["Q1(a) P(X)=7/12"])
    submission = upload_submission_pdf(
        client, int(assessment["id"]), pdf_path, token, "S-PADDLE"
    )
    run_response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"replace_existing": True},
    )
    assert run_response.status_code == 200, run_response.text
    mapping_payload = next(
        item for item in run_response.json()["mappings"] if item["answer_region_id"] is not None
    )
    mapping = db_session.get(AnswerRegionMapping, int(mapping_payload["id"]))
    assert mapping is not None
    mapping.provider = "local_paddle_qwen"
    db_session.commit()
    confirm_mapping = client.post(
        f"/question-node-mappings/{mapping.id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"teacher_confirmed": True},
    )
    assert confirm_mapping.status_code == 200, confirm_mapping.text
    region_id = int(confirm_mapping.json()["answer_region_id"])

    fake = FakePaddleClient()
    monkeypatch.setenv("BRAIN_ALLOW_REAL_PROVIDERS", "true")
    monkeypatch.setenv("LOCAL_PADDLE_OCR_ENABLED", "true")
    monkeypatch.setenv("LOCAL_PADDLE_OCR_API_KEY", "test-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.answer_region_ocr_service.LocalOcrClient.from_settings",
        classmethod(lambda _cls, _settings=None: fake),
    )
    enqueue_options: list[dict[str, object]] = []

    class InlineQueue:
        def enqueue(self, function: object, *args: object, **kwargs: object) -> None:
            enqueue_options.append(kwargs)
            function(*args)  # type: ignore[operator]

    monkeypatch.setattr("app.api.routes.ocr.get_default_queue", lambda: InlineQueue())

    draft_response = client.post(
        f"/answer-regions/{region_id}/ocr-runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "expected_model": "PaddleOCR-VL-1.6",
            "expected_layout_model": "PP-DocLayoutV3",
            "draft_only_confirmed": True,
        },
    )
    assert draft_response.status_code == 202, draft_response.text
    draft = draft_response.json()
    assert draft["status"] == "succeeded"
    assert draft["draft_text"] == "P(X)=7/12"
    assert fake.calls == 1
    assert enqueue_options[0]["retry"] is None

    _, intruder_token = register_teacher(client, "paddle-intruder")
    hidden = client.get(
        f"/answer-region-ocr-runs/{draft['id']}",
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert hidden.status_code == 404

    stale = client.post(
        f"/answer-regions/{region_id}/ocr-runs/{draft['id']}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"teacher_confirmed": True, "draft_text_sha256": "0" * 64},
    )
    assert stale.status_code == 409

    confirmed = client.post(
        f"/answer-regions/{region_id}/ocr-runs/{draft['id']}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "teacher_confirmed": True,
            "draft_text_sha256": hashlib.sha256(b"P(X)=7/12").hexdigest(),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    refreshed_region = db_session.get(AnswerRegion, region_id)
    assert refreshed_region is not None
    db_session.refresh(refreshed_region)
    assert refreshed_region.manual_answer_text == "P(X)=7/12"
    assert refreshed_region.evidence_status == "partial"
    assert int(db_session.query(FinalGrade).count()) == 0
    audit_payloads = [
        str(row.payload_json)
        for row in db_session.query(AuditLog)
        .filter(AuditLog.entity_type == "answer_region_ocr_run")
        .all()
    ]
    assert audit_payloads
    assert all("P(X)=7/12" not in payload for payload in audit_payloads)


def test_workflow_state_blocks_unconfirmed_or_uncertain_mappings(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher, token = register_teacher(client, "map-ready")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    question_a = create_question(client, int(assessment["id"]), "Q1(a)", token)
    question_b = create_question(client, int(assessment["id"]), "Q1(b)", token)
    create_active_rubric(client, int(question_a["id"]), token)
    create_active_rubric(client, int(question_b["id"]), token)
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


@pytest.mark.parametrize("provider", ["local_paddle_qwen", "local_qwen38_visual"])
def test_local_mapping_provider_requires_explicit_draft_only_authorization(
    client: TestClient, tmp_path: Path, provider: str
) -> None:
    teacher, token = register_teacher(client, f"mapping-auth-{provider}")
    assessment = create_assessment_for_teacher(client, int(teacher["id"]), token)
    pdf_path = tmp_path / f"{provider}.pdf"
    make_text_pdf(pdf_path, ["Visible student answer"])
    submission = upload_submission_pdf(
        client, int(assessment["id"]), pdf_path, token, f"S-{provider}"
    )

    response = client.post(
        f"/submissions/{submission['id']}/question-node-mappings/run",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "provider": provider,
            "replace_existing": False,
            "repair_unconfirmed_only": True,
            "draft_only_confirmed": False,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Local model mapping requires explicit draft-only confirmation"
    )
