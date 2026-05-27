from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.assessments import get_assessment_or_404
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Submission,
    SubmissionPage,
)
from app.schemas import SubmissionRead
from app.services.storage import LocalStorage
from app.services.submission_processing import classify_upload, extract_page_images

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["submissions"])


def get_submission_or_404(submission_id: int, db: Session) -> Submission:
    statement = (
        select(Submission)
        .options(selectinload(Submission.pages))
        .where(Submission.id == submission_id)
    )
    submission = db.scalars(statement).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    submission.pages.sort(key=lambda page: page.page_no)
    return submission


@router.post(
    "/assessments/{assessment_id}/submissions/upload",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_submission(
    assessment_id: int,
    db: DbSession,
    student_identifier: Annotated[str, Form(min_length=1, max_length=128)],
    file: Annotated[UploadFile, File()],
    student_name: Annotated[str | None, Form(max_length=255)] = None,
) -> Submission:
    get_assessment_or_404(assessment_id, db)
    kind, suffix = classify_upload(file)
    storage = LocalStorage()

    submission = Submission(
        assessment_id=assessment_id,
        student_identifier=student_identifier,
        student_name=student_name or None,
        status="uploaded",
    )
    db.add(submission)
    db.flush()

    stored_upload = storage.save_upload(file, submission.id, suffix)
    page_paths = extract_page_images(
        storage=storage,
        submission_id=submission.id,
        uploaded_path=stored_upload.absolute_path,
        kind=kind,
    )
    for page_no, image_path in enumerate(page_paths, start=1):
        db.add(
            SubmissionPage(
                submission_id=submission.id,
                page_no=page_no,
                image_path=image_path,
                quality_score=None,
            )
        )

    db.commit()
    db.refresh(submission)
    submission.pages.sort(key=lambda page: page.page_no)
    return submission


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
def get_submission(submission_id: int, db: DbSession) -> Submission:
    return get_submission_or_404(submission_id, db)


@router.get("/assessments/{assessment_id}/submissions", response_model=list[SubmissionRead])
def list_assessment_submissions(assessment_id: int, db: DbSession) -> Sequence[Submission]:
    get_assessment_or_404(assessment_id, db)
    statement = (
        select(Submission)
        .options(selectinload(Submission.pages))
        .where(Submission.assessment_id == assessment_id)
        .order_by(Submission.id)
    )
    submissions = db.scalars(statement).all()
    for submission in submissions:
        submission.pages.sort(key=lambda page: page.page_no)
    return submissions


@router.delete(
    "/assessments/{assessment_id}/submissions/{submission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_assessment_submission(assessment_id: int, submission_id: int, db: DbSession) -> Response:
    get_assessment_or_404(assessment_id, db)
    statement = (
        select(Submission)
        .options(
            selectinload(Submission.pages),
            selectinload(Submission.answer_regions),
        )
        .where(Submission.id == submission_id, Submission.assessment_id == assessment_id)
    )
    submission = db.scalars(statement).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    answer_region_ids = [region.id for region in submission.answer_regions]
    relative_paths = [page.image_path for page in submission.pages]
    relative_paths.extend(region.image_path for region in submission.answer_regions)

    if answer_region_ids:
        grade_suggestion_ids = db.scalars(
            select(GradeSuggestion.id).where(GradeSuggestion.answer_region_id.in_(answer_region_ids))
        ).all()
        db.execute(delete(FinalGrade).where(FinalGrade.answer_region_id.in_(answer_region_ids)))
        if grade_suggestion_ids:
            db.execute(delete(FinalGrade).where(FinalGrade.suggestion_id.in_(grade_suggestion_ids)))
        db.execute(delete(GradeSuggestion).where(GradeSuggestion.answer_region_id.in_(answer_region_ids)))
        db.execute(delete(GradingJob).where(GradingJob.answer_region_id.in_(answer_region_ids)))
        db.execute(delete(AnswerRegion).where(AnswerRegion.id.in_(answer_region_ids)))

    db.execute(delete(SubmissionPage).where(SubmissionPage.submission_id == submission_id))
    db.execute(delete(Submission).where(Submission.id == submission_id))
    db.commit()

    LocalStorage().delete_submission_files(submission_id, relative_paths)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/submission-pages/{page_id}/image")
def get_submission_page_image(page_id: int, db: DbSession) -> FileResponse:
    page = db.get(SubmissionPage, page_id)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page not found",
        )
    path = LocalStorage().resolve_relative(page.image_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page image not found",
        )
    return FileResponse(path, media_type="image/png")
