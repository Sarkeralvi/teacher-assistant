from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models import Assessment, BatchEvidencePrepRun, Course, User
from app.schemas import BatchEvidencePrepRunRead
from app.services.evidence_prep_service import EvidencePrepService

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["evidence-prep"])


def get_owned_assessment_or_404(assessment_id: int, db: Session, teacher: User) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    course = db.get(Course, assessment.course_id)
    if course is None or course.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    return assessment


def build_response_from_summary(
    summary: dict[str, object], run: BatchEvidencePrepRun | None = None
) -> dict[str, object]:
    response = dict(summary)
    if run is not None:
        response.update(
            {
                "id": run.id,
                "created_by_teacher_id": run.created_by_teacher_id,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
        )
    return response


@router.get(
    "/assessments/{assessment_id}/evidence-prep-summary",
    response_model=BatchEvidencePrepRunRead,
)
def read_evidence_prep_summary(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    summary = EvidencePrepService(db).summarize_assessment(assessment_id)
    summary["created_by_teacher_id"] = current_user.id
    return summary


@router.post(
    "/assessments/{assessment_id}/evidence-prep-runs",
    response_model=BatchEvidencePrepRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence_prep_run(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    run = BatchEvidencePrepRun(
        assessment_id=assessment_id,
        created_by_teacher_id=current_user.id,
        status="running",
    )
    db.add(run)
    db.flush()
    try:
        summary = EvidencePrepService(db).summarize_assessment(assessment_id)
        run.status = str(summary["status"])
        run.total_submissions = int(summary["total_submissions"])
        run.total_expected_packets = int(summary["total_expected_packets"])
        run.ready_packet_count = int(summary["ready_packet_count"])
        run.blocked_packet_count = int(summary["blocked_packet_count"])
        run.warning_packet_count = int(summary["warning_packet_count"])
        run.blank_packet_count = int(summary["blank_packet_count"])
        run.partial_packet_count = int(summary["partial_packet_count"])
        run.error = None
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        summary = {
            "assessment_id": assessment_id,
            "status": "failed",
            "total_submissions": 0,
            "total_expected_packets": 0,
            "ready_packet_count": 0,
            "blocked_packet_count": 0,
            "warning_packet_count": 0,
            "blank_packet_count": 0,
            "partial_packet_count": 0,
            "packets": [],
            "error": str(exc),
        }
    db.commit()
    db.refresh(run)
    return build_response_from_summary(summary, run)


@router.get(
    "/assessments/{assessment_id}/evidence-prep-runs/{run_id}",
    response_model=BatchEvidencePrepRunRead,
)
def read_evidence_prep_run(
    assessment_id: int, run_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    run = db.get(BatchEvidencePrepRun, run_id)
    if (
        run is None
        or run.assessment_id != assessment_id
        or run.created_by_teacher_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence prep run not found"
        )
    summary = EvidencePrepService(db).summarize_assessment(assessment_id)
    return build_response_from_summary(summary, run)
