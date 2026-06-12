"""add manual answer evidence text

Revision ID: 0013_manual_answer_text
Revises: 0012_grading_queue_scaffold
Create Date: 2026-06-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_manual_answer_text"
down_revision: str | None = "0012_grading_queue_scaffold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_regions", sa.Column("manual_answer_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("answer_regions", "manual_answer_text")
