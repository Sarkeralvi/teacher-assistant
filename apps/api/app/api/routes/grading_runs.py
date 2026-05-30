from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import Assessment, Course, GradingRun, User
from app.schemas import GradingRunCreate, GradingRunRead, GradingRunUpdate
from app.services.storage import LocalStorage

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalMaterialFile = Annotated[UploadFile | None, File()]

router = APIRouter(tags=["grading-runs"])

PDF_CONTENT_TYPE = "application/pdf"
PDF_SUFFIX = ".pdf"


def get_owned_assessment_or_404(assessment_id: int, db: Session, teacher: User) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    course = db.get(Course, assessment.course_id)
    if course is None or course.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def get_owned_grading_run_or_404(grading_run_id: int, db: Session, teacher: User) -> GradingRun:
    grading_run = db.get(GradingRun, grading_run_id)
    if grading_run is None or grading_run.created_by_teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grading run not found")
    return grading_run


@router.post(
    "/assessments/{assessment_id}/grading-runs/custom",
    response_model=GradingRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_custom_grading_run(
    assessment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    payload: GradingRunCreate | None = None,
) -> GradingRun:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    grading_run = GradingRun(
        assessment_id=assessment_id,
        created_by_teacher_id=current_user.id,
        mode="custom_controlled",
        status="draft",
        notes=payload.notes if payload else None,
    )
    db.add(grading_run)
    db.commit()
    db.refresh(grading_run)
    return grading_run


@router.get("/assessments/{assessment_id}/grading-runs", response_model=list[GradingRunRead])
def list_assessment_grading_runs(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> list[GradingRun]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return list(
        db.scalars(
            select(GradingRun)
            .where(GradingRun.assessment_id == assessment_id)
            .where(GradingRun.created_by_teacher_id == current_user.id)
            .order_by(GradingRun.created_at.asc(), GradingRun.id.asc())
        )
    )


@router.get("/grading-runs/{grading_run_id}", response_model=GradingRunRead)
def get_grading_run(
    grading_run_id: int, db: DbSession, current_user: CurrentUser
) -> GradingRun:
    return get_owned_grading_run_or_404(grading_run_id, db, current_user)


@router.patch("/grading-runs/{grading_run_id}", response_model=GradingRunRead)
def update_grading_run(
    grading_run_id: int,
    payload: GradingRunUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> GradingRun:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    if payload.status is not None:
        grading_run.status = payload.status
    if payload.notes is not None:
        grading_run.notes = payload.notes
    db.commit()
    db.refresh(grading_run)
    return grading_run


@router.post("/grading-runs/{grading_run_id}/materials", response_model=GradingRunRead)
def upload_grading_run_materials(
    grading_run_id: int,
    db: DbSession,
    current_user: CurrentUser,
    question_pdf: OptionalMaterialFile = None,
    solution_pdf: OptionalMaterialFile = None,
    rubric_pdf: OptionalMaterialFile = None,
) -> GradingRun:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    uploads = {
        "question_pdf_path": ("question_pdf", question_pdf),
        "solution_pdf_path": ("solution_pdf", solution_pdf),
        "rubric_pdf_path": ("rubric_pdf", rubric_pdf),
    }
    if all(upload is None for _, upload in uploads.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at least one PDF"
        )

    storage = LocalStorage()
    for field_name, (material_type, upload) in uploads.items():
        if upload is None:
            continue
        if upload.content_type != PDF_CONTENT_TYPE:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Custom controlled grading materials must be PDF files",
            )
        stored = storage.save_grading_run_material(
            upload, grading_run_id, material_type, PDF_SUFFIX
        )
        setattr(grading_run, field_name, stored.relative_path)

    grading_run.status = "materials_uploaded"
    db.commit()
    db.refresh(grading_run)
    return grading_run
