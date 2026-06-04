from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.evidence_prep import get_owned_assessment_or_404
from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import BatchEvidencePrepRun, GradingQueueRun, User
from app.schemas import GradingQueueRunCreate, GradingQueueRunRead
from app.services.grading_queue_service import GradingQueueService

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["grading-queue"])


def _load_queue_run_or_404(
    assessment_id: int, run_id: int, db: Session, teacher: User
) -> GradingQueueRun:
    run = db.get(
        GradingQueueRun,
        run_id,
        options=(selectinload(GradingQueueRun.items),),
    )
    if (
        run is None
        or run.assessment_id != assessment_id
        or run.created_by_teacher_id != teacher.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grading queue run not found",
        )
    return run


def _verify_prep_run(
    assessment_id: int,
    evidence_prep_run_id: int | None,
    db: Session,
    teacher: User,
) -> None:
    if evidence_prep_run_id is None:
        return
    prep_run = db.get(BatchEvidencePrepRun, evidence_prep_run_id)
    if (
        prep_run is None
        or prep_run.assessment_id != assessment_id
        or prep_run.created_by_teacher_id != teacher.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence prep run not found",
        )


def _response_from_run(
    run: GradingQueueRun,
    items: list[dict[str, Any]],
    refused_items: list[dict[str, Any]],
) -> dict[str, object]:
    return {
        "id": run.id,
        "assessment_id": run.assessment_id,
        "evidence_prep_run_id": run.evidence_prep_run_id,
        "created_by_teacher_id": run.created_by_teacher_id,
        "status": run.status,
        "total_candidate_packets": run.total_candidate_packets,
        "queued_item_count": run.queued_item_count,
        "refused_item_count": run.refused_item_count,
        "items": items,
        "refused_items": refused_items,
        "error": run.error,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


@router.get(
    "/assessments/{assessment_id}/grading-queue-summary",
    response_model=GradingQueueRunRead,
)
def read_grading_queue_summary(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    latest_run = db.scalars(
        select(GradingQueueRun)
        .options(selectinload(GradingQueueRun.items))
        .where(
            GradingQueueRun.assessment_id == assessment_id,
            GradingQueueRun.created_by_teacher_id == current_user.id,
        )
        .order_by(GradingQueueRun.id.desc())
        .limit(1)
    ).first()
    if latest_run is not None:
        items, refused_items = GradingQueueService(db).summarize_queue_run(latest_run)
        return _response_from_run(latest_run, items, refused_items)
    summary = GradingQueueService(db).summarize_assessment(assessment_id)
    summary["created_by_teacher_id"] = current_user.id
    return summary


@router.post(
    "/assessments/{assessment_id}/grading-queue-runs",
    response_model=GradingQueueRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_grading_queue_run(
    assessment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    payload: GradingQueueRunCreate | None = None,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    evidence_prep_run_id = payload.evidence_prep_run_id if payload else None
    _verify_prep_run(assessment_id, evidence_prep_run_id, db, current_user)
    run, refused_items = GradingQueueService(db).build_queue_run(
        assessment_id=assessment_id,
        created_by_teacher_id=current_user.id,
        evidence_prep_run_id=evidence_prep_run_id,
    )
    items = GradingQueueService(db).validate_queue_run(run)
    return _response_from_run(run, items, refused_items)


@router.get(
    "/assessments/{assessment_id}/grading-queue-runs/{run_id}",
    response_model=GradingQueueRunRead,
)
def read_grading_queue_run(
    assessment_id: int,
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    run = _load_queue_run_or_404(assessment_id, run_id, db, current_user)
    items, refused_items = GradingQueueService(db).summarize_queue_run(run)
    return _response_from_run(run, items, refused_items)



@router.post(
    "/assessments/{assessment_id}/grading-queue-runs/{run_id}/validate-staleness",
    response_model=GradingQueueRunRead,
)
def validate_grading_queue_run_staleness(
    assessment_id: int,
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    run = _load_queue_run_or_404(assessment_id, run_id, db, current_user)
    items, refused_items = GradingQueueService(db).summarize_queue_run(run)
    return _response_from_run(run, items, refused_items)
