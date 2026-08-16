"""Add persistent, image-grounded OCR rescue runs.

Revision ID: 0021_answer_region_ocr_rescue
Revises: 0020_reference_extraction
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_answer_region_ocr_rescue"
down_revision = "0020_reference_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_answer_region_ocr_runs_status", "answer_region_ocr_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_answer_region_ocr_runs_status",
        "answer_region_ocr_runs",
        "status in ('queued', 'running', 'succeeded', 'failed', 'confirmed', "
        "'rejected', 'uncertain')",
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("profile", sa.String(64), nullable=False, server_default="baseline"),
    )
    op.add_column(
        "answer_region_ocr_runs", sa.Column("source_image_sha256", sa.String(64))
    )
    for column_name in (
        "queued_at",
        "started_at",
        "heartbeat_at",
        "completed_at",
        "rejected_at",
    ):
        op.add_column(
            "answer_region_ocr_runs",
            sa.Column(column_name, sa.DateTime(timezone=True)),
        )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("call_limit", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "answer_region_ocr_runs", sa.Column("candidate_set_sha256", sa.String(64))
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column(
            "rejected_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column(
            "rejection_reason_codes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "ux_answer_region_ocr_rescue_active",
        "answer_region_ocr_runs",
        ["answer_region_id"],
        unique=True,
        postgresql_where=sa.text(
            "profile = 'math_handwriting_rescue' and status in ('queued', 'running')"
        ),
    )

    op.create_table(
        "answer_region_ocr_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ocr_run_id",
            sa.Integer(),
            sa.ForeignKey("answer_region_ocr_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_segment_id",
            sa.Integer(),
            sa.ForeignKey("answer_region_segments.id", ondelete="SET NULL"),
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("x", sa.Numeric(12, 2), nullable=False),
        sa.Column("y", sa.Numeric(12, 2), nullable=False),
        sa.Column("width", sa.Numeric(12, 2), nullable=False),
        sa.Column("height", sa.Numeric(12, 2), nullable=False),
        sa.Column("image_path", sa.String(1024), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "classification in ('text', 'formula')", name="ck_ocr_band_class"
        ),
        sa.UniqueConstraint("ocr_run_id", "order_index", name="uq_ocr_band_run_order"),
    )
    op.create_index(
        "ix_answer_region_ocr_bands_run_id", "answer_region_ocr_bands", ["ocr_run_id"]
    )
    op.create_table(
        "answer_region_ocr_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "band_id",
            sa.Integer(),
            sa.ForeignKey("answer_region_ocr_bands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("prompt_label", sa.String(32), nullable=False),
        sa.Column("preprocessing_profile", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(7, 6)),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "engine in ('ppocr_v6', 'paddleocr_vl')", name="ck_ocr_candidate_engine"
        ),
    )
    op.create_index(
        "ix_answer_region_ocr_candidates_band_id",
        "answer_region_ocr_candidates",
        ["band_id"],
    )


def downgrade() -> None:
    op.drop_table("answer_region_ocr_candidates")
    op.drop_table("answer_region_ocr_bands")
    op.drop_index("ux_answer_region_ocr_rescue_active", table_name="answer_region_ocr_runs")
    for column_name in (
        "rejection_reason_codes_json",
        "rejected_by_teacher_id",
        "candidate_set_sha256",
        "calls_used",
        "call_limit",
        "rejected_at",
        "completed_at",
        "heartbeat_at",
        "started_at",
        "queued_at",
        "source_image_sha256",
        "profile",
    ):
        op.drop_column("answer_region_ocr_runs", column_name)
    op.drop_constraint(
        "ck_answer_region_ocr_runs_status", "answer_region_ocr_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_answer_region_ocr_runs_status",
        "answer_region_ocr_runs",
        "status in ('running', 'succeeded', 'failed', 'confirmed')",
    )
