import pytest
from rq import SimpleWorker, Worker

from app.worker import jobs
from app.worker.run import get_worker_class


def test_windows_uses_simple_worker() -> None:
    assert get_worker_class("nt") is SimpleWorker


def test_posix_uses_standard_worker() -> None:
    assert get_worker_class("posix") is Worker


def test_bulk_worker_requeue_failure_pauses_the_durable_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    sessions: list[object] = []

    class FakeSession:
        def close(self) -> None:
            sessions.append(self)

    class FakeService:
        def __init__(self, db: FakeSession) -> None:
            self.db = db

        def run_next(self, run_id: int) -> bool:
            calls.append(("run_next", run_id))
            return True

        def pause_after_enqueue_failure(self, run_id: int) -> None:
            calls.append(("pause", run_id))

    class FailingQueue:
        def enqueue(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic queue outage")

    monkeypatch.setattr(jobs, "SessionLocal", FakeSession)
    monkeypatch.setattr(jobs, "BulkEvaluationService", FakeService)
    monkeypatch.setattr(jobs, "get_default_queue", FailingQueue)

    with pytest.raises(RuntimeError, match="synthetic queue outage"):
        jobs.run_bulk_evaluation_next_job(41)

    assert calls == [("run_next", 41), ("pause", 41)]
    assert len(sessions) == 2
