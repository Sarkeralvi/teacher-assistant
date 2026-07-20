"""RQ job functions. Each opens its own DB session — workers run in a
separate process from the request that enqueued them.
"""

from app.db.session import SessionLocal
from app.services.grading_service import GradingService


def run_grade_answer_region_job(
    grading_job_id: int, *, marking_policy: str = "general"
) -> None:
    db = SessionLocal()
    try:
        GradingService(db).run_queued_job(grading_job_id, marking_policy=marking_policy)
    finally:
        db.close()
