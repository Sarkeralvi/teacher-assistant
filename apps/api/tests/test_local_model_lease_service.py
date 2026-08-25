from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import LocalModelLease
from app.services.local_ai_phase_manager import LocalAiPhaseError, LocalAiPhaseManager
from app.services.local_model_call_guard import (
    LocalModelCallGuardError,
    assert_local_model_call_authorized,
    clear_local_model_call_authorization_for_shutdown,
)
from app.services.local_model_lease_service import (
    LEASE_KEY,
    LocalModelLeaseError,
    LocalModelLeaseService,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        db.execute(delete(LocalModelLease))
        db.commit()
        yield db
    finally:
        clear_local_model_call_authorization_for_shutdown()
        db.execute(delete(LocalModelLease))
        db.commit()
        db.close()


def _row(db: Session) -> LocalModelLease:
    row = db.scalar(select(LocalModelLease).where(LocalModelLease.lease_key == LEASE_KEY))
    assert row is not None
    return row


def test_lease_is_free_before_anyone_takes_it(db_session: Session) -> None:
    state = LocalModelLeaseService(db_session).read()

    assert state.held is False
    assert state.holder_id is None


def test_acquire_takes_the_slot_and_records_the_phase(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)

    state = service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")

    assert state.held is True
    assert state.model_phase == "Qwen38"
    assert state.holder_id == "job-1"
    assert service.read().held is True


def test_paddle_lease_is_a_first_class_exclusive_phase(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)

    state = service.acquire(
        model_phase="PaddleOcr", holder_kind="visual_transcription", holder_id="ocr-1"
    )

    assert state.model_phase == "PaddleOcr"
    assert_local_model_call_authorized(model_phase="PaddleOcr")
    with pytest.raises(LocalModelCallGuardError, match="phase does not match"):
        assert_local_model_call_authorized(model_phase="Qwen")
    with pytest.raises(LocalModelLeaseError, match="held by"):
        service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="vision-1")


def test_acquire_authorizes_only_the_matching_local_model_phase(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")

    assert_local_model_call_authorized(model_phase="Qwen38")
    with pytest.raises(LocalModelCallGuardError, match="phase does not match"):
        assert_local_model_call_authorized(model_phase="Qwen")

    service.release(holder_id="job-1")
    with pytest.raises(LocalModelCallGuardError, match="lease is required"):
        assert_local_model_call_authorized(model_phase="Qwen38")


def test_second_holder_is_refused_while_the_lease_is_live(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")

    with pytest.raises(LocalModelLeaseError, match="held by"):
        service.acquire(model_phase="Qwen", holder_kind="worker_job", holder_id="job-2")

    # The original holder must be untouched by the refused attempt.
    assert service.read().holder_id == "job-1"
    assert service.read().model_phase == "Qwen38"


def test_the_same_holder_may_reacquire_and_extend(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    first = service.acquire(
        model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1", lease_seconds=60
    )

    second = service.acquire(
        model_phase="Qwen", holder_kind="worker_job", holder_id="job-1", lease_seconds=600
    )

    assert second.model_phase == "Qwen"
    assert first.expires_at is not None
    assert second.expires_at is not None
    assert second.expires_at > first.expires_at


def test_an_expired_lease_is_reclaimable_so_a_dead_holder_cannot_block_forever(
    db_session: Session,
) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="dead-job")
    row = _row(db_session)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert service.read().held is False
    state = service.acquire(model_phase="Qwen", holder_kind="worker_job", holder_id="job-2")

    assert state.holder_id == "job-2"


def test_release_frees_the_slot(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")

    service.release(holder_id="job-1")

    assert service.read().held is False
    service.acquire(model_phase="Qwen", holder_kind="worker_job", holder_id="job-2")


def test_hold_releases_the_slot_when_the_provider_operation_fails(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)

    with pytest.raises(RuntimeError, match="provider failed"):
        with service.hold(
            model_phase="Qwen38", holder_kind="worker_job", holder_id="job-failing"
        ):
            assert service.read().holder_id == "job-failing"
            raise RuntimeError("provider failed")

    assert service.read().held is False


def test_release_by_a_non_holder_does_not_steal_the_slot(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")

    # A finally-block release from a job that never got the lease must not
    # hand the slot away from whoever legitimately holds it.
    service.release(holder_id="job-2")

    assert service.read().holder_id == "job-1"


def test_release_clears_a_stale_process_authorization_after_ownership_is_lost(
    db_session: Session,
) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")
    assert_local_model_call_authorized(model_phase="Qwen38")

    # Simulate a database-side lease takeover before this worker's finally
    # block runs.  It must never retain an in-process proof it no longer owns.
    row = _row(db_session)
    row.holder_id = "job-2"
    db_session.commit()

    service.release(holder_id="job-1")

    assert service.read().holder_id == "job-2"
    with pytest.raises(LocalModelCallGuardError, match="lease is required"):
        assert_local_model_call_authorized(model_phase="Qwen38")


def test_heartbeat_extends_only_for_the_holder(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(
        model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1", lease_seconds=60
    )
    before = _row(db_session).expires_at
    assert before is not None

    service.heartbeat(holder_id="job-1", lease_seconds=600)

    after = _row(db_session).expires_at
    assert after is not None
    assert after > before

    with pytest.raises(LocalModelLeaseError, match="no longer holds"):
        service.heartbeat(holder_id="job-2")


def test_heartbeat_after_expiry_tells_the_holder_to_stop(db_session: Session) -> None:
    service = LocalModelLeaseService(db_session)
    service.acquire(model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1")
    row = _row(db_session)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    # Continuing against a model that may have been switched is the failure
    # this lease exists to prevent, so an expired holder must be told to stop.
    with pytest.raises(LocalModelLeaseError, match="no longer holds"):
        service.heartbeat(holder_id="job-1")


def test_phase_switch_refuses_when_the_caller_does_not_hold_the_lease(
    db_session: Session,
) -> None:
    LocalModelLeaseService(db_session).acquire(
        model_phase="Qwen38", holder_kind="worker_job", holder_id="job-1"
    )
    calls: list[object] = []
    manager = LocalAiPhaseManager(
        runner=lambda *args, **kwargs: calls.append(args),
        db=db_session,
        settings=Settings(
            LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
            LOCAL_AI_PHASE_SWITCH_ENABLED=True,
        ),
    )

    with pytest.raises(LocalAiPhaseError, match="does not hold the local model slot"):
        manager.switch("Qwen", lease_holder_id="job-2")

    # The refusal must happen before anything is executed.
    assert calls == []


def test_phase_switch_refuses_a_named_lease_without_a_session(db_session: Session) -> None:
    del db_session
    calls: list[object] = []
    manager = LocalAiPhaseManager(
        runner=lambda *args, **kwargs: calls.append(args),
        settings=Settings(
            LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
            LOCAL_AI_PHASE_SWITCH_ENABLED=True,
        ),
    )

    with pytest.raises(LocalAiPhaseError, match="no database session"):
        manager.switch("Qwen", lease_holder_id="job-1")

    assert calls == []
