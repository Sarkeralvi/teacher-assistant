"""Version question assignment separately from the source transcript.

With the source transcript durable, which question a piece of writing answers
becomes a separate, re-derivable decision. Two things follow that the existing
``answer_region_mappings`` row cannot express:

* ``ck_answer_region_mappings_status`` admits only
  ``mapped|uncertain|blocked|teacher_confirmed``, so ``local_script_page_read``
  coerced its own ``not_found`` into ``blocked``. A genuinely unanswered
  question was therefore indistinguishable from an unreadable, ambiguous,
  missing or failed one, which is exactly the confusion that lets a failure be
  marked down as a blank answer.
* An assignment had no version of its own, so it could not be re-derived
  against a newer canonical question structure without rewriting the evidence.

That CHECK constraint is deliberately left alone: the legacy status stays a
projection of the state recorded here, so every existing record keeps working.

Revision ID: 0032_answer_evidence
Revises: 0031_script_transcript
"""

import sqlalchemy as sa

from alembic import op

revision = "0032_answer_evidence"
down_revision = "0031_script_transcript"
branch_labels = None
depends_on = None

# The work order's six states. Stored snake_case to match the rest of the
# schema; the uppercase names in the specification map one to one.
_EVIDENCE_STATES = (
    "'answer_present', 'no_answer_found', 'unreadable', "
    "'ambiguous', 'missing_page', 'processing_failed'"
)


def upgrade() -> None:
    op.create_table(
        "answer_evidence_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Integer(),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "script_transcript_id",
            sa.Integer(),
            sa.ForeignKey("script_transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_node_id",
            sa.Integer(),
            sa.ForeignKey("question_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        # Whether every source page of this transcript reached a successful
        # read. Without it "no answer found" cannot be told apart from "we
        # never managed to look".
        sa.Column("coverage_complete", sa.Boolean(), nullable=False),
        sa.Column("unresolved_block_count", sa.Integer(), nullable=False),
        sa.Column("unassigned_block_count", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            f"state in ({_EVIDENCE_STATES})",
            name="ck_answer_evidence_assignment_state",
        ),
        sa.CheckConstraint(
            "assignment_version > 0",
            name="ck_answer_evidence_assignment_version",
        ),
        sa.CheckConstraint(
            "unresolved_block_count >= 0 and unassigned_block_count >= 0",
            name="ck_answer_evidence_assignment_counts",
        ),
        # The rule the whole table exists for. "No answer found" is a claim
        # about a fully processed script with nothing left over; anything else
        # must keep its own state and must never be scored as a blank.
        sa.CheckConstraint(
            "state <> 'no_answer_found' "
            "or (coverage_complete = true and unassigned_block_count = 0)",
            name="ck_answer_evidence_no_answer_requires_coverage",
        ),
        sa.CheckConstraint(
            "state = 'answer_present' or state_reason is not null",
            name="ck_answer_evidence_non_present_has_reason",
        ),
        sa.UniqueConstraint(
            "script_transcript_id",
            "question_node_id",
            "assignment_version",
            name="uq_answer_evidence_assignment_version",
        ),
    )
    op.create_index(
        "ix_answer_evidence_assignments_submission_id",
        "answer_evidence_assignments",
        ["submission_id"],
    )
    op.create_index(
        "ix_answer_evidence_assignments_transcript_id",
        "answer_evidence_assignments",
        ["script_transcript_id"],
    )
    # At most one current assignment per canonical question per source version.
    op.create_index(
        "ux_answer_evidence_assignments_current",
        "answer_evidence_assignments",
        ["script_transcript_id", "question_node_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "answer_evidence_spans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("answer_evidence_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "script_transcript_block_id",
            sa.Integer(),
            sa.ForeignKey("script_transcript_blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        # Null bounds mean the whole block. A quote must resolve against the
        # stored source text, so the bounds are offsets into that block's text
        # rather than a copy of it.
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("order_index >= 0", name="ck_answer_evidence_span_order"),
        sa.CheckConstraint("page_no > 0", name="ck_answer_evidence_span_page_no"),
        sa.CheckConstraint(
            "(char_start is null) = (char_end is null)",
            name="ck_answer_evidence_span_bounds_paired",
        ),
        sa.CheckConstraint(
            "char_start is null or (char_start >= 0 and char_end > char_start)",
            name="ck_answer_evidence_span_bounds_ordered",
        ),
        sa.UniqueConstraint(
            "assignment_id",
            "order_index",
            name="uq_answer_evidence_span_order",
        ),
    )
    op.create_index(
        "ix_answer_evidence_spans_assignment_id",
        "answer_evidence_spans",
        ["assignment_id"],
    )
    op.create_index(
        "ix_answer_evidence_spans_block_id",
        "answer_evidence_spans",
        ["script_transcript_block_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_answer_evidence_spans_block_id", table_name="answer_evidence_spans")
    op.drop_index("ix_answer_evidence_spans_assignment_id", table_name="answer_evidence_spans")
    op.drop_table("answer_evidence_spans")
    op.drop_index(
        "ux_answer_evidence_assignments_current",
        table_name="answer_evidence_assignments",
    )
    op.drop_index(
        "ix_answer_evidence_assignments_transcript_id",
        table_name="answer_evidence_assignments",
    )
    op.drop_index(
        "ix_answer_evidence_assignments_submission_id",
        table_name="answer_evidence_assignments",
    )
    op.drop_table("answer_evidence_assignments")
