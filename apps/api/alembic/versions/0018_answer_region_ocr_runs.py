"""Add persisted local OCR draft and confirmation runs.

Revision ID: 0018_answer_region_ocr_runs
Revises: 0017_grade_suggestion_rubric_pin
Create Date: 2026-08-07
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018_answer_region_ocr_runs"
down_revision = "0017_grade_suggestion_rubric_pin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        "provider in ('host_bridge_codex', 'mock', 'disabled', 'gemini', "
        "'local_paddle_qwen')",
    )
    op.create_table(
        "answer_region_ocr_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "answer_region_id",
            sa.Integer(),
            sa.ForeignKey("answer_regions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("layout_model_name", sa.String(length=255), nullable=True),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("normalized_result_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("confirmed_text", sa.Text(), nullable=True),
        sa.Column(
            "confirmed_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status in ('running', 'succeeded', 'failed', 'confirmed')",
            name="ck_answer_region_ocr_runs_status",
        ),
    )
    op.create_index(
        "ix_answer_region_ocr_runs_answer_region_id",
        "answer_region_ocr_runs",
        ["answer_region_id"],
    )
    op.create_index(
        "ix_answer_region_ocr_runs_requested_by_teacher_id",
        "answer_region_ocr_runs",
        ["requested_by_teacher_id"],
    )
    op.create_index(
        "ux_answer_region_ocr_runs_request_id",
        "answer_region_ocr_runs",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_answer_region_ocr_runs_request_id", table_name="answer_region_ocr_runs"
    )
    op.drop_index(
        "ix_answer_region_ocr_runs_requested_by_teacher_id",
        table_name="answer_region_ocr_runs",
    )
    op.drop_index(
        "ix_answer_region_ocr_runs_answer_region_id",
        table_name="answer_region_ocr_runs",
    )
    op.drop_table("answer_region_ocr_runs")
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        "provider in ('host_bridge_codex', 'mock', 'disabled', 'gemini')",
    )
