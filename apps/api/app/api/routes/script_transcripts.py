"""Read and correct the whole-script transcript, and the evidence it supports.

The teacher-facing half of the transcript-first workflow. Until now the durable
transcript existed only for the machinery that produced it; a reviewer could see
per-question draft text but never the script as one document, never which source
block a quote came from, never why a block was attached to a question, and never
that a page read had an outcome nobody could determine.

Everything here is read-or-correct. No route in this module makes a provider
request, creates a grade, or approves anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.submissions import get_owned_submission_or_404
from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import (
    AuditLog,
    Question,
    QuestionNode,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    ScriptTranscriptBlockRevision,
    User,
)
from app.schemas import (
    AnswerEvidenceRead,
    AnswerEvidenceSpanRead,
    ScriptTranscriptBlockRead,
    ScriptTranscriptBlockRevisionRead,
    ScriptTranscriptBlockUpdate,
    ScriptTranscriptPageRead,
    ScriptTranscriptRead,
    ScriptTranscriptReconcileRequest,
    SubmissionAnswerEvidenceRead,
)
from app.services.answer_evidence_assignment import (
    AnswerEvidenceAssignmentError,
    AnswerEvidenceAssignmentService,
    CanonicalQuestion,
    assignment_summary,
)
from app.services.evidence_invalidation import EvidenceInvalidationService
from app.services.script_transcript_store import (
    ScriptTranscriptError,
    ScriptTranscriptStore,
)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["script-transcripts"])


def _current_transcript(db: Session, submission_id: int) -> ScriptTranscript:
    transcript = db.scalars(
        select(ScriptTranscript)
        .options(
            selectinload(ScriptTranscript.pages)
            .selectinload(ScriptPageTranscript.blocks)
            .selectinload(ScriptTranscriptBlock.revisions)
        )
        .where(
            ScriptTranscript.submission_id == submission_id,
            ScriptTranscript.status != "superseded",
        )
        .order_by(ScriptTranscript.id.desc())
    ).first()
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This script has no source transcript yet",
        )
    return transcript


def _block_read(block: ScriptTranscriptBlock) -> ScriptTranscriptBlockRead:
    return ScriptTranscriptBlockRead(
        id=block.id,
        block_index=block.block_index,
        reading_order=block.reading_order,
        text=block.text,
        edited_text=block.edited_text,
        effective_text=block.effective_text,
        revision=block.revision,
        edited_at=block.edited_at,
        observed_heading_text=block.observed_heading_text,
        question_label_raw=block.question_label_raw,
        label_source=block.label_source,
        continues_from_previous=block.continues_from_previous,
        confidence=block.confidence,
        # Auxiliary navigation metadata only. Nothing in the workflow decides
        # question identity from it.
        bbox=(block.bbox_json or {}).get("normalized_bbox"),
        unresolved=block.unresolved,
        unresolved_reason=block.unresolved_reason,
    )


def _page_read(page: ScriptPageTranscript) -> ScriptTranscriptPageRead:
    return ScriptTranscriptPageRead(
        id=page.id,
        submission_page_id=page.submission_page_id,
        page_no=page.page_no,
        page_order=page.page_order,
        state=page.state,
        is_blank_page=page.is_blank_page,
        error=page.error,
        provider=page.provider,
        model_name=page.model_name,
        prompt_version=page.prompt_version,
        provider_request_count=page.provider_request_count,
        repair_pass=page.repair_pass,
        reserved_by=page.reserved_by,
        reserved_at=page.reserved_at,
        reconciled_at=page.reconciled_at,
        needs_reconciliation=page.state == "unknown_outcome",
        blocks=[
            _block_read(block)
            for block in sorted(page.blocks, key=lambda item: item.block_index)
        ],
    )


@router.get(
    "/submissions/{submission_id}/script-transcript",
    response_model=ScriptTranscriptRead,
)
def read_script_transcript(
    submission_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> ScriptTranscriptRead:
    """The whole script as one reviewable document, with its provenance."""

    get_owned_submission_or_404(submission_id, db, current_user)
    transcript = _current_transcript(db, submission_id)
    pages = sorted(transcript.pages, key=lambda item: (item.page_order, item.page_no))
    return ScriptTranscriptRead(
        id=transcript.id,
        submission_id=transcript.submission_id,
        status=transcript.status,
        provider=transcript.provider,
        model_name=transcript.model_name,
        prompt_version=transcript.prompt_version,
        schema_version=transcript.schema_version,
        source_manifest_sha256=transcript.source_manifest_sha256,
        page_count=transcript.page_count,
        pages_read=len(pages),
        # The real number of provider requests this transcript cost, summed
        # from the pages rather than estimated from the page count.
        provider_request_count=sum(page.provider_request_count for page in pages),
        pages_needing_reconciliation=[
            page.page_no for page in pages if page.state == "unknown_outcome"
        ],
        coverage_complete=(
            len(pages) == transcript.page_count
            and all(page.state == "succeeded" for page in pages)
        ),
        pages=[_page_read(page) for page in pages],
    )


@router.get(
    "/submissions/{submission_id}/answer-evidence",
    response_model=SubmissionAnswerEvidenceRead,
)
def read_answer_evidence(
    submission_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> SubmissionAnswerEvidenceRead:
    """Per-question evidence: state, why, and the exact source spans."""

    get_owned_submission_or_404(submission_id, db, current_user)
    transcript = _current_transcript(db, submission_id)
    service = AnswerEvidenceAssignmentService(db)
    assignments = service.current_assignments(transcript.id)
    blocks = {
        block.id: (page, block)
        for page in transcript.pages
        for block in page.blocks
    }
    assigned_block_ids = {
        span.script_transcript_block_id
        for assignment in assignments
        for span in assignment.spans
    }

    evidence: list[AnswerEvidenceRead] = []
    for assignment in assignments:
        question = db.get(Question, assignment.question_id)
        spans: list[AnswerEvidenceSpanRead] = []
        for span in sorted(assignment.spans, key=lambda item: item.order_index):
            entry = blocks.get(span.script_transcript_block_id)
            if entry is None:
                continue
            _page, block = entry
            spans.append(
                AnswerEvidenceSpanRead(
                    order_index=span.order_index,
                    page_no=span.page_no,
                    script_transcript_block_id=block.id,
                    assignment_basis=span.assignment_basis,
                    text=service.resolve_span_text(span),
                    unresolved=block.unresolved,
                    unresolved_reason=block.unresolved_reason,
                )
            )
        evidence.append(
            AnswerEvidenceRead(
                question_id=assignment.question_id,
                question_node_id=assignment.question_node_id,
                question_label=question.question_no if question else None,
                state=assignment.state,
                state_reason=assignment.state_reason,
                assignment_version=assignment.assignment_version,
                coverage_complete=assignment.coverage_complete,
                unresolved_block_count=assignment.unresolved_block_count,
                unassigned_block_count=assignment.unassigned_block_count,
                spans=spans,
            )
        )

    # Writing that belongs to no question stays visible rather than being
    # attached to whichever question happened to be nearest.
    unassigned = [
        _block_read(block)
        for page in sorted(transcript.pages, key=lambda item: item.page_order)
        for block in sorted(page.blocks, key=lambda item: item.block_index)
        if block.id not in assigned_block_ids and block.effective_text.strip()
    ]
    return SubmissionAnswerEvidenceRead(
        submission_id=submission_id,
        script_transcript_id=transcript.id,
        summary=assignment_summary(assignments),
        evidence=evidence,
        unassigned_blocks=unassigned,
    )


@router.patch(
    "/script-transcript-blocks/{block_id}",
    response_model=ScriptTranscriptBlockRead,
)
def correct_script_transcript_block(
    block_id: int,
    payload: ScriptTranscriptBlockUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> ScriptTranscriptBlockRead:
    """Record a teacher's correction without overwriting what the model read.

    ``text`` keeps the verbatim provider output. The correction is a new
    revision, so a model error stays distinguishable from a human fix and the
    next preparation cannot mistake one for the other.
    """

    block = db.get(ScriptTranscriptBlock, block_id)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transcript block not found"
        )
    page = db.get(ScriptPageTranscript, block.script_page_transcript_id)
    transcript = db.get(ScriptTranscript, page.script_transcript_id) if page else None
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transcript block not found"
        )
    get_owned_submission_or_404(transcript.submission_id, db, current_user)

    previous = block.effective_text
    if payload.edited_text == previous:
        return _block_read(block)

    block.revision += 1
    block.edited_text = payload.edited_text
    block.edited_at = datetime.now(UTC)
    block.edited_by_teacher_id = current_user.id
    db.add(
        ScriptTranscriptBlockRevision(
            script_transcript_block_id=block.id,
            revision=block.revision,
            previous_text=previous,
            new_text=payload.edited_text,
            reason=payload.reason,
            edited_by_teacher_id=current_user.id,
        )
    )
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="script_transcript_block_corrected",
            entity_type="script_transcript_block",
            entity_id=block.id,
            payload_json={
                "script_transcript_id": transcript.id,
                "submission_id": transcript.submission_id,
                "page_no": page.page_no if page else None,
                "revision": block.revision,
                # The text itself is student-derived and is deliberately not
                # copied into the audit log.
                "reason": payload.reason,
            },
        )
    )
    db.flush()
    # A correction is new evidence, so any draft grade produced from the old
    # text is marked out of date. Nothing is deleted or re-graded.
    EvidenceInvalidationService(db).supersede_stale_suggestions(
        submission_id=transcript.submission_id,
        reason="the source transcript was corrected by a teacher",
    )
    db.commit()
    db.refresh(block)
    return _block_read(block)


@router.get(
    "/script-transcript-blocks/{block_id}/revisions",
    response_model=list[ScriptTranscriptBlockRevisionRead],
)
def read_script_transcript_block_revisions(
    block_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> list[ScriptTranscriptBlockRevisionRead]:
    block = db.get(ScriptTranscriptBlock, block_id)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transcript block not found"
        )
    page = db.get(ScriptPageTranscript, block.script_page_transcript_id)
    transcript = db.get(ScriptTranscript, page.script_transcript_id) if page else None
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transcript block not found"
        )
    get_owned_submission_or_404(transcript.submission_id, db, current_user)
    return [
        ScriptTranscriptBlockRevisionRead(
            revision=item.revision,
            previous_text=item.previous_text,
            new_text=item.new_text,
            reason=item.reason,
            created_at=item.created_at,
        )
        for item in sorted(block.revisions, key=lambda item: item.revision)
    ]


@router.post(
    "/script-transcript-pages/{page_transcript_id}/reconcile",
    response_model=ScriptTranscriptPageRead,
)
def reconcile_script_transcript_page(
    page_transcript_id: int,
    payload: ScriptTranscriptReconcileRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ScriptTranscriptPageRead:
    """Settle a page read whose provider outcome nobody could determine.

    Never automatic. The provider may have produced and billed a result nobody
    saw, so a person records what they decided and only then does the page
    become readable again.
    """

    page = db.get(ScriptPageTranscript, page_transcript_id)
    transcript = db.get(ScriptTranscript, page.script_transcript_id) if page else None
    if page is None or transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Page transcript not found"
        )
    get_owned_submission_or_404(transcript.submission_id, db, current_user)
    store = ScriptTranscriptStore(db)
    try:
        updated = store.reconcile_page(
            transcript=transcript,
            submission_page_id=page.submission_page_id,
            resolution=payload.resolution,
            note=payload.note,
        )
    except ScriptTranscriptError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="script_page_read_reconciled",
            entity_type="script_page_transcript",
            entity_id=updated.id,
            payload_json={
                "script_transcript_id": transcript.id,
                "submission_id": transcript.submission_id,
                "page_no": updated.page_no,
                "resolution": payload.resolution,
                "note": payload.note,
            },
        )
    )
    db.commit()
    db.refresh(updated)
    return _page_read(updated)


@router.post(
    "/submissions/{submission_id}/answer-evidence/rederive",
    response_model=SubmissionAnswerEvidenceRead,
)
def rederive_answer_evidence(
    submission_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> SubmissionAnswerEvidenceRead:
    """Re-run assignment against the stored transcript. Makes no provider call.

    This is the operation a corrected transcript or a corrected canonical
    question structure needs, and the reason the transcript is stored at all:
    it costs nothing and reads no page again.
    """

    get_owned_submission_or_404(submission_id, db, current_user)
    transcript = _current_transcript(db, submission_id)
    nodes = db.scalars(
        select(QuestionNode)
        .join(Question, Question.assessment_id == QuestionNode.assessment_id)
        .where(QuestionNode.teacher_confirmed.is_(True))
        .where(QuestionNode.node_type.in_(["question", "subquestion"]))
    ).unique().all()
    node_by_label = {}
    for node in nodes:
        for value in (node.label, node.question_number):
            node_by_label.setdefault(value.strip().casefold(), node)

    existing = AnswerEvidenceAssignmentService(db).current_assignments(transcript.id)
    canonical: list[CanonicalQuestion] = []
    for assignment in existing:
        question = db.get(Question, assignment.question_id)
        if question is None:
            continue
        canonical.append(
            CanonicalQuestion(
                question_id=question.id,
                question_node_id=assignment.question_node_id,
                question_no=question.question_no,
            )
        )
    if not canonical:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This script has no canonical question assignment to re-derive",
        )

    service = AnswerEvidenceAssignmentService(db)
    try:
        service.assign(
            submission_id=submission_id,
            transcript=service.load_transcript(transcript.id),
            questions=canonical,
        )
    except AnswerEvidenceAssignmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    EvidenceInvalidationService(db).supersede_stale_suggestions(
        submission_id=submission_id,
        reason="the question assignment was re-derived from the stored transcript",
    )
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="answer_evidence_rederived",
            entity_type="submission",
            entity_id=submission_id,
            payload_json={
                "script_transcript_id": transcript.id,
                "provider_request_count": 0,
                "question_count": len(canonical),
            },
        )
    )
    db.commit()
    return read_answer_evidence(submission_id, db, current_user)
