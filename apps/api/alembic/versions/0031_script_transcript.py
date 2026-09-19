"""Persist the durable, question-independent script source transcript.

The one-call-per-page read already produced a full-page transcript, but it only
ever existed as a local variable: what reached the database was the
per-question, geometry-keyed ``AnswerRegion``/``AnswerRegionOcrRun``/
``AnswerRegionMapping`` triple. Three consequences this migration removes the
storage-level cause of:

* A crash after page *n* discarded *n* completed provider reads.
* Re-preparing after a remap or a rubric change re-read every page with vision,
  because there was nothing to reuse.
* Question assignment and source text were written in one operation, so the
  source evidence could not be versioned independently of the assignment.

The tables are additive. ``answer_region_mappings`` and its status CHECK are
untouched, so every existing record stays readable and the legacy
mapping-then-transcription path keeps working unchanged.

Revision ID: 0031_script_transcript
Revises: 0030_grading_run_brain_profile
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0031_script_transcript"
down_revision = "0030_grading_run_brain_profile"
branch_labels = None
depends_on = None

# A transcript is reusable only for the exact settings that produced it, so the
# terminal states below are about the *source read*, never about a question.
_TRANSCRIPT_STATUSES = "'in_progress', 'complete', 'failed', 'superseded'"
# 'missing_page' is distinct from 'unreadable' on purpose: neither is a blank
# page, and a caller must not be able to collapse either into one.
_PAGE_STATES = "'succeeded', 'unreadable', 'missing_page', 'failed'"
_LABEL_SOURCES = "'heading', 'continuation', 'inferred'"


def upgrade() -> None:
    op.create_table(
        "script_transcripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Integer(),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The reuse key. Everything that can change what the model would read
        # goes into this digest, so a transcript is never reused across a
        # different model, prompt, schema, or preprocessing setting.
        sa.Column("settings_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("preprocessing_fingerprint", sa.String(length=64), nullable=False),
        # Ordered digest of every source page image. A changed source page
        # changes this value, which is what makes stale reuse detectable
        # rather than merely unlikely.
        sa.Column("source_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            f"status in ({_TRANSCRIPT_STATUSES})",
            name="ck_script_transcript_status",
        ),
        sa.CheckConstraint("page_count >= 0", name="ck_script_transcript_page_count"),
        sa.UniqueConstraint(
            "submission_id",
            "settings_fingerprint",
            "source_manifest_sha256",
            name="uq_script_transcript_submission_settings",
        ),
    )
    op.create_index(
        "ix_script_transcripts_submission_id",
        "script_transcripts",
        ["submission_id"],
    )

    op.create_table(
        "script_page_transcripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "script_transcript_id",
            sa.Integer(),
            sa.ForeignKey("script_transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submission_page_id",
            sa.Integer(),
            sa.ForeignKey("submission_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("page_order", sa.Integer(), nullable=False),
        sa.Column("source_image_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("is_blank_page", sa.Boolean(), nullable=False),
        # Provenance is denormalized per page so one page may be repaired under
        # a newer prompt without invalidating the pages that were already read.
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("provider_request_count", sa.Integer(), nullable=False),
        sa.Column("repair_pass", sa.Integer(), nullable=False),
        # The provider payload exactly as validated, kept so a superseded read
        # is still inspectable after a repair pass replaces its blocks.
        sa.Column("raw_output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(f"state in ({_PAGE_STATES})", name="ck_script_page_transcript_state"),
        sa.CheckConstraint("page_no > 0", name="ck_script_page_transcript_page_no"),
        sa.CheckConstraint("page_order >= 0", name="ck_script_page_transcript_page_order"),
        sa.CheckConstraint(
            "provider_request_count >= 0",
            name="ck_script_page_transcript_request_count",
        ),
        sa.CheckConstraint("repair_pass >= 0", name="ck_script_page_transcript_repair_pass"),
        # A page that did not succeed is not evidence of a blank page. Without
        # this the "no answer" state can be reconstructed from a failure.
        sa.CheckConstraint(
            "state = 'succeeded' or is_blank_page = false",
            name="ck_script_page_transcript_blank_requires_success",
        ),
        sa.CheckConstraint(
            "state = 'succeeded' or error is not null",
            name="ck_script_page_transcript_failure_has_reason",
        ),
        sa.UniqueConstraint(
            "script_transcript_id",
            "submission_page_id",
            name="uq_script_page_transcript_page",
        ),
    )
    op.create_index(
        "ix_script_page_transcripts_transcript_id",
        "script_page_transcripts",
        ["script_transcript_id"],
    )
    op.create_index(
        "ix_script_page_transcripts_submission_page_id",
        "script_page_transcripts",
        ["submission_page_id"],
    )

    op.create_table(
        "script_transcript_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "script_page_transcript_id",
            sa.Integer(),
            sa.ForeignKey("script_page_transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # The heading the model reports it can actually see, kept separate from
        # the canonical label it was matched to. Assignment must be auditable
        # against what is on the page, not only against the match result.
        sa.Column("observed_heading_text", sa.String(length=255), nullable=True),
        sa.Column("question_label_raw", sa.String(length=128), nullable=True),
        sa.Column("label_source", sa.String(length=32), nullable=False),
        sa.Column("continues_from_previous", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        # Auxiliary navigation/highlighting geometry only. Question identity
        # never depends on it.
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unresolved", sa.Boolean(), nullable=False),
        sa.Column("unresolved_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            f"label_source in ({_LABEL_SOURCES})",
            name="ck_script_transcript_block_label_source",
        ),
        sa.CheckConstraint("block_index >= 0", name="ck_script_transcript_block_index"),
        sa.CheckConstraint("reading_order >= 0", name="ck_script_transcript_block_reading_order"),
        sa.CheckConstraint(
            "unresolved = false or unresolved_reason is not null",
            name="ck_script_transcript_block_unresolved_has_reason",
        ),
        # An unlabelled block has exactly one coherent source; this mirrors the
        # schema-level reconciliation so a direct insert cannot bypass it.
        sa.CheckConstraint(
            "question_label_raw is not null or label_source = 'continuation'",
            name="ck_script_transcript_block_unlabelled_is_continuation",
        ),
        sa.UniqueConstraint(
            "script_page_transcript_id",
            "block_index",
            name="uq_script_transcript_block_index",
        ),
    )
    op.create_index(
        "ix_script_transcript_blocks_page_transcript_id",
        "script_transcript_blocks",
        ["script_page_transcript_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_script_transcript_blocks_page_transcript_id",
        table_name="script_transcript_blocks",
    )
    op.drop_table("script_transcript_blocks")
    op.drop_index(
        "ix_script_page_transcripts_submission_page_id",
        table_name="script_page_transcripts",
    )
    op.drop_index(
        "ix_script_page_transcripts_transcript_id",
        table_name="script_page_transcripts",
    )
    op.drop_table("script_page_transcripts")
    op.drop_index("ix_script_transcripts_submission_id", table_name="script_transcripts")
    op.drop_table("script_transcripts")
