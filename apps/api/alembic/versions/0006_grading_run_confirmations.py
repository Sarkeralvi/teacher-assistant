"""add grading run confirmation timestamps

Revision ID: 0006_run_confirms
Revises: 0005_grading_runs
Create Date: 2026-05-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_run_confirms"
down_revision: str | None = "0005_grading_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grading_runs",
        sa.Column("materials_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "grading_runs",
        sa.Column("questions_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "grading_runs",
        sa.Column("rubrics_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("grading_runs", "rubrics_confirmed_at")
    op.drop_column("grading_runs", "questions_confirmed_at")
    op.drop_column("grading_runs", "materials_confirmed_at")
