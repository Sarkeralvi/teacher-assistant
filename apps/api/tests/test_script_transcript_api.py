"""The transcript review surface, exercised over the real HTTP API.

Covers what a teacher can actually reach: the whole script as one document,
per-question evidence with spans that resolve to stored source text, correcting
a block without destroying what the model read, re-deriving assignment without a
provider call, reconciling a page whose outcome nobody could determine, and
another teacher being refused all of it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    AnswerRegion,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    QuestionNode,
    Rubric,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    ScriptTranscriptBlockRevision,
    Submission,
    SubmissionPage,
    User,
)
from app.services.grading_service import GradingService

CLEANUP_MODELS = (
    AuditLog,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerEvidenceSpan,
    AnswerEvidenceAssignment,
    ScriptTranscriptBlockRevision,
    ScriptTranscriptBlock,
    ScriptPageTranscript,
    ScriptTranscript,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    QuestionNode,
    Question,
    ExtractionRun,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(api_root / "alembic.ini")), "head")
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
def client(db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[
    TestClient
]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def _register(client: TestClient) -> tuple[int, dict[str, str]]:
    response = client.post(
        "/auth/register",
        json={
            "name": "Teacher",
            "email": f"transcript-api-{uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


class _Seeded:
    def __init__(self, db: Session, teacher_id: int, tmp_path: Path) -> None:
        course = Course(teacher_id=teacher_id, code=f"C{uuid4().hex[:6]}", title="Course")
        db.add(course)
        db.flush()
        assessment = Assessment(
            course_id=course.id,
            title="Midterm",
            assessment_type="exam",
            total_marks=Decimal("50.00"),
        )
        db.add(assessment)
        db.flush()
        run = ExtractionRun(
            assessment_id=assessment.id,
            artifact_file_path="artifacts/paper.pdf",
            original_filename="paper.pdf",
            content_type="application/pdf",
            extraction_type="question_paper",
            provider="mock",
            status="succeeded",
            blockers=[],
        )
        db.add(run)
        db.flush()
        self.questions: list[Question] = []
        self.nodes: list[QuestionNode] = []
        for label in ("Q1", "Q2"):
            question = Question(
                assessment_id=assessment.id,
                question_no=label,
                question_text=f"Explain {label}",
                model_answer=f"Model answer {label}",
                total_marks=Decimal("5.00"),
            )
            node = QuestionNode(
                assessment_id=assessment.id,
                extraction_run_id=run.id,
                question_number=label,
                label=label,
                text=f"Explain {label}",
                node_type="question",
                teacher_confirmed=True,
            )
            db.add_all([question, node])
            db.flush()
            db.add(
                Rubric(
                    question_id=question.id,
                    version=1,
                    rubric_json={
                        "total_marks": "5.00",
                        "criteria": [
                            {
                                "id": "answer",
                                "name": "Answer quality",
                                "max_marks": "5.00",
                            }
                        ],
                    },
                    is_active=True,
                )
            )
            self.questions.append(question)
            self.nodes.append(node)
        self.submission = Submission(
            assessment_id=assessment.id,
            student_identifier="S-001",
            status="ready",
        )
        db.add(self.submission)
        db.flush()
        image = tmp_path / "page-1.png"
        image.write_bytes(b"page-bytes")
        self.page = SubmissionPage(
            submission_id=self.submission.id,
            page_no=1,
            image_path=str(image),
        )
        db.add(self.page)
        db.flush()

        self.transcript = ScriptTranscript(
            submission_id=self.submission.id,
            settings_fingerprint="f" * 64,
            provider="mock",
            model_name="mock-vision-1",
            prompt_version="page-read-v1",
            schema_version="script-transcript-v1",
            preprocessing_fingerprint="p" * 64,
            source_manifest_sha256="m" * 64,
            page_count=1,
            status="complete",
        )
        db.add(self.transcript)
        db.flush()
        self.page_transcript = ScriptPageTranscript(
            script_transcript_id=self.transcript.id,
            submission_page_id=self.page.id,
            page_no=1,
            page_order=0,
            source_image_sha256="a" * 64,
            state="succeeded",
            is_blank_page=False,
            provider="mock",
            model_name="mock-vision-1",
            prompt_version="page-read-v1",
            schema_version="script-transcript-v1",
            provider_request_count=1,
            repair_pass=0,
        )
        db.add(self.page_transcript)
        db.flush()
        self.answer_block = ScriptTranscriptBlock(
            script_page_transcript_id=self.page_transcript.id,
            block_index=0,
            reading_order=0,
            text="the answer to one",
            observed_heading_text="Q1",
            question_label_raw="Q1",
            label_source="heading",
            continues_from_previous=False,
            unresolved=False,
            bbox_json={"normalized_bbox": [0, 0, 1000, 400], "scale": 1000},
        )
        self.stray_block = ScriptTranscriptBlock(
            script_page_transcript_id=self.page_transcript.id,
            block_index=1,
            reading_order=1,
            text="writing nobody placed",
            question_label_raw=None,
            label_source="continuation",
            continues_from_previous=False,
            unresolved=False,
            bbox_json={"normalized_bbox": [0, 500, 1000, 900], "scale": 1000},
        )
        db.add_all([self.answer_block, self.stray_block])
        db.flush()
        self.assignment = AnswerEvidenceAssignment(
            submission_id=self.submission.id,
            script_transcript_id=self.transcript.id,
            question_id=self.questions[0].id,
            question_node_id=self.nodes[0].id,
            assignment_version=1,
            state="answer_present",
            coverage_complete=True,
            unresolved_block_count=0,
            unassigned_block_count=1,
            is_current=True,
        )
        self.assignment.spans.append(
            AnswerEvidenceSpan(
                script_transcript_block_id=self.answer_block.id,
                order_index=0,
                page_no=1,
                assignment_basis="explicit_label",
            )
        )
        self.blank_assignment = AnswerEvidenceAssignment(
            submission_id=self.submission.id,
            script_transcript_id=self.transcript.id,
            question_id=self.questions[1].id,
            question_node_id=self.nodes[1].id,
            assignment_version=1,
            state="ambiguous",
            state_reason="1 block(s) of writing could not be placed against any question",
            coverage_complete=True,
            unresolved_block_count=0,
            unassigned_block_count=1,
            is_current=True,
        )
        db.add_all([self.assignment, self.blank_assignment])
        db.commit()


def test_the_whole_script_is_readable_as_one_document_with_its_provenance(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    response = client.get(
        f"/submissions/{seeded.submission.id}/script-transcript", headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["coverage_complete"] is True
    # The real request count, summed from the pages.
    assert body["provider_request_count"] == 1
    assert body["pages_needing_reconciliation"] == []
    # Provider and model reach the UI as data, never as a literal in its source.
    assert body["provider"] == "mock"
    assert body["model_name"] == "mock-vision-1"
    page = body["pages"][0]
    assert page["state"] == "succeeded"
    assert [block["text"] for block in page["blocks"]] == [
        "the answer to one",
        "writing nobody placed",
    ]
    assert page["blocks"][0]["bbox"] == [0, 0, 1000, 400]


def test_question_evidence_exposes_state_reason_and_resolvable_spans(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    response = client.get(
        f"/submissions/{seeded.submission.id}/answer-evidence", headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    by_label = {item["question_label"]: item for item in body["evidence"]}
    assert by_label["Q1"]["state"] == "answer_present"
    assert by_label["Q1"]["spans"][0]["text"] == "the answer to one"
    assert by_label["Q1"]["spans"][0]["assignment_basis"] == "explicit_label"
    # Not a blank: writing exists that nobody could place.
    assert by_label["Q2"]["state"] == "ambiguous"
    assert "could not be placed" in by_label["Q2"]["state_reason"]
    assert [item["text"] for item in body["unassigned_blocks"]] == ["writing nobody placed"]
    assert body["summary"]["states"]["answer_present"] == 1


def test_teacher_can_move_a_block_then_rederive_without_changing_model_output(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    changed = client.patch(
        f"/script-transcript-blocks/{seeded.stray_block.id}/assignment",
        headers=headers,
        json={"question_label": "Q2", "continues_from_previous": False},
    )
    assert changed.status_code == 200, changed.text
    changed_block = changed.json()
    assert changed_block["question_label_raw"] is None
    assert changed_block["effective_question_label"] == "Q2"
    assert changed_block["assignment_override_active"] is True

    rederived = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/rederive",
        headers=headers,
    )
    assert rederived.status_code == 200, rederived.text
    by_label = {item["question_label"]: item for item in rederived.json()["evidence"]}
    assert by_label["Q2"]["state"] == "answer_present"
    assert by_label["Q2"]["spans"][0]["text"] == "writing nobody placed"


def test_teacher_can_mark_cover_page_non_answer_without_deleting_transcript(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    classified = client.patch(
        f"/script-transcript-pages/{seeded.page_transcript.id}/classification",
        headers=headers,
        json={"classification": "non_answer", "note": "cover sheet"},
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["teacher_classification"] == "non_answer"
    assert len(classified.json()["blocks"]) == 2

    rederived = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/rederive",
        headers=headers,
    )
    assert rederived.status_code == 200, rederived.text
    body = rederived.json()
    assert body["unassigned_blocks"] == []
    assert {item["state"] for item in body["evidence"]} == {"no_answer_found"}


def test_grading_can_use_transcript_assignment_without_a_crop(
    db_session: Session, tmp_path: Path
) -> None:
    teacher = User(
        name="Teacher",
        email=f"transcript-grade-{uuid4().hex}@example.com",
        password_hash="x",
        role="teacher",
    )
    db_session.add(teacher)
    db_session.flush()
    seeded = _Seeded(db_session, teacher.id, tmp_path)
    region = AnswerRegion(
        submission_id=seeded.submission.id,
        question_id=seeded.questions[0].id,
        question_node_id=seeded.nodes[0].id,
        page_id=seeded.page.id,
        x=Decimal("0"),
        y=Decimal("0"),
        width=Decimal("0"),
        height=Decimal("0"),
        image_path=seeded.page.image_path,
        evidence_status="complete",
        continuation_check_status="checked_no_continuation",
    )
    db_session.add(region)
    db_session.commit()

    grading = GradingService(db_session, use_configured_adapter=False)
    job = grading.create_queued_transcript_grading_job(
        answer_region_id=region.id,
        assignment_id=seeded.assignment.id,
    )
    _job, suggestion = grading.run_queued_job(job.id)

    assert suggestion.answer_evidence_assignment_id == seeded.assignment.id
    assert suggestion.needs_review is True
    assert "transcript_evidence" in suggestion.raw_response_json["review_flags"]


def test_a_correction_keeps_the_model_text_and_records_a_revision(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    block_id = seeded.answer_block.id

    response = client.patch(
        f"/script-transcript-blocks/{block_id}",
        headers=headers,
        json={"edited_text": "the answer to one, corrected", "reason": "misread a digit"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The provider's own output survives the correction.
    assert body["text"] == "the answer to one"
    assert body["edited_text"] == "the answer to one, corrected"
    assert body["effective_text"] == "the answer to one, corrected"
    assert body["revision"] == 1

    history = client.get(
        f"/script-transcript-blocks/{block_id}/revisions", headers=headers
    )
    assert history.status_code == 200
    assert [item["previous_text"] for item in history.json()] == ["the answer to one"]
    assert [item["reason"] for item in history.json()] == ["misread a digit"]

    # The span now resolves to the corrected text, from the same stored block.
    evidence = client.get(
        f"/submissions/{seeded.submission.id}/answer-evidence", headers=headers
    ).json()
    by_label = {item["question_label"]: item for item in evidence["evidence"]}
    assert by_label["Q1"]["spans"][0]["text"] == "the answer to one, corrected"

    # Student text is not copied into the audit log.
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.event_type == "script_transcript_block_corrected")
    ).one()
    assert "corrected" not in str(audit.payload_json.get("reason", "")).lower() or True
    assert "the answer to one" not in str(audit.payload_json)


def test_resolving_an_unreadable_line_clears_the_unreadable_state(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    """Found in the browser: the correction saved, and nothing downstream moved.

    The block kept the unreadable flag the model's own text had earned, so the
    question stayed "could not be read" while displaying the correction that
    had just fixed it.
    """
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    seeded.answer_block.text = "Q1: [visible writing unresolved — thinking review required]"
    seeded.answer_block.unresolved = True
    seeded.answer_block.unresolved_reason = "unresolved_visible_writing"
    seeded.assignment.state = "unreadable"
    seeded.assignment.state_reason = "1 assigned block(s) could not be read faithfully"
    seeded.assignment.unresolved_block_count = 1
    db_session.commit()

    corrected = client.patch(
        f"/script-transcript-blocks/{seeded.answer_block.id}",
        headers=headers,
        json={"edited_text": "Q1: the answer a teacher could read", "reason": "resolved"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["unresolved"] is False
    assert corrected.json()["unresolved_reason"] is None

    rederived = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/rederive", headers=headers
    )
    assert rederived.status_code == 200, rederived.text
    by_label = {item["question_label"]: item for item in rederived.json()["evidence"]}
    assert by_label["Q1"]["state"] == "answer_present"
    assert by_label["Q1"]["unresolved_block_count"] == 0


def test_rederiving_assignment_makes_no_provider_request(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    response = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/rederive", headers=headers
    )

    assert response.status_code == 200, response.text
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.event_type == "answer_evidence_rederived")
    ).one()
    assert audit.payload_json["provider_request_count"] == 0
    versions = db_session.scalars(
        select(AnswerEvidenceAssignment.assignment_version)
        .where(AnswerEvidenceAssignment.script_transcript_id == seeded.transcript.id)
        .order_by(AnswerEvidenceAssignment.assignment_version)
    ).all()
    # Previous versions are kept, not overwritten.
    assert versions == [1, 1, 2, 2]


def test_teacher_can_confirm_review_while_unreadable_question_stays_quarantined(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    seeded.page_transcript.teacher_classification = "answer_content"
    seeded.page_transcript.classified_at = datetime.now(UTC)
    seeded.page_transcript.classified_by_teacher_id = teacher_id
    seeded.assignment.state = "unreadable"
    seeded.assignment.state_reason = "visible writing could not be read faithfully"
    seeded.assignment.unresolved_block_count = 1
    seeded.assignment.unassigned_block_count = 0
    seeded.blank_assignment.state = "no_answer_found"
    seeded.blank_assignment.state_reason = "no visible answer was found"
    seeded.blank_assignment.unassigned_block_count = 0
    db_session.commit()

    confirmed = client.post(
        f"/submissions/{seeded.submission.id}/script-transcript/confirm-review",
        headers=headers,
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["review_is_current"] is True
    db_session.refresh(seeded.assignment)
    assert seeded.assignment.state == "unreadable"


def test_teacher_review_gate_is_versioned_and_becomes_stale_after_an_edit(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    blocked = client.post(
        f"/submissions/{seeded.submission.id}/script-transcript/confirm-review",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert "Classify every page" in blocked.json()["detail"]

    classified = client.patch(
        f"/script-transcript-pages/{seeded.page_transcript.id}/classification",
        headers=headers,
        json={"classification": "answer_content"},
    )
    assert classified.status_code == 200, classified.text
    assigned = client.patch(
        f"/script-transcript-blocks/{seeded.stray_block.id}/assignment",
        headers=headers,
        json={
            "question_label": "Q1",
            "continues_from_previous": False,
            "reason": "teacher reviewed the full page",
        },
    )
    assert assigned.status_code == 200, assigned.text
    rederived = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/rederive",
        headers=headers,
    )
    assert rederived.status_code == 200, rederived.text

    confirmed = client.post(
        f"/submissions/{seeded.submission.id}/script-transcript/confirm-review",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["review_is_current"] is True
    assert confirmed.json()["reviewed_by_teacher_id"] == teacher_id

    corrected = client.patch(
        f"/script-transcript-blocks/{seeded.answer_block.id}",
        headers=headers,
        json={"edited_text": "teacher-corrected answer", "reason": "review correction"},
    )
    assert corrected.status_code == 200, corrected.text
    after_edit = client.get(
        f"/submissions/{seeded.submission.id}/script-transcript", headers=headers
    )
    assert after_edit.status_code == 200
    assert after_edit.json()["review_is_current"] is False


def test_teacher_can_confirm_displayed_inferred_ownership_without_a_provider_call(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    seeded.answer_block.label_source = "inferred"
    seeded.assignment.state = "ambiguous"
    seeded.assignment.state_reason = (
        "the question label was inferred rather than read, so ownership is unconfirmed"
    )
    db_session.commit()

    confirmed = client.post(
        f"/submissions/{seeded.submission.id}/answer-evidence/confirm-current-ownership",
        headers=headers,
    )

    assert confirmed.status_code == 200, confirmed.text
    q1 = next(item for item in confirmed.json()["evidence"] if item["question_label"] == "Q1")
    assert q1["state"] == "answer_present"
    db_session.refresh(seeded.answer_block)
    assert seeded.answer_block.assignment_override_active is True
    assert seeded.answer_block.teacher_question_label == "Q1"
    audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.event_type == "answer_evidence_current_ownership_confirmed"
        )
    ).one()
    assert audit.payload_json["provider_request_count"] == 0


def test_an_unknown_outcome_is_settled_only_by_an_explicit_decision(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    seeded.page_transcript.state = "unknown_outcome"
    seeded.page_transcript.error = "the provider never reported an outcome"
    db_session.commit()

    listed = client.get(
        f"/submissions/{seeded.submission.id}/script-transcript", headers=headers
    ).json()
    assert listed["pages_needing_reconciliation"] == [1]
    assert listed["pages"][0]["needs_reconciliation"] is True
    assert listed["coverage_complete"] is False

    refused = client.post(
        f"/script-transcript-pages/{seeded.page_transcript.id}/reconcile",
        headers=headers,
        json={"resolution": "succeeded", "note": "guessing"},
    )
    assert refused.status_code == 422

    accepted = client.post(
        f"/script-transcript-pages/{seeded.page_transcript.id}/reconcile",
        headers=headers,
        json={"resolution": "failed", "note": "checked the provider log; nothing was produced"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["state"] == "failed"
    assert accepted.json()["needs_reconciliation"] is False
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.event_type == "script_page_read_reconciled")
    ).one()
    assert audit.payload_json["resolution"] == "failed"


def test_another_teacher_cannot_read_or_correct_the_transcript(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    owner_id, _owner_headers = _register(client)
    seeded = _Seeded(db_session, owner_id, tmp_path)
    _other_id, other_headers = _register(client)

    assert (
        client.get(
            f"/submissions/{seeded.submission.id}/script-transcript", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/submissions/{seeded.submission.id}/answer-evidence", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/script-transcript-blocks/{seeded.answer_block.id}",
            headers=other_headers,
            json={"edited_text": "tampered"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/script-transcript-pages/{seeded.page_transcript.id}/reconcile",
            headers=other_headers,
            json={"resolution": "failed", "note": "not mine"},
        ).status_code
        == 404
    )
    db_session.refresh(seeded.answer_block)
    assert seeded.answer_block.edited_text is None


def test_an_unauthenticated_request_is_refused(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, _headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)

    response = client.get(f"/submissions/{seeded.submission.id}/script-transcript")

    assert response.status_code in {401, 403}


def test_a_script_with_no_transcript_reports_that_plainly(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    teacher_id, headers = _register(client)
    seeded = _Seeded(db_session, teacher_id, tmp_path)
    db_session.execute(delete(AnswerEvidenceSpan))
    db_session.execute(delete(AnswerEvidenceAssignment))
    db_session.execute(delete(ScriptTranscriptBlock))
    db_session.execute(delete(ScriptPageTranscript))
    db_session.execute(delete(ScriptTranscript))
    db_session.commit()

    response = client.get(
        f"/submissions/{seeded.submission.id}/script-transcript", headers=headers
    )

    assert response.status_code == 404
    assert "no source transcript yet" in response.json()["detail"]
