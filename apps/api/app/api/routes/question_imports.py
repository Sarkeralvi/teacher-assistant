from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Assessment, Question, QuestionImportJob
from app.schemas import (
    DraftQuestionAccept,
    QuestionImportAcceptRequest,
    QuestionImportAcceptResponse,
    QuestionImportJobRead,
)
from app.services.question_import_extractor import MockQuestionExtractor
from app.services.storage import LocalStorage

DbSession = Annotated[Session, Depends(get_db)]
QuestionImportFile = Annotated[UploadFile, File(...)]

router = APIRouter(tags=["question-imports"])

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


@router.post(
    "/assessments/{assessment_id}/question-imports",
    response_model=QuestionImportJobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_question_import(
    assessment_id: int,
    db: DbSession,
    file: QuestionImportFile,
) -> QuestionImportJob:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    suffix = ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Question paper must be a PDF, PNG, JPG, or JPEG file",
        )

    storage = LocalStorage()
    stored = storage.save_question_import(file, assessment_id, suffix)
    extractor = MockQuestionExtractor()
    job = QuestionImportJob(
        assessment_id=assessment_id,
        status="uploaded",
        original_filename=file.filename or f"question-paper{suffix}",
        content_type=file.content_type or "application/octet-stream",
        file_path=stored.relative_path,
        provider=extractor.provider,
        draft_questions=[],
    )
    db.add(job)
    db.flush()
    try:
        drafts = extractor.extract(stored.absolute_path, job.content_type)
        job.draft_questions = [draft.model_dump(mode="json") for draft in drafts]
        job.status = "drafted"
    except Exception as exc:  # pragma: no cover - defensive safety path
        job.status = "failed"
        job.error = "Question extraction failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Question extraction failed",
        ) from exc
    db.commit()
    db.refresh(job)
    return job


@router.get("/question-imports/{job_id}", response_model=QuestionImportJobRead)
def get_question_import(job_id: int, db: DbSession) -> QuestionImportJob:
    return get_question_import_or_404(job_id, db)


@router.post(
    "/question-imports/{job_id}/accept",
    response_model=QuestionImportAcceptResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_question_import(
    job_id: int, payload: QuestionImportAcceptRequest, db: DbSession
) -> QuestionImportAcceptResponse:
    job = get_question_import_or_404(job_id, db)
    known_draft_ids = {str(draft.get("draft_id")) for draft in job.draft_questions}
    questions = [
        create_question_from_draft(job.assessment_id, draft)
        for draft in payload.draft_questions
    ]
    for draft in payload.draft_questions:
        if draft.draft_id not in known_draft_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Draft question {draft.draft_id} does not belong to this import job",
            )
    db.add_all(questions)
    job.status = "accepted"
    db.commit()
    for question in questions:
        db.refresh(question)
    return QuestionImportAcceptResponse(
        job_id=job.id, created_count=len(questions), questions=questions
    )


def get_question_import_or_404(job_id: int, db: Session) -> QuestionImportJob:
    job = db.get(QuestionImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Question import not found"
        )
    return job


def create_question_from_draft(assessment_id: int, draft: DraftQuestionAccept) -> Question:
    return Question(
        assessment_id=assessment_id,
        question_no=draft.question_no,
        question_text=draft.question_text,
        model_answer=draft.model_answer,
        total_marks=draft.total_marks,
    )
