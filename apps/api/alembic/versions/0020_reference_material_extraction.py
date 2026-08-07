"""Add the teacher-controlled reference-material extraction state.

Revision ID: 0020_reference_extraction
Revises: 0019_grading_dispatch_runs
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020_reference_extraction"
down_revision = "0019_grading_dispatch_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grading_runs", sa.Column("question_pdf_name", sa.String(255)))
    op.add_column("grading_runs", sa.Column("solution_pdf_name", sa.String(255)))
    op.add_column("grading_runs", sa.Column("rubric_pdf_name", sa.String(255)))
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_extraction_status",
            sa.String(32),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_extraction_stage",
            sa.String(64),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column("grading_runs", sa.Column("reference_extraction_error", sa.Text()))
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_extraction_warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_material_hashes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_question_run_id",
            sa.Integer(),
            sa.ForeignKey("extraction_runs.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_rubric_run_id",
            sa.Integer(),
            sa.ForeignKey("extraction_runs.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_ocr_call_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "reference_qwen_call_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "grading_runs",
        sa.Column("reference_extraction_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "grading_runs",
        sa.Column("reference_extraction_completed_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_grading_runs_reference_extraction_status",
        "grading_runs",
        "reference_extraction_status in "
        "('not_started', 'queued', 'running', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_grading_runs_reference_extraction_status", "grading_runs", type_="check"
    )
    op.drop_column("grading_runs", "reference_extraction_completed_at")
    op.drop_column("grading_runs", "reference_extraction_started_at")
    op.drop_column("grading_runs", "reference_qwen_call_count")
    op.drop_column("grading_runs", "reference_ocr_call_count")
    op.drop_column("grading_runs", "reference_rubric_run_id")
    op.drop_column("grading_runs", "reference_question_run_id")
    op.drop_column("grading_runs", "reference_material_hashes")
    op.drop_column("grading_runs", "reference_extraction_warnings")
    op.drop_column("grading_runs", "reference_extraction_error")
    op.drop_column("grading_runs", "reference_extraction_stage")
    op.drop_column("grading_runs", "reference_extraction_status")
    op.drop_column("grading_runs", "rubric_pdf_name")
    op.drop_column("grading_runs", "solution_pdf_name")
    op.drop_column("grading_runs", "question_pdf_name")
