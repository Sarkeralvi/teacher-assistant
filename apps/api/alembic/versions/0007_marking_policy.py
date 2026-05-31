"""add marking policy fields

Revision ID: 0007_marking_policy
Revises: 0006_run_confirms
Create Date: 2026-05-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_marking_policy"
down_revision: str | None = "0006_run_confirms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED = "marking_policy in ('tough', 'general', 'easy')"


def upgrade() -> None:
    op.add_column(
        "grading_runs",
        sa.Column(
            "marking_policy",
            sa.String(length=16),
            nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "grade_suggestions",
        sa.Column(
            "marking_policy",
            sa.String(length=16),
            nullable=False,
            server_default="general",
        ),
    )
    op.create_check_constraint("ck_grading_runs_marking_policy", "grading_runs", _ALLOWED)
    op.create_check_constraint("ck_grade_suggestions_marking_policy", "grade_suggestions", _ALLOWED)
    op.alter_column("grading_runs", "marking_policy", server_default=None)
    op.alter_column("grade_suggestions", "marking_policy", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_grade_suggestions_marking_policy", "grade_suggestions", type_="check")
    op.drop_constraint("ck_grading_runs_marking_policy", "grading_runs", type_="check")
    op.drop_column("grade_suggestions", "marking_policy")
    op.drop_column("grading_runs", "marking_policy")
