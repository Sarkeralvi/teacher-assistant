"""Add durable bulk-supervised evaluation runs and verification provenance.

Revision ID: 0026_bulk_supervised_evaluation
Revises: 0025_paddle_ocr_model_phase
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0026_bulk_supervised_evaluation"
down_revision = "0025_paddle_ocr_model_phase"
branch_labels = None
depends_on = None


RUN_STATUSES = (
    "'preflighting', 'queued', 'mapping', 'transcribing', 'grading', "
    "'review_ready', 'completed_with_exceptions', 'completed', 'stopping', "
    "'stopped', 'paused', 'failed'"
)


def upgrade() -> None:
    op.drop_constraint("ck_grading_runs_mode", "grading_runs", type_="check")
    op.create_check_constraint(
        "ck_grading_runs_mode",
        "grading_runs",
        "mode in ('custom_controlled', 'semi_automated', 'bulk_supervised')",
    )

    op.create_table(
        "bulk_evaluation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grading_run_id",
            sa.Integer(),
            sa.ForeignKey("grading_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_teacher_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("marking_policy", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reference_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("review_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "import_manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("authorized_call_limit", sa.Integer(), nullable=False),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_submissions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clean_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exception_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            f"status in ({RUN_STATUSES})", name="ck_bulk_evaluation_runs_status"
        ),
        sa.CheckConstraint(
            "stage in ('ingestion', 'mapping', 'evidence_verification', "
            "'transcription', 'grading', 'review', 'complete')",
            name="ck_bulk_evaluation_runs_stage",
        ),
        sa.CheckConstraint(
            "authorized_call_limit >= 1 and authorized_call_limit <= 2000",
            name="ck_bulk_evaluation_runs_call_limit",
        ),
        sa.CheckConstraint(
            "calls_used >= 0 and calls_used <= authorized_call_limit",
            name="ck_bulk_evaluation_runs_calls_used",
        ),
    )
    op.create_index(
        "ix_bulk_evaluation_runs_assessment_id", "bulk_evaluation_runs", ["assessment_id"]
    )
    op.create_index(
        "ix_bulk_evaluation_runs_grading_run_id", "bulk_evaluation_runs", ["grading_run_id"]
    )
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

    op.create_table(
        "bulk_evaluation_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("bulk_evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submission_id",
            sa.Integer(),
            sa.ForeignKey("submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("answer_region_mappings.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "answer_region_id",
            sa.Integer(),
            sa.ForeignKey("answer_regions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "transcription_run_id",
            sa.Integer(),
            sa.ForeignKey("answer_region_ocr_runs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "grading_job_id",
            sa.Integer(),
            sa.ForeignKey("grading_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "grade_suggestion_id",
            sa.Integer(),
            sa.ForeignKey("grade_suggestions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "final_grade_id",
            sa.Integer(),
            sa.ForeignKey("final_grades.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("verification_source", sa.String(length=32), nullable=True),
        sa.Column("mapping_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("transcription_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("grading_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("evidence_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("rubric_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "exception_codes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("provider_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'clean', 'exception', 'uncertain', "
            "'graded', 'approved', 'stopped')",
            name="ck_bulk_evaluation_items_status",
        ),
        sa.CheckConstraint(
            "stage in ('mapping', 'transcription', 'grading', 'review', 'complete')",
            name="ck_bulk_evaluation_items_stage",
        ),
        sa.UniqueConstraint(
            "run_id", "submission_id", "question_id", name="uq_bulk_item_run_submission_question"
        ),
    )
    op.create_index("ix_bulk_evaluation_items_run_id", "bulk_evaluation_items", ["run_id"])
    op.create_index(
        "ix_bulk_evaluation_items_submission_id", "bulk_evaluation_items", ["submission_id"]
    )
    op.create_index(
        "ix_bulk_evaluation_items_question_id", "bulk_evaluation_items", ["question_id"]
    )
    op.create_index(
        "ix_bulk_evaluation_items_answer_region_id",
        "bulk_evaluation_items",
        ["answer_region_id"],
    )

    op.add_column(
        "answer_region_mappings",
        sa.Column("bulk_policy_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "answer_region_mappings",
        sa.Column(
            "bulk_verification_run_id",
            sa.Integer(),
            sa.ForeignKey("bulk_evaluation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "answer_regions",
        sa.Column("full_answer_verification_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "answer_regions",
        sa.Column(
            "bulk_verification_run_id",
            sa.Integer(),
            sa.ForeignKey("bulk_evaluation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column("verification_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "answer_region_ocr_runs",
        sa.Column(
            "bulk_verification_run_id",
            sa.Integer(),
            sa.ForeignKey("bulk_evaluation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("answer_region_ocr_runs", "bulk_verification_run_id")
    op.drop_column("answer_region_ocr_runs", "verification_source")
    op.drop_column("answer_regions", "bulk_verification_run_id")
    op.drop_column("answer_regions", "full_answer_verification_source")
    op.drop_column("answer_region_mappings", "bulk_verification_run_id")
    op.drop_column("answer_region_mappings", "bulk_policy_verified")
    op.drop_index("ix_bulk_evaluation_items_answer_region_id", table_name="bulk_evaluation_items")
    op.drop_index("ix_bulk_evaluation_items_question_id", table_name="bulk_evaluation_items")
    op.drop_index("ix_bulk_evaluation_items_submission_id", table_name="bulk_evaluation_items")
    op.drop_index("ix_bulk_evaluation_items_run_id", table_name="bulk_evaluation_items")
    op.drop_table("bulk_evaluation_items")
    op.drop_index("ux_bulk_evaluation_runs_active_archive", table_name="bulk_evaluation_runs")
    op.drop_index("ix_bulk_evaluation_runs_grading_run_id", table_name="bulk_evaluation_runs")
    op.drop_index("ix_bulk_evaluation_runs_assessment_id", table_name="bulk_evaluation_runs")
    op.drop_table("bulk_evaluation_runs")
    op.drop_constraint("ck_grading_runs_mode", "grading_runs", type_="check")
    op.create_check_constraint(
        "ck_grading_runs_mode",
        "grading_runs",
        "mode in ('custom_controlled', 'semi_automated')",
    )
