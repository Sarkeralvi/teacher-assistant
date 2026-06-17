"""add answer region mapping support

Revision ID: 0015_answer_region_mapping
Revises: 0014_doc_extract
Create Date: 2026-06-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015_answer_region_mapping"
down_revision = "0014_doc_extract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "answer_regions",
        sa.Column("question_node_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_answer_regions_question_node_id_question_nodes",
        "answer_regions",
        "question_nodes",
        ["question_node_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "answer_region_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("question_node_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("answer_region_id", sa.Integer(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("mapping_status", sa.String(length=32), nullable=False),
        sa.Column("blocker_reason", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "teacher_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mapping_status in ('mapped', 'uncertain', 'blocked', 'teacher_confirmed')",
            name="ck_answer_region_mappings_status",
        ),
        sa.ForeignKeyConstraint(["answer_region_id"], ["answer_regions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_node_id"], ["question_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_answer_region_mappings_assessment_id", "answer_region_mappings", ["assessment_id"]
    )
    op.create_index(
        "ix_answer_region_mappings_submission_id", "answer_region_mappings", ["submission_id"]
    )
    op.create_index(
        "ix_answer_region_mappings_question_node_id", "answer_region_mappings", ["question_node_id"]
    )
    op.create_index(
        "ux_answer_region_mappings_submission_question_node",
        "answer_region_mappings",
        ["submission_id", "question_node_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_answer_region_mappings_submission_question_node", table_name="answer_region_mappings"
    )
    op.drop_index("ix_answer_region_mappings_question_node_id", table_name="answer_region_mappings")
    op.drop_index("ix_answer_region_mappings_submission_id", table_name="answer_region_mappings")
    op.drop_index("ix_answer_region_mappings_assessment_id", table_name="answer_region_mappings")
    op.drop_table("answer_region_mappings")
    op.drop_constraint(
        "fk_answer_regions_question_node_id_question_nodes", "answer_regions", type_="foreignkey"
    )
    op.drop_column("answer_regions", "question_node_id")
