from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingRun,
    Question,
    QuestionImportJob,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import GradingRunCreate, GradingRunRead, GradingRunUpdate
from app.services.grading_service import GradingService
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
    get_owned_assessment_or_404(grading_run.assessment_id, db, teacher)
    return grading_run


def scalar_count(db: Session, statement: Any) -> int:
    return int(db.scalar(statement) or 0)


def build_workflow_state(grading_run: GradingRun, db: Session) -> dict[str, object]:
    assessment_id = grading_run.assessment_id
    question_count = scalar_count(
        db, select(func.count(Question.id)).where(Question.assessment_id == assessment_id)
    )
    active_rubric_count = scalar_count(
        db,
        select(func.count(func.distinct(Rubric.question_id)))
        .join(Question, Rubric.question_id == Question.id)
        .where(Question.assessment_id == assessment_id)
        .where(Rubric.is_active.is_(True)),
    )
    submission_count = scalar_count(
        db, select(func.count(Submission.id)).where(Submission.assessment_id == assessment_id)
    )
    submission_page_count = scalar_count(
        db,
        select(func.count(SubmissionPage.id))
        .join(Submission, SubmissionPage.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    answer_region_count = scalar_count(
        db,
        select(func.count(AnswerRegion.id))
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    mapped_question_count = scalar_count(
        db,
        select(func.count(func.distinct(AnswerRegion.question_id)))
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    mapped_page_count = scalar_count(
        db,
        select(func.count(func.distinct(AnswerRegion.page_id)))
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    mapped_submission_count = scalar_count(
        db,
        select(func.count(func.distinct(AnswerRegion.submission_id)))
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    unmapped_question_count = max(question_count - mapped_question_count, 0)
    unmapped_page_count = max(submission_page_count - mapped_page_count, 0)
    unmapped_submission_count = max(submission_count - mapped_submission_count, 0)
    grade_suggestion_count = scalar_count(
        db,
        select(func.count(GradeSuggestion.id))
        .join(AnswerRegion, GradeSuggestion.answer_region_id == AnswerRegion.id)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )
    final_grade_count = scalar_count(
        db,
        select(func.count(FinalGrade.id))
        .join(AnswerRegion, FinalGrade.answer_region_id == AnswerRegion.id)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .where(Submission.assessment_id == assessment_id),
    )

    question_paper_uploaded = grading_run.question_pdf_path is not None
    latest_question_import_job = db.scalars(
        select(QuestionImportJob)
        .where(QuestionImportJob.assessment_id == assessment_id)
        .order_by(QuestionImportJob.created_at.desc(), QuestionImportJob.id.desc())
    ).first()
    drafts_created = bool(
        latest_question_import_job and latest_question_import_job.draft_questions
    )
    if grading_run.mode == "semi_automated":
        materials_uploaded = question_paper_uploaded
    else:
        materials_uploaded = all(
            [
                grading_run.question_pdf_path,
                grading_run.solution_pdf_path,
                grading_run.rubric_pdf_path,
            ]
        )
    materials_confirmed = grading_run.materials_confirmed_at is not None
    questions_confirmed = grading_run.questions_confirmed_at is not None and question_count > 0
    rubrics_confirmed = (
        grading_run.rubrics_confirmed_at is not None
        and question_count > 0
        and active_rubric_count >= question_count
    )
    drafts_confirmed = (
        grading_run.mode == "semi_automated"
        and drafts_created
        and questions_confirmed
        and rubrics_confirmed
    )
    scripts_uploaded = submission_count > 0 and submission_page_count > 0
    answer_regions_created = answer_region_count > 0
    grading_ready = (
        materials_uploaded
        and materials_confirmed
        and questions_confirmed
        and rubrics_confirmed
        and scripts_uploaded
        and answer_regions_created
    )
    suggestions_created = grade_suggestion_count > 0
    review_ready = suggestions_created
    final_grades_created = final_grade_count > 0
    export_ready = final_grades_created

    blockers: list[str] = []
    if grading_run.mode == "semi_automated":
        if not question_paper_uploaded:
            blockers.append("Upload question paper.")
        if question_paper_uploaded and not materials_confirmed:
            blockers.append("Confirm uploaded question paper.")
        if question_paper_uploaded and materials_confirmed and not drafts_created:
            blockers.append("Generate draft questions/model answers/rubrics.")
        if drafts_created and not drafts_confirmed:
            blockers.append("Confirm draft questions/model answers/rubrics.")
    else:
        if not grading_run.question_pdf_path:
            blockers.append("Upload question PDF.")
        if not grading_run.solution_pdf_path:
            blockers.append("Upload solution/model answer PDF.")
        if not grading_run.rubric_pdf_path:
            blockers.append("Upload rubric PDF.")
        if materials_uploaded and not materials_confirmed:
            blockers.append("Confirm uploaded materials.")
    if question_count == 0:
        blockers.append("Create or confirm at least one question.")
    elif not questions_confirmed:
        blockers.append("Confirm questions/model answers.")
    if question_count > 0 and active_rubric_count < question_count:
        blockers.append("Create active rubric for each selected question.")
    elif question_count > 0 and not rubrics_confirmed:
        blockers.append("Confirm rubrics.")
    if submission_count == 0:
        blockers.append("Upload at least one script.")
    if answer_region_count == 0:
        blockers.append("Create at least one answer region.")
    if grading_ready and not suggestions_created:
        blockers.append("Run grading before review/export.")
    if suggestions_created and not final_grades_created:
        blockers.append("Review and finalize suggestions before export.")

    next_actions: list[str] = []
    if grading_run.mode == "semi_automated":
        if not question_paper_uploaded:
            next_actions.append("Upload question paper.")
        if question_paper_uploaded and not materials_confirmed:
            next_actions.append("Confirm uploaded question paper.")
        if question_paper_uploaded and materials_confirmed and not drafts_created:
            next_actions.append("Generate draft questions/model answers/rubrics.")
        if drafts_created and not drafts_confirmed:
            next_actions.append("Confirm draft questions/model answers/rubrics.")
    else:
        if not materials_uploaded:
            next_actions.append("Upload required materials.")
        if materials_uploaded and not materials_confirmed:
            next_actions.append("Confirm uploaded materials.")
        if not (questions_confirmed and rubrics_confirmed):
            next_actions.append("Confirm questions and rubrics.")
    if not scripts_uploaded:
        next_actions.append("Upload scripts.")
    if scripts_uploaded and not answer_regions_created:
        next_actions.append("Create answer regions.")
    if unmapped_question_count > 0 and answer_regions_created:
        next_actions.append("Map remaining questions to pages as needed.")
    if grading_ready and not suggestions_created:
        next_actions.append("Run mock grading or one real Codex grading.")
    if suggestions_created and not final_grades_created:
        next_actions.append("Review suggestions.")
    if export_ready:
        next_actions.append("Export final grades.")

    if export_ready:
        derived_status = "completed"
    elif review_ready:
        derived_status = "review_ready"
    elif grading_ready:
        derived_status = "grading_ready"
    elif answer_regions_created:
        derived_status = "regions_ready"
    elif scripts_uploaded:
        derived_status = "scripts_uploaded"
    elif questions_confirmed and rubrics_confirmed:
        derived_status = "questions_ready"
    elif materials_uploaded:
        derived_status = "materials_uploaded"
    else:
        derived_status = "draft"

    return {
        "materials_uploaded": materials_uploaded,
        "materials_confirmed": materials_confirmed,
        "question_paper_uploaded": question_paper_uploaded,
        "drafts_created": drafts_created,
        "drafts_confirmed": drafts_confirmed,
        "questions_confirmed": questions_confirmed,
        "rubrics_confirmed": rubrics_confirmed,
        "scripts_uploaded": scripts_uploaded,
        "answer_regions_created": answer_regions_created,
        "grading_ready": grading_ready,
        "suggestions_created": suggestions_created,
        "review_ready": review_ready,
        "final_grades_created": final_grades_created,
        "export_ready": export_ready,
        "question_count": question_count,
        "rubric_count": active_rubric_count,
        "submission_count": submission_count,
        "submission_page_count": submission_page_count,
        "answer_region_count": answer_region_count,
        "mapped_question_count": mapped_question_count,
        "mapped_page_count": mapped_page_count,
        "mapped_submission_count": mapped_submission_count,
        "unmapped_question_count": unmapped_question_count,
        "unmapped_page_count": unmapped_page_count,
        "unmapped_submission_count": unmapped_submission_count,
        "grade_suggestion_count": grade_suggestion_count,
        "final_grade_count": final_grade_count,
        "blockers": blockers,
        "next_actions": next_actions,
        "derived_status": derived_status,
    }


def serialize_grading_run(grading_run: GradingRun, db: Session) -> dict[str, object]:
    return {
        "id": grading_run.id,
        "assessment_id": grading_run.assessment_id,
        "created_by_teacher_id": grading_run.created_by_teacher_id,
        "mode": grading_run.mode,
        "status": grading_run.status,
        "marking_policy": grading_run.marking_policy,
        "question_pdf_path": grading_run.question_pdf_path,
        "solution_pdf_path": grading_run.solution_pdf_path,
        "rubric_pdf_path": grading_run.rubric_pdf_path,
        "materials_confirmed_at": grading_run.materials_confirmed_at,
        "questions_confirmed_at": grading_run.questions_confirmed_at,
        "rubrics_confirmed_at": grading_run.rubrics_confirmed_at,
        "notes": grading_run.notes,
        "workflow_state": build_workflow_state(grading_run, db),
        "created_at": grading_run.created_at,
        "updated_at": grading_run.updated_at,
    }


def ensure_grading_ready(grading_run: GradingRun, db: Session) -> None:
    workflow_state = build_workflow_state(grading_run, db)
    if workflow_state["grading_ready"] is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Custom Controlled grading is not ready.",
                "blockers": workflow_state["blockers"],
            },
        )


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
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    grading_run = GradingRun(
        assessment_id=assessment_id,
        created_by_teacher_id=current_user.id,
        mode=payload.mode if payload else "custom_controlled",
        status="draft",
        marking_policy=payload.marking_policy if payload else "general",
        notes=payload.notes if payload else None,
    )
    db.add(grading_run)
    db.commit()
    db.refresh(grading_run)
    return serialize_grading_run(grading_run, db)


@router.get("/assessments/{assessment_id}/grading-runs", response_model=list[GradingRunRead])
def list_assessment_grading_runs(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> list[dict[str, object]]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    runs = db.scalars(
        select(GradingRun)
        .where(GradingRun.assessment_id == assessment_id)
        .where(GradingRun.created_by_teacher_id == current_user.id)
        .order_by(GradingRun.created_at.asc(), GradingRun.id.asc())
    ).all()
    return [serialize_grading_run(run, db) for run in runs]


@router.get("/grading-runs/{grading_run_id}", response_model=GradingRunRead)
def get_grading_run(
    grading_run_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    return serialize_grading_run(
        get_owned_grading_run_or_404(grading_run_id, db, current_user), db
    )


@router.patch("/grading-runs/{grading_run_id}", response_model=GradingRunRead)
def update_grading_run(
    grading_run_id: int,
    payload: GradingRunUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    if payload.status is not None:
        grading_run.status = payload.status
    if payload.notes is not None:
        grading_run.notes = payload.notes
    if payload.marking_policy is not None:
        grading_run.marking_policy = payload.marking_policy
    db.commit()
    db.refresh(grading_run)
    return serialize_grading_run(grading_run, db)


@router.post("/grading-runs/{grading_run_id}/materials", response_model=GradingRunRead)
def upload_grading_run_materials(
    grading_run_id: int,
    db: DbSession,
    current_user: CurrentUser,
    question_pdf: OptionalMaterialFile = None,
    solution_pdf: OptionalMaterialFile = None,
    rubric_pdf: OptionalMaterialFile = None,
) -> dict[str, object]:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    if grading_run.mode == "semi_automated":
        if question_pdf is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload a question paper PDF for semi-automated runs",
            )
        if solution_pdf is not None or rubric_pdf is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Semi-automated runs only accept question paper uploads here",
            )
        uploads = {"question_pdf_path": ("question_pdf", question_pdf)}
    else:
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
                detail="Grading materials must be PDF files",
            )
        stored = storage.save_grading_run_material(
            upload, grading_run_id, material_type, PDF_SUFFIX
        )
        setattr(grading_run, field_name, stored.relative_path)

    grading_run.status = "materials_uploaded"
    grading_run.materials_confirmed_at = None
    db.commit()
    db.refresh(grading_run)
    return serialize_grading_run(grading_run, db)


@router.post("/grading-runs/{grading_run_id}/confirm-materials", response_model=GradingRunRead)
def confirm_grading_run_materials(
    grading_run_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    if grading_run.mode == "semi_automated":
        if not grading_run.question_pdf_path:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Upload question paper before confirmation",
            )
    elif not all(
        [
            grading_run.question_pdf_path,
            grading_run.solution_pdf_path,
            grading_run.rubric_pdf_path,
        ]
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload question, solution/model answer, and rubric PDFs before confirmation",
        )
    grading_run.materials_confirmed_at = datetime.now(UTC)
    db.commit()
    db.refresh(grading_run)
    return serialize_grading_run(grading_run, db)


@router.post(
    "/grading-runs/{grading_run_id}/confirm-questions-rubrics",
    response_model=GradingRunRead,
)
def confirm_grading_run_questions_rubrics(
    grading_run_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    workflow_state = build_workflow_state(grading_run, db)
    if workflow_state["materials_confirmed"] is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirm uploaded materials before confirming questions and rubrics",
        )
    if workflow_state["question_count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create at least one canonical question before confirmation",
        )
    question_count = workflow_state["question_count"]
    rubric_count = workflow_state["rubric_count"]
    if not isinstance(question_count, int) or not isinstance(rubric_count, int):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    if rubric_count < question_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create one active rubric for each canonical question before confirmation",
        )
    now = datetime.now(UTC)
    grading_run.questions_confirmed_at = now
    grading_run.rubrics_confirmed_at = now
    grading_run.status = "questions_ready"
    db.commit()
    db.refresh(grading_run)
    return serialize_grading_run(grading_run, db)


@router.post("/grading-runs/{grading_run_id}/grade-all-mock")
def grade_grading_run_ready_regions_mock(
    grading_run_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    grading_run = get_owned_grading_run_or_404(grading_run_id, db, current_user)
    ensure_grading_ready(grading_run, db)
    result = GradingService(db).grade_assessment_ungraded_regions_mock(
        grading_run.assessment_id,
        marking_policy=grading_run.marking_policy,
    )
    db.refresh(grading_run)
    result["marking_policy"] = grading_run.marking_policy
    result["workflow_state"] = build_workflow_state(grading_run, db)
    return result
