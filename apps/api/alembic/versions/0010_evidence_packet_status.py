"""add evidence packet status fields

Revision ID: 0010_evidence_packet_status
Revises: 0009_answer_region_segments
Create Date: 2026-06-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_evidence_packet_status"
down_revision: str | None = "0009_answer_region_segments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answer_regions",
        sa.Column(
            "evidence_status",
            sa.String(length=32),
            nullable=False,
            server_default="unconfirmed",
        ),
    )
    op.add_column(
        "answer_regions",
        sa.Column(
            "continuation_check_status",
            sa.String(length=64),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.create_check_constraint(
        "ck_answer_regions_evidence_status",
        "answer_regions",
        "evidence_status in ('unconfirmed', 'complete', 'partial', 'blank')",
    )
    op.create_check_constraint(
        "ck_answer_regions_continuation_check_status",
        "answer_regions",
        "continuation_check_status in ("
        "'not_checked', "
        "'checked_no_continuation', "
        "'possible_continuation', "
        "'continuation_confirmed_included', "
        "'continuation_confirmed_not_needed'"
        ")",
    )
    op.execute(
        """
        UPDATE answer_regions
        SET evidence_status = CASE WHEN full_answer_confirmed THEN 'complete' ELSE 'unconfirmed' END
        """
    )
    op.alter_column("answer_regions", "evidence_status", server_default=None)
    op.alter_column("answer_regions", "continuation_check_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_answer_regions_continuation_check_status", "answer_regions", type_="check"
    )
    op.drop_constraint("ck_answer_regions_evidence_status", "answer_regions", type_="check")
    op.drop_column("answer_regions", "continuation_check_status")
    op.drop_column("answer_regions", "evidence_status")
