"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.CheckConstraint("role in ('teacher', 'admin')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("semester", sa.String(length=64), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_teacher_id", "courses", ["teacher_id"])

    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("assessment_type", sa.String(length=64), nullable=False),
        sa.Column("total_marks", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.CheckConstraint(
            "status in ('draft', 'ready', 'open', 'closed', 'archived')",
            name="ck_assessments_status",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessments_course_id", "assessments", ["course_id"])

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("question_no", sa.String(length=32), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("model_answer", sa.Text(), nullable=True),
        sa.Column("total_marks", sa.Numeric(10, 2), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_assessment_id", "questions", ["assessment_id"])

    op.create_table(
        "rubrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rubric_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rubrics_question_id", "rubrics", ["question_id"])

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("student_identifier", sa.String(length=128), nullable=False),
        sa.Column("student_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.CheckConstraint(
            "status in ('uploaded', 'processing', 'ready', 'graded', 'error')",
            name="ck_submissions_status",
        ),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_submissions_assessment_id", "submissions", ["assessment_id"])

    op.create_table(
        "submission_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        sa.Column("quality_score", sa.Numeric(5, 4), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "answer_regions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("x", sa.Numeric(12, 2), nullable=False),
        sa.Column("y", sa.Numeric(12, 2), nullable=False),
        sa.Column("width", sa.Numeric(12, 2), nullable=False),
        sa.Column("height", sa.Numeric(12, 2), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["page_id"], ["submission_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answer_regions_question_id", "answer_regions", ["question_id"])

    op.create_table(
        "grading_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("answer_region_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        timestamp_column("created_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["answer_region_id"], ["answer_regions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "grade_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grading_job_id", sa.Integer(), nullable=False),
        sa.Column("answer_region_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("raw_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_score", sa.Numeric(10, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(12, 6), nullable=True),
        timestamp_column("created_at"),
        sa.ForeignKeyConstraint(["answer_region_id"], ["answer_regions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grading_job_id"], ["grading_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_grade_suggestions_answer_region_id", "grade_suggestions", ["answer_region_id"]
    )

    op.create_table(
        "final_grades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("answer_region_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=True),
        sa.Column("final_score", sa.Numeric(10, 2), nullable=False),
        sa.Column("teacher_comment", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.CheckConstraint(
            "approval_status in ('pending', 'approved', 'edited', 'rejected')",
            name="ck_final_grades_approval_status",
        ),
        sa.ForeignKeyConstraint(["answer_region_id"], ["answer_regions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["grade_suggestions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_final_grades_answer_region_id", "final_grades", ["answer_region_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("ix_final_grades_answer_region_id", table_name="final_grades")
    op.drop_table("final_grades")
    op.drop_index("ix_grade_suggestions_answer_region_id", table_name="grade_suggestions")
    op.drop_table("grade_suggestions")
    op.drop_table("grading_jobs")
    op.drop_index("ix_answer_regions_question_id", table_name="answer_regions")
    op.drop_table("answer_regions")
    op.drop_table("submission_pages")
    op.drop_index("ix_submissions_assessment_id", table_name="submissions")
    op.drop_table("submissions")
    op.drop_index("ix_rubrics_question_id", table_name="rubrics")
    op.drop_table("rubrics")
    op.drop_index("ix_questions_assessment_id", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_assessments_course_id", table_name="assessments")
    op.drop_table("assessments")
    op.drop_index("ix_courses_teacher_id", table_name="courses")
    op.drop_table("courses")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
