"""Allow gemini as an extraction run provider.

Revision ID: 0016_extraction_provider_gemini
Revises: 0015_answer_region_mapping
Create Date: 2026-07-20
"""

from alembic import op

revision = "0016_extraction_provider_gemini"
down_revision = "0015_answer_region_mapping"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_extraction_runs_provider"
_TABLE = "extraction_runs"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "provider in ('host_bridge_codex', 'mock', 'disabled', 'gemini')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "provider in ('host_bridge_codex', 'mock', 'disabled')",
    )
