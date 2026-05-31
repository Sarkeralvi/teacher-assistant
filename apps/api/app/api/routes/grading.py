from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.answer_regions import get_answer_region_or_404
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    GradeSuggestion,
    GradingJob,
    Submission,
    User,
)
from app.schemas import (
    BatchMockGradeResponse,
    BrowserCodexGradeResponse,
    GradeAnswerRegionResponse,
    GradeSuggestionRead,
    GradingJobRead,
)
from app.services.grading_service import GradingService

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["grading"])


def make_browser_codex_grade_response(
    job: GradingJob, suggestion: GradeSuggestion
) -> dict[str, object]:
    raw = suggestion.raw_response_json or {}
    review_flags = raw.get("review_flags", [])
    if not isinstance(review_flags, list):
        review_flags = []
    return {
        "job": job,
        "suggestion": {
            "id": suggestion.id,
            "grading_job_id": suggestion.grading_job_id,
            "answer_region_id": suggestion.answer_region_id,
            "question_id": suggestion.question_id,
            "model_provider": suggestion.model_provider,
            "model_name": suggestion.model_name,
            "prompt_version": suggestion.prompt_version,
            "score": suggestion.score,
            "max_score": suggestion.max_score,
            "confidence": suggestion.confidence,
            "needs_review": suggestion.needs_review,
            "feedback": suggestion.feedback,
            "cost_estimate": suggestion.cost_estimate,
            "review_flags": review_flags,
            "created_at": suggestion.created_at,
        },
    }


def assert_teacher_owns_answer_region(
    answer_region_id: int, db: Session, current_user: User
) -> AnswerRegion:
    statement = (
        select(AnswerRegion)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id)
        .join(Course, Assessment.course_id == Course.id)
        .where(AnswerRegion.id == answer_region_id)
        .where(Course.teacher_id == current_user.id)
    )
    region = db.scalars(statement).first()
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found")
    return region


@router.post(
    "/answer-regions/{answer_region_id}/grade",
    response_model=GradeAnswerRegionResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region(answer_region_id: int, db: DbSession) -> dict[str, object]:
    job, suggestion = GradingService(db).grade_answer_region(answer_region_id)
    return {"job": job, "suggestion": suggestion}


@router.post(
    "/answer-regions/{answer_region_id}/grade-codex-dev",
    response_model=BrowserCodexGradeResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region_with_codex_dev(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    settings = get_settings()
    if not settings.codex_browser_grading_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Codex browser grading is unavailable in this backend runtime. "
                "Use host-backend Codex dev mode with CODEX_BROWSER_GRADING_ENABLED=true."
            ),
        )
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    try:
        job, suggestion = GradingService(db).grade_answer_region_with_codex_cli(answer_region_id)
    except HTTPException as exc:
        if "codex command not found" in str(exc.detail).lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Codex CLI is not available in this backend runtime. "
                    "Use host-backend Codex dev mode."
                ),
            ) from exc
        raise
    return make_browser_codex_grade_response(job, suggestion)


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
