from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    BatchEvidencePrepRun,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingRun,
    Question,
    QuestionImportJob,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import AssessmentCreate, AssessmentRead, AssessmentUpdate
from app.services.storage import LocalStorage

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["assessments"])
_ALLOWED_STATUSES = {"draft", "ready", "open", "closed", "archived"}


def get_course_or_404(course_id: int, db: Session) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


def get_assessment_or_404(assessment_id: int, db: Session) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def get_owned_assessment_or_404(
    assessment_id: int, db: Session, teacher: User
) -> Assessment:
    statement = (
        select(Assessment)
        .join(Course, Assessment.course_id == Course.id)
        .where(Assessment.id == assessment_id, Course.teacher_id == teacher.id)
    )
    assessment = db.scalars(statement).first()
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def validate_status(value: str | None) -> None:
    if value is not None and value not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid status",
        )


@router.post(
    "/courses/{course_id}/assessments",
    response_model=AssessmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_assessment(
    course_id: int, payload: AssessmentCreate, db: DbSession
) -> Assessment:
    get_course_or_404(course_id, db)
    validate_status(payload.status)
    assessment = Assessment(course_id=course_id, **payload.model_dump())
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.get("/courses/{course_id}/assessments", response_model=list[AssessmentRead])
def list_assessments(course_id: int, db: DbSession) -> Sequence[Assessment]:
    get_course_or_404(course_id, db)
    statement = select(Assessment).where(Assessment.course_id == course_id).order_by(Assessment.id)
    return db.scalars(statement).all()


@router.get("/assessments/{assessment_id}", response_model=AssessmentRead)
def get_assessment(assessment_id: int, db: DbSession) -> Assessment:
    return get_assessment_or_404(assessment_id, db)


@router.patch("/assessments/{assessment_id}", response_model=AssessmentRead)
def update_assessment(
    assessment_id: int, payload: AssessmentUpdate, db: DbSession
) -> Assessment:
    assessment = get_assessment_or_404(assessment_id, db)
    updates = payload.model_dump(exclude_unset=True)
    validate_status(updates.get("status"))
    for field, value in updates.items():
        setattr(assessment, field, value)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.delete("/assessments/{assessment_id}/test-data")
def delete_assessment_test_data(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, int]:
    assessment = get_owned_assessment_or_404(assessment_id, db, current_user)
    storage = LocalStorage()

    submissions = db.scalars(
        select(Submission)
        .options(selectinload(Submission.pages), selectinload(Submission.answer_regions))
        .where(Submission.assessment_id == assessment.id)
    ).all()
    submission_ids = [submission.id for submission in submissions]
    answer_region_ids = [
        region.id for submission in submissions for region in submission.answer_regions
    ]
    stored_relative_paths = [
        page.image_path for submission in submissions for page in submission.pages
    ]
    stored_relative_paths.extend(
        region.image_path for submission in submissions for region in submission.answer_regions
    )

    grading_runs = db.scalars(
        select(GradingRun).where(GradingRun.assessment_id == assessment.id)
    ).all()
    grading_run_ids = [grading_run.id for grading_run in grading_runs]
    for grading_run in grading_runs:
        stored_relative_paths.extend(
            path
            for path in (
                grading_run.question_pdf_path,
                grading_run.solution_pdf_path,
                grading_run.rubric_pdf_path,
            )
            if path
        )

    question_import_jobs = db.scalars(
        select(QuestionImportJob).where(QuestionImportJob.assessment_id == assessment.id)
    ).all()
    stored_relative_paths.extend(job.file_path for job in question_import_jobs)

    grade_suggestion_ids: list[int] = []
    if answer_region_ids:
        grade_suggestion_ids = list(
            db.scalars(
                select(GradeSuggestion.id).where(
                    GradeSuggestion.answer_region_id.in_(answer_region_ids)
                )
            ).all()
        )
        db.execute(delete(FinalGrade).where(FinalGrade.answer_region_id.in_(answer_region_ids)))
        if grade_suggestion_ids:
            db.execute(delete(FinalGrade).where(FinalGrade.suggestion_id.in_(grade_suggestion_ids)))
        db.execute(
            delete(GradeSuggestion).where(GradeSuggestion.answer_region_id.in_(answer_region_ids))
        )
        db.execute(delete(GradingJob).where(GradingJob.answer_region_id.in_(answer_region_ids)))
        db.execute(delete(AnswerRegion).where(AnswerRegion.id.in_(answer_region_ids)))

    if submission_ids:
        db.execute(delete(SubmissionPage).where(SubmissionPage.submission_id.in_(submission_ids)))
        db.execute(delete(Submission).where(Submission.id.in_(submission_ids)))

    rubric_question_ids = select(Question.id).where(Question.assessment_id == assessment.id)
    db.execute(delete(Rubric).where(Rubric.question_id.in_(rubric_question_ids)))
    db.execute(delete(QuestionImportJob).where(QuestionImportJob.assessment_id == assessment.id))
    db.execute(
        delete(BatchEvidencePrepRun).where(BatchEvidencePrepRun.assessment_id == assessment.id)
    )
    db.execute(delete(GradingRun).where(GradingRun.assessment_id == assessment.id))
    db.execute(delete(Question).where(Question.assessment_id == assessment.id))
    db.commit()

    file_delete_error_count = storage.delete_relative_files(stored_relative_paths)
    for submission_id in submission_ids:
        storage.delete_submission_files(submission_id, [])
    storage.delete_grading_run_dirs(grading_run_ids)
    storage.delete_question_import_dir(assessment.id)

    return {
        "assessment_id": assessment.id,
        "submissions_deleted": len(submission_ids),
        "answer_regions_deleted": len(answer_region_ids),
        "grade_suggestions_deleted": len(grade_suggestion_ids),
        "grading_runs_deleted": len(grading_run_ids),
        "question_imports_deleted": len(question_import_jobs),
        "file_delete_error_count": file_delete_error_count,
    }


@router.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assessment(assessment_id: int, db: DbSession) -> Response:
    assessment = get_assessment_or_404(assessment_id, db)
    db.delete(assessment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Assessment has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
