"""Persist the immutable brain profile selected for a grading run.

Revision ID: 0030_grading_run_brain_profile
Revises: 0029_fix_bulk_item_fk_drift
"""

import sqlalchemy as sa

from alembic import op

revision = "0030_grading_run_brain_profile"
down_revision = "0029_fix_bulk_item_fk_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grading_runs",
        sa.Column("brain_profile_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "grading_runs",
        sa.Column(
            "brain_profile_data_boundary_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("grading_runs", "brain_profile_data_boundary_confirmed_at")
    op.drop_column("grading_runs", "brain_profile_id")
