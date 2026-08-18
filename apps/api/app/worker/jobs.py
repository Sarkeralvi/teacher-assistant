"""RQ job functions. Each opens its own DB session â€” workers run in a
separate process from the request that enqueued them.
"""

from app.db.session import SessionLocal
from app.services.grading_dispatch_service import GradingDispatchService
from app.services.grading_service import GradingService
from app.services.reference_extraction_service import ReferenceExtractionService


def run_grade_answer_region_job(
    grading_job_id: int, *, marking_policy: str = "general"
) -> None:
    db = SessionLocal()
    try:
        GradingService(db).run_queued_job(grading_job_id, marking_policy=marking_policy)
    finally:
        db.close()


def run_grading_dispatch_job(grading_dispatch_run_id: int) -> None:
    db = SessionLocal()
    try:
        GradingDispatchService(db).run_dispatch(grading_dispatch_run_id)
    finally:
        db.close()


def run_reference_extraction_job(grading_run_id: int) -> None:
    db = SessionLocal()
    try:
        ReferenceExtractionService(db).run(grading_run_id)
    finally:
        db.close()

