"""Persist Qwen3.8 visual evidence provenance.

Revision ID: 0023_qwen38_visual_preparation
Revises: 0022_ocr_rescue_v2
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023_qwen38_visual_preparation"
down_revision = "0022_ocr_rescue_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        "provider in ("
        "'host_bridge_codex', 'mock', 'disabled', 'gemini', 'local_paddle_qwen', 'llama_cpp_qwen38'"
        ")",
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("task_kind", sa.String(length=64), nullable=False, server_default="legacy_ocr"),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("reasoning_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column(
            "source_image_hashes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("input_manifest_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("model_asset_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("mmproj_asset_sha256", sa.String(length=64), nullable=True),
    )
    op.alter_column("answer_region_ocr_runs", "task_kind", server_default=None)
    op.alter_column("answer_region_ocr_runs", "source_image_hashes_json", server_default=None)


def downgrade() -> None:
    for name in (
        "mmproj_asset_sha256",
        "model_asset_sha256",
        "output_sha256",
        "input_manifest_sha256",
        "source_image_hashes_json",
        "prompt_version",
        "reasoning_mode",
        "task_kind",
    ):
        op.drop_column("answer_region_ocr_runs", name)
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        "provider in ('host_bridge_codex', 'mock', 'disabled', 'gemini', 'local_paddle_qwen')",
    )
