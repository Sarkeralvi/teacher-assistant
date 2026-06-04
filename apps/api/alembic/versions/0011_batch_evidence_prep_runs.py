"""add batch evidence prep runs

Revision ID: 0011_batch_evidence_prep_runs
Revises: 0010_evidence_packet_status
Create Date: 2026-06-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_batch_evidence_prep_runs"
down_revision: str | None = "0010_evidence_packet_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch_evidence_prep_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("created_by_teacher_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_submissions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_expected_packets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ready_packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blank_packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_packet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ("
            "'pending', 'running', 'completed', 'completed_with_blockers', 'failed'"
            ")",
            name="ck_batch_evidence_prep_runs_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_batch_evidence_prep_runs_assessment_id",
        "batch_evidence_prep_runs",
        ["assessment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_batch_evidence_prep_runs_assessment_id",
        table_name="batch_evidence_prep_runs",
    )
    op.drop_table("batch_evidence_prep_runs")
