from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Question, Rubric
from app.schemas import RubricCreate, RubricRead, RubricUpdate

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["rubrics"])


def get_question_or_404(question_id: int, db: Session) -> Question:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


def get_rubric_or_404(rubric_id: int, db: Session) -> Rubric:
    rubric = db.get(Rubric, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found")
    return rubric


def ensure_no_other_active_rubric(
    db: Session, question_id: int, rubric_id: int | None = None
) -> None:
    statement = select(Rubric).where(Rubric.question_id == question_id, Rubric.is_active.is_(True))
    if rubric_id is not None:
        statement = statement.where(Rubric.id != rubric_id)
    if db.scalars(statement).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Question already has an active rubric",
        )


@router.post(
    "/questions/{question_id}/rubrics",
    response_model=RubricRead,
    status_code=status.HTTP_201_CREATED,
)
def create_rubric(question_id: int, payload: RubricCreate, db: DbSession) -> Rubric:
    get_question_or_404(question_id, db)
    if payload.is_active:
        ensure_no_other_active_rubric(db, question_id)
    rubric = Rubric(question_id=question_id, **payload.model_dump())
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric


@router.get("/questions/{question_id}/rubrics", response_model=list[RubricRead])
def list_rubrics(question_id: int, db: DbSession) -> Sequence[Rubric]:
    get_question_or_404(question_id, db)
    statement = select(Rubric).where(Rubric.question_id == question_id).order_by(Rubric.id)
    return db.scalars(statement).all()


@router.get("/rubrics/{rubric_id}", response_model=RubricRead)
def get_rubric(rubric_id: int, db: DbSession) -> Rubric:
    return get_rubric_or_404(rubric_id, db)


@router.patch("/rubrics/{rubric_id}", response_model=RubricRead)
def update_rubric(rubric_id: int, payload: RubricUpdate, db: DbSession) -> Rubric:
    rubric = get_rubric_or_404(rubric_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("is_active") is True:
        ensure_no_other_active_rubric(db, rubric.question_id, rubric.id)
    for field, value in updates.items():
        setattr(rubric, field, value)
    db.commit()
    db.refresh(rubric)
    return rubric


@router.delete("/rubrics/{rubric_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rubric(rubric_id: int, db: DbSession) -> Response:
    rubric = get_rubric_or_404(rubric_id, db)
    db.delete(rubric)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rubric has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
