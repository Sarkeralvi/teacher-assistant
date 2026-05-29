"""add question import jobs

Revision ID: 0003_question_import_jobs
Revises: 0002_final_status
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_question_import_jobs"
down_revision: str | None = "0002_final_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_import_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("draft_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "status in ('uploaded', 'drafted', 'accepted', 'failed')",
            name="ck_question_import_jobs_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_import_jobs_assessment_id",
        "question_import_jobs",
        ["assessment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_question_import_jobs_assessment_id", table_name="question_import_jobs")
    op.drop_table("question_import_jobs")
