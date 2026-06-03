"""add multi-segment answer regions

Revision ID: 0009_answer_region_segments
Revises: 0008_semi_automated_mode
Create Date: 2026-06-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_answer_region_segments"
down_revision: str | None = "0008_semi_automated_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answer_regions",
        sa.Column("full_answer_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "answer_region_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("answer_region_id", sa.Integer(), nullable=False),
        sa.Column("submission_page_id", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("x", sa.Numeric(12, 2), nullable=False),
        sa.Column("y", sa.Numeric(12, 2), nullable=False),
        sa.Column("width", sa.Numeric(12, 2), nullable=False),
        sa.Column("height", sa.Numeric(12, 2), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source in ('manual', 'suggestion', 'imported')",
            name="ck_answer_region_segments_source",
        ),
        sa.ForeignKeyConstraint(["answer_region_id"], ["answer_regions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submission_page_id"], ["submission_pages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_answer_region_segments_answer_region_id",
        "answer_region_segments",
        ["answer_region_id"],
    )
    op.execute(
        """
        INSERT INTO answer_region_segments (
            answer_region_id, submission_page_id, order_index, x, y, width, height,
            image_path, source, confirmed, is_primary, created_at, updated_at
        )
        SELECT id, page_id, 1, x, y, width, height, image_path,
               'manual', true, true, created_at, updated_at
        FROM answer_regions
        """
    )
    op.alter_column("answer_regions", "full_answer_confirmed", server_default=None)
    op.alter_column("answer_region_segments", "order_index", server_default=None)
    op.alter_column("answer_region_segments", "source", server_default=None)
    op.alter_column("answer_region_segments", "confirmed", server_default=None)
    op.alter_column("answer_region_segments", "is_primary", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_answer_region_segments_answer_region_id", table_name="answer_region_segments")
    op.drop_table("answer_region_segments")
    op.drop_column("answer_regions", "full_answer_confirmed")
