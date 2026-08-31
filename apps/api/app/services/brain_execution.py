from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseService
from packages.brain.adapter import BrainAdapter


@dataclass
class BrainExecutionSession:
    lease: LocalModelLeaseService | None
    holder_id: str

    def heartbeat(self, *, holder_id: str | None = None) -> None:
        del holder_id
        if self.lease is not None:
            self.lease.heartbeat(holder_id=self.holder_id)


@contextmanager
def hold_brain_execution(
    *,
    db: Session,
    settings: Settings,
    adapter: BrainAdapter,
    holder_kind: str,
    holder_id: str,
    phase_manager: LocalAiPhaseManager | None = None,
) -> Iterator[BrainExecutionSession]:
    """Apply local GPU coordination only when the provider declares it.

    Cloud, CLI, mock, and externally managed local endpoints use the same
    workflow contract without touching the local phase manager or lease row.
    """

    phase = adapter.runtime.managed_local_phase
    verify = getattr(adapter, "verify_available_model", None)
    if phase is None:
        if callable(verify):
            verify()
        yield BrainExecutionSession(lease=None, holder_id=holder_id)
        return

    lease = LocalModelLeaseService(db)
    with lease.hold(
        model_phase=phase,
        holder_kind=holder_kind,
        holder_id=holder_id,
    ):
        if settings.local_ai_phase_switch_enabled:
            manager = phase_manager or LocalAiPhaseManager(settings=settings, db=db)
            manager.switch(phase, lease_holder_id=holder_id)
        if callable(verify):
            verify()
        session = BrainExecutionSession(lease=lease, holder_id=holder_id)
        session.heartbeat()
        yield session
        session.heartbeat()
