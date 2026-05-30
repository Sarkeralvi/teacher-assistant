"""add custom controlled grading runs

Revision ID: 0005_grading_runs
Revises: 0004_qimport_warn
Create Date: 2026-05-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_grading_runs"
down_revision: str | None = "0004_qimport_warn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GRADING_RUN_STATUSES = (
    "draft",
    "materials_uploaded",
    "questions_ready",
    "scripts_uploaded",
    "regions_ready",
    "grading_ready",
    "review_ready",
    "completed",
)


def upgrade() -> None:
    op.create_table(
        "grading_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("created_by_teacher_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("question_pdf_path", sa.String(length=1024), nullable=True),
        sa.Column("solution_pdf_path", sa.String(length=1024), nullable=True),
        sa.Column("rubric_pdf_path", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint("mode in ('custom_controlled')", name="ck_grading_runs_mode"),
        sa.CheckConstraint(
            "status in " + str(GRADING_RUN_STATUSES),
            name="ck_grading_runs_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grading_runs_assessment_id", "grading_runs", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_grading_runs_assessment_id", table_name="grading_runs")
    op.drop_table("grading_runs")
