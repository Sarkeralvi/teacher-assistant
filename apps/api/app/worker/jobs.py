"""RQ job functions. Each opens its own DB session â€” workers run in a
separate process from the request that enqueued them.
"""

from app.db.session import SessionLocal
from app.services.answer_region_ocr_service import AnswerRegionOcrService
from app.services.bulk_evaluation_service import BulkEvaluationService
from app.services.grading_dispatch_service import GradingDispatchService
from app.services.grading_service import GradingService
from app.services.qwen38_visual_transcription_service import Qwen38VisualTranscriptionService
from app.services.reference_extraction_service import ReferenceExtractionService
from app.worker.rq_app import get_default_queue


def run_grade_answer_region_job(grading_job_id: int, *, marking_policy: str = "general") -> None:
    db = SessionLocal()
    try:
        # The legacy async route stores no explicit real-provider authorization.
        # Keep its worker execution mock-only; Brain-authorized grading uses the
        # dedicated controlled routes.
        GradingService(db, use_configured_adapter=False).run_queued_job(
            grading_job_id,
            marking_policy=marking_policy,
        )
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


def run_answer_region_paddle_ocr_job(ocr_run_id: int) -> None:
    db = SessionLocal()
    try:
        AnswerRegionOcrService(db).run(ocr_run_id)
    finally:
        db.close()


def run_qwen38_visual_transcription_job(ocr_run_id: int) -> None:
    db = SessionLocal()
    try:
        Qwen38VisualTranscriptionService(db).run(ocr_run_id)
    finally:
        db.close()


def run_qwen38_thinking_repair_job(ocr_run_id: int) -> None:
    db = SessionLocal()
    try:
        Qwen38VisualTranscriptionService(db).run_thinking_repair(ocr_run_id)
    finally:
        db.close()


def run_bulk_evaluation_next_job(bulk_evaluation_run_id: int) -> None:
    """Advance exactly one durable bulk unit, then enqueue the next one.

    retry=None is set on every enqueue. A worker interruption during a provider
    call therefore cannot repeat that call automatically.
    """

    db = SessionLocal()
    try:
        has_more = BulkEvaluationService(db).run_next(bulk_evaluation_run_id)
    finally:
        db.close()
    if has_more:
        get_default_queue().enqueue(
            run_bulk_evaluation_next_job,
            bulk_evaluation_run_id,
            retry=None,
            job_timeout=3600,
        )
