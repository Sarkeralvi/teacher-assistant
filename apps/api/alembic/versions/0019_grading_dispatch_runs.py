"""Add safe persistent cohort grading dispatches.

Revision ID: 0019_grading_dispatch_runs
Revises: 0018_answer_region_ocr_runs
Create Date: 2026-08-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_grading_dispatch_runs"
down_revision = "0018_answer_region_ocr_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_grade_suggestions_grading_job_id",
        "grade_suggestions",
        ["grading_job_id"],
    )
    op.create_index(
        "ux_grading_jobs_active_answer_region",
        "grading_jobs",
        ["answer_region_id"],
        unique=True,
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_table(
        "grading_dispatch_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "queue_run_id",
            sa.Integer(),
            sa.ForeignKey("grading_queue_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grading_run_id",
            sa.Integer(),
            sa.ForeignKey("grading_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("marking_policy", sa.String(length=16), nullable=False),
        sa.Column("maximum_calls", sa.Integer(), nullable=False),
        sa.Column(
            "draft_only_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("running_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uncertain_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calls_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status in ('queued', 'running', 'stopping', 'stopped', 'completed', 'failed')",
            name="ck_grading_dispatch_runs_status",
        ),
        sa.CheckConstraint(
            "marking_policy in ('tough', 'general', 'easy')",
            name="ck_grading_dispatch_runs_marking_policy",
        ),
        sa.CheckConstraint(
            "maximum_calls >= 1 and maximum_calls <= 25",
            name="ck_grading_dispatch_runs_maximum_calls",
        ),
    )
    op.create_index(
        "ix_grading_dispatch_runs_queue_run_id",
        "grading_dispatch_runs",
        ["queue_run_id"],
    )
    op.create_index(
        "ix_grading_dispatch_runs_grading_run_id",
        "grading_dispatch_runs",
        ["grading_run_id"],
    )
    op.create_index(
        "ix_grading_dispatch_runs_assessment_question",
        "grading_dispatch_runs",
        ["assessment_id", "question_id"],
    )
    op.create_table(
        "grading_dispatch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dispatch_run_id",
            sa.Integer(),
            sa.ForeignKey("grading_dispatch_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "queue_item_id",
            sa.Integer(),
            sa.ForeignKey("grading_queue_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "answer_region_id",
            sa.Integer(),
            sa.ForeignKey("answer_regions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grading_job_id",
            sa.Integer(),
            sa.ForeignKey("grading_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rubric_id",
            sa.Integer(),
            sa.ForeignKey("rubrics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("rubric_snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status in ('pending', 'running', 'succeeded', 'failed', 'refused', "
            "'skipped', 'uncertain')",
            name="ck_grading_dispatch_items_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 and attempt_count <= 1",
            name="ck_grading_dispatch_items_attempt_count",
        ),
        sa.UniqueConstraint(
            "dispatch_run_id",
            "queue_item_id",
            name="uq_grading_dispatch_items_run_queue_item",
        ),
        sa.UniqueConstraint(
            "grading_job_id", name="uq_grading_dispatch_items_grading_job_id"
        ),
    )
    op.create_index(
        "ix_grading_dispatch_items_dispatch_run_id",
        "grading_dispatch_items",
        ["dispatch_run_id"],
    )
    op.create_index(
        "ix_grading_dispatch_items_answer_region_id",
        "grading_dispatch_items",
        ["answer_region_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_grading_dispatch_items_answer_region_id", table_name="grading_dispatch_items"
    )
    op.drop_index(
        "ix_grading_dispatch_items_dispatch_run_id", table_name="grading_dispatch_items"
    )
    op.drop_table("grading_dispatch_items")
    op.drop_index(
        "ix_grading_dispatch_runs_assessment_question", table_name="grading_dispatch_runs"
    )
    op.drop_index(
        "ix_grading_dispatch_runs_grading_run_id", table_name="grading_dispatch_runs"
    )
    op.drop_index(
        "ix_grading_dispatch_runs_queue_run_id", table_name="grading_dispatch_runs"
    )
    op.drop_table("grading_dispatch_runs")
    op.drop_index("ux_grading_jobs_active_answer_region", table_name="grading_jobs")
    op.drop_constraint(
        "uq_grade_suggestions_grading_job_id",
        "grade_suggestions",
        type_="unique",
    )
