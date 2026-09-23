"""Gate transcript grading on the exact teacher-reviewed snapshot.

Revision ID: 0039_transcript_review_gate
Revises: 0038_bulk_transcript
"""

import sqlalchemy as sa

from alembic import op

revision = "0039_transcript_review_gate"
down_revision = "0038_bulk_transcript"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "script_transcripts",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "script_transcripts",
        sa.Column("reviewed_by_teacher_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "script_transcripts",
        sa.Column("review_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_script_transcripts_reviewed_by_teacher_id",
        "script_transcripts",
        "users",
        ["reviewed_by_teacher_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_script_transcript_review_is_attributed",
        "script_transcripts",
        "reviewed_at is null or "
        "(reviewed_by_teacher_id is not null and review_snapshot_sha256 is not null)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_script_transcript_review_is_attributed",
        "script_transcripts",
        type_="check",
    )
    op.drop_constraint(
        "fk_script_transcripts_reviewed_by_teacher_id",
        "script_transcripts",
        type_="foreignkey",
    )
    op.drop_column("script_transcripts", "review_snapshot_sha256")
    op.drop_column("script_transcripts", "reviewed_by_teacher_id")
    op.drop_column("script_transcripts", "reviewed_at")
