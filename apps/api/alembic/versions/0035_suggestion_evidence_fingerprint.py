"""Bind every draft suggestion to the exact evidence it was graded against.

A suggestion recorded which rubric it used, but nothing recorded *which
evidence*. So re-reading a source page, re-deriving an assignment, editing a
transcript or changing a model answer left an existing draft looking current
next to evidence it never saw, and a teacher could approve it into a final
grade without anything noticing.

The fingerprint is checked again at finalization, so the gate does not depend on
an invalidation hook having been remembered at every write site. Existing rows
have no fingerprint and are deliberately left alone: a null means "not recorded"
and keeps its previous behaviour rather than silently becoming either fresh or
stale.

``superseded_at`` marks a draft the workflow already knows is out of date, for
the review UI. Nothing is deleted: the superseded draft and its reason stay
readable, and finalization stays a teacher action either way.

Revision ID: 0035_suggestion_evidence
Revises: 0034_page_reservation
"""

import sqlalchemy as sa

from alembic import op

revision = "0035_suggestion_evidence"
down_revision = "0034_page_reservation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "grade_suggestions",
        sa.Column("source_evidence_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "grade_suggestions",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "grade_suggestions",
        sa.Column("superseded_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_grade_suggestions_superseded_has_reason",
        "grade_suggestions",
        "superseded_at is null or superseded_reason is not null",
    )
    op.create_index(
        "ix_grade_suggestions_superseded_at",
        "grade_suggestions",
        ["superseded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_grade_suggestions_superseded_at", table_name="grade_suggestions")
    op.drop_constraint(
        "ck_grade_suggestions_superseded_has_reason", "grade_suggestions", type_="check"
    )
    op.drop_column("grade_suggestions", "superseded_reason")
    op.drop_column("grade_suggestions", "superseded_at")
    op.drop_column("grade_suggestions", "source_evidence_fingerprint")
