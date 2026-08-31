"""Allow registered brain providers in extraction provenance.

Revision ID: 0027_universal_brain
Revises: 0026_bulk_supervised_evaluation
"""

from alembic import op

revision = "0027_universal_brain"
down_revision = "0026_bulk_supervised_evaluation"
branch_labels = None
depends_on = None

_LEGACY_EXTRACTION_PROVIDERS = (
    "'host_bridge_codex', 'mock', 'disabled', 'gemini', 'local_paddle_qwen', "
    "'llama_cpp_qwen38', 'llama_cpp_qwen'"
)


def upgrade() -> None:
    # Provider identifiers are application registry keys. A database enum-like
    # CHECK would require a migration for every new provider plugin.
    op.drop_constraint("ck_extraction_runs_provider", "extraction_runs", type_="check")


def downgrade() -> None:
    op.create_check_constraint(
        "ck_extraction_runs_provider",
        "extraction_runs",
        f"provider in ({_LEGACY_EXTRACTION_PROVIDERS})",
    )
