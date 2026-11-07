from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.ownership import get_owned_assessment_or_404
from app.db.session import get_db
from app.models import (
    BulkEvaluationItem,
    BulkEvaluationRun,
    GradingRun,
    Question,
    ScriptTranscript,
    Submission,
    User,
)
from app.schemas import (
    BulkEvaluationApprovalPreview,
    BulkEvaluationApprovalRequest,
    BulkEvaluationApprovalResponse,
    BulkEvaluationCallLimitRequest,
    BulkEvaluationExceptionRead,
    BulkEvaluationItemRead,
    BulkEvaluationReleaseResponse,
    BulkEvaluationReleaseSkipped,
    BulkEvaluationRunRead,
)
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.transcript_review import transcript_review_is_current
from app.worker.jobs import run_bulk_evaluation_next_job
from app.worker.rq_app import get_default_queue
from packages.brain.adapter import BrainProviderConfigurationError
from packages.brain.capabilities import BrainExecutionLocation
from packages.brain.policy import brain_policy_for_profile

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["bulk-evaluations"])


def _owned_run(run_id: int, db: Session, teacher: User) -> BulkEvaluationRun:
    run = db.scalar(
        select(BulkEvaluationRun)
        .options(selectinload(BulkEvaluationRun.items))
        .where(
            BulkEvaluationRun.id == run_id,
            BulkEvaluationRun.created_by_teacher_id == teacher.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Bulk evaluation run not found")
    return run


_REVIEWABLE_RUN_STATUSES = frozenset({"review_ready", "completed_with_exceptions"})


def _run_read(db: Session, run: BulkEvaluationRun) -> BulkEvaluationRunRead:
    """The run as the teacher sees it, with the clean-draft hash computed now.

    The stored hash dates from the end of processing; any per-item decision since then moved the
    clean set, so posting it back would be refused. The value shown is the one approve-clean
    recomputes, for exactly the items in this response.
    """

    live = (
        BulkEvaluationService(db).review_snapshot_hash(run)
        if run.status in _REVIEWABLE_RUN_STATUSES
        else None
    )
    # Validated after the hash: computing it also links items to any final grade made since.
    read = BulkEvaluationRunRead.model_validate(run)
    if live is not None:
        read = read.model_copy(update={"review_snapshot_sha256": live})
    return read


def _enqueue(run_id: int, provider: str) -> None:
    settings = get_settings()
    timeout = brain_policy_for_profile(settings, provider).job_timeout_seconds
    get_default_queue().enqueue(
        run_bulk_evaluation_next_job,
        run_id,
        retry=None,
        job_timeout=max(3600, timeout),
    )


_ACTIVE_RUN_STATUSES = frozenset(
    {"preflighting", "queued", "reading", "mapping", "transcribing", "grading", "stopping"}
)


def _enqueue_or_pause(db: Session, run: BulkEvaluationRun, *, pause: bool = True) -> None:
    """Queue the next unit for a resumed run, or fail visibly instead of stranding it.

    If the queue is down, the run the route just made active has no job anywhere, so it is
    paused (the same state the create route and the worker chain use) and the caller gets a 503.
    ``pause=False`` is for a run that was already active before the route touched it: its own
    worker chain may still be alive, so the failed extra enqueue must not stop it.
    """

    try:
        _enqueue(run.id, run.provider)
    except Exception as exc:
        if pause:
            BulkEvaluationService(db).pause_after_enqueue_failure(run.id)
        raise HTTPException(status_code=503, detail="Bulk evaluation could not be resumed") from exc


@router.post(
    "/assessments/{assessment_id}/bulk-evaluation-runs",
    response_model=BulkEvaluationRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_bulk_evaluation_run(
    assessment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    grading_run_id: Annotated[int, Form(gt=0)],
    provider: Annotated[str, Form(min_length=1, max_length=64)],
    expected_model: Annotated[str, Form(min_length=1, max_length=255)],
    marking_policy: Annotated[Literal["tough", "general", "easy"], Form()] = "general",
    maximum_provider_calls: Annotated[int, Form(ge=1, le=2000)] = 1800,
    local_only_confirmed: Annotated[bool, Form()] = False,
    provider_data_boundary_confirmed: Annotated[bool, Form()] = False,
    strict_auto_pass_confirmed: Annotated[bool, Form()] = False,
    draft_only_confirmed: Annotated[bool, Form()] = False,
) -> BulkEvaluationRun:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    if not (strict_auto_pass_confirmed and draft_only_confirmed):
        raise HTTPException(
            status_code=422,
            detail="Strict auto-pass and draft-only authorization are required",
        )
    try:
        policy = brain_policy_for_profile(get_settings(), provider)
    except BrainProviderConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if (
        policy.location is BrainExecutionLocation.CLOUD
        and not provider_data_boundary_confirmed
    ):
        raise HTTPException(
            status_code=422,
            detail="Cloud provider data transfer must be explicitly confirmed",
        )
    if policy.location is not BrainExecutionLocation.CLOUD and not local_only_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Local/provider-managed processing must be explicitly confirmed",
        )
    grading_run = db.get(GradingRun, grading_run_id)
    if (
        grading_run is None
        or grading_run.assessment_id != assessment_id
        or grading_run.created_by_teacher_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Grading run not found")
    created_run: BulkEvaluationRun | None = None
    service = BulkEvaluationService(db)
    try:
        created_run = service.create_from_zip(
            assessment_id=assessment_id,
            grading_run=grading_run,
            teacher=current_user,
            upload=file,
            expected_model=expected_model,
            marking_policy=marking_policy,
            maximum_provider_calls=maximum_provider_calls,
            provider=provider,
        )
        if service.reused_existing_run:
            # An idempotent re-upload: that run already has (or has paused) its own worker chain.
            return created_run
        _enqueue(created_run.id, created_run.provider)
        return created_run
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if created_run is not None and created_run.status == "queued":
            created_run.status = "paused"
            created_run.error = "Bulk worker could not be enqueued"
            db.commit()
        raise HTTPException(status_code=503, detail="Bulk evaluation could not be started") from exc


@router.get("/bulk-evaluation-runs/{run_id}", response_model=BulkEvaluationRunRead)
def read_bulk_evaluation_run(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationRunRead:
    return _run_read(db, _owned_run(run_id, db, current_user))


@router.get(
    "/assessments/{assessment_id}/bulk-evaluation-runs",
    response_model=list[BulkEvaluationRunRead],
)
def list_bulk_evaluation_runs(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> list[BulkEvaluationRunRead]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    runs = db.scalars(
        select(BulkEvaluationRun)
        .options(selectinload(BulkEvaluationRun.items))
        .where(
            BulkEvaluationRun.assessment_id == assessment_id,
            BulkEvaluationRun.created_by_teacher_id == current_user.id,
        )
        .order_by(BulkEvaluationRun.id.desc())
    ).all()
    return [_run_read(db, run) for run in runs]


@router.post("/bulk-evaluation-runs/{run_id}/stop", response_model=BulkEvaluationRunRead)
def stop_bulk_evaluation_run(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationRun:
    run = _owned_run(run_id, db, current_user)
    return BulkEvaluationService(db).stop(run, teacher_id=current_user.id)


@router.post("/bulk-evaluation-runs/{run_id}/resume", response_model=BulkEvaluationRunRead)
def resume_bulk_evaluation_run(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationRun:
    run = _owned_run(run_id, db, current_user)
    try:
        resumed = BulkEvaluationService(db).resume(run, teacher_id=current_user.id)
        _enqueue_or_pause(db, run)
        return resumed
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/bulk-evaluation-runs/{run_id}/exceptions",
    response_model=list[BulkEvaluationExceptionRead],
)
def list_bulk_evaluation_exceptions(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> list[BulkEvaluationExceptionRead]:
    run = _owned_run(run_id, db, current_user)
    rows = db.execute(
        select(BulkEvaluationItem, Submission, Question)
        .join(Submission, Submission.id == BulkEvaluationItem.submission_id)
        .join(Question, Question.id == BulkEvaluationItem.question_id)
        .where(
            BulkEvaluationItem.run_id == run.id,
            BulkEvaluationItem.status.in_(("exception", "uncertain")),
        )
        .order_by(Submission.student_identifier, Question.id)
    ).all()
    submission_ids = {submission.id for _, submission, _ in rows}
    transcripts_by_submission: dict[int, ScriptTranscript] = {}
    transcript_review_by_submission: dict[int, bool] = {}
    if submission_ids:
        transcripts = db.scalars(
            select(ScriptTranscript)
            .where(
                ScriptTranscript.submission_id.in_(submission_ids),
                ScriptTranscript.status != "superseded",
            )
            .order_by(ScriptTranscript.id.desc())
        ).all()
        for transcript in transcripts:
            transcripts_by_submission.setdefault(transcript.submission_id, transcript)
        transcript_review_by_submission = {
            submission_id: transcript_review_is_current(db, transcript)
            for submission_id, transcript in transcripts_by_submission.items()
        }
    return [
        BulkEvaluationExceptionRead(
            item_id=item.id,
            submission_id=submission.id,
            student_identifier=submission.student_identifier,
            question_id=question.id,
            question_label=question.question_no,
            answer_region_id=item.answer_region_id,
            stage=item.stage,
            exception_codes=item.exception_codes,
            warnings=item.warnings,
            transcript_review_is_current=transcript_review_by_submission.get(
                submission.id, False
            ),
        )
        for item, submission, question in rows
    ]


@router.get(
    "/bulk-evaluation-runs/{run_id}/items/{item_id}",
    response_model=BulkEvaluationItemRead,
)
def read_bulk_evaluation_item(
    run_id: int, item_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationItem:
    run = _owned_run(run_id, db, current_user)
    item = db.get(BulkEvaluationItem, item_id)
    if item is None or item.run_id != run.id:
        raise HTTPException(status_code=404, detail="Bulk evaluation item not found")
    return item


@router.post(
    "/bulk-evaluation-runs/{run_id}/items/{item_id}/resume",
    response_model=BulkEvaluationItemRead,
)
def resume_bulk_evaluation_item(
    run_id: int, item_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationItem:
    run = _owned_run(run_id, db, current_user)
    item = db.get(BulkEvaluationItem, item_id)
    if item is None or item.run_id != run.id:
        raise HTTPException(status_code=404, detail="Bulk evaluation item not found")
    was_active = run.status in _ACTIVE_RUN_STATUSES
    try:
        resumed = BulkEvaluationService(db).resume_item(
            run, item, teacher_id=current_user.id
        )
        _enqueue_or_pause(db, run, pause=not was_active)
        return resumed
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/bulk-evaluation-runs/{run_id}/release-reviewed",
    response_model=BulkEvaluationReleaseResponse,
)
def release_reviewed_to_grading(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationReleaseResponse:
    """Release every script whose transcript review is confirmed to grading (one action)."""

    run = _owned_run(run_id, db, current_user)
    was_active = run.status in _ACTIVE_RUN_STATUSES
    service = BulkEvaluationService(db)
    try:
        released, skipped = service.release_reviewed_to_grading(run, teacher_id=current_user.id)
        if released:
            _enqueue_or_pause(db, run, pause=not was_active)
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = db.execute(
        select(BulkEvaluationItem.id, Submission.student_identifier, Question.question_no)
        .join(Submission, Submission.id == BulkEvaluationItem.submission_id)
        .join(Question, Question.id == BulkEvaluationItem.question_id)
        .where(BulkEvaluationItem.id.in_([item.id for item, _ in skipped]))
    ).all()
    labels = {item_id: (student, question) for item_id, student, question in rows}
    return BulkEvaluationReleaseResponse(
        run_id=run_id,
        released_count=len(released),
        skipped=[
            BulkEvaluationReleaseSkipped(
                item_id=item.id,
                student_identifier=labels.get(item.id, (None, ""))[0],
                question_label=labels.get(item.id, (None, ""))[1],
                reason=reason,
            )
            for item, reason in skipped
        ],
    )


@router.post(
    "/bulk-evaluation-runs/{run_id}/call-limit",
    response_model=BulkEvaluationRunRead,
)
def raise_bulk_call_limit(
    run_id: int,
    payload: BulkEvaluationCallLimitRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkEvaluationRunRead:
    """Explicitly authorise more provider calls for a paused run; Resume continues it."""

    run = _owned_run(run_id, db, current_user)
    try:
        raised = BulkEvaluationService(db).raise_call_limit(
            run, new_limit=payload.authorized_call_limit, teacher_id=current_user.id
        )
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_read(db, raised)


@router.get(
    "/bulk-evaluation-runs/{run_id}/approval-preview",
    response_model=BulkEvaluationApprovalPreview,
)
def preview_bulk_approval(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> BulkEvaluationApprovalPreview:
    """Per-student scores the teacher checks before a bulk approval; read only."""

    run = _owned_run(run_id, db, current_user)
    try:
        return BulkEvaluationService(db).approval_preview(run)
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/bulk-evaluation-runs/{run_id}/approve-clean",
    response_model=BulkEvaluationApprovalResponse,
)
def approve_clean_bulk_drafts(
    run_id: int,
    payload: BulkEvaluationApprovalRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkEvaluationApprovalResponse:
    run = _owned_run(run_id, db, current_user)
    try:
        approved, already_approved, snapshot = BulkEvaluationService(db).approve_clean(
            run,
            suggestion_ids=payload.suggestion_ids,
            review_snapshot_sha256=payload.review_snapshot_sha256,
            teacher_id=current_user.id,
        )
        refreshed = _owned_run(run_id, db, current_user)
        return BulkEvaluationApprovalResponse(
            run_id=run.id,
            approved_count=approved,
            already_approved_count=already_approved,
            exception_count=refreshed.exception_count,
            review_snapshot_sha256=snapshot,
        )
    except BulkEvaluationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/bulk-evaluation-runs/{run_id}/results.xlsx")
def download_bulk_results(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> StreamingResponse:
    run = _owned_run(run_id, db, current_user)
    if run.status not in {"completed", "completed_with_exceptions"}:
        raise HTTPException(status_code=409, detail="Approve clean drafts before exporting results")
    content = BulkEvaluationService(db).build_results_workbook(run)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="bulk-evaluation-{run.id}.xlsx"'
        },
    )
