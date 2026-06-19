from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Assessment, ExtractionRun, QuestionNode, RubricExtractionCriterion
from app.schemas import (
    ExtractionRunRead,
    QuestionNodeRead,
    QuestionNodeUpdate,
    RubricExtractionCriterionRead,
    RubricExtractionCriterionUpdate,
)
from app.services.document_extraction import (
    BridgeUnavailableError,
    DocumentExtractionError,
    allowed_extraction_content_types,
    apply_extraction_result,
    build_document_extractor,
    mark_extraction_run_blocked,
    mark_extraction_run_failed,
)
from app.services.storage import LocalStorage

DbSession = Annotated[Session, Depends(get_db)]
ExtractionFile = Annotated[UploadFile, File(...)]
ExtractionTypeValue = Annotated[str, Form()]
ExtractionProviderValue = Annotated[str | None, Form()]

router = APIRouter(tags=["document-extraction"])


@router.post(
    "/assessments/{assessment_id}/extraction-runs",
    response_model=ExtractionRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_extraction_run(
    assessment_id: int,
    extraction_type: ExtractionTypeValue,
    db: DbSession,
    file: ExtractionFile,
    provider: ExtractionProviderValue = None,
) -> ExtractionRun:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    suffix = allowed_extraction_content_types().get(file.content_type or "")
    if suffix is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Extraction upload must be a PDF, PNG, JPG, JPEG, or TXT file",
        )
    if extraction_type not in {"question_paper", "rubric"}:
        raise HTTPException(
            status_code=422, detail="extraction_type must be question_paper or rubric"
        )

    try:
        extractor = build_document_extractor(requested_provider=provider)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    storage = LocalStorage()
    stored = storage.save_question_import(file, assessment_id, suffix)
    run = ExtractionRun(
        assessment_id=assessment_id,
        artifact_file_path=stored.relative_path,
        original_filename=file.filename or f"{extraction_type}{suffix}",
        content_type=file.content_type or "application/octet-stream",
        extraction_type=extraction_type,
        provider=extractor.provider,
        status="pending",
        blockers=[],
    )
    db.add(run)
    db.flush()

    try:
        result = extractor.extract(stored.absolute_path, extraction_type, run.content_type)
        apply_extraction_result(db, run, result)
    except BridgeUnavailableError as exc:
        mark_extraction_run_blocked(run, str(exc))
    except DocumentExtractionError as exc:
        mark_extraction_run_failed(run, str(exc))
    except Exception as exc:  # pragma: no cover
        mark_extraction_run_failed(run, "Document extraction failed")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document extraction failed",
        ) from exc

    db.commit()
    db.refresh(run)
    return run


@router.get("/extraction-runs/{run_id}", response_model=ExtractionRunRead)
def get_extraction_run(run_id: int, db: DbSession) -> ExtractionRun:
    run = db.get(ExtractionRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Extraction run not found"
        )
    return run


@router.get(
    "/assessments/{assessment_id}/question-nodes",
    response_model=list[QuestionNodeRead],
)
def list_question_nodes(assessment_id: int, db: DbSession) -> list[QuestionNode]:
    if db.get(Assessment, assessment_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    statement = (
        select(QuestionNode)
        .where(QuestionNode.assessment_id == assessment_id)
        .order_by(QuestionNode.extraction_run_id.desc(), QuestionNode.id.asc())
    )
    return list(db.scalars(statement).all())


@router.get(
    "/assessments/{assessment_id}/rubric-extraction-criteria",
    response_model=list[RubricExtractionCriterionRead],
)
def list_rubric_extraction_criteria(
    assessment_id: int, db: DbSession
) -> list[RubricExtractionCriterion]:
    if db.get(Assessment, assessment_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    statement = (
        select(RubricExtractionCriterion)
        .where(RubricExtractionCriterion.assessment_id == assessment_id)
        .order_by(
            RubricExtractionCriterion.extraction_run_id.desc(), RubricExtractionCriterion.id.asc()
        )
    )
    return list(db.scalars(statement).all())


@router.patch("/question-nodes/{node_id}", response_model=QuestionNodeRead)
def update_question_node(node_id: int, payload: QuestionNodeUpdate, db: DbSession):
    node = db.get(QuestionNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question node not found")
    provided_fields = payload.model_fields_set
    if payload.question_number is not None:
        node.question_number = payload.question_number.strip()
    if payload.parent_question_number is not None:
        cleaned_parent = payload.parent_question_number.strip()
        node.parent_question_number = cleaned_parent or None
    elif "parent_question_number" in provided_fields:
        node.parent_question_number = None
    if payload.label is not None:
        node.label = payload.label.strip()
    if payload.text is not None:
        node.text = payload.text.strip()
    if "marks" in provided_fields:
        node.marks = payload.marks
    if "source_page" in provided_fields:
        node.source_page = payload.source_page
    if "source_reference" in provided_fields:
        node.source_reference = payload.source_reference
    if payload.teacher_confirmed is not None:
        node.teacher_confirmed = payload.teacher_confirmed
    db.commit()
    db.refresh(node)
    return node


@router.patch(
    "/rubric-extraction-criteria/{criterion_id}",
    response_model=RubricExtractionCriterionRead,
)
def update_rubric_extraction_criterion(
    criterion_id: int, payload: RubricExtractionCriterionUpdate, db: DbSession
):
    criterion = db.get(RubricExtractionCriterion, criterion_id)
    if criterion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rubric extraction criterion not found",
        )
    provided_fields = payload.model_fields_set
    if payload.question_number is not None:
        cleaned_question_number = payload.question_number.strip()
        criterion.question_number = cleaned_question_number or None
    elif "question_number" in provided_fields:
        criterion.question_number = None
    if payload.criterion_label is not None:
        criterion.criterion_label = payload.criterion_label.strip()
    if payload.description is not None:
        criterion.description = payload.description.strip()
    if "max_marks" in provided_fields:
        criterion.max_marks = payload.max_marks
    if payload.blocker is not None:
        cleaned_blocker = payload.blocker.strip()
        criterion.blocker = cleaned_blocker or None
    elif "blocker" in provided_fields:
        criterion.blocker = None
    if payload.teacher_confirmed is not None:
        criterion.teacher_confirmed = payload.teacher_confirmed
    db.commit()
    db.refresh(criterion)
    return criterion
