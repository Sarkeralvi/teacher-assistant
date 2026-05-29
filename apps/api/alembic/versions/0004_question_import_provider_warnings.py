"""add question import provider warnings

Revision ID: 0004_qimport_warn
Revises: 0003_question_import_jobs
Create Date: 2026-05-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_qimport_warn"
down_revision: str | None = "0003_question_import_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "question_import_jobs",
        sa.Column(
            "provider_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("question_import_jobs", "provider_warnings", server_default=None)


def downgrade() -> None:
    op.drop_column("question_import_jobs", "provider_warnings")
