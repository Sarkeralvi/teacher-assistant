"""Pin the rubric version each grade suggestion graded against.

Revision ID: 0017_grade_suggestion_rubric_pin
Revises: 0016_extraction_provider_gemini
Create Date: 2026-07-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_grade_suggestion_rubric_pin"
down_revision = "0016_extraction_provider_gemini"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grade_suggestions",
        sa.Column("rubric_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_grade_suggestions_rubric_id",
        "grade_suggestions",
        "rubrics",
        ["rubric_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_grade_suggestions_rubric_id", "grade_suggestions", type_="foreignkey"
    )
    op.drop_column("grade_suggestions", "rubric_id")
