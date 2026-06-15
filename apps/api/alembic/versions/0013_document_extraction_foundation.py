"""document extraction foundation

Revision ID: 0014_doc_extract
Revises: 0013_manual_answer_text
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_doc_extract"
down_revision: str | None = "0013_manual_answer_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("artifact_file_path", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("extraction_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("normalized_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "blockers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "extraction_type in ('question_paper', 'rubric')",
            name="ck_extraction_runs_type",
        ),
        sa.CheckConstraint(
            "provider in ('host_bridge_codex', 'mock', 'disabled')",
            name="ck_extraction_runs_provider",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'succeeded', 'failed', 'blocked')",
            name="ck_extraction_runs_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("extraction_runs", "blockers", server_default=None)
    op.create_index("ix_extraction_runs_assessment_id", "extraction_runs", ["assessment_id"])

    op.create_table(
        "question_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("extraction_run_id", sa.Integer(), nullable=False),
        sa.Column("question_number", sa.String(length=64), nullable=False),
        sa.Column("parent_question_number", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("marks", sa.Numeric(10, 2), nullable=True),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "teacher_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "node_type in ('question', 'subquestion', 'instruction')",
            name="ck_question_nodes_type",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("question_nodes", "teacher_confirmed", server_default=None)
    op.create_index("ix_question_nodes_assessment_id", "question_nodes", ["assessment_id"])
    op.create_index("ix_question_nodes_extraction_run_id", "question_nodes", ["extraction_run_id"])

    op.create_table(
        "rubric_extraction_criteria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("extraction_run_id", sa.Integer(), nullable=False),
        sa.Column("question_number", sa.String(length=64), nullable=True),
        sa.Column("criterion_label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("max_marks", sa.Numeric(10, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("blocker", sa.Text(), nullable=True),
        sa.Column(
            "teacher_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("rubric_extraction_criteria", "teacher_confirmed", server_default=None)
    op.create_index(
        "ix_rubric_extraction_criteria_assessment_id",
        "rubric_extraction_criteria",
        ["assessment_id"],
    )
    op.create_index(
        "ix_rubric_extraction_criteria_extraction_run_id",
        "rubric_extraction_criteria",
        ["extraction_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rubric_extraction_criteria_extraction_run_id",
        table_name="rubric_extraction_criteria",
    )
    op.drop_index(
        "ix_rubric_extraction_criteria_assessment_id",
        table_name="rubric_extraction_criteria",
    )
    op.drop_table("rubric_extraction_criteria")
    op.drop_index("ix_question_nodes_extraction_run_id", table_name="question_nodes")
    op.drop_index("ix_question_nodes_assessment_id", table_name="question_nodes")
    op.drop_table("question_nodes")
    op.drop_index("ix_extraction_runs_assessment_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
