from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.ownership import get_owned_answer_region_or_404
from app.db.session import get_db
from app.models import AnswerRegionOcrRun, User
from app.schemas import (
    AnswerRegionOcrRunRead,
    PaddleOcrConfirmationRequest,
    PaddleOcrRejectionRequest,
    PaddleOcrRunRequest,
)
from app.services.answer_region_ocr_service import AnswerRegionOcrError, AnswerRegionOcrService
from app.worker.jobs import run_answer_region_paddle_ocr_job
from app.worker.rq_app import get_default_queue

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
router = APIRouter(tags=["local-paddle-ocr"])


def _conflict(exc: AnswerRegionOcrError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs",
    response_model=AnswerRegionOcrRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_answer_region_ocr_run(
    answer_region_id: int,
    payload: PaddleOcrRunRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = AnswerRegionOcrService(db)
    region = service.load_region(answer_region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="Answer region not found")
    try:
        run = service.create_draft(
            region,
            current_user,
            expected_model=payload.expected_model,
            expected_layout_model=payload.expected_layout_model,
        )
    except AnswerRegionOcrError as exc:
        raise _conflict(exc) from exc
    try:
        timeout = max(
            900,
            int(get_settings().local_paddle_ocr_timeout_seconds * max(run.call_limit, 1))
            + get_settings().local_ai_phase_timeout_seconds,
        )
        get_default_queue().enqueue(
            run_answer_region_paddle_ocr_job,
            run.id,
            retry=None,
            job_timeout=timeout,
        )
    except Exception as exc:
        service.mark_enqueue_failed(run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local PaddleOCR transcription could not be queued",
        ) from exc
    db.refresh(run)
    return run


@router.get(
    "/answer-regions/{answer_region_id}/ocr-runs",
    response_model=list[AnswerRegionOcrRunRead],
)
def list_answer_region_ocr_runs(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> list[AnswerRegionOcrRun]:
    get_owned_answer_region_or_404(answer_region_id, db, current_user)
    return AnswerRegionOcrService(db).list_runs(answer_region_id)


@router.get("/answer-region-ocr-runs/{run_id}", response_model=AnswerRegionOcrRunRead)
def read_answer_region_ocr_run(
    run_id: int, db: DbSession, current_user: CurrentUser
) -> AnswerRegionOcrRun:
    service = AnswerRegionOcrService(db)
    try:
        run = service.get_run(run_id)
    except AnswerRegionOcrError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    get_owned_answer_region_or_404(run.answer_region_id, db, current_user)
    return run


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs/{run_id}/confirm",
    response_model=AnswerRegionOcrRunRead,
)
def confirm_answer_region_ocr_run(
    answer_region_id: int,
    run_id: int,
    payload: PaddleOcrConfirmationRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = AnswerRegionOcrService(db)
    try:
        return service.confirm(
            region,
            service.get_run(run_id),
            teacher=current_user,
            draft_hash=payload.draft_text_sha256,
        )
    except AnswerRegionOcrError as exc:
        raise _conflict(exc) from exc


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs/{run_id}/reject",
    response_model=AnswerRegionOcrRunRead,
)
def reject_answer_region_ocr_run(
    answer_region_id: int,
    run_id: int,
    payload: PaddleOcrRejectionRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = AnswerRegionOcrService(db)
    try:
        return service.reject(
            region,
            service.get_run(run_id),
            teacher=current_user,
            reason=payload.reason,
        )
    except AnswerRegionOcrError as exc:
        raise _conflict(exc) from exc
