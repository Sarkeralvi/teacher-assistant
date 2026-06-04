"""grading queue scaffold

Revision ID: 0012_grading_queue_scaffold
Revises: 0011_batch_evidence_prep_runs
Create Date: 2026-06-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_grading_queue_scaffold"
down_revision: str | None = "0011_batch_evidence_prep_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "grading_queue_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("evidence_prep_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by_teacher_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_candidate_packets", sa.Integer(), nullable=False),
        sa.Column("queued_item_count", sa.Integer(), nullable=False),
        sa.Column("refused_item_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('pending', 'built', 'blocked', 'failed')",
            name="ck_grading_queue_runs_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_teacher_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_prep_run_id"],
            ["batch_evidence_prep_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_grading_queue_runs_assessment_id", "grading_queue_runs", ["assessment_id"]
    )
    op.create_index(
        "ix_grading_queue_runs_evidence_prep_run_id",
        "grading_queue_runs",
        ["evidence_prep_run_id"],
    )
    op.create_table(
        "grading_queue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("queue_run_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("student_identifier", sa.String(length=128), nullable=True),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("grading_unit_id", sa.Integer(), nullable=False),
        sa.Column("grading_unit_label", sa.String(length=64), nullable=False),
        sa.Column("max_marks", sa.Numeric(10, 2), nullable=False),
        sa.Column("answer_region_id", sa.Integer(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("pages_covered", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("continuation_check_status", sa.String(length=64), nullable=False),
        sa.Column("queue_status", sa.String(length=64), nullable=False),
        sa.Column("provider_allowed", sa.Boolean(), nullable=False),
        sa.Column("evidence_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "readiness_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "queue_status in ('pending_review', 'ready_for_provider_later', 'blocked')",
            name="ck_grading_queue_items_status",
        ),
        sa.ForeignKeyConstraint(
            ["answer_region_id"], ["answer_regions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grading_unit_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["queue_run_id"], ["grading_queue_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_grading_queue_items_answer_region_id",
        "grading_queue_items",
        ["answer_region_id"],
    )
    op.create_index(
        "ix_grading_queue_items_queue_run_id", "grading_queue_items", ["queue_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grading_queue_items_queue_run_id", table_name="grading_queue_items")
    op.drop_index("ix_grading_queue_items_answer_region_id", table_name="grading_queue_items")
    op.drop_table("grading_queue_items")
    op.drop_index(
        "ix_grading_queue_runs_evidence_prep_run_id", table_name="grading_queue_runs"
    )
    op.drop_index("ix_grading_queue_runs_assessment_id", table_name="grading_queue_runs")
    op.drop_table("grading_queue_runs")
