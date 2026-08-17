from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.ownership import get_owned_answer_region_or_404
from app.db.session import get_db
from app.models import AnswerRegionOcrBand, AnswerRegionOcrRun, User
from app.schemas import (
    AnswerRegionOcrRunRead,
    OcrCandidateConfirmationRequest,
    OcrCandidateRejectionRequest,
    OcrConfirmationRequest,
    OcrRejectionRead,
    OcrRescueRunRequest,
)
from app.services.answer_region_ocr_service import AnswerRegionOcrService
from app.services.ocr_rescue_service import OcrRescueService
from app.services.storage import LocalStorage
from app.worker.jobs import run_answer_region_ocr_rescue_job
from app.worker.rq_app import get_default_queue

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
    service = OcrRescueService(db)
    run = service.get_run(run_id)
    get_owned_answer_region_or_404(run.answer_region_id, db, current_user)
    return run


@router.post(
    "/answer-regions/{answer_region_id}/ocr-rescue-runs",
    response_model=AnswerRegionOcrRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_answer_region_ocr_rescue_run(
    answer_region_id: int,
    payload: OcrRescueRunRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    run = OcrRescueService(db).create_run(
        region=region,
        teacher=current_user,
        max_calls=payload.max_calls,
    )
    try:
        get_default_queue().enqueue(run_answer_region_ocr_rescue_job, run.id, retry=None)
    except Exception as exc:
        run.status = "failed"
        run.error = "OCR rescue could not be enqueued"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OCR rescue could not be enqueued",
        ) from exc
    return run


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs/{run_id}/confirm-candidates",
    response_model=AnswerRegionOcrRunRead,
)
def confirm_answer_region_ocr_candidates(
    answer_region_id: int,
    run_id: int,
    payload: OcrCandidateConfirmationRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> AnswerRegionOcrRun:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = OcrRescueService(db)
    return service.confirm_candidates(
        region=region,
        run=service.get_run(run_id),
        teacher=current_user,
        candidate_ids=payload.candidate_ids,
    )


@router.post(
    "/answer-regions/{answer_region_id}/ocr-runs/{run_id}/reject",
    response_model=OcrRejectionRead,
)
def reject_answer_region_ocr_candidates(
    answer_region_id: int,
    run_id: int,
    payload: OcrCandidateRejectionRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> OcrRejectionRead:
    region = get_owned_answer_region_or_404(answer_region_id, db, current_user)
    service = OcrRescueService(db)
    run, mapping_id, reference = service.reject(
        region=region,
        run=service.get_run(run_id),
        teacher=current_user,
        reasons=list(payload.reasons),
    )
    return OcrRejectionRead(
        run_id=run.id,
        mapping_id=mapping_id,
        diagnostic_reference=reference,
        status="rejected",
    )


@router.get("/answer-region-ocr-bands/{band_id}/image")
def get_answer_region_ocr_band_image(
    band_id: int, db: DbSession, current_user: CurrentUser
) -> FileResponse:
    band = db.get(AnswerRegionOcrBand, band_id)
    if band is None:
        raise HTTPException(status_code=404, detail="OCR band not found")
    run = OcrRescueService(db).get_run(band.ocr_run_id)
    get_owned_answer_region_or_404(run.answer_region_id, db, current_user)
    path = LocalStorage().resolve_relative(band.image_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="OCR band image not found")
    return FileResponse(path, media_type="image/png")


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
    if run.profile.startswith("math_handwriting_rescue"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enhanced OCR must be confirmed with immutable candidate IDs",
        )
    return service.confirm(
        region=region,
        run=run,
        teacher=current_user,
        confirmed_text=payload.confirmed_text,
    )
