from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role in ('teacher', 'admin')", name="ck_users_role"),
        Index("ix_users_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="teacher")

    courses: Mapped[list[Course]] = relationship(back_populates="teacher")
    grading_runs: Mapped[list[GradingRun]] = relationship(back_populates="created_by_teacher")
    final_grades: Mapped[list[FinalGrade]] = relationship(back_populates="teacher")


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (Index("ix_courses_teacher_id", "teacher_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    semester: Mapped[str | None] = mapped_column(String(64), nullable=True)

    teacher: Mapped[User] = relationship(back_populates="courses")
    assessments: Mapped[list[Assessment]] = relationship(back_populates="course")


class Assessment(TimestampMixin, Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft', 'ready', 'open', 'closed', 'archived')",
            name="ck_assessments_status",
        ),
        Index("ix_assessments_course_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    assessment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    total_marks: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    course: Mapped[Course] = relationship(back_populates="assessments")
    questions: Mapped[list[Question]] = relationship(back_populates="assessment")
    submissions: Mapped[list[Submission]] = relationship(back_populates="assessment")
    grading_runs: Mapped[list[GradingRun]] = relationship(back_populates="assessment")
    question_import_jobs: Mapped[list[QuestionImportJob]] = relationship(
        back_populates="assessment"
    )


class GradingRun(TimestampMixin, Base):
    __tablename__ = "grading_runs"
    __table_args__ = (
        CheckConstraint(
            "mode in ('custom_controlled', 'semi_automated')",
            name="ck_grading_runs_mode",
        ),
        CheckConstraint(
            "status in ("
            "'draft', 'materials_uploaded', 'questions_ready', 'scripts_uploaded', "
            "'regions_ready', 'grading_ready', 'review_ready', 'completed'"
            ")",
            name="ck_grading_runs_status",
        ),
        CheckConstraint(
            "marking_policy in ('tough', 'general', 'easy')",
            name="ck_grading_runs_marking_policy",
        ),
        Index("ix_grading_runs_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    created_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(64), nullable=False, default="custom_controlled")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    marking_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="general")
    question_pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    solution_pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    rubric_pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    materials_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    questions_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rubrics_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="grading_runs")
    created_by_teacher: Mapped[User] = relationship(back_populates="grading_runs")


class QuestionImportJob(TimestampMixin, Base):
    __tablename__ = "question_import_jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('uploaded', 'drafted', 'accepted', 'failed')",
            name="ck_question_import_jobs_status",
        ),
        Index("ix_question_import_jobs_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False, default="mock")
    draft_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    provider_warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="question_import_jobs")


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_assessment_id", "assessment_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    question_no: Mapped[str] = mapped_column(String(32), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_marks: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    assessment: Mapped[Assessment] = relationship(back_populates="questions")
    rubrics: Mapped[list[Rubric]] = relationship(back_populates="question")
    answer_regions: Mapped[list[AnswerRegion]] = relationship(back_populates="question")
    grade_suggestions: Mapped[list[GradeSuggestion]] = relationship(back_populates="question")


class Rubric(TimestampMixin, Base):
    __tablename__ = "rubrics"
    __table_args__ = (Index("ix_rubrics_question_id", "question_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    question: Mapped[Question] = relationship(back_populates="rubrics")


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        CheckConstraint(
            "status in ('uploaded', 'processing', 'ready', 'graded', 'error')",
            name="ck_submissions_status",
        ),
        Index("ix_submissions_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    student_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    student_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")

    assessment: Mapped[Assessment] = relationship(back_populates="submissions")
    pages: Mapped[list[SubmissionPage]] = relationship(back_populates="submission")
    answer_regions: Mapped[list[AnswerRegion]] = relationship(back_populates="submission")


class SubmissionPage(TimestampMixin, Base):
    __tablename__ = "submission_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="pages")
    answer_regions: Mapped[list[AnswerRegion]] = relationship(back_populates="page")


class AnswerRegion(TimestampMixin, Base):
    __tablename__ = "answer_regions"
    __table_args__ = (Index("ix_answer_regions_question_id", "question_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    page_id: Mapped[int] = mapped_column(
        ForeignKey("submission_pages.id", ondelete="CASCADE"), nullable=False
    )
    x: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    y: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    submission: Mapped[Submission] = relationship(back_populates="answer_regions")
    question: Mapped[Question] = relationship(back_populates="answer_regions")
    page: Mapped[SubmissionPage] = relationship(back_populates="answer_regions")
    grading_jobs: Mapped[list[GradingJob]] = relationship(back_populates="answer_region")
    grade_suggestions: Mapped[list[GradeSuggestion]] = relationship(back_populates="answer_region")
    final_grades: Mapped[list[FinalGrade]] = relationship(back_populates="answer_region")


class GradingJob(Base):
    __tablename__ = "grading_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    answer_region: Mapped[AnswerRegion] = relationship(back_populates="grading_jobs")
    grade_suggestions: Mapped[list[GradeSuggestion]] = relationship(back_populates="grading_job")


class GradeSuggestion(Base):
    __tablename__ = "grade_suggestions"
    __table_args__ = (
        CheckConstraint(
            "marking_policy in ('tough', 'general', 'easy')",
            name="ck_grade_suggestions_marking_policy",
        ),
        Index("ix_grade_suggestions_answer_region_id", "answer_region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grading_job_id: Mapped[int] = mapped_column(
        ForeignKey("grading_jobs.id", ondelete="CASCADE"), nullable=False
    )
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    model_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    marking_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="general")
    raw_response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    needs_review: Mapped[bool] = mapped_column(nullable=False, default=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    grading_job: Mapped[GradingJob] = relationship(back_populates="grade_suggestions")
    answer_region: Mapped[AnswerRegion] = relationship(back_populates="grade_suggestions")
    question: Mapped[Question] = relationship(back_populates="grade_suggestions")
    final_grades: Mapped[list[FinalGrade]] = relationship(back_populates="suggestion")


class FinalGrade(TimestampMixin, Base):
    __tablename__ = "final_grades"
    __table_args__ = (
        CheckConstraint(
            "approval_status in ('pending', 'approved', 'edited', 'rejected')",
            name="ck_final_grades_approval_status",
        ),
        Index("ix_final_grades_answer_region_id", "answer_region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("grade_suggestions.id", ondelete="SET NULL"), nullable=True
    )
    final_score: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    teacher_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    answer_region: Mapped[AnswerRegion] = relationship(back_populates="final_grades")
    teacher: Mapped[User] = relationship(back_populates="final_grades")
    suggestion: Mapped[GradeSuggestion | None] = relationship(back_populates="final_grades")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
