from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Course, User
from app.schemas import CourseCreate, CourseRead, CourseUpdate

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/courses", tags=["courses"])


def ensure_teacher_exists(db: Session, teacher_id: int) -> None:
    if db.get(User, teacher_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, db: DbSession) -> Course:
    ensure_teacher_exists(db, payload.teacher_id)
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseRead])
def list_courses(db: DbSession) -> Sequence[Course]:
    return db.scalars(select(Course).order_by(Course.id)).all()


@router.get("/{course_id}", response_model=CourseRead)
def get_course(course_id: int, db: DbSession) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


@router.patch("/{course_id}", response_model=CourseRead)
def update_course(course_id: int, payload: CourseUpdate, db: DbSession) -> Course:
    course = get_course(course_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "teacher_id" in updates and updates["teacher_id"] is not None:
        ensure_teacher_exists(db, updates["teacher_id"])
    for field, value in updates.items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: int, db: DbSession) -> Response:
    course = get_course(course_id, db)
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
