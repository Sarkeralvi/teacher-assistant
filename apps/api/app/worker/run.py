"""Entrypoint for the RQ worker process (`python -m app.worker.run`)."""

import os

from rq import SimpleWorker, Worker

from app.redis_client import get_redis_client
from app.worker.rq_app import get_default_queue


def get_worker_class(platform_name: str | None = None) -> type[Worker]:
    """Return an RQ worker implementation supported by the current host."""

    return SimpleWorker if (platform_name or os.name) == "nt" else Worker


def main() -> None:
    queue = get_default_queue()
    worker_class = get_worker_class()
    worker_name = os.environ.get("RQ_WORKER_NAME") or None
    worker = worker_class([queue], connection=get_redis_client(), name=worker_name)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
