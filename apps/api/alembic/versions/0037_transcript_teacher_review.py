"""Store teacher page classification and block ownership overrides.

Revision ID: 0037_transcript_review
Revises: 0036_block_revision
"""

import sqlalchemy as sa

from alembic import op

revision = "0037_transcript_review"
down_revision = "0036_block_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "script_page_transcripts", sa.Column("teacher_classification", sa.String(32), nullable=True)
    )
    op.add_column(
        "script_page_transcripts", sa.Column("classification_note", sa.Text(), nullable=True)
    )
    op.add_column(
        "script_page_transcripts",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "script_page_transcripts",
        sa.Column(
            "classified_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_script_page_transcript_teacher_classification",
        "script_page_transcripts",
        "teacher_classification is null or "
        "teacher_classification in ('answer_content', 'non_answer')",
    )
    op.create_check_constraint(
        "ck_script_page_transcript_classification_is_attributed",
        "script_page_transcripts",
        "teacher_classification is null or "
        "(classified_at is not null and classified_by_teacher_id is not null)",
    )

    op.add_column(
        "script_transcript_blocks",
        sa.Column(
            "assignment_override_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("teacher_question_label", sa.String(128), nullable=True),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("teacher_continues_from_previous", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("assignment_override_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("assignment_edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column(
            "assignment_edited_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("script_transcript_blocks", "assignment_override_active", server_default=None)
    op.alter_column("script_transcript_blocks", "assignment_override_revision", server_default=None)
    op.create_check_constraint(
        "ck_script_transcript_block_assignment_override_revision",
        "script_transcript_blocks",
        "assignment_override_revision >= 0",
    )
    op.create_check_constraint(
        "ck_script_transcript_block_assignment_override_is_attributed",
        "script_transcript_blocks",
        "assignment_override_active = false or "
        "(assignment_edited_at is not null and "
        "assignment_edited_by_teacher_id is not null and "
        "assignment_override_revision > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_script_transcript_block_assignment_override_is_attributed",
        "script_transcript_blocks",
        type_="check",
    )
    op.drop_constraint(
        "ck_script_transcript_block_assignment_override_revision",
        "script_transcript_blocks",
        type_="check",
    )
    for column in (
        "assignment_edited_by_teacher_id",
        "assignment_edited_at",
        "assignment_override_revision",
        "teacher_continues_from_previous",
        "teacher_question_label",
        "assignment_override_active",
    ):
        op.drop_column("script_transcript_blocks", column)
    op.drop_constraint(
        "ck_script_page_transcript_classification_is_attributed",
        "script_page_transcripts",
        type_="check",
    )
    op.drop_constraint(
        "ck_script_page_transcript_teacher_classification", "script_page_transcripts", type_="check"
    )
    for column in (
        "classified_by_teacher_id",
        "classified_at",
        "classification_note",
        "teacher_classification",
    ):
        op.drop_column("script_page_transcripts", column)
