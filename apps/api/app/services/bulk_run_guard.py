"""Process-level guards for bulk runs: what the launcher and the worker check at startup.

* ``active_bulk_run_ids`` lets ``Start-TeacherPilot.ps1`` leave the worker and the loaded model
  alone while a bulk run owns them (RC-56).
* ``reconcile_interrupted_bulk_runs`` runs when the worker starts. A run still marked active
  whose heartbeat is older than the stale window cannot have a live worker unit (this is the
  only worker), so it is paused visibly instead of looking busy forever after a restart or a
  reboot (RC-57). Nothing is resumed or retried automatically.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import BulkEvaluationRun

logger = logging.getLogger(__name__)

ACTIVE_RUN_STATUSES = (
    "preflighting",
    "queued",
    "reading",
    "mapping",
    "transcribing",
    "grading",
    "stopping",
)


def active_bulk_run_ids() -> list[int]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(BulkEvaluationRun.id)
                .where(BulkEvaluationRun.status.in_(ACTIVE_RUN_STATUSES))
                .order_by(BulkEvaluationRun.id)
            ).all()
        )
    finally:
        db.close()


def reconcile_interrupted_bulk_runs(settings: Settings | None = None) -> list[int]:
    """Pause every active run with a stale heartbeat; return their ids."""

    from app.services.bulk_evaluation_service import BulkEvaluationService

    db = SessionLocal()
    try:
        service = BulkEvaluationService(db, settings=settings or get_settings())
        paused = service.reconcile_interrupted_runs()
        if paused:
            logger.warning("Paused interrupted bulk runs at worker start: %s", paused)
        return paused
    finally:
        db.close()
