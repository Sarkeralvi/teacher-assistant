from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    Submission,
    User,
)
from app.schemas import (
    AssessmentSummaryRead,
    BatchFinalGradeApproveRequest,
    BatchFinalGradeApproveResponse,
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
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_owned_assessment_or_404(assessment_id: int, db: Session, teacher: User) -> Assessment:
    assessment = (
        db.query(Assessment)
        .join(Course, Assessment.course_id == Course.id)
        .filter(Assessment.id == assessment_id, Course.teacher_id == teacher.id)
        .first()
    )
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def get_owned_grade_suggestion_or_404(
    grade_suggestion_id: int, db: Session, teacher: User
) -> GradeSuggestion:
    suggestion = (
        db.query(GradeSuggestion)
        .join(AnswerRegion, GradeSuggestion.answer_region_id == AnswerRegion.id)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id)
        .join(Course, Assessment.course_id == Course.id)
        .filter(GradeSuggestion.id == grade_suggestion_id, Course.teacher_id == teacher.id)
        .first()
    )
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grade suggestion not found"
        )
    return suggestion


def get_owned_answer_region_or_404(
    answer_region_id: int, db: Session, teacher: User
) -> AnswerRegion:
    region = (
        db.query(AnswerRegion)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id)
        .join(Course, Assessment.course_id == Course.id)
        .filter(AnswerRegion.id == answer_region_id, Course.teacher_id == teacher.id)
        .first()
    )
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found")
    return region


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
    current_user: CurrentUser,
) -> FinalGrade:
    get_owned_grade_suggestion_or_404(grade_suggestion_id, db, current_user)
    payload.teacher_id = current_user.id
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
    current_user: CurrentUser,
) -> FinalGrade:
    get_owned_grade_suggestion_or_404(grade_suggestion_id, db, current_user)
    final_grade, created = FinalGradeService(db).approve_suggestion(
        grade_suggestion_id,
        teacher_id=current_user.id,
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
    current_user: CurrentUser,
) -> FinalGrade:
    get_owned_grade_suggestion_or_404(grade_suggestion_id, db, current_user)
    final_grade, created = FinalGradeService(db).edit_suggestion(
        grade_suggestion_id,
        teacher_id=current_user.id,
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
    current_user: CurrentUser,
) -> FinalGrade:
    get_owned_grade_suggestion_or_404(grade_suggestion_id, db, current_user)
    final_grade, created = FinalGradeService(db).reject_suggestion(
        grade_suggestion_id,
        teacher_id=current_user.id,
        teacher_comment=payload.teacher_comment,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return final_grade


@router.get("/answer-regions/{answer_region_id}/final-grade", response_model=FinalGradeRead)
def get_answer_region_final_grade(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> FinalGrade:
    get_owned_answer_region_or_404(answer_region_id, db, current_user)
    return FinalGradeService(db).get_final_grade_for_region(answer_region_id)


@router.post(
    "/assessments/{assessment_id}/final-grades/approve-selected",
    response_model=BatchFinalGradeApproveResponse,
)
def approve_selected_final_grades(
    assessment_id: int,
    payload: BatchFinalGradeApproveRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BatchFinalGradeApproveResponse:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return FinalGradeService(db).approve_selected_suggestions(
        assessment_id=assessment_id,
        suggestion_ids=payload.grade_suggestion_ids,
        teacher_id=current_user.id,
    )


@router.get("/assessments/{assessment_id}/review-queue", response_model=list[ReviewQueueItem])
def get_assessment_review_queue(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> Sequence[ReviewQueueItem]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return FinalGradeService(db).get_review_queue(assessment_id)


@router.get("/assessments/{assessment_id}/summary", response_model=AssessmentSummaryRead)
def get_assessment_summary(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> AssessmentSummaryRead:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return FinalGradeService(db).get_assessment_summary(assessment_id)


@router.get("/assessments/{assessment_id}/export/final-grades.xlsx")
def export_assessment_final_grades_xlsx(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> StreamingResponse:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    content = FinalGradeService(db).build_final_grades_workbook(assessment_id)
    filename = f"assessment-{assessment_id}-final-grades.xlsx"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
