"""Process-local proof that an inference call owns the database model lease.

The database lease is the source of truth for the one physical local-model
slot. This context guard closes a separate failure mode: a future call site
could accidentally construct a local provider and invoke it without first
taking that database lease. The providers check this guard immediately before
their ``/chat/completions`` request and fail before any network call when it is
absent or names the wrong model phase.

It is deliberately process-local. It is not a second lock and never replaces
the durable database lease; ``LocalModelLeaseService`` activates it only after
a successful acquire and clears it on release.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

LocalModelPhase = Literal["Qwen", "Qwen38"]


class LocalModelCallGuardError(RuntimeError):
    """Raised before an unleased local-model inference request can start."""


@dataclass(frozen=True)
class LocalModelCallAuthorization:
    model_phase: LocalModelPhase
    holder_id: str
    expires_at: datetime


_ACTIVE_AUTHORIZATION: ContextVar[LocalModelCallAuthorization | None] = ContextVar(
    "active_local_model_call_authorization",
    default=None,
)


def activate_local_model_call_authorization(
    *, model_phase: LocalModelPhase, holder_id: str, expires_at: datetime
) -> None:
    """Mark this execution context as owning a successfully acquired lease."""

    _ACTIVE_AUTHORIZATION.set(
        LocalModelCallAuthorization(
            model_phase=model_phase,
            holder_id=holder_id,
            expires_at=expires_at,
        )
    )


def clear_local_model_call_authorization(*, holder_id: str) -> None:
    """Clear only the authorization belonging to the releasing holder."""

    active = _ACTIVE_AUTHORIZATION.get()
    if active is not None and active.holder_id == holder_id:
        _ACTIVE_AUTHORIZATION.set(None)


def clear_local_model_call_authorization_for_shutdown() -> None:
    """Fail closed during controlled worker/test teardown.

    Clearing can only make a subsequent inference call fail. It is useful when
    a test or a worker is being torn down after its database transaction has
    already been discarded.
    """

    _ACTIVE_AUTHORIZATION.set(None)


def assert_local_model_call_authorized(*, model_phase: LocalModelPhase) -> None:
    """Require the active execution context to own the matching model lease."""

    active = _ACTIVE_AUTHORIZATION.get()
    if active is None:
        raise LocalModelCallGuardError(
            "Local model lease is required before an inference call; no provider request was made"
        )
    expires_at = active.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise LocalModelCallGuardError(
            "Local model lease expired before this inference call; no provider request was made"
        )
    if active.model_phase != model_phase:
        raise LocalModelCallGuardError(
            "Local model lease phase does not match this inference call; "
            "no provider request was made"
        )
