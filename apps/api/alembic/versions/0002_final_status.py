"""allow edited final grade approval status

Revision ID: 0002_final_status
Revises: 0001_initial_schema
Create Date: 2026-05-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_final_status"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_final_grades_approval_status", "final_grades", type_="check"
    )
    op.create_check_constraint(
        "ck_final_grades_approval_status",
        "final_grades",
        "approval_status in ('pending', 'approved', 'edited', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_final_grades_approval_status", "final_grades", type_="check"
    )
    op.create_check_constraint(
        "ck_final_grades_approval_status",
        "final_grades",
        "approval_status in ('pending', 'approved', 'rejected')",
    )
