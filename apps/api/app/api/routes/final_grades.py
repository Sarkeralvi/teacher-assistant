from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import FinalGrade
from app.schemas import FinalGradeCreate, FinalGradeRead, ReviewQueueItem
from app.services.final_grade_service import FinalGradeService

router = APIRouter(tags=["review"])
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/grade-suggestions/{grade_suggestion_id}/finalize",
    response_model=FinalGradeRead,
    status_code=status.HTTP_201_CREATED,
)
def finalize_grade_suggestion(
    grade_suggestion_id: int, payload: FinalGradeCreate, response: Response, db: DbSession
) -> FinalGrade:
    final_grade, created = FinalGradeService(db).finalize_suggestion(grade_suggestion_id, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.get("/answer-regions/{answer_region_id}/final-grade", response_model=FinalGradeRead)
def get_answer_region_final_grade(answer_region_id: int, db: DbSession) -> FinalGrade:
    return FinalGradeService(db).get_final_grade_for_region(answer_region_id)


@router.get("/assessments/{assessment_id}/review-queue", response_model=list[ReviewQueueItem])
def get_assessment_review_queue(assessment_id: int, db: DbSession) -> Sequence[ReviewQueueItem]:
    return FinalGradeService(db).get_review_queue(assessment_id)
