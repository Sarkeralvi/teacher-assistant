"""A draft grade cannot be finalized against evidence that has moved.

These run against the real database and the real FinalGradeService, because the
point of the check is that it sits at the irreversible step rather than in a
hook someone has to remember to call.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.db.session import SessionLocal
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
from app.services.evidence_invalidation import (
    EvidenceChangedError,
    EvidenceInvalidationService,
)
from app.services.final_grade_service import FinalGradeService

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


class _Graded:
    """A submission with one graded answer region and a stored transcript."""

    def __init__(self, db: Session, tmp_path: Path) -> None:
        self.db = db
        self.teacher = User(
            name="Teacher",
            email=f"invalidation-{uuid4().hex}@example.com",
            password_hash="x",
            role="teacher",
        )
        db.add(self.teacher)
        db.flush()
        course = Course(teacher_id=self.teacher.id, code=f"C{uuid4().hex[:6]}", title="Course")
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
        self.question = Question(
            assessment_id=assessment.id,
            question_no="Q1",
            question_text="Explain Q1",
            model_answer="Model answer Q1",
            total_marks=Decimal("10.00"),
        )
        db.add(self.question)
        db.flush()
        self.rubric = Rubric(
            question_id=self.question.id,
            version=1,
            rubric_json={"total_marks": "10.00", "criteria": []},
            is_active=True,
        )
        node = QuestionNode(
            assessment_id=assessment.id,
            extraction_run_id=run.id,
            question_number="Q1",
            label="Q1",
            text="Explain Q1",
            node_type="question",
            teacher_confirmed=True,
        )
        db.add_all([self.rubric, node])
        db.flush()
        self.submission = Submission(
            assessment_id=assessment.id,
            student_identifier="S-001",
            status="ready",
        )
        db.add(self.submission)
        db.flush()
        image = tmp_path / "page-1.png"
        image.write_bytes(b"not-a-real-image")
        page = SubmissionPage(
            submission_id=self.submission.id,
            page_no=1,
            image_path=str(image),
        )
        db.add(page)
        db.flush()
        self.region = AnswerRegion(
            submission_id=self.submission.id,
            question_id=self.question.id,
            question_node_id=node.id,
            page_id=page.id,
            x=Decimal("0"),
            y=Decimal("0"),
            width=Decimal("100"),
            height=Decimal("100"),
            image_path="crops/region-1.png",
            full_answer_confirmed=True,
        )
        db.add(self.region)
        db.flush()

        self.transcript = ScriptTranscript(
            submission_id=self.submission.id,
            settings_fingerprint="f" * 64,
            provider="mock",
            model_name="mock-vision-1",
            prompt_version="p",
            schema_version="s",
            preprocessing_fingerprint="p" * 64,
            source_manifest_sha256="m" * 64,
            page_count=1,
            status="complete",
        )
        db.add(self.transcript)
        db.flush()
        page_transcript = ScriptPageTranscript(
            script_transcript_id=self.transcript.id,
            submission_page_id=page.id,
            page_no=1,
            page_order=0,
            source_image_sha256="a" * 64,
            state="succeeded",
            is_blank_page=False,
            provider="mock",
            model_name="mock-vision-1",
            prompt_version="p",
            schema_version="s",
            provider_request_count=1,
            repair_pass=0,
        )
        db.add(page_transcript)
        db.flush()
        self.block = ScriptTranscriptBlock(
            script_page_transcript_id=page_transcript.id,
            block_index=0,
            reading_order=0,
            text="the student answer",
            question_label_raw="Q1",
            label_source="heading",
            continues_from_previous=False,
            unresolved=False,
            bbox_json={"normalized_bbox": [0, 0, 1000, 500], "scale": 1000},
        )
        db.add(self.block)
        db.flush()
        self.assignment = AnswerEvidenceAssignment(
            submission_id=self.submission.id,
            script_transcript_id=self.transcript.id,
            question_id=self.question.id,
            question_node_id=node.id,
            assignment_version=1,
            state="answer_present",
            coverage_complete=True,
            unresolved_block_count=0,
            unassigned_block_count=0,
            is_current=True,
        )
        self.assignment.spans.append(
            AnswerEvidenceSpan(
                script_transcript_block_id=self.block.id,
                order_index=0,
                page_no=1,
                assignment_basis="explicit_label",
            )
        )
        db.add(self.assignment)
        db.flush()

        job = GradingJob(answer_region_id=self.region.id, status="succeeded")
        db.add(job)
        db.flush()
        self.suggestion = GradeSuggestion(
            grading_job_id=job.id,
            answer_region_id=self.region.id,
            question_id=self.question.id,
            rubric_id=self.rubric.id,
            model_provider="mock",
            model_name="mock-grader",
            prompt_version="v1",
            marking_policy="general",
            raw_response_json={"synthetic": True},
            score=Decimal("8.00"),
            max_score=Decimal("10.00"),
            needs_review=True,
            source_evidence_fingerprint=EvidenceInvalidationService(db).fingerprint_for_region(
                self.region
            ),
        )
        db.add(self.suggestion)
        db.commit()


def test_an_unchanged_packet_stays_current_and_can_be_approved(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Graded(db_session, tmp_path)
    service = EvidenceInvalidationService(db_session)

    assert service.suggestion_evidence_status(fixture.suggestion) == "current"
    final_grade, created = FinalGradeService(db_session).approve_suggestion(
        fixture.suggestion.id, teacher_id=fixture.teacher.id
    )
    assert created is True
    assert final_grade.approval_status == "approved"


@pytest.mark.parametrize(
    "mutation",
    ["transcript_text", "rubric", "model_answer", "assignment_version", "span_removed"],
)
def test_changed_evidence_supersedes_the_draft_and_blocks_approval(
    db_session: Session, tmp_path: Path, mutation: str
) -> None:
    fixture = _Graded(db_session, tmp_path)
    service = EvidenceInvalidationService(db_session)

    if mutation == "transcript_text":
        # A teacher correction: no source pixel moved, but the evidence did.
        fixture.block.edited_text = "the corrected student answer"
        fixture.block.revision = 1
        from datetime import UTC, datetime

        fixture.block.edited_at = datetime.now(UTC)
    elif mutation == "rubric":
        fixture.rubric.rubric_json = {"total_marks": "10.00", "criteria": [{"id": "x"}]}
    elif mutation == "model_answer":
        fixture.question.model_answer = "A different model answer"
    elif mutation == "assignment_version":
        fixture.assignment.assignment_version = 2
    elif mutation == "span_removed":
        fixture.assignment.spans.clear()
    db_session.commit()

    assert service.suggestion_evidence_status(fixture.suggestion) == "stale"

    superseded = service.supersede_stale_suggestions(
        submission_id=fixture.submission.id, reason="evidence changed in a test"
    )
    assert [item.id for item in superseded] == [fixture.suggestion.id]
    assert fixture.suggestion.superseded_at is not None
    # History is preserved: the draft is still readable, with its reason.
    assert fixture.suggestion.superseded_reason == "evidence changed in a test"
    assert db_session.get(GradeSuggestion, fixture.suggestion.id) is not None

    with pytest.raises(HTTPException) as caught:
        FinalGradeService(db_session).approve_suggestion(
            fixture.suggestion.id, teacher_id=fixture.teacher.id
        )
    assert caught.value.status_code == 409
    assert "evidence behind this draft has changed" in str(caught.value.detail)
    assert db_session.scalars(select(FinalGrade)).first() is None


def test_the_gate_holds_even_when_nothing_marked_the_draft_superseded(
    db_session: Session, tmp_path: Path
) -> None:
    """The check is at the irreversible step, not only at the change site."""
    fixture = _Graded(db_session, tmp_path)
    fixture.question.model_answer = "changed without calling any invalidation hook"
    db_session.commit()
    assert fixture.suggestion.superseded_at is None

    with pytest.raises(HTTPException) as caught:
        FinalGradeService(db_session).approve_suggestion(
            fixture.suggestion.id, teacher_id=fixture.teacher.id
        )
    assert caught.value.status_code == 409


def test_a_teacher_may_still_reject_a_draft_whose_evidence_moved(
    db_session: Session, tmp_path: Path
) -> None:
    """Refusing to record a rejection of stale evidence would be backwards."""
    fixture = _Graded(db_session, tmp_path)
    fixture.question.model_answer = "changed"
    db_session.commit()

    final_grade, _created = FinalGradeService(db_session).reject_suggestion(
        fixture.suggestion.id, teacher_id=fixture.teacher.id
    )
    assert final_grade.approval_status == "rejected"
    assert final_grade.final_score == 0


def test_a_draft_with_no_recorded_fingerprint_keeps_its_previous_behaviour(
    db_session: Session, tmp_path: Path
) -> None:
    """A null means 'never recorded', which is not a claim either way."""
    fixture = _Graded(db_session, tmp_path)
    fixture.suggestion.source_evidence_fingerprint = None
    fixture.question.model_answer = "changed"
    db_session.commit()
    service = EvidenceInvalidationService(db_session)

    assert service.suggestion_evidence_status(fixture.suggestion) == "unverified"
    assert service.supersede_stale_suggestions(
        submission_id=fixture.submission.id, reason="x"
    ) == []
    final_grade, _created = FinalGradeService(db_session).approve_suggestion(
        fixture.suggestion.id, teacher_id=fixture.teacher.id
    )
    assert final_grade.approval_status == "approved"


def test_the_fingerprint_is_stable_when_nothing_relevant_changed(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Graded(db_session, tmp_path)
    service = EvidenceInvalidationService(db_session)
    first = service.fingerprint_for_region(fixture.region)

    # Grading metadata is not evidence and must not move the fingerprint.
    fixture.suggestion.feedback = "some later reviewer note"
    fixture.suggestion.confidence = Decimal("0.5")
    db_session.commit()

    assert service.fingerprint_for_region(fixture.region) == first


def test_assert_raises_the_typed_error_outside_the_http_layer(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Graded(db_session, tmp_path)
    fixture.question.model_answer = "changed"
    db_session.commit()

    with pytest.raises(EvidenceChangedError):
        EvidenceInvalidationService(db_session).assert_suggestion_matches_current_evidence(
            fixture.suggestion
        )
