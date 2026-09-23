"""Persist one whole-transcript question-assignment pass.

Revision ID: 0040_full_transcript_assignment
Revises: 0039_transcript_review_gate
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0040_full_transcript_assignment"
down_revision = "0039_transcript_review_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "script_transcripts",
        sa.Column(
            "assignment_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "script_transcripts",
        sa.Column("assignment_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "script_transcripts",
        sa.Column("assignment_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "script_transcripts",
        sa.Column(
            "assignment_provider_request_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "script_transcripts",
        sa.Column("assignment_error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_script_transcript_assignment_status",
        "script_transcripts",
        "assignment_status in "
        "('not_started', 'in_progress', 'complete', 'failed', 'unknown_outcome')",
    )
    op.create_check_constraint(
        "ck_script_transcript_assignment_request_count",
        "script_transcripts",
        "assignment_provider_request_count >= 0",
    )
    op.create_check_constraint(
        "ck_script_transcript_assignment_complete",
        "script_transcripts",
        "assignment_status <> 'complete' or "
        "(assignment_fingerprint is not null and assignment_result_json is not null)",
    )
    op.drop_constraint(
        "ck_answer_evidence_span_basis", "answer_evidence_spans", type_="check"
    )
    op.create_check_constraint(
        "ck_answer_evidence_span_basis",
        "answer_evidence_spans",
        "assignment_basis in "
        "('explicit_label', 'same_page_reading_order', 'declared_continuation', "
        "'full_transcript_model')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_answer_evidence_span_basis", "answer_evidence_spans", type_="check"
    )
    op.create_check_constraint(
        "ck_answer_evidence_span_basis",
        "answer_evidence_spans",
        "assignment_basis in "
        "('explicit_label', 'same_page_reading_order', 'declared_continuation')",
    )
    op.drop_constraint(
        "ck_script_transcript_assignment_complete", "script_transcripts", type_="check"
    )
    op.drop_constraint(
        "ck_script_transcript_assignment_request_count",
        "script_transcripts",
        type_="check",
    )
    op.drop_constraint(
        "ck_script_transcript_assignment_status", "script_transcripts", type_="check"
    )
    op.drop_column("script_transcripts", "assignment_error")
    op.drop_column("script_transcripts", "assignment_provider_request_count")
    op.drop_column("script_transcripts", "assignment_result_json")
    op.drop_column("script_transcripts", "assignment_fingerprint")
    op.drop_column("script_transcripts", "assignment_status")
