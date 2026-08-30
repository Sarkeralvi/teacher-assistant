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
    Submission,
    User,
)
from app.schemas import (
    BulkEvaluationApprovalRequest,
    BulkEvaluationApprovalResponse,
    BulkEvaluationExceptionRead,
    BulkEvaluationItemRead,
    BulkEvaluationRunRead,
)
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.worker.jobs import run_bulk_evaluation_next_job
from app.worker.rq_app import get_default_queue

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


def _enqueue(run_id: int) -> None:
    settings = get_settings()
    get_default_queue().enqueue(
        run_bulk_evaluation_next_job,
        run_id,
        retry=None,
        job_timeout=max(3600, settings.local_qwen38_visual_job_timeout_seconds),
    )


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
    provider: Annotated[Literal["llama_cpp_qwen38"], Form()],
    expected_model: Annotated[str, Form(min_length=1, max_length=255)],
    marking_policy: Annotated[Literal["tough", "general", "easy"], Form()] = "general",
    maximum_provider_calls: Annotated[int, Form(ge=1, le=2000)] = 2000,
    local_only_confirmed: Annotated[bool, Form()] = False,
    strict_auto_pass_confirmed: Annotated[bool, Form()] = False,
    draft_only_confirmed: Annotated[bool, Form()] = False,
) -> BulkEvaluationRun:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    if not (local_only_confirmed and strict_auto_pass_confirmed and draft_only_confirmed):
        raise HTTPException(
            status_code=422,
            detail="Local-only, strict auto-pass, and draft-only authorization are required",
        )
    if provider != "llama_cpp_qwen38":
        raise HTTPException(status_code=422, detail="Bulk evaluation is local Qwen3.8 only")
    grading_run = db.get(GradingRun, grading_run_id)
    if (
        grading_run is None
        or grading_run.assessment_id != assessment_id
        or grading_run.created_by_teacher_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Grading run not found")
    created_run: BulkEvaluationRun | None = None
    try:
        created_run = BulkEvaluationService(db).create_from_zip(
            assessment_id=assessment_id,
            grading_run=grading_run,
            teacher=current_user,
            upload=file,
            expected_model=expected_model,
            marking_policy=marking_policy,
            maximum_provider_calls=maximum_provider_calls,
        )
        _enqueue(created_run.id)
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
) -> BulkEvaluationRun:
    return _owned_run(run_id, db, current_user)


@router.get(
    "/assessments/{assessment_id}/bulk-evaluation-runs",
    response_model=list[BulkEvaluationRunRead],
)
def list_bulk_evaluation_runs(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> list[BulkEvaluationRun]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return list(
        db.scalars(
            select(BulkEvaluationRun)
            .options(selectinload(BulkEvaluationRun.items))
            .where(
                BulkEvaluationRun.assessment_id == assessment_id,
                BulkEvaluationRun.created_by_teacher_id == current_user.id,
            )
            .order_by(BulkEvaluationRun.id.desc())
        )
    )


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
        _enqueue(run.id)
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
    try:
        resumed = BulkEvaluationService(db).resume_item(
            run, item, teacher_id=current_user.id
        )
        _enqueue(run.id)
        return resumed
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
