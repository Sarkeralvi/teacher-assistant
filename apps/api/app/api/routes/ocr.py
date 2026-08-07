from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.ownership import get_owned_answer_region_or_404
from app.db.session import get_db
from app.models import AnswerRegionOcrRun, User
from app.schemas import AnswerRegionOcrRunRead, OcrConfirmationRequest
from app.services.answer_region_ocr_service import AnswerRegionOcrService

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["local-ocr"])


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs",
    response_model=AnswerRegionOcrRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_answer_region_ocr_run(
    answer_region_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = AnswerRegionOcrService(db)
    region = service.load_region(answer_region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="Answer region not found")
    return service.create_draft(region, current_user)


@router.get(
    "/answer-regions/{answer_region_id}/ocr-runs",
    response_model=list[AnswerRegionOcrRunRead],
)
def list_answer_region_ocr_runs(
    answer_region_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> list[AnswerRegionOcrRun]:
    get_owned_answer_region_or_404(answer_region_id, db, current_user)
    return AnswerRegionOcrService(db).list_runs(answer_region_id)


@router.get(
    "/answer-region-ocr-runs/{run_id}",
    response_model=AnswerRegionOcrRunRead,
)
def read_answer_region_ocr_run(
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    service = AnswerRegionOcrService(db)
    run = service.get_run(run_id)
    get_owned_answer_region_or_404(run.answer_region_id, db, current_user)
    return run


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs/{run_id}/confirm",
    response_model=AnswerRegionOcrRunRead,
)
def confirm_answer_region_ocr_run(
    answer_region_id: int,
    run_id: int,
    payload: OcrConfirmationRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = AnswerRegionOcrService(db)
    run = service.get_run(run_id)
    return service.confirm(
        region=region,
        run=run,
        teacher=current_user,
        confirmed_text=payload.confirmed_text,
    )
