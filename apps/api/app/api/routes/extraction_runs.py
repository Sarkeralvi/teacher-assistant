from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Assessment, ExtractionRun, QuestionNode, RubricExtractionCriterion
from app.schemas import ExtractionRunRead, QuestionNodeRead, RubricExtractionCriterionRead
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

    storage = LocalStorage()
    stored = storage.save_question_import(file, assessment_id, suffix)
    extractor = build_document_extractor(requested_provider=provider)
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
