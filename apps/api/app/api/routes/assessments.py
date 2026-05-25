from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Assessment, Course
from app.schemas import AssessmentCreate, AssessmentRead, AssessmentUpdate

DbSession = Annotated[Session, Depends(get_db)]

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
