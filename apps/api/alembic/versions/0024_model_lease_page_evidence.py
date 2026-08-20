"""Add the local-model lease and per-page OCR evidence.

Two prerequisites for the tiered OCR pipeline, plus two CHECK constraints that
would otherwise reject its writes:

* ``local_model_leases`` gives the single GPU model slot an owner. Only one of
  Qwen3.6/Qwen3.8 fits in VRAM, and nothing currently stops one job switching
  the model out from under another that is mid-call.
* ``reference_page_ocr_runs`` records per-page provenance. Reference runs store
  aggregate counts only today, which cannot support an auditable
  confidence-based escalation gate.
* ``ck_extraction_runs_provider`` did not permit ``llama_cpp_qwen``, so moving
  correlation onto Qwen3.6 would fail on insert.
* ``ck_ocr_candidate_engine`` permitted only the three retired Paddle engines,
  so no replacement tier-1 engine could persist a candidate.

Revision ID: 0024_model_lease_page_evidence
Revises: 0023_qwen38_visual_preparation

Note: alembic_version.version_num is varchar(32), so a revision id longer than
that fails only after the migration body has already run. Keep ids short.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0024_model_lease_page_evidence"
down_revision = "0023_qwen38_visual_preparation"
branch_labels = None
depends_on = None

_EXTRACTION_PROVIDERS_NEW = (
    "'host_bridge_codex', 'mock', 'disabled', 'gemini', 'local_paddle_qwen', "
    "'llama_cpp_qwen38', 'llama_cpp_qwen'"
)
_EXTRACTION_PROVIDERS_OLD = (
    "'host_bridge_codex', 'mock', 'disabled', 'gemini', 'local_paddle_qwen', "
    "'llama_cpp_qwen38'"
)
# 'paddle_ensemble' and friends stay listed so existing rows remain valid.
_CANDIDATE_ENGINES_NEW = (
    "'ppocr_v6', 'paddleocr_vl', 'paddle_ensemble', 'rapidocr_ppocr', "
    "'tesseract', 'llama_cpp_qwen38'"
)
_CANDIDATE_ENGINES_OLD = "'ppocr_v6', 'paddleocr_vl', 'paddle_ensemble'"


def upgrade() -> None:
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        f"provider in ({_EXTRACTION_PROVIDERS_NEW})",
    )
    op.drop_constraint("ck_ocr_candidate_engine", "answer_region_ocr_candidates", type_="check")
    op.create_check_constraint(
        "ck_ocr_candidate_engine",
        "answer_region_ocr_candidates",
        f"engine in ({_CANDIDATE_ENGINES_NEW})",
    )

    op.create_table(
        "local_model_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        # One row per slot. The unique constraint is what makes the lease
        # single-holder; callers contend on this row rather than on a flag.
        sa.Column("lease_key", sa.String(length=64), nullable=False),
        sa.Column("model_phase", sa.String(length=32), nullable=True),
        sa.Column("holder_kind", sa.String(length=32), nullable=True),
        sa.Column("holder_id", sa.String(length=128), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "model_phase is null or model_phase in ('Qwen', 'Qwen38')",
            name="ck_local_model_lease_phase",
        ),
        sa.CheckConstraint(
            "holder_id is null or (acquired_at is not null and expires_at is not null)",
            name="ck_local_model_lease_held_rows_are_complete",
        ),
        sa.UniqueConstraint("lease_key", name="uq_local_model_lease_key"),
    )

    op.create_table(
        "reference_page_ocr_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "grading_run_id",
            sa.Integer(),
            sa.ForeignKey("grading_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_role", sa.String(length=32), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("render_dpi", sa.Integer(), nullable=False),
        sa.Column("page_image_sha256", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("engine_model_sha256", sa.String(length=64), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column(
            "reason_codes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Per-line bbox/text/score. JSONB rather than a child table so a change
        # of engine does not require a schema change to record what it read.
        sa.Column(
            "lines_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("min_confidence", sa.Numeric(7, 6), nullable=True),
        sa.Column("mean_confidence", sa.Numeric(7, 6), nullable=True),
        sa.Column("uncovered_ink_ratio", sa.Numeric(7, 6), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vision_model_name", sa.String(length=255), nullable=True),
        sa.Column("vision_image_sha256", sa.String(length=64), nullable=True),
        sa.Column("vision_latency_ms", sa.Integer(), nullable=True),
        sa.Column("vision_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("vision_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("text_sha256", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "document_role in ('question_paper', 'solution', 'rubric')",
            name="ck_reference_page_ocr_role",
        ),
        sa.CheckConstraint(
            "decision in ('tier1_accepted', 'escalated_regions', 'escalated_page', 'failed')",
            name="ck_reference_page_ocr_decision",
        ),
        sa.CheckConstraint("page_no > 0", name="ck_reference_page_ocr_page_no"),
        sa.CheckConstraint("render_dpi > 0", name="ck_reference_page_ocr_render_dpi"),
        sa.UniqueConstraint(
            "grading_run_id",
            "document_role",
            "page_no",
            name="uq_reference_page_ocr_run_page",
        ),
    )
    op.create_index(
        "ix_reference_page_ocr_runs_grading_run_id",
        "reference_page_ocr_runs",
        ["grading_run_id"],
    )
    op.alter_column("reference_page_ocr_runs", "reason_codes_json", server_default=None)
    op.alter_column("reference_page_ocr_runs", "lines_json", server_default=None)
    op.alter_column("reference_page_ocr_runs", "escalated", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_reference_page_ocr_runs_grading_run_id", table_name="reference_page_ocr_runs"
    )
    op.drop_table("reference_page_ocr_runs")
    op.drop_table("local_model_leases")
    op.drop_constraint("ck_ocr_candidate_engine", "answer_region_ocr_candidates", type_="check")
    op.create_check_constraint(
        "ck_ocr_candidate_engine",
        "answer_region_ocr_candidates",
        f"engine in ({_CANDIDATE_ENGINES_OLD})",
    )
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        f"provider in ({_EXTRACTION_PROVIDERS_OLD})",
    )
