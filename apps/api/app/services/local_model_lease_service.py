"""Ownership of the single local model slot.

Qwen3.6 (~20.6 GB) and Qwen3.8 (~17.7 GB) cannot both be resident in this
host's 12.2 GB of VRAM, so selecting a phase unloads whichever model is
running. Nothing else in the system prevents one job switching the model out
from under another that is mid-call, which would fail the second job in a way
that looks like a provider error rather than a scheduling bug.

This lease makes that impossible to do by accident:

* one holder at a time, enforced by a unique row rather than by convention;
* a holder that dies stops blocking the slot once its lease expires;
* a non-holder fails immediately with a clear message instead of waiting.

The lease deliberately does not queue. Model loads take 30-90 seconds and calls
run for minutes, so a queued caller would sit far past any sensible request
timeout. Failing fast lets the caller report honestly that the model is busy.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import GradingJob, LocalModelLease
from app.services.local_model_call_guard import (
    activate_local_model_call_authorization,
    clear_local_model_call_authorization,
)

LocalModelPhase = Literal["PaddleOcr", "Qwen", "Qwen38"]

# One slot, one key. A second slot would need a second key and a real scheduler.
LEASE_KEY = "local_model"
DEFAULT_LEASE_SECONDS = 1800


class LocalModelLeaseError(RuntimeError):
    """Raised when the model slot cannot be taken or is not held by the caller."""


@dataclass(frozen=True)
class LeaseState:
    held: bool
    model_phase: str | None
    holder_kind: str | None
    holder_id: str | None
    expires_at: datetime | None


class LocalModelLeaseService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def acquire(
        self,
        *,
        model_phase: LocalModelPhase,
        holder_kind: str,
        holder_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> LeaseState:
        """Take the model slot, or raise if someone else holds it.

        Re-acquiring while already the holder is allowed and extends the lease:
        a job that takes the slot for OCR and then needs it again for grading
        should not have to release and race for it.
        """
        if lease_seconds <= 0:
            raise LocalModelLeaseError("Lease duration must be positive")
        now = datetime.now(UTC)
        row = self._locked_row()
        if self._is_held_by_other(row, now=now, holder_id=holder_id):
            # A successful grading call commits its terminal job immediately
            # before releasing the lease. If the process is terminated in that
            # tiny window, no inference is still running but the durable row
            # used to block all grading for up to 30 minutes. Reclaim only when
            # the exact owner job is durably terminal; unknown or running
            # owners remain fail-closed.
            if self._is_terminal_grading_holder(row):
                self._clear(row)
            else:
                raise LocalModelLeaseError(
                    f"The local model slot is held by {row.holder_kind}:{row.holder_id} "
                    f"running {row.model_phase} until {row.expires_at:%H:%M:%S}. "
                    "Wait for it to finish; this run will not switch the model underneath it."
                )
        row.model_phase = model_phase
        row.holder_kind = holder_kind
        row.holder_id = holder_id
        row.acquired_at = now
        row.heartbeat_at = now
        row.expires_at = now + timedelta(seconds=lease_seconds)
        self.db.commit()
        self.db.refresh(row)
        # Providers independently verify this process-local proof immediately
        # before /chat/completions. The database row remains the authoritative
        # cross-process lock.
        state = self._state(row, now=datetime.now(UTC))
        if state.expires_at is None:
            raise LocalModelLeaseError("The local model lease did not record an expiry")
        activate_local_model_call_authorization(
            model_phase=model_phase,
            holder_id=holder_id,
            expires_at=state.expires_at,
        )
        return state

    @contextmanager
    def hold(
        self,
        *,
        model_phase: LocalModelPhase,
        holder_kind: str,
        holder_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> Iterator[LocalModelLeaseService]:
        """Hold the only local-model slot for one complete provider operation.

        This is deliberately fail-closed: ``acquire`` raises before the body
        starts if another operation owns the slot.  The matching ``finally``
        release means failures cannot leave a healthy worker blocking the next
        teacher action.  Long operations should still call ``heartbeat``
        immediately before and after each provider request.
        """
        self.acquire(
            model_phase=model_phase,
            holder_kind=holder_kind,
            holder_id=holder_id,
            lease_seconds=lease_seconds,
        )
        try:
            yield self
        finally:
            self.release(holder_id=holder_id)

    def heartbeat(
        self,
        *,
        holder_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        """Extend the caller's lease. Long calls must call this periodically.

        Raises if the caller is not the holder, which is the signal that its
        lease expired and someone else may already have switched the model.
        """
        now = datetime.now(UTC)
        row = self._locked_row()
        if row.holder_id != holder_id or self._is_expired(row, now=now):
            raise LocalModelLeaseError(
                "This job no longer holds the local model slot; its lease expired "
                "or was taken over. Stop rather than continue against a model that "
                "may have been switched."
            )
        row.heartbeat_at = now
        row.expires_at = now + timedelta(seconds=lease_seconds)
        self.db.commit()
        if row.model_phase not in {"PaddleOcr", "Qwen", "Qwen38"} or row.expires_at is None:
            raise LocalModelLeaseError("The local model lease heartbeat is missing its phase")
        activate_local_model_call_authorization(
            model_phase=row.model_phase,
            holder_id=holder_id,
            expires_at=row.expires_at,
        )

    def release(self, *, holder_id: str) -> None:
        """Give the slot back. Releasing a lease you do not hold is a no-op.

        A no-op rather than an error so a ``finally`` block can release
        unconditionally without masking the original failure.
        """
        # Clear the in-process proof even if the durable release cannot finish
        # (for example because the session is being torn down).  Clearing only
        # makes a later inference fail, while retaining it could otherwise
        # leave an unexpired authorization after a failed release.
        try:
            row = self._locked_row()
            if row.holder_id != holder_id:
                self.db.commit()
                return
            self._clear(row)
            self.db.commit()
        finally:
            clear_local_model_call_authorization(holder_id=holder_id)

    def read(self) -> LeaseState:
        now = datetime.now(UTC)
        row = self.db.scalar(select(LocalModelLease).where(LocalModelLease.lease_key == LEASE_KEY))
        if row is None:
            return LeaseState(
                held=False, model_phase=None, holder_kind=None, holder_id=None, expires_at=None
            )
        return self._state(row, now=now)

    def _state(self, row: LocalModelLease, *, now: datetime) -> LeaseState:
        if row.holder_id is None or self._is_expired(row, now=now):
            return LeaseState(
                held=False, model_phase=None, holder_kind=None, holder_id=None, expires_at=None
            )
        return LeaseState(
            held=True,
            model_phase=row.model_phase,
            holder_kind=row.holder_kind,
            holder_id=row.holder_id,
            expires_at=row.expires_at,
        )

    def _locked_row(self) -> LocalModelLease:
        """Fetch the lease row FOR UPDATE, creating it once if absent.

        Row-level locking is what serialises concurrent acquire attempts; two
        callers arriving together are ordered by the database rather than by
        who read the row first.
        """
        row = self.db.scalar(
            select(LocalModelLease).where(LocalModelLease.lease_key == LEASE_KEY).with_for_update()
        )
        if row is not None:
            return row
        row = LocalModelLease(lease_key=LEASE_KEY)
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError:
            # Another caller created it between our select and insert; take theirs.
            self.db.rollback()
            row = self.db.scalar(
                select(LocalModelLease)
                .where(LocalModelLease.lease_key == LEASE_KEY)
                .with_for_update()
            )
            if row is None:
                raise LocalModelLeaseError(
                    "The local model lease row could not be created"
                ) from None
        return row

    def _is_held_by_other(
        self, row: LocalModelLease, *, now: datetime, holder_id: str
    ) -> bool:
        if row.holder_id is None or row.holder_id == holder_id:
            return False
        return not self._is_expired(row, now=now)

    def _is_terminal_grading_holder(self, row: LocalModelLease) -> bool:
        if row.holder_kind != "grading" or not row.holder_id:
            return False
        prefix, separator, remainder = row.holder_id.partition(":")
        job_id_text, second_separator, _nonce = remainder.partition(":")
        if prefix != "grading_job" or not separator or not second_separator:
            return False
        try:
            job_id = int(job_id_text)
        except ValueError:
            return False
        job = self.db.get(GradingJob, job_id)
        return job is not None and job.status in {"succeeded", "failed"}

    @staticmethod
    def _is_expired(row: LocalModelLease, *, now: datetime) -> bool:
        if row.expires_at is None:
            return True
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= now

    @staticmethod
    def _clear(row: LocalModelLease) -> None:
        row.model_phase = None
        row.holder_kind = None
        row.holder_id = None
        row.acquired_at = None
        row.heartbeat_at = None
        row.expires_at = None
