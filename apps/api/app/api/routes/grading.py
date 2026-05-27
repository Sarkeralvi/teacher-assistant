from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.answer_regions import get_answer_region_or_404
from app.db.session import get_db
from app.models import GradeSuggestion, GradingJob
from app.schemas import (
    BatchMockGradeResponse,
    GradeAnswerRegionResponse,
    GradeSuggestionRead,
    GradingJobRead,
)
from app.services.grading_service import GradingService

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["grading"])


@router.post(
    "/answer-regions/{answer_region_id}/grade",
    response_model=GradeAnswerRegionResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region(answer_region_id: int, db: DbSession) -> dict[str, object]:
    job, suggestion = GradingService(db).grade_answer_region(answer_region_id)
    return {"job": job, "suggestion": suggestion}


@router.post(
    "/assessments/{assessment_id}/grade-all-mock",
    response_model=BatchMockGradeResponse,
    status_code=status.HTTP_201_CREATED,
)
def batch_mock_grade_assessment(assessment_id: int, db: DbSession) -> dict[str, object]:
    return GradingService(db, use_configured_adapter=False).grade_assessment_ungraded_regions_mock(
        assessment_id
    )


@router.get(
    "/answer-regions/{answer_region_id}/grade-suggestions",
    response_model=list[GradeSuggestionRead],
)
def list_grade_suggestions(answer_region_id: int, db: DbSession) -> Sequence[GradeSuggestion]:
    get_answer_region_or_404(answer_region_id, db)
    statement = (
        select(GradeSuggestion)
        .where(GradeSuggestion.answer_region_id == answer_region_id)
        .order_by(GradeSuggestion.id)
    )
    return db.scalars(statement).all()


@router.get("/grade-suggestions/{grade_suggestion_id}", response_model=GradeSuggestionRead)
def get_grade_suggestion(grade_suggestion_id: int, db: DbSession) -> GradeSuggestion:
    suggestion = db.get(GradeSuggestion, grade_suggestion_id)
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grade suggestion not found",
        )
    return suggestion


@router.get("/grading-jobs/{grading_job_id}", response_model=GradingJobRead)
def get_grading_job(grading_job_id: int, db: DbSession) -> GradingJob:
    job = db.get(GradingJob, grading_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grading job not found")
    return job
