from rq import SimpleWorker, Worker

from app.worker.run import get_worker_class


def test_windows_uses_simple_worker() -> None:
    assert get_worker_class("nt") is SimpleWorker


def test_posix_uses_standard_worker() -> None:
    assert get_worker_class("posix") is Worker
