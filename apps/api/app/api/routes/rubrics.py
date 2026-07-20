from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.ownership import get_owned_question_or_404, get_owned_rubric_or_404
from app.db.session import get_db
from app.models import Question, Rubric, User
from app.schemas import RubricCreate, RubricRead, RubricUpdate, validate_rubric_json_schema

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["rubrics"])


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


def validate_rubric_or_422(rubric_json: dict[str, object], question: Question) -> None:
    try:
        rubric_schema = validate_rubric_json_schema(rubric_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rubric_schema.total_marks != question.total_marks:
        raise HTTPException(
            status_code=422,
            detail="rubric_json.total_marks must match question.total_marks",
        )


@router.post(
    "/questions/{question_id}/rubrics",
    response_model=RubricRead,
    status_code=status.HTTP_201_CREATED,
)
def create_rubric(
    question_id: int, payload: RubricCreate, db: DbSession, current_user: CurrentUser
) -> Rubric:
    question = get_owned_question_or_404(question_id, db, current_user)
    validate_rubric_or_422(payload.rubric_json, question)
    if payload.is_active:
        ensure_no_other_active_rubric(db, question_id)
    rubric = Rubric(question_id=question_id, **payload.model_dump())
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric


@router.get("/questions/{question_id}/rubrics", response_model=list[RubricRead])
def list_rubrics(
    question_id: int, db: DbSession, current_user: CurrentUser
) -> Sequence[Rubric]:
    get_owned_question_or_404(question_id, db, current_user)
    statement = select(Rubric).where(Rubric.question_id == question_id).order_by(Rubric.id)
    return db.scalars(statement).all()


@router.get("/rubrics/{rubric_id}", response_model=RubricRead)
def get_rubric(rubric_id: int, db: DbSession, current_user: CurrentUser) -> Rubric:
    return get_owned_rubric_or_404(rubric_id, db, current_user)


@router.patch("/rubrics/{rubric_id}", response_model=RubricRead)
def update_rubric(
    rubric_id: int, payload: RubricUpdate, db: DbSession, current_user: CurrentUser
) -> Rubric:
    rubric = get_owned_rubric_or_404(rubric_id, db, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if "rubric_json" in updates:
        validate_rubric_or_422(updates["rubric_json"], rubric.question)
    if updates.get("is_active") is True:
        ensure_no_other_active_rubric(db, rubric.question_id, rubric.id)
    for field, value in updates.items():
        setattr(rubric, field, value)
    db.commit()
    db.refresh(rubric)
    return rubric


@router.delete("/rubrics/{rubric_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rubric(rubric_id: int, db: DbSession, current_user: CurrentUser) -> Response:
    rubric = get_owned_rubric_or_404(rubric_id, db, current_user)
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
