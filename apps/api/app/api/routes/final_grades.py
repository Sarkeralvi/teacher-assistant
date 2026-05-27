from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional
from app.db.session import get_db
from app.models import FinalGrade, User
from app.schemas import (
    AssessmentSummaryRead,
    FinalGradeApprove,
    FinalGradeCreate,
    FinalGradeEdit,
    FinalGradeRead,
    FinalGradeReject,
    ReviewQueueItem,
)
from app.services.final_grade_service import FinalGradeService

router = APIRouter(tags=["review"])
DbSession = Annotated[Session, Depends(get_db)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]


def auth_teacher_id(payload_teacher_id: int | None, current_user: User | None) -> int:
    if current_user is not None:
        return current_user.id
    if payload_teacher_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required for teacher review actions",
        )
    return payload_teacher_id


@router.post(
    "/grade-suggestions/{grade_suggestion_id}/finalize",
    response_model=FinalGradeRead,
    status_code=status.HTTP_201_CREATED,
)
def finalize_grade_suggestion(
    grade_suggestion_id: int,
    payload: FinalGradeCreate,
    response: Response,
    db: DbSession,
    current_user: CurrentUserOptional,
) -> FinalGrade:
    payload.teacher_id = auth_teacher_id(payload.teacher_id, current_user)
    final_grade, created = FinalGradeService(db).finalize_suggestion(grade_suggestion_id, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.post(
    "/grade-suggestions/{grade_suggestion_id}/approve",
    response_model=FinalGradeRead,
    status_code=status.HTTP_201_CREATED,
)
def approve_grade_suggestion(
    grade_suggestion_id: int,
    payload: FinalGradeApprove,
    response: Response,
    db: DbSession,
    current_user: CurrentUserOptional,
) -> FinalGrade:
    final_grade, created = FinalGradeService(db).approve_suggestion(
        grade_suggestion_id,
        teacher_id=auth_teacher_id(payload.teacher_id, current_user),
        teacher_comment=payload.teacher_comment,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.post(
    "/grade-suggestions/{grade_suggestion_id}/edit",
    response_model=FinalGradeRead,
    status_code=status.HTTP_201_CREATED,
)
def edit_grade_suggestion(
    grade_suggestion_id: int,
    payload: FinalGradeEdit,
    response: Response,
    db: DbSession,
    current_user: CurrentUserOptional,
) -> FinalGrade:
    final_grade, created = FinalGradeService(db).edit_suggestion(
        grade_suggestion_id,
        teacher_id=auth_teacher_id(payload.teacher_id, current_user),
        final_score=payload.final_score,
        teacher_comment=payload.teacher_comment,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.post(
    "/grade-suggestions/{grade_suggestion_id}/reject",
    response_model=FinalGradeRead,
    status_code=status.HTTP_201_CREATED,
)
def reject_grade_suggestion(
    grade_suggestion_id: int,
    payload: FinalGradeReject,
    response: Response,
    db: DbSession,
    current_user: CurrentUserOptional,
) -> FinalGrade:
    final_grade, created = FinalGradeService(db).reject_suggestion(
        grade_suggestion_id,
        teacher_id=auth_teacher_id(payload.teacher_id, current_user),
        teacher_comment=payload.teacher_comment,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.get("/answer-regions/{answer_region_id}/final-grade", response_model=FinalGradeRead)
def get_answer_region_final_grade(answer_region_id: int, db: DbSession) -> FinalGrade:
    return FinalGradeService(db).get_final_grade_for_region(answer_region_id)


@router.get("/assessments/{assessment_id}/review-queue", response_model=list[ReviewQueueItem])
def get_assessment_review_queue(assessment_id: int, db: DbSession) -> Sequence[ReviewQueueItem]:
    return FinalGradeService(db).get_review_queue(assessment_id)


@router.get("/assessments/{assessment_id}/summary", response_model=AssessmentSummaryRead)
def get_assessment_summary(assessment_id: int, db: DbSession) -> AssessmentSummaryRead:
    return FinalGradeService(db).get_assessment_summary(assessment_id)


@router.get("/assessments/{assessment_id}/export/final-grades.xlsx")
def export_assessment_final_grades_xlsx(assessment_id: int, db: DbSession) -> StreamingResponse:
    content = FinalGradeService(db).build_final_grades_workbook(assessment_id)
    filename = f"assessment-{assessment_id}-final-grades.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
