"""Entrypoint for the RQ worker process (`python -m app.worker.run`)."""

import logging
import os

from rq import SimpleWorker, Worker

from app.redis_client import get_redis_client
from app.services.bulk_run_guard import reconcile_interrupted_bulk_runs
from app.worker.rq_app import get_default_queue

logger = logging.getLogger(__name__)


def get_worker_class(platform_name: str | None = None) -> type[Worker]:
    """Return an RQ worker implementation supported by the current host."""

    return SimpleWorker if (platform_name or os.name) == "nt" else Worker


def main() -> None:
    try:
        # A run left 'active' by a dead worker (restart, reboot) is paused visibly before
        # this worker takes any job; a failure here must not keep the worker from starting.
        reconcile_interrupted_bulk_runs()
    except Exception:
        logger.exception("Interrupted bulk-run reconciliation failed at worker start")
    queue = get_default_queue()
    worker_class = get_worker_class()
    worker_name = os.environ.get("RQ_WORKER_NAME") or None
    worker = worker_class([queue], connection=get_redis_client(), name=worker_name)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
