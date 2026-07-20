"""Entrypoint for the RQ worker process (`python -m app.worker.run`)."""

from rq import Worker

from app.redis_client import get_redis_client
from app.worker.rq_app import get_default_queue


def main() -> None:
    queue = get_default_queue()
    worker = Worker([queue], connection=get_redis_client())
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
