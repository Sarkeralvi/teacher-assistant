"""allow semi-automated grading runs

Revision ID: 0008_semi_automated_mode
Revises: 0007_marking_policy
Create Date: 2026-06-01 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_semi_automated_mode"
down_revision: str | None = "0007_marking_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED = "mode in ('custom_controlled', 'semi_automated')"
_LEGACY_ALLOWED = "mode in ('custom_controlled')"


def upgrade() -> None:
    op.drop_constraint("ck_grading_runs_mode", "grading_runs", type_="check")
    op.create_check_constraint("ck_grading_runs_mode", "grading_runs", _ALLOWED)



def downgrade() -> None:
    op.drop_constraint("ck_grading_runs_mode", "grading_runs", type_="check")
    op.create_check_constraint("ck_grading_runs_mode", "grading_runs", _LEGACY_ALLOWED)
