from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Assessment, Question
from app.schemas import QuestionCreate, QuestionRead, QuestionUpdate

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(tags=["questions"])


def get_assessment_or_404(assessment_id: int, db: Session) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def get_question_or_404(question_id: int, db: Session) -> Question:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


def ensure_unique_question_label(
    assessment_id: int, question_no: str, db: Session, question_id: int | None = None
) -> None:
    label = question_no.strip()
    statement = select(Question).where(
        Question.assessment_id == assessment_id,
        Question.question_no == label,
    )
    if question_id is not None:
        statement = statement.where(Question.id != question_id)
    if db.scalars(statement).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Canonical grading unit label already exists in this assessment: {label}",
        )


@router.post(
    "/assessments/{assessment_id}/questions",
    response_model=QuestionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_question(
    assessment_id: int, payload: QuestionCreate, db: DbSession
) -> Question:
    get_assessment_or_404(assessment_id, db)
    data = payload.model_dump()
    data["question_no"] = data["question_no"].strip()
    ensure_unique_question_label(assessment_id, data["question_no"], db)
    question = Question(assessment_id=assessment_id, **data)
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


@router.get("/assessments/{assessment_id}/questions", response_model=list[QuestionRead])
def list_questions(assessment_id: int, db: DbSession) -> Sequence[Question]:
    get_assessment_or_404(assessment_id, db)
    statement = (
        select(Question)
        .where(Question.assessment_id == assessment_id)
        .order_by(Question.id)
    )
    return db.scalars(statement).all()


@router.get("/questions/{question_id}", response_model=QuestionRead)
def get_question(question_id: int, db: DbSession) -> Question:
    return get_question_or_404(question_id, db)


@router.patch("/questions/{question_id}", response_model=QuestionRead)
def update_question(
    question_id: int, payload: QuestionUpdate, db: DbSession
) -> Question:
    question = get_question_or_404(question_id, db)
    updates = payload.model_dump(exclude_unset=True)
    if "question_no" in updates:
        updates["question_no"] = updates["question_no"].strip()
        ensure_unique_question_label(
            question.assessment_id, updates["question_no"], db, question.id
        )
    for field, value in updates.items():
        setattr(question, field, value)
    db.commit()
    db.refresh(question)
    return question


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(question_id: int, db: DbSession) -> Response:
    question = get_question_or_404(question_id, db)
    db.delete(question)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Question has related records and cannot be deleted safely",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
