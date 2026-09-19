"""Claim a source page before dispatching it, and keep ambiguous outcomes apart.

Before this, a page read was recorded only after the provider returned. Two
problems followed from that:

* Nothing stopped two workers, a double-clicked button or a restarted job from
  dispatching the same page at the same time. Both would pay, and the second
  write would simply overwrite the first.
* A call that timed out was recorded as ``failed``, and ``failed`` is retriable.
  A provider that timed out may still have produced and billed output, so
  retrying it is a blind resubmission of work whose outcome is unknown.

A page is now claimed as ``dispatched`` and committed *before* the request goes
out. ``uq_script_page_transcript_page`` makes that claim the concurrency
control: a second worker's insert fails rather than duplicating the call. An
outcome that cannot be determined becomes ``unknown_outcome``, which is
deliberately **not** retriable and requires an explicit reconciliation.

Revision ID: 0034_page_reservation
Revises: 0033_evidence_basis
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_page_reservation"
down_revision = "0033_evidence_basis"
branch_labels = None
depends_on = None

_STATES_NEW = (
    "'succeeded', 'unreadable', 'missing_page', 'failed', 'dispatched', 'unknown_outcome'"
)
_STATES_OLD = "'succeeded', 'unreadable', 'missing_page', 'failed'"


def upgrade() -> None:
    op.add_column(
        "script_page_transcripts",
        sa.Column("reservation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "script_page_transcripts",
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "script_page_transcripts",
        sa.Column("reserved_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "script_page_transcripts",
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint(
        "ck_script_page_transcript_state", "script_page_transcripts", type_="check"
    )
    op.create_check_constraint(
        "ck_script_page_transcript_state",
        "script_page_transcripts",
        f"state in ({_STATES_NEW})",
    )

    # A claimed page has not failed yet, so it has no reason to record. Every
    # other non-success state still must carry one.
    op.drop_constraint(
        "ck_script_page_transcript_failure_has_reason",
        "script_page_transcripts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_script_page_transcript_failure_has_reason",
        "script_page_transcripts",
        "state in ('succeeded', 'dispatched') or error is not null",
    )
    # A claim without an owner cannot be reconciled, and an owner without a
    # claim is a row that was never actually reserved.
    op.create_check_constraint(
        "ck_script_page_transcript_reservation_is_complete",
        "script_page_transcripts",
        "state <> 'dispatched' or (reservation_id is not null and reserved_at is not null)",
    )


def downgrade() -> None:
    # Rows in the two new states have no representation in the old vocabulary.
    # An unknown outcome must never silently become a retriable failure, so it
    # is recorded as failed with its reason preserved in the error text.
    op.execute(
        "update script_page_transcripts "
        "set state = 'failed', "
        "    error = coalesce(error, 'outcome unknown before downgrade') "
        "where state in ('dispatched', 'unknown_outcome')"
    )
    op.drop_constraint(
        "ck_script_page_transcript_reservation_is_complete",
        "script_page_transcripts",
        type_="check",
    )
    op.drop_constraint(
        "ck_script_page_transcript_failure_has_reason",
        "script_page_transcripts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_script_page_transcript_failure_has_reason",
        "script_page_transcripts",
        "state = 'succeeded' or error is not null",
    )
    op.drop_constraint(
        "ck_script_page_transcript_state", "script_page_transcripts", type_="check"
    )
    op.create_check_constraint(
        "ck_script_page_transcript_state",
        "script_page_transcripts",
        f"state in ({_STATES_OLD})",
    )
    op.drop_column("script_page_transcripts", "reconciled_at")
    op.drop_column("script_page_transcripts", "reserved_by")
    op.drop_column("script_page_transcripts", "reserved_at")
    op.drop_column("script_page_transcripts", "reservation_id")
