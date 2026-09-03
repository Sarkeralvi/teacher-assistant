from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.ownership import get_owned_course_or_404
from app.db.session import get_db
from app.models import Course, User
from app.schemas import CourseCreate, CourseRead, CourseUpdate

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, db: DbSession, current_user: CurrentUser) -> Course:
    course = Course(**payload.model_dump(exclude={"teacher_id"}), teacher_id=current_user.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseRead])
def list_courses(db: DbSession, current_user: CurrentUser) -> Sequence[Course]:
    statement = (
        select(Course).where(Course.teacher_id == current_user.id).order_by(Course.id)
    )
    return db.scalars(statement).all()


@router.get("/{course_id}", response_model=CourseRead)
def get_course(course_id: int, db: DbSession, current_user: CurrentUser) -> Course:
    return get_owned_course_or_404(course_id, db, current_user)


@router.patch("/{course_id}", response_model=CourseRead)
def update_course(
    course_id: int, payload: CourseUpdate, db: DbSession, current_user: CurrentUser
) -> Course:
    course = get_owned_course_or_404(course_id, db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if "teacher_id" in updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Course ownership cannot be changed through this endpoint",
        )
    for field, value in updates.items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    course = get_owned_course_or_404(course_id, db, current_user)
    db.delete(course)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
