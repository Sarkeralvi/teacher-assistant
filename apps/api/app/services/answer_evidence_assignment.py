"""Derive which stored source blocks answer each canonical question.

This step reads only the persisted transcript and the canonical question
structure. It makes no provider request, so a remap, a corrected question
structure or a new rubric costs no vision work.

Two rules drive everything here:

* Question identity comes from the label the model reported reading, matched
  against the canonical structure, plus reading order. It never comes from a
  bounding box.
* A state is a claim about what is known. ``no_answer_found`` claims the whole
  script was processed and nothing was left over. A failed read, a missing page
  or writing nobody could place is a different claim and keeps its own state, so
  it can never be scored as a blank answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
)

ANSWER_PRESENT = "answer_present"
NO_ANSWER_FOUND = "no_answer_found"
UNREADABLE = "unreadable"
AMBIGUOUS = "ambiguous"
MISSING_PAGE = "missing_page"
PROCESSING_FAILED = "processing_failed"

EVIDENCE_STATES = (
    ANSWER_PRESENT,
    NO_ANSWER_FOUND,
    UNREADABLE,
    AMBIGUOUS,
    MISSING_PAGE,
    PROCESSING_FAILED,
)

# How each state appears to code that still reads the legacy mapping status.
# ``answer_region_mappings`` admits only four values and is deliberately not
# widened, so everything that is not reviewable draft evidence projects to
# 'blocked'. This preserves the page-read path's existing behaviour exactly:
# evidence produced a draft the teacher must review, absence produced a blocker.
LEGACY_MAPPING_STATUS_BY_STATE = {
    ANSWER_PRESENT: "uncertain",
    NO_ANSWER_FOUND: "blocked",
    UNREADABLE: "blocked",
    AMBIGUOUS: "blocked",
    MISSING_PAGE: "blocked",
    PROCESSING_FAILED: "blocked",
}


class AnswerEvidenceAssignmentError(RuntimeError):
    """An assignment could not be derived or stored safely."""


@dataclass(frozen=True)
class CanonicalQuestion:
    """One canonical grading unit, independent of any ORM session."""

    question_id: int
    question_node_id: int
    question_no: str


@dataclass
class QuestionEvidence:
    """The derived evidence for one canonical question, before persistence."""

    question: CanonicalQuestion
    state: str
    state_reason: str | None
    block_ids: list[int] = field(default_factory=list)
    page_numbers: list[int] = field(default_factory=list)
    unresolved_block_count: int = 0


@dataclass
class AssignmentDerivation:
    """The whole script's assignment decision for one transcript version."""

    by_question: list[QuestionEvidence]
    unassigned_block_ids: list[int]
    coverage_complete: bool
    unassigned_block_count: int
    coverage_reason: str | None
    basis_by_block_id: dict[int, str] = field(default_factory=dict)
    unplaced_reason_by_block_id: dict[int, str] = field(default_factory=dict)
    # Keyed by (page_no, block_index) so geometry assembly can consume exactly
    # the same ownership decision without recomputing it.
    owner_node_by_block_key: dict[tuple[int, int], int] = field(default_factory=dict)


EXPLICIT_LABEL = "explicit_label"
SAME_PAGE_READING_ORDER = "same_page_reading_order"
DECLARED_CONTINUATION = "declared_continuation"

ASSIGNMENT_BASES = (EXPLICIT_LABEL, SAME_PAGE_READING_ORDER, DECLARED_CONTINUATION)

UNPLACED_NO_PRECEDING_QUESTION = "no_preceding_canonical_question"
UNPLACED_UNKNOWN_LABEL = "label_matches_no_canonical_question"
UNPLACED_NO_CONTINUATION_CLAIM = "unlabelled_block_across_a_page_break_without_a_continuation_claim"


@dataclass(frozen=True)
class OwnershipInput:
    """The only block facts ownership is allowed to depend on.

    Deliberately excludes geometry. A box may order blocks on a page and may
    highlight one for a teacher, but it never decides which question an answer
    belongs to.
    """

    key: tuple[int, int]
    page_no: int
    question_label_raw: str | None
    label_source: str
    continues_from_previous: bool


@dataclass(frozen=True)
class OwnedBlock:
    source: OwnershipInput
    question: CanonicalQuestion
    basis: str

    @property
    def question_node_id(self) -> int:
        return self.question.question_node_id


@dataclass(frozen=True)
class UnplacedBlock:
    source: OwnershipInput
    reason: str


@dataclass(frozen=True)
class Ownership:
    owned: list[OwnedBlock]
    unplaced: list[UnplacedBlock]

    def node_by_key(self) -> dict[tuple[int, int], int]:
        return {item.source.key: item.question_node_id for item in self.owned}

    def basis_by_key(self) -> dict[tuple[int, int], str]:
        return {item.source.key: item.basis for item in self.owned}

    def unplaced_reason_by_key(self) -> dict[tuple[int, int], str]:
        return {item.source.key: item.reason for item in self.unplaced}


def resolve_block_ownership(
    *,
    blocks: list[OwnershipInput],
    questions: list[CanonicalQuestion],
) -> Ownership:
    """Decide which canonical question owns each block. One rule, one place.

    Both the evidence-assignment layer and the geometry/text assembly consume
    this. When they each decided ownership for themselves they could disagree,
    and a crop would then show evidence the assignment layer considered
    unplaced.

    An explicit label owns its block outright. An unlabelled block is *not*
    automatically a continuation:

    * on the same page as the block before it, reading order is directly
      observed, so it follows the current owner;
    * across a page break it follows the current owner only when the read
      actually claims ``continues_from_previous``; otherwise it stays unplaced
      and visible, and ownership is closed rather than carried on;
    * with no canonical question before it, it stays unplaced.

    A label matching no canonical question also closes ownership, so following
    blocks are not silently attached to the question before the unknown one.
    """

    by_label: dict[str, CanonicalQuestion] = {}
    for question in questions:
        key = question.question_no.strip().casefold()
        if key in by_label:
            raise AnswerEvidenceAssignmentError(
                "Canonical question labels must be unique to assign evidence"
            )
        by_label[key] = question

    owned: list[OwnedBlock] = []
    unplaced: list[UnplacedBlock] = []
    current: CanonicalQuestion | None = None
    previous_page_no: int | None = None

    for item in blocks:
        if item.question_label_raw is not None:
            matched = by_label.get(item.question_label_raw.strip().casefold())
            if matched is None:
                unplaced.append(UnplacedBlock(source=item, reason=UNPLACED_UNKNOWN_LABEL))
                current = None
                previous_page_no = item.page_no
                continue
            current = matched
            owned.append(
                OwnedBlock(
                    source=item,
                    question=matched,
                    basis=EXPLICIT_LABEL,
                )
            )
        elif current is None:
            unplaced.append(UnplacedBlock(source=item, reason=UNPLACED_NO_PRECEDING_QUESTION))
        elif previous_page_no == item.page_no:
            owned.append(
                OwnedBlock(
                    source=item,
                    question=current,
                    basis=SAME_PAGE_READING_ORDER,
                )
            )
        elif item.continues_from_previous:
            owned.append(
                OwnedBlock(
                    source=item,
                    question=current,
                    basis=DECLARED_CONTINUATION,
                )
            )
        else:
            unplaced.append(UnplacedBlock(source=item, reason=UNPLACED_NO_CONTINUATION_CLAIM))
            current = None
        previous_page_no = item.page_no

    return Ownership(owned=owned, unplaced=unplaced)


@dataclass(frozen=True)
class _OrderedBlock:
    block: ScriptTranscriptBlock
    page_no: int


def _ordered_blocks(transcript: ScriptTranscript) -> list[_OrderedBlock]:
    ordered: list[_OrderedBlock] = []
    for page in sorted(transcript.pages, key=lambda item: (item.page_order, item.page_no)):
        if page.state != "succeeded":
            continue
        for block in sorted(page.blocks, key=lambda item: item.block_index):
            ordered.append(_OrderedBlock(block=block, page_no=page.page_no))
    return ordered


def _coverage(transcript: ScriptTranscript) -> tuple[bool, str | None, set[str]]:
    """Report whether every source page of this script was actually read."""

    states = {page.state for page in transcript.pages}
    read_count = len(transcript.pages)
    if read_count < transcript.page_count:
        missing = transcript.page_count - read_count
        # A page that was never dispatched is not the same fact as a page
        # confirmed absent from the upload, so the real 'missing_page' state is
        # not synthesised here. Both block a blank claim; they say different
        # things to the teacher about what to do next.
        return (
            False,
            f"{missing} of {transcript.page_count} source pages were never read",
            states,
        )
    unread = sorted(state for state in states if state != "succeeded")
    if unread:
        return (
            False,
            f"source pages remain in state {', '.join(unread)}",
            states,
        )
    return True, None, states


def derive_assignments(
    *,
    transcript: ScriptTranscript,
    questions: list[CanonicalQuestion],
) -> AssignmentDerivation:
    """Assign stored blocks to canonical questions, deterministically.

    An explicit label owns its block. An unlabelled continuation block follows
    the nearest labelled block before it, across page breaks, and the next
    explicit label ends that ownership. Grouping is by canonical label rather
    than answer sequence, so a student may answer out of order and return to a
    question later.
    """

    coverage_complete, coverage_reason, page_states = _coverage(transcript)

    ordered = _ordered_blocks(transcript)
    by_key = {(item.page_no, item.block.block_index): item for item in ordered}
    ownership = resolve_block_ownership(
        blocks=[
            OwnershipInput(
                key=(item.page_no, item.block.block_index),
                page_no=item.page_no,
                question_label_raw=item.block.question_label_raw,
                label_source=item.block.label_source,
                continues_from_previous=item.block.continues_from_previous,
            )
            for item in ordered
        ],
        questions=questions,
    )

    blocks_by_node: dict[int, list[_OrderedBlock]] = {
        question.question_node_id: [] for question in questions
    }
    basis_by_block_id: dict[int, str] = {}
    inferred_nodes: set[int] = set()
    for owned in ownership.owned:
        item = by_key[owned.source.key]
        blocks_by_node[owned.question_node_id].append(item)
        basis_by_block_id[item.block.id] = owned.basis
        if item.block.label_source == "inferred":
            inferred_nodes.add(owned.question_node_id)

    # Only writing, not whitespace, counts as material a teacher must place.
    unassigned_material = [
        by_key[unplaced.source.key]
        for unplaced in ownership.unplaced
        if by_key[unplaced.source.key].block.text.strip()
    ]
    unassigned_count = len(unassigned_material)

    derived: list[QuestionEvidence] = []
    for question in questions:
        items = blocks_by_node[question.question_node_id]
        unresolved = [item for item in items if item.block.unresolved]
        state, reason = _state_for(
            question=question,
            has_evidence=bool(items),
            unresolved_count=len(unresolved),
            inferred=question.question_node_id in inferred_nodes,
            coverage_complete=coverage_complete,
            coverage_reason=coverage_reason,
            page_states=page_states,
            unassigned_count=unassigned_count,
        )
        derived.append(
            QuestionEvidence(
                question=question,
                state=state,
                state_reason=reason,
                block_ids=[item.block.id for item in items],
                page_numbers=[item.page_no for item in items],
                unresolved_block_count=len(unresolved),
            )
        )

    return AssignmentDerivation(
        by_question=derived,
        unassigned_block_ids=[item.block.id for item in unassigned_material],
        coverage_complete=coverage_complete,
        unassigned_block_count=unassigned_count,
        coverage_reason=coverage_reason,
        basis_by_block_id=basis_by_block_id,
        unplaced_reason_by_block_id={
            by_key[unplaced.source.key].block.id: unplaced.reason
            for unplaced in ownership.unplaced
        },
        owner_node_by_block_key=ownership.node_by_key(),
    )


def _state_for(
    *,
    question: CanonicalQuestion,
    has_evidence: bool,
    unresolved_count: int,
    inferred: bool,
    coverage_complete: bool,
    coverage_reason: str | None,
    page_states: set[str],
    unassigned_count: int,
) -> tuple[str, str | None]:
    """Choose the single state that describes what is actually known."""

    if has_evidence:
        if unresolved_count:
            return (
                UNREADABLE,
                f"{unresolved_count} assigned block(s) could not be read faithfully",
            )
        if inferred:
            return (
                AMBIGUOUS,
                "the question label was inferred rather than read, so ownership is unconfirmed",
            )
        return ANSWER_PRESENT, None

    # No evidence. The reason it is absent decides the state; "blank" is the
    # only reading that requires proof, and it is checked last.
    if "missing_page" in page_states:
        return MISSING_PAGE, "at least one source page of this script is missing"
    if {"failed", "unreadable"} & page_states:
        return (
            PROCESSING_FAILED,
            "at least one source page failed to read, so absence is not established",
        )
    # Incomplete coverage outranks ambiguity: unplaced writing is a question
    # about material that was read, while an unread page means the material was
    # never seen at all.
    if not coverage_complete:
        return (
            PROCESSING_FAILED,
            coverage_reason or "source coverage is incomplete",
        )
    if unassigned_count:
        return (
            AMBIGUOUS,
            f"{unassigned_count} block(s) of writing could not be placed against any question",
        )
    return (
        NO_ANSWER_FOUND,
        "the whole script was read and nothing answers this question",
    )


class AnswerEvidenceAssignmentService:
    """Persist derived assignments as a new, separately versioned record."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def load_transcript(self, transcript_id: int) -> ScriptTranscript:
        transcript = self.db.scalars(
            select(ScriptTranscript)
            .options(selectinload(ScriptTranscript.pages).selectinload(ScriptPageTranscript.blocks))
            .where(ScriptTranscript.id == transcript_id)
        ).first()
        if transcript is None:
            raise AnswerEvidenceAssignmentError("No such script transcript")
        return transcript

    def assign(
        self,
        *,
        submission_id: int,
        transcript: ScriptTranscript,
        questions: list[CanonicalQuestion],
    ) -> list[AnswerEvidenceAssignment]:
        """Derive and store the current assignment for every canonical question.

        Prior versions are retained and marked not current, so the evidence a
        teacher already looked at stays readable after a re-derivation.
        """

        derivation = derive_assignments(transcript=transcript, questions=questions)
        blocks = {
            block.id: (page.page_no, block)
            for page in transcript.pages
            for block in page.blocks
        }

        created: list[AnswerEvidenceAssignment] = []
        for evidence in derivation.by_question:
            node_id = evidence.question.question_node_id
            previous = self.db.scalars(
                select(AnswerEvidenceAssignment)
                .where(
                    AnswerEvidenceAssignment.script_transcript_id == transcript.id,
                    AnswerEvidenceAssignment.question_node_id == node_id,
                )
                .order_by(AnswerEvidenceAssignment.assignment_version.desc())
            ).all()
            for row in previous:
                row.is_current = False
            # Flushed before the insert so the partial unique index on
            # is_current never sees two current rows at once.
            self.db.flush()
            assignment = AnswerEvidenceAssignment(
                submission_id=submission_id,
                script_transcript_id=transcript.id,
                question_id=evidence.question.question_id,
                question_node_id=node_id,
                assignment_version=(previous[0].assignment_version + 1) if previous else 1,
                state=evidence.state,
                state_reason=evidence.state_reason,
                coverage_complete=derivation.coverage_complete,
                unresolved_block_count=evidence.unresolved_block_count,
                unassigned_block_count=derivation.unassigned_block_count,
                is_current=True,
            )
            for order_index, block_id in enumerate(evidence.block_ids):
                page_no, _block = blocks[block_id]
                assignment.spans.append(
                    AnswerEvidenceSpan(
                        script_transcript_block_id=block_id,
                        order_index=order_index,
                        page_no=page_no,
                        # Why this block is attached here, so a teacher can see
                        # the difference between a heading they can check and an
                        # inheritance the workflow inferred.
                        assignment_basis=derivation.basis_by_block_id[block_id],
                    )
                )
            self.db.add(assignment)
            created.append(assignment)
        self.db.commit()
        return created

    def current_assignments(self, transcript_id: int) -> list[AnswerEvidenceAssignment]:
        return list(
            self.db.scalars(
                select(AnswerEvidenceAssignment)
                .options(selectinload(AnswerEvidenceAssignment.spans))
                .where(
                    AnswerEvidenceAssignment.script_transcript_id == transcript_id,
                    AnswerEvidenceAssignment.is_current.is_(True),
                )
                .order_by(AnswerEvidenceAssignment.question_node_id)
            ).all()
        )

    def resolve_span_text(self, span: AnswerEvidenceSpan) -> str:
        """Resolve a span against the stored source, never a copied quote."""

        block = span.block
        if block is None:
            raise AnswerEvidenceAssignmentError("An evidence span must resolve to a source block")
        if span.char_start is None:
            return block.text
        if span.char_end is None or span.char_end > len(block.text):
            raise AnswerEvidenceAssignmentError(
                "An evidence span does not resolve inside its source block"
            )
        return block.text[span.char_start : span.char_end]


def legacy_mapping_status(state: str) -> str:
    """Project an evidence state onto the unchanged legacy mapping status."""

    try:
        return LEGACY_MAPPING_STATUS_BY_STATE[state]
    except KeyError as exc:  # pragma: no cover - guarded by the CHECK constraint
        raise AnswerEvidenceAssignmentError(f"{state!r} is not an evidence state") from exc


def assignment_summary(assignments: list[AnswerEvidenceAssignment]) -> dict[str, Any]:
    """Counts per state, for audit logging and teacher-facing readiness."""

    counts = dict.fromkeys(EVIDENCE_STATES, 0)
    for assignment in assignments:
        counts[assignment.state] += 1
    return {
        "states": counts,
        "review_ready": counts[ANSWER_PRESENT] > 0,
        "blocked_states": {
            state: counts[state]
            for state in (UNREADABLE, AMBIGUOUS, MISSING_PAGE, PROCESSING_FAILED)
            if counts[state]
        },
    }
