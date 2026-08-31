from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.ownership import get_owned_assessment_or_404, get_owned_question_import_job_or_404
from app.db.session import get_db
from app.models import ExtractionRun, Question, QuestionImportJob, QuestionNode, User
from app.schemas import (
    DraftQuestionAccept,
    QuestionImportAcceptRequest,
    QuestionImportAcceptResponse,
    QuestionImportJobRead,
)
from app.services.brain_execution import hold_brain_execution
from app.services.question_import_extractor import (
    CodexQuestionExtractionError,
    build_question_extractor,
)
from app.services.storage import LocalStorage
from packages.brain.capabilities import BrainExecutionLocation

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
QuestionImportFile = Annotated[UploadFile, File(...)]
QuestionImportProvider = Annotated[str | None, Form()]
ProviderDataBoundaryConfirmed = Annotated[bool, Form()]

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
    current_user: CurrentUser,
    file: QuestionImportFile,
    provider: QuestionImportProvider = None,
    provider_data_boundary_confirmed: ProviderDataBoundaryConfirmed = False,
) -> QuestionImportJob:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    suffix = ALLOWED_CONTENT_TYPES.get(file.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Question paper must be a PDF, PNG, JPG, or JPEG file",
        )

    try:
        extractor = build_question_extractor(
            settings=get_settings(), requested_provider=provider
        )
    except CodexQuestionExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    adapter = getattr(extractor, "adapter", None)
    if (
        adapter is not None
        and adapter.runtime.location is BrainExecutionLocation.CLOUD
        and not provider_data_boundary_confirmed
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cloud provider data transfer must be explicitly confirmed",
        )

    storage = LocalStorage()
    stored = storage.save_question_import(file, assessment_id, suffix)
    job = QuestionImportJob(
        assessment_id=assessment_id,
        status="uploaded",
        original_filename=file.filename or f"question-paper{suffix}",
        content_type=file.content_type or "application/octet-stream",
        file_path=stored.relative_path,
        provider=extractor.provider,
        draft_questions=[],
        provider_warnings=[],
    )
    db.add(job)
    db.flush()
    try:
        if adapter is None:
            result = extractor.extract(stored.absolute_path, job.content_type)
        else:
            with hold_brain_execution(
                db=db,
                settings=get_settings(),
                adapter=adapter,
                holder_kind="question_import",
                holder_id=f"question_import:{job.id}",
            ):
                result = extractor.extract(stored.absolute_path, job.content_type)
        job.draft_questions = [draft.model_dump(mode="json") for draft in result.draft_questions]
        job.provider_warnings = result.warnings
        job.status = "drafted"
    except CodexQuestionExtractionError as exc:
        job.status = "failed"
        job.error = str(exc)
        job.provider_warnings = [str(exc)]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
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
def get_question_import(
    job_id: int, db: DbSession, current_user: CurrentUser
) -> QuestionImportJob:
    return get_owned_question_import_job_or_404(job_id, db, current_user)


@router.post(
    "/question-imports/{job_id}/accept",
    response_model=QuestionImportAcceptResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_question_import(
    job_id: int,
    payload: QuestionImportAcceptRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> QuestionImportAcceptResponse:
    job = get_owned_question_import_job_or_404(job_id, db, current_user)
    known_draft_ids = {str(draft.get("draft_id")) for draft in job.draft_questions}
    for draft in payload.draft_questions:
        if draft.draft_id not in known_draft_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Draft question {draft.draft_id} does not belong to this import job",
            )
    ensure_unique_question_labels(job.assessment_id, payload.draft_questions, db)
    extraction_run = ensure_acceptance_extraction_run(job.id, job.assessment_id, db)
    questions: list[Question] = []
    for draft in payload.draft_questions:
        question = upsert_question_from_draft(job.assessment_id, draft, db)
        questions.append(question)
        upsert_question_node_from_question(
            extraction_run.id, job.assessment_id, question, draft, db
        )
    job.status = "accepted"
    db.commit()
    for question in questions:
        db.refresh(question)
    return QuestionImportAcceptResponse(
        job_id=job.id, created_count=len(questions), questions=questions
    )


def ensure_unique_question_labels(
    assessment_id: int, drafts: list[DraftQuestionAccept], db: Session
) -> None:
    labels = [draft.question_no.strip() for draft in drafts]
    duplicate_payload_labels = sorted({label for label in labels if labels.count(label) > 1})
    if duplicate_payload_labels:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Duplicate canonical grading unit labels in accepted drafts: "
                + ", ".join(duplicate_payload_labels)
            ),
        )
    # Existing questions are intentionally allowed so the accept flow is idempotent.


def create_question_from_draft(assessment_id: int, draft: DraftQuestionAccept) -> Question:
    return Question(
        assessment_id=assessment_id,
        question_no=draft.question_no.strip(),
        question_text=draft.question_text,
        model_answer=draft.model_answer,
        total_marks=draft.total_marks,
    )


def upsert_question_from_draft(
    assessment_id: int, draft: DraftQuestionAccept, db: Session
) -> Question:
    question_no = draft.question_no.strip()
    existing = db.scalar(
        select(Question).where(
            Question.assessment_id == assessment_id, Question.question_no == question_no
        )
    )
    if existing is not None:
        existing.question_text = draft.question_text
        existing.model_answer = draft.model_answer
        existing.total_marks = draft.total_marks
        return existing
    question = create_question_from_draft(assessment_id, draft)
    db.add(question)
    db.flush()
    return question


def upsert_question_node_from_question(
    extraction_run_id: int,
    assessment_id: int,
    question: Question,
    draft: DraftQuestionAccept,
    db: Session,
) -> QuestionNode:
    normalized_question_no = question.question_no.strip()
    existing = db.scalar(
        select(QuestionNode).where(
            QuestionNode.assessment_id == assessment_id,
            QuestionNode.question_number == normalized_question_no,
            QuestionNode.teacher_confirmed.is_(True),
            QuestionNode.node_type.in_(["question", "subquestion"]),
        )
    )
    if existing is not None:
        existing.label = normalized_question_no
        existing.text = draft.question_text
        existing.marks = draft.total_marks
        existing.parent_question_number = normalize_parent_question_number(normalized_question_no)
        existing.node_type = infer_question_node_type(normalized_question_no)
        existing.teacher_confirmed = True
        return existing
    node = QuestionNode(
        assessment_id=assessment_id,
        extraction_run_id=extraction_run_id,
        question_number=normalized_question_no,
        parent_question_number=normalize_parent_question_number(normalized_question_no),
        label=normalized_question_no,
        text=draft.question_text,
        marks=draft.total_marks,
        node_type=infer_question_node_type(normalized_question_no),
        source_page=None,
        source_reference={"source": "question_import_accept"},
        confidence=None,
        teacher_confirmed=True,
    )
    db.add(node)
    db.flush()
    return node


def infer_question_node_type(question_no: str) -> str:
    return "subquestion" if "(" in question_no and question_no.endswith(")") else "question"


def normalize_parent_question_number(question_no: str) -> str | None:
    if "(" not in question_no or not question_no.endswith(")"):
        return None
    return question_no.split("(", 1)[0].strip() or None


def ensure_acceptance_extraction_run(job_id: int, assessment_id: int, db: Session) -> ExtractionRun:
    existing = db.scalar(
        select(ExtractionRun).where(
            ExtractionRun.assessment_id == assessment_id,
            ExtractionRun.extraction_type == "question_paper",
            ExtractionRun.artifact_file_path == f"question-imports/{job_id}/accepted",
        )
    )
    if existing is not None:
        return existing
    extraction_run = ExtractionRun(
        assessment_id=assessment_id,
        artifact_file_path=f"question-imports/{job_id}/accepted",
        original_filename=f"question-import-{job_id}-accepted.json",
        content_type="application/json",
        extraction_type="question_paper",
        provider="mock",
        status="succeeded",
        raw_output="{}",
        normalized_output={"question_nodes": []},
        blockers=[],
        error=None,
    )
    db.add(extraction_run)
    db.flush()
    return extraction_run
