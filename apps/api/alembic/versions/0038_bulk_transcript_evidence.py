"""Let bulk grading point directly at transcript evidence assignments.

Revision ID: 0038_bulk_transcript
Revises: 0037_transcript_review
"""

import sqlalchemy as sa

from alembic import op

revision = "0038_bulk_transcript"
down_revision = "0037_transcript_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("bulk_evaluation_items", "grading_jobs", "grade_suggestions"):
        op.add_column(
            table,
            sa.Column("answer_evidence_assignment_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_answer_evidence_assignment_id",
            table,
            "answer_evidence_assignments",
            ["answer_evidence_assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.drop_constraint("ck_bulk_evaluation_runs_status", "bulk_evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_bulk_evaluation_runs_status",
        "bulk_evaluation_runs",
        "status in ('preflighting', 'queued', 'reading', 'mapping', 'transcribing', "
        "'grading', 'review_ready', 'completed_with_exceptions', 'completed', "
        "'stopping', 'stopped', 'paused', 'failed')",
    )
    op.drop_constraint("ck_bulk_evaluation_runs_stage", "bulk_evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_bulk_evaluation_runs_stage",
        "bulk_evaluation_runs",
        "stage in ('ingestion', 'reading', 'mapping', 'evidence_verification', "
        "'transcription', 'grading', 'review', 'complete')",
    )
    op.drop_index("ux_bulk_evaluation_runs_active_archive", table_name="bulk_evaluation_runs")
    op.create_index(
        "ux_bulk_evaluation_runs_active_archive",
        "bulk_evaluation_runs",
        ["assessment_id", "archive_sha256", "reference_bundle_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "status in ('preflighting', 'queued', 'reading', 'mapping', 'transcribing', "
            "'grading', 'review_ready', 'stopping', 'paused')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ux_bulk_evaluation_runs_active_archive", table_name="bulk_evaluation_runs")
    op.create_index(
        "ux_bulk_evaluation_runs_active_archive",
        "bulk_evaluation_runs",
        ["assessment_id", "archive_sha256", "reference_bundle_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "status in ('preflighting', 'queued', 'mapping', 'transcribing', "
            "'grading', 'review_ready', 'stopping', 'paused')"
        ),
    )
    op.drop_constraint("ck_bulk_evaluation_runs_stage", "bulk_evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_bulk_evaluation_runs_stage",
        "bulk_evaluation_runs",
        "stage in ('ingestion', 'mapping', 'evidence_verification', 'transcription', "
        "'grading', 'review', 'complete')",
    )
    op.drop_constraint("ck_bulk_evaluation_runs_status", "bulk_evaluation_runs", type_="check")
    op.create_check_constraint(
        "ck_bulk_evaluation_runs_status",
        "bulk_evaluation_runs",
        "status in ('preflighting', 'queued', 'mapping', 'transcribing', 'grading', "
        "'review_ready', 'completed_with_exceptions', 'completed', 'stopping', "
        "'stopped', 'paused', 'failed')",
    )
    for table in ("grade_suggestions", "grading_jobs", "bulk_evaluation_items"):
        op.drop_constraint(f"fk_{table}_answer_evidence_assignment_id", table, type_="foreignkey")
        op.drop_column(table, "answer_evidence_assignment_id")
