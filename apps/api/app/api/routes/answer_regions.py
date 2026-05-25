from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.routes.assessments import get_assessment_or_404
from app.api.routes.questions import get_question_or_404
from app.api.routes.submissions import get_submission_or_404
from app.db.session import get_db
from app.models import AnswerRegion, Submission, SubmissionPage
from app.schemas import AnswerRegionCreate, AnswerRegionRead
from app.services.answer_region_processing import crop_answer_region_image
from app.services.storage import LocalStorage

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["answer-regions"])


def get_submission_page_or_404(page_id: int, db: Session) -> SubmissionPage:
    statement = (
        select(SubmissionPage)
        .options(joinedload(SubmissionPage.submission))
        .where(SubmissionPage.id == page_id)
    )
    page = db.scalars(statement).first()
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission page not found",
        )
    return page


def get_answer_region_or_404(answer_region_id: int, db: Session) -> AnswerRegion:
    region = db.get(AnswerRegion, answer_region_id)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found")
    return region


@router.post(
    "/submission-pages/{page_id}/answer-regions",
    response_model=AnswerRegionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_answer_region(
    page_id: int, payload: AnswerRegionCreate, db: DbSession
) -> AnswerRegion:
    page = get_submission_page_or_404(page_id, db)
    question = get_question_or_404(payload.question_id, db)
    if question.assessment_id != page.submission.assessment_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Question assessment must match submission assessment",
        )

    image_path = crop_answer_region_image(
        storage=LocalStorage(),
        source_image_path=page.image_path,
        submission_id=page.submission_id,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
    )
    region = AnswerRegion(
        submission_id=page.submission_id,
        question_id=payload.question_id,
        page_id=page.id,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        image_path=image_path,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.get("/submissions/{submission_id}/answer-regions", response_model=list[AnswerRegionRead])
def list_submission_answer_regions(submission_id: int, db: DbSession) -> Sequence[AnswerRegion]:
    get_submission_or_404(submission_id, db)
    statement = (
        select(AnswerRegion)
        .where(AnswerRegion.submission_id == submission_id)
        .order_by(AnswerRegion.id)
    )
    return db.scalars(statement).all()


@router.get("/assessments/{assessment_id}/answer-regions", response_model=list[AnswerRegionRead])
def list_assessment_answer_regions(
    assessment_id: int, db: DbSession, question_id: int | None = None
) -> Sequence[AnswerRegion]:
    get_assessment_or_404(assessment_id, db)
    statement = (
        select(AnswerRegion)
        .join(Submission, Submission.id == AnswerRegion.submission_id)
        .where(Submission.assessment_id == assessment_id)
        .order_by(AnswerRegion.id)
    )
    if question_id is not None:
        statement = statement.where(AnswerRegion.question_id == question_id)
    return db.scalars(statement).all()


@router.get("/answer-regions/{answer_region_id}", response_model=AnswerRegionRead)
def get_answer_region(answer_region_id: int, db: DbSession) -> AnswerRegion:
    return get_answer_region_or_404(answer_region_id, db)


@router.get("/answer-regions/{answer_region_id}/image")
def get_answer_region_image(answer_region_id: int, db: DbSession) -> FileResponse:
    region = get_answer_region_or_404(answer_region_id, db)
    path = LocalStorage().resolve_relative(region.image_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer region image not found",
        )
    return FileResponse(path, media_type="image/png")


@router.delete("/answer-regions/{answer_region_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer_region(answer_region_id: int, db: DbSession) -> Response:
    region = get_answer_region_or_404(answer_region_id, db)
    db.delete(region)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Answer region has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
