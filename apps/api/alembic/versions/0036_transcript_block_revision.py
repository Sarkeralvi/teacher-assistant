"""Let a teacher correct a transcript without overwriting what the model read.

Review requires editing, and editing a transcript in place would destroy the
two things the record exists for: what the provider actually produced, and the
ability to tell a model error from a teacher's correction. It would also defeat
reuse, because the next preparation would find the edited text under an
unchanged source hash and treat a human correction as model output.

So ``text`` stays the verbatim provider output forever, ``edited_text`` carries
the teacher's correction, and every edit appends a row to
``script_transcript_block_revisions`` rather than replacing the previous one.
``revision`` counts the corrections and is part of the evidence fingerprint, so
a correction invalidates a draft grade even though no source pixel moved.

Revision ID: 0036_block_revision
Revises: 0035_suggestion_evidence
"""

import sqlalchemy as sa

from alembic import op

revision = "0036_block_revision"
down_revision = "0035_suggestion_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "script_transcript_blocks",
        sa.Column("edited_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "script_transcript_blocks",
        sa.Column(
            "edited_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.alter_column("script_transcript_blocks", "revision", server_default=None)
    op.create_check_constraint(
        "ck_script_transcript_block_revision",
        "script_transcript_blocks",
        "revision >= 0",
    )
    # An edit is only an edit if someone made it and it says when.
    op.create_check_constraint(
        "ck_script_transcript_block_edit_is_attributed",
        "script_transcript_blocks",
        "edited_text is null or (edited_at is not null and revision > 0)",
    )

    op.create_table(
        "script_transcript_block_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "script_transcript_block_id",
            sa.Integer(),
            sa.ForeignKey("script_transcript_blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        # What the text was before this edit, so a correction can be read back
        # against what it replaced.
        sa.Column("previous_text", sa.Text(), nullable=False),
        sa.Column("new_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "edited_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("revision > 0", name="ck_block_revision_number"),
        sa.UniqueConstraint(
            "script_transcript_block_id",
            "revision",
            name="uq_block_revision_number",
        ),
    )
    op.create_index(
        "ix_block_revisions_block_id",
        "script_transcript_block_revisions",
        ["script_transcript_block_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_block_revisions_block_id", table_name="script_transcript_block_revisions"
    )
    op.drop_table("script_transcript_block_revisions")
    op.drop_constraint(
        "ck_script_transcript_block_edit_is_attributed",
        "script_transcript_blocks",
        type_="check",
    )
    op.drop_constraint(
        "ck_script_transcript_block_revision", "script_transcript_blocks", type_="check"
    )
    op.drop_column("script_transcript_blocks", "edited_by_teacher_id")
    op.drop_column("script_transcript_blocks", "edited_at")
    op.drop_column("script_transcript_blocks", "revision")
    op.drop_column("script_transcript_blocks", "edited_text")
