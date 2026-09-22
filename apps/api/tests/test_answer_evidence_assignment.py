"""Question assignment derived from the stored transcript, with distinct states.

Every assertion about a state is made against ``AnswerEvidenceAssignment.state``,
not against the legacy ``answer_region_mappings.mapping_status``. The legacy
column admits only four values and is deliberately unchanged, so asserting on it
would pass without proving the six states are actually distinguished.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.db.session import SessionLocal
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    Assessment,
    Course,
    ExtractionRun,
    Question,
    QuestionNode,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
    User,
)
from app.services.answer_evidence_assignment import (
    AMBIGUOUS,
    ANSWER_PRESENT,
    MISSING_PAGE,
    NO_ANSWER_FOUND,
    PROCESSING_FAILED,
    UNREADABLE,
    AnswerEvidenceAssignmentError,
    AnswerEvidenceAssignmentService,
    CanonicalQuestion,
    assignment_summary,
    legacy_mapping_status,
)
from app.services.script_transcript_store import ScriptTranscriptStore
from packages.brain.schemas_qwen38 import (
    UNRESOLVED_VISIBLE_WRITING,
    VISUAL_PAGE_READ_PROMPT_VERSION,
    VisualPageBlock,
    VisualPageTranscriptOutput,
)

CLEANUP_MODELS = (
    AnswerEvidenceSpan,
    AnswerEvidenceAssignment,
    ScriptTranscriptBlock,
    ScriptPageTranscript,
    ScriptTranscript,
    SubmissionPage,
    Submission,
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


class _Fixture:
    def __init__(self, db: Session, tmp_path: Path, labels: list[str], page_count: int) -> None:
        self.db = db
        teacher = User(
            name="Teacher",
            email=f"assign-{uuid4().hex}@example.com",
            password_hash="x",
            role="teacher",
        )
        db.add(teacher)
        db.flush()
        self.teacher = teacher
        course = Course(teacher_id=teacher.id, code=f"C{uuid4().hex[:6]}", title="Course")
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
        self.questions: list[CanonicalQuestion] = []
        for label in labels:
            question = Question(
                assessment_id=assessment.id,
                question_no=label,
                question_text=f"Explain {label}",
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
            self.questions.append(
                CanonicalQuestion(
                    question_id=question.id,
                    question_node_id=node.id,
                    question_no=label,
                )
            )
        self.submission = Submission(
            assessment_id=assessment.id,
            student_identifier="S-001",
            status="ready",
        )
        db.add(self.submission)
        db.flush()
        self.pages: list[SubmissionPage] = []
        for page_no in range(1, page_count + 1):
            path = tmp_path / f"page-{page_no}.png"
            Image.new("RGB", (400, 400), "white").save(path)
            page = SubmissionPage(
                submission_id=self.submission.id,
                page_no=page_no,
                image_path=str(path),
            )
            db.add(page)
            self.pages.append(page)
        db.commit()
        self.store = ScriptTranscriptStore(db)
        digests = [
            hashlib.sha256(Path(page.image_path).read_bytes()).hexdigest() + str(page.page_no)
            for page in self.pages
        ]
        self.transcript = self.store.get_or_create(
            submission_id=self.submission.id,
            provider="mock",
            model_name="mock-vision-1",
            prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
            ordered_page_hashes=[digest[:64] for digest in digests],
        )
        self._reading_order = 0

    def read_page(
        self,
        index: int,
        *blocks: VisualPageBlock,
        blank: bool = False,
    ) -> ScriptPageTranscript:
        page = self.pages[index]
        output = VisualPageTranscriptOutput(blocks=list(blocks), is_blank_page=blank)
        stored = self.store.record_page_success(
            transcript=self.transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=index,
            source_image_sha256=hashlib.sha256(str(page.id).encode()).hexdigest(),
            output=output,
            reading_order_start=self._reading_order,
        )
        self._reading_order += len(blocks)
        return stored

    def fail_page(self, index: int, *, state: str, error: str) -> ScriptPageTranscript:
        page = self.pages[index]
        return self.store.record_page_failure(
            transcript=self.transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=index,
            source_image_sha256=hashlib.sha256(str(page.id).encode()).hexdigest(),
            state=state,
            error=error,
        )

    def assign(self) -> dict[str, AnswerEvidenceAssignment]:
        service = AnswerEvidenceAssignmentService(self.db)
        transcript = service.load_transcript(self.transcript.id)
        service.assign(
            submission_id=self.submission.id,
            transcript=transcript,
            questions=self.questions,
        )
        by_node = {question.question_node_id: question.question_no for question in self.questions}
        return {
            by_node[assignment.question_node_id]: assignment
            for assignment in service.current_assignments(self.transcript.id)
        }


def _block(
    label: str | None,
    text: str,
    *,
    top: int = 100,
    label_source: str | None = None,
    continues: bool = False,
) -> VisualPageBlock:
    return VisualPageBlock(
        question_label=label,
        bbox=[50, top, 950, top + 200],
        text=text,
        continues_from_previous=continues,
        label_source=label_source or ("continuation" if label is None else "heading"),
        confidence=Decimal("0.95"),
    )


def test_a_fully_read_script_distinguishes_an_answer_from_a_genuine_blank(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=1)
    fixture.read_page(0, _block("Q1", "the answer to one"))

    assignments = fixture.assign()

    assert assignments["Q1"].state == ANSWER_PRESENT
    assert assignments["Q1"].state_reason is None
    assert [span.page_no for span in assignments["Q1"].spans] == [1]
    # Q2 is the only case in which "no answer" is a supportable claim: the whole
    # script was read and nothing was left unplaced.
    assert assignments["Q2"].state == NO_ANSWER_FOUND
    assert assignments["Q2"].coverage_complete is True
    assert assignments["Q2"].unassigned_block_count == 0
    assert assignments["Q2"].spans == []


def test_a_failed_page_never_becomes_a_blank_answer(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=2)
    fixture.read_page(0, _block("Q1", "the answer to one"))
    fixture.fail_page(1, state="failed", error="provider timed out")

    assignments = fixture.assign()

    assert assignments["Q2"].state == PROCESSING_FAILED
    assert "absence is not established" in (assignments["Q2"].state_reason or "")
    assert assignments["Q2"].coverage_complete is False
    # Q1's evidence is still real, but the script is not fully covered.
    assert assignments["Q1"].state == ANSWER_PRESENT
    assert assignments["Q1"].coverage_complete is False


def test_a_missing_page_is_distinct_from_a_failed_read(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=2)
    fixture.read_page(0, _block("Q1", ""))
    fixture.fail_page(1, state="missing_page", error="source page absent from the upload")

    assignments = fixture.assign()

    # Q1 does have a block, but it carries no faithful text.
    assert assignments["Q1"].state == UNREADABLE
    assert assignments["Q1"].unresolved_block_count == 1
    # Q2 has nothing, and a confirmed-absent page says why. That is a different
    # fact from a read that failed, and it keeps its own state.
    assert assignments["Q2"].state == MISSING_PAGE
    assert "missing" in (assignments["Q2"].state_reason or "")


def test_a_page_that_was_never_read_is_not_reported_as_a_missing_page(
    db_session: Session, tmp_path: Path
) -> None:
    """Stopping early and a page absent from the upload are different facts."""
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=3)
    fixture.read_page(0, _block("Q2x", "writing nobody can place"))

    assignments = fixture.assign()

    assert assignments["Q1"].state == PROCESSING_FAILED
    assert "never read" in (assignments["Q1"].state_reason or "")
    assert assignments["Q1"].coverage_complete is False
    # The unknown label is not discarded: it stays counted as unplaced writing.
    assert assignments["Q1"].unassigned_block_count == 1


def test_unreadable_writing_is_not_an_answer(db_session: Session, tmp_path: Path) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    fixture.read_page(0, _block("Q1", f"first line {UNRESOLVED_VISIBLE_WRITING}"))

    assignments = fixture.assign()

    assert assignments["Q1"].state == UNREADABLE
    assert assignments["Q1"].unresolved_block_count == 1
    assert "faithfully" in (assignments["Q1"].state_reason or "")


def test_unplaceable_writing_makes_a_question_ambiguous_not_blank(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=1)
    # Leading writing with no canonical label before it, then a labelled block.
    fixture.read_page(
        0,
        _block(None, "unowned leading work", top=50),
        _block("Q1", "the answer to one", top=400),
    )

    assignments = fixture.assign()

    assert assignments["Q1"].state == ANSWER_PRESENT
    assert assignments["Q2"].state == AMBIGUOUS
    assert assignments["Q2"].unassigned_block_count == 1
    assert "could not be placed" in (assignments["Q2"].state_reason or "")


def test_teacher_assignment_override_moves_a_block_without_overwriting_model_label(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=1)
    page = fixture.read_page(0, _block("Q1", "actually answers question two"))
    block = page.blocks[0]
    block.assignment_override_active = True
    block.teacher_question_label = "Q2"
    block.teacher_continues_from_previous = False
    block.assignment_override_revision = 1
    block.assignment_edited_at = datetime.now(UTC)
    block.assignment_edited_by_teacher_id = fixture.teacher.id
    db_session.commit()

    assignments = fixture.assign()

    assert block.question_label_raw == "Q1"
    assert assignments["Q1"].state == NO_ANSWER_FOUND
    assert assignments["Q2"].state == ANSWER_PRESENT
    assert assignments["Q2"].spans[0].script_transcript_block_id == block.id


def test_teacher_non_answer_page_keeps_text_but_excludes_it_from_evidence(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    page = fixture.read_page(0, _block(None, "University cover sheet"))
    page.teacher_classification = "non_answer"
    page.classified_at = datetime.now(UTC)
    page.classified_by_teacher_id = fixture.teacher.id
    db_session.commit()

    assignments = fixture.assign()

    assert page.blocks[0].text == "University cover sheet"
    assert assignments["Q1"].state == NO_ANSWER_FOUND
    assert assignments["Q1"].unassigned_block_count == 0


def test_an_inferred_label_is_ambiguous_rather_than_a_confirmed_answer(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    fixture.read_page(0, _block("Q1", "probably one", label_source="inferred"))

    assignments = fixture.assign()

    assert assignments["Q1"].state == AMBIGUOUS
    assert "inferred" in (assignments["Q1"].state_reason or "")
    # The evidence is still attached, so a teacher can confirm or move it.
    assert len(assignments["Q1"].spans) == 1


def test_one_answer_spans_nonadjacent_pages_in_reading_order(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2"], page_count=3)
    fixture.read_page(0, _block("Q1", "first part of one"))
    fixture.read_page(1, _block("Q2", "all of two"))
    fixture.read_page(
        2,
        _block("Q1", "returned to one", top=100),
        _block(None, "and continued", top=400, continues=True),
    )

    assignments = fixture.assign()

    assert assignments["Q1"].state == ANSWER_PRESENT
    assert [span.page_no for span in assignments["Q1"].spans] == [1, 3, 3]
    assert [span.order_index for span in assignments["Q1"].spans] == [0, 1, 2]
    assert [span.page_no for span in assignments["Q2"].spans] == [2]


def test_a_continuation_crosses_a_page_break_to_its_owner(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=2)
    fixture.read_page(0, _block("Q1", "the start"))
    fixture.read_page(1, _block(None, "the finish", continues=True))

    assignments = fixture.assign()

    assert assignments["Q1"].state == ANSWER_PRESENT
    assert [span.page_no for span in assignments["Q1"].spans] == [1, 2]


def test_reassignment_versions_rather_than_overwriting(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    fixture.read_page(0, _block("Q1", "the answer to one"))
    first = fixture.assign()
    assert first["Q1"].assignment_version == 1

    # Re-deriving is what a remap or a corrected question structure triggers.
    # It must not read the source again, and it must not erase what a teacher
    # has already seen.
    second = fixture.assign()

    assert second["Q1"].assignment_version == 2
    assert second["Q1"].is_current is True
    history = db_session.scalars(
        select(AnswerEvidenceAssignment)
        .where(AnswerEvidenceAssignment.script_transcript_id == fixture.transcript.id)
        .order_by(AnswerEvidenceAssignment.assignment_version)
    ).all()
    assert [row.assignment_version for row in history] == [1, 2]
    assert [row.is_current for row in history] == [False, True]
    # Only one current row per canonical question, enforced by the index.
    assert sum(1 for row in history if row.is_current) == 1


def test_a_span_resolves_against_the_stored_source_text(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    fixture.read_page(0, _block("Q1", "integral of x dx equals x squared over two"))
    assignments = fixture.assign()
    service = AnswerEvidenceAssignmentService(db_session)
    span = assignments["Q1"].spans[0]

    assert service.resolve_span_text(span) == "integral of x dx equals x squared over two"

    span.char_start = 0
    span.char_end = 10
    db_session.flush()
    assert service.resolve_span_text(span) == "integral o"

    span.char_end = 9999
    db_session.flush()
    with pytest.raises(AnswerEvidenceAssignmentError, match="does not resolve inside"):
        service.resolve_span_text(span)
    db_session.rollback()


def test_the_database_refuses_a_blank_claim_without_coverage(
    db_session: Session, tmp_path: Path
) -> None:
    """The safety rule is a constraint, not only service logic."""
    fixture = _Fixture(db_session, tmp_path, ["Q1"], page_count=1)
    fixture.read_page(0, _block("Q1", "an answer"))
    question = fixture.questions[0]

    db_session.add(
        AnswerEvidenceAssignment(
            submission_id=fixture.submission.id,
            script_transcript_id=fixture.transcript.id,
            question_id=question.question_id,
            question_node_id=question.question_node_id,
            assignment_version=1,
            state=NO_ANSWER_FOUND,
            state_reason="claimed without coverage",
            coverage_complete=False,
            unresolved_block_count=0,
            unassigned_block_count=0,
            is_current=True,
        )
    )
    with pytest.raises(Exception, match="ck_answer_evidence_no_answer_requires_coverage"):
        db_session.flush()
    db_session.rollback()


def test_the_legacy_status_projection_keeps_every_non_answer_blocked() -> None:
    assert legacy_mapping_status(ANSWER_PRESENT) == "uncertain"
    for state in (NO_ANSWER_FOUND, UNREADABLE, AMBIGUOUS, MISSING_PAGE, PROCESSING_FAILED):
        assert legacy_mapping_status(state) == "blocked"
    with pytest.raises(AnswerEvidenceAssignmentError):
        legacy_mapping_status("teacher_confirmed")


def test_the_summary_reports_each_state_separately(
    db_session: Session, tmp_path: Path
) -> None:
    fixture = _Fixture(db_session, tmp_path, ["Q1", "Q2", "Q3"], page_count=1)
    fixture.read_page(
        0,
        _block("Q1", "a real answer", top=50),
        _block("Q2", f"{UNRESOLVED_VISIBLE_WRITING}", top=400),
    )

    summary = assignment_summary(list(fixture.assign().values()))

    assert summary["states"][ANSWER_PRESENT] == 1
    assert summary["states"][UNREADABLE] == 1
    assert summary["states"][NO_ANSWER_FOUND] == 1
    assert summary["blocked_states"] == {UNREADABLE: 1}
