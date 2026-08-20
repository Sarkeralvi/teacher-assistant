from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    evidence_prep_runs: Mapped[list[BatchEvidencePrepRun]] = relationship(
        back_populates="created_by_teacher"
    )
    grading_queue_runs: Mapped[list[GradingQueueRun]] = relationship(
        back_populates="created_by_teacher"
    )
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
    evidence_prep_runs: Mapped[list[BatchEvidencePrepRun]] = relationship(
        back_populates="assessment"
    )
    grading_queue_runs: Mapped[list[GradingQueueRun]] = relationship(back_populates="assessment")
    question_import_jobs: Mapped[list[QuestionImportJob]] = relationship(
        back_populates="assessment"
    )
    extraction_runs: Mapped[list[ExtractionRun]] = relationship(back_populates="assessment")
    question_nodes: Mapped[list[QuestionNode]] = relationship(back_populates="assessment")
    rubric_extraction_criteria: Mapped[list[RubricExtractionCriterion]] = relationship(
        back_populates="assessment"
    )
    answer_region_mappings: Mapped[list[AnswerRegionMapping]] = relationship(
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
        CheckConstraint(
            "reference_extraction_status in "
            "('not_started', 'queued', 'running', 'succeeded', 'failed')",
            name="ck_grading_runs_reference_extraction_status",
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
    question_pdf_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    solution_pdf_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rubric_pdf_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    materials_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    questions_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rubrics_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reference_extraction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_started"
    )
    reference_extraction_stage: Mapped[str] = mapped_column(
        String(64), nullable=False, default="not_started"
    )
    reference_extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_extraction_warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    reference_material_hashes: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reference_question_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    reference_rubric_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="SET NULL"), nullable=True
    )
    reference_ocr_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reference_qwen_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reference_extraction_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reference_extraction_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="grading_runs")
    created_by_teacher: Mapped[User] = relationship(back_populates="grading_runs")


class BatchEvidencePrepRun(TimestampMixin, Base):
    __tablename__ = "batch_evidence_prep_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'running', 'completed', 'completed_with_blockers', 'failed')",
            name="ck_batch_evidence_prep_runs_status",
        ),
        Index("ix_batch_evidence_prep_runs_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    created_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    total_submissions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_expected_packets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ready_packet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_packet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_packet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blank_packet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial_packet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="evidence_prep_runs")
    created_by_teacher: Mapped[User] = relationship(back_populates="evidence_prep_runs")
    grading_queue_runs: Mapped[list[GradingQueueRun]] = relationship(
        back_populates="evidence_prep_run"
    )


class GradingQueueRun(TimestampMixin, Base):
    __tablename__ = "grading_queue_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'built', 'blocked', 'failed')",
            name="ck_grading_queue_runs_status",
        ),
        Index("ix_grading_queue_runs_assessment_id", "assessment_id"),
        Index("ix_grading_queue_runs_evidence_prep_run_id", "evidence_prep_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    evidence_prep_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("batch_evidence_prep_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    total_candidate_packets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refused_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="grading_queue_runs")
    evidence_prep_run: Mapped[BatchEvidencePrepRun | None] = relationship(
        back_populates="grading_queue_runs"
    )
    created_by_teacher: Mapped[User] = relationship(back_populates="grading_queue_runs")
    items: Mapped[list[GradingQueueItem]] = relationship(
        back_populates="queue_run",
        cascade="all, delete-orphan",
        order_by="GradingQueueItem.id",
    )


class GradingQueueItem(TimestampMixin, Base):
    __tablename__ = "grading_queue_items"
    __table_args__ = (
        CheckConstraint(
            "queue_status in ('pending_review', 'ready_for_provider_later', 'blocked')",
            name="ck_grading_queue_items_status",
        ),
        Index("ix_grading_queue_items_queue_run_id", "queue_run_id"),
        Index("ix_grading_queue_items_answer_region_id", "answer_region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue_run_id: Mapped[int] = mapped_column(
        ForeignKey("grading_queue_runs.id", ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    student_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    grading_unit_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    grading_unit_label: Mapped[str] = mapped_column(String(64), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_covered: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    continuation_check_status: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending_review")
    provider_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_snapshot_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    readiness_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    queue_run: Mapped[GradingQueueRun] = relationship(back_populates="items")


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


class ExtractionRun(TimestampMixin, Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint(
            "extraction_type in ('question_paper', 'rubric')",
            name="ck_extraction_runs_type",
        ),
        CheckConstraint(
            "provider in ('host_bridge_codex', 'mock', 'disabled', 'gemini', "
            "'local_paddle_qwen', 'llama_cpp_qwen38')",
            name="ck_extraction_runs_provider",
        ),
        CheckConstraint(
            "status in ('pending', 'succeeded', 'failed', 'blocked')",
            name="ck_extraction_runs_status",
        ),
        Index("ix_extraction_runs_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    artifact_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    extraction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    blockers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped[Assessment] = relationship(back_populates="extraction_runs")
    question_nodes: Mapped[list[QuestionNode]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan"
    )
    rubric_criteria: Mapped[list[RubricExtractionCriterion]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan"
    )


class QuestionNode(TimestampMixin, Base):
    __tablename__ = "question_nodes"
    __table_args__ = (
        CheckConstraint(
            "node_type in ('question', 'subquestion', 'instruction')",
            name="ck_question_nodes_type",
        ),
        Index("ix_question_nodes_assessment_id", "assessment_id"),
        Index("ix_question_nodes_extraction_run_id", "extraction_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    extraction_run_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    question_number: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_question_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    marks: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    teacher_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="question_nodes")
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="question_nodes")


class RubricExtractionCriterion(TimestampMixin, Base):
    __tablename__ = "rubric_extraction_criteria"
    __table_args__ = (
        Index("ix_rubric_extraction_criteria_assessment_id", "assessment_id"),
        Index("ix_rubric_extraction_criteria_extraction_run_id", "extraction_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    extraction_run_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    question_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criterion_label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    max_marks: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    teacher_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="rubric_extraction_criteria")
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="rubric_criteria")


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
    answer_region_mappings: Mapped[list[AnswerRegionMapping]] = relationship(
        back_populates="submission"
    )


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
    question_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("question_nodes.id", ondelete="SET NULL"), nullable=True
    )
    page_id: Mapped[int] = mapped_column(
        ForeignKey("submission_pages.id", ondelete="CASCADE"), nullable=False
    )
    x: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    y: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    manual_answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_answer_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unconfirmed")
    continuation_check_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="not_checked"
    )

    submission: Mapped[Submission] = relationship(back_populates="answer_regions")
    question: Mapped[Question] = relationship(back_populates="answer_regions")
    question_node: Mapped[QuestionNode | None] = relationship()
    page: Mapped[SubmissionPage] = relationship(back_populates="answer_regions")
    segments: Mapped[list[AnswerRegionSegment]] = relationship(
        back_populates="answer_region",
        cascade="all, delete-orphan",
        order_by="AnswerRegionSegment.order_index",
    )
    grading_jobs: Mapped[list[GradingJob]] = relationship(back_populates="answer_region")
    grade_suggestions: Mapped[list[GradeSuggestion]] = relationship(back_populates="answer_region")
    final_grades: Mapped[list[FinalGrade]] = relationship(back_populates="answer_region")
    mapping_links: Mapped[list[AnswerRegionMapping]] = relationship(back_populates="answer_region")
    ocr_runs: Mapped[list[AnswerRegionOcrRun]] = relationship(
        back_populates="answer_region",
        cascade="all, delete-orphan",
        order_by="AnswerRegionOcrRun.id",
    )


class AnswerRegionOcrRun(TimestampMixin, Base):
    __tablename__ = "answer_region_ocr_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed', 'confirmed', "
            "'rejected', 'uncertain')",
            name="ck_answer_region_ocr_runs_status",
        ),
        Index("ix_answer_region_ocr_runs_answer_region_id", "answer_region_id"),
        Index("ix_answer_region_ocr_runs_requested_by_teacher_id", "requested_by_teacher_id"),
        Index("ux_answer_region_ocr_runs_request_id", "request_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    profile: Mapped[str] = mapped_column(String(64), nullable=False, default="baseline")
    task_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy_ocr")
    reasoning_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_image_hashes: Mapped[list[str]] = mapped_column(
        "source_image_hashes_json", JSONB, nullable=False, default=list
    )
    input_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_asset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mmproj_asset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    call_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_set_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    layout_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_result: Mapped[dict[str, Any] | None] = mapped_column(
        "normalized_result_json", JSONB, nullable=True
    )
    warnings: Mapped[list[str]] = mapped_column(
        "warnings_json", JSONB, nullable=False, default=list
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rejection_reason_codes: Mapped[list[str]] = mapped_column(
        "rejection_reason_codes_json", JSONB, nullable=False, default=list
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    answer_region: Mapped[AnswerRegion] = relationship(back_populates="ocr_runs")
    bands: Mapped[list[AnswerRegionOcrBand]] = relationship(
        back_populates="ocr_run",
        cascade="all, delete-orphan",
        order_by="AnswerRegionOcrBand.order_index",
    )


class AnswerRegionOcrBand(TimestampMixin, Base):
    __tablename__ = "answer_region_ocr_bands"
    __table_args__ = (
        UniqueConstraint("ocr_run_id", "order_index", name="uq_ocr_band_run_order"),
        CheckConstraint("classification in ('text', 'formula')", name="ck_ocr_band_class"),
        Index("ix_answer_region_ocr_bands_run_id", "ocr_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ocr_run_id: Mapped[int] = mapped_column(
        ForeignKey("answer_region_ocr_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("answer_region_segments.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    y: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)

    ocr_run: Mapped[AnswerRegionOcrRun] = relationship(back_populates="bands")
    candidates: Mapped[list[AnswerRegionOcrCandidate]] = relationship(
        back_populates="band",
        cascade="all, delete-orphan",
        order_by="AnswerRegionOcrCandidate.id",
    )


class AnswerRegionOcrCandidate(TimestampMixin, Base):
    __tablename__ = "answer_region_ocr_candidates"
    __table_args__ = (
        CheckConstraint(
            "engine in ('ppocr_v6', 'paddleocr_vl', 'paddle_ensemble')",
            name="ck_ocr_candidate_engine",
        ),
        Index("ix_answer_region_ocr_candidates_band_id", "band_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    band_id: Mapped[int] = mapped_column(
        ForeignKey("answer_region_ocr_bands.id", ondelete="CASCADE"), nullable=False
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_label: Mapped[str] = mapped_column(String(32), nullable=False)
    preprocessing_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        "warnings_json", JSONB, nullable=False, default=list
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    band: Mapped[AnswerRegionOcrBand] = relationship(back_populates="candidates")


class LocalModelLease(TimestampMixin, Base):
    """Ownership of the single local model slot.

    Qwen3.6 and Qwen3.8 cannot both be resident in 12 GB of VRAM, so switching
    phases unloads whichever model is running. Without an owner, one job can
    switch the model out from under another that is mid-call. One row per
    ``lease_key``; the unique constraint is what makes it single-holder.
    A held row always carries ``acquired_at`` and ``expires_at`` so a lease
    orphaned by a crashed holder can be reclaimed on expiry rather than
    deadlocking the slot forever.
    """

    __tablename__ = "local_model_leases"
    __table_args__ = (
        CheckConstraint(
            "model_phase is null or model_phase in ('Qwen', 'Qwen38')",
            name="ck_local_model_lease_phase",
        ),
        CheckConstraint(
            "holder_id is null or (acquired_at is not null and expires_at is not null)",
            name="ck_local_model_lease_held_rows_are_complete",
        ),
        UniqueConstraint("lease_key", name="uq_local_model_lease_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lease_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    holder_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    holder_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferencePageOcrRun(TimestampMixin, Base):
    """Per-page provenance for one reference page's reading.

    A confidence-gated escalation decision is only auditable if the inputs to it
    are recorded: which engine read the page, at what render DPI, over which
    exact image bytes, what confidence it reported, which triggers fired, and
    whether the vision model was spent on it.
    """

    __tablename__ = "reference_page_ocr_runs"
    __table_args__ = (
        CheckConstraint(
            "document_role in ('question_paper', 'solution', 'rubric')",
            name="ck_reference_page_ocr_role",
        ),
        CheckConstraint(
            "decision in ('tier1_accepted', 'escalated_regions', 'escalated_page', 'failed')",
            name="ck_reference_page_ocr_decision",
        ),
        CheckConstraint("page_no > 0", name="ck_reference_page_ocr_page_no"),
        CheckConstraint("render_dpi > 0", name="ck_reference_page_ocr_render_dpi"),
        UniqueConstraint(
            "grading_run_id",
            "document_role",
            "page_no",
            name="uq_reference_page_ocr_run_page",
        ),
        Index("ix_reference_page_ocr_runs_grading_run_id", "grading_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grading_run_id: Mapped[int] = mapped_column(
        ForeignKey("grading_runs.id", ondelete="CASCADE"), nullable=False
    )
    document_role: Mapped[str] = mapped_column(String(32), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    render_dpi: Mapped[int] = mapped_column(Integer, nullable=False)
    page_image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_model_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(
        "reason_codes_json", JSONB, nullable=False, default=list
    )
    lines: Mapped[list[dict[str, Any]]] = mapped_column(
        "lines_json", JSONB, nullable=False, default=list
    )
    min_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    mean_confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    uncovered_ink_ratio: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vision_model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vision_image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vision_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vision_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vision_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnswerRegionSegment(TimestampMixin, Base):
    __tablename__ = "answer_region_segments"
    __table_args__ = (
        CheckConstraint(
            "source in ('manual', 'suggestion', 'imported')",
            name="ck_answer_region_segments_source",
        ),
        Index("ix_answer_region_segments_answer_region_id", "answer_region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    submission_page_id: Mapped[int] = mapped_column(
        ForeignKey("submission_pages.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    x: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    y: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    answer_region: Mapped[AnswerRegion] = relationship(back_populates="segments")
    page: Mapped[SubmissionPage] = relationship()

    @property
    def page_id(self) -> int:
        return self.submission_page_id


class AnswerRegionMapping(TimestampMixin, Base):
    __tablename__ = "answer_region_mappings"
    __table_args__ = (
        CheckConstraint(
            "mapping_status in ('mapped', 'uncertain', 'blocked', 'teacher_confirmed')",
            name="ck_answer_region_mappings_status",
        ),
        Index("ix_answer_region_mappings_assessment_id", "assessment_id"),
        Index("ix_answer_region_mappings_submission_id", "submission_id"),
        Index("ix_answer_region_mappings_question_node_id", "question_node_id"),
        Index(
            "ux_answer_region_mappings_submission_question_node",
            "submission_id",
            "question_node_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    question_node_id: Mapped[int] = mapped_column(
        ForeignKey("question_nodes.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), nullable=True
    )
    answer_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="SET NULL"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked")
    blocker_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="deterministic_layout"
    )
    teacher_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="answer_region_mappings")
    submission: Mapped[Submission] = relationship(back_populates="answer_region_mappings")
    question_node: Mapped[QuestionNode] = relationship()
    question: Mapped[Question | None] = relationship()
    answer_region: Mapped[AnswerRegion | None] = relationship(back_populates="mapping_links")


class GradingJob(Base):
    __tablename__ = "grading_jobs"
    __table_args__ = (
        Index(
            "ux_grading_jobs_active_answer_region",
            "answer_region_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
        ),
    )

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
        UniqueConstraint("grading_job_id", name="uq_grade_suggestions_grading_job_id"),
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
    rubric_id: Mapped[int | None] = mapped_column(
        ForeignKey("rubrics.id", ondelete="SET NULL"), nullable=True
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


class GradingDispatchRun(TimestampMixin, Base):
    __tablename__ = "grading_dispatch_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'stopping', 'stopped', 'completed', 'failed')",
            name="ck_grading_dispatch_runs_status",
        ),
        CheckConstraint(
            "marking_policy in ('tough', 'general', 'easy')",
            name="ck_grading_dispatch_runs_marking_policy",
        ),
        CheckConstraint(
            "maximum_calls >= 1 and maximum_calls <= 25",
            name="ck_grading_dispatch_runs_maximum_calls",
        ),
        Index("ix_grading_dispatch_runs_queue_run_id", "queue_run_id"),
        Index("ix_grading_dispatch_runs_grading_run_id", "grading_run_id"),
        Index("ix_grading_dispatch_runs_assessment_question", "assessment_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue_run_id: Mapped[int] = mapped_column(
        ForeignKey("grading_queue_runs.id", ondelete="CASCADE"), nullable=False
    )
    grading_run_id: Mapped[int] = mapped_column(
        ForeignKey("grading_runs.id", ondelete="CASCADE"), nullable=False
    )
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    created_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    marking_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    maximum_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_only_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refused_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uncertain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_started: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[GradingDispatchItem]] = relationship(
        back_populates="dispatch_run",
        cascade="all, delete-orphan",
        order_by="GradingDispatchItem.id",
    )


class GradingDispatchItem(TimestampMixin, Base):
    __tablename__ = "grading_dispatch_items"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'running', 'succeeded', 'failed', 'refused', "
            "'skipped', 'uncertain')",
            name="ck_grading_dispatch_items_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 and attempt_count <= 1",
            name="ck_grading_dispatch_items_attempt_count",
        ),
        UniqueConstraint(
            "dispatch_run_id",
            "queue_item_id",
            name="uq_grading_dispatch_items_run_queue_item",
        ),
        UniqueConstraint("grading_job_id", name="uq_grading_dispatch_items_grading_job_id"),
        Index("ix_grading_dispatch_items_dispatch_run_id", "dispatch_run_id"),
        Index("ix_grading_dispatch_items_answer_region_id", "answer_region_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispatch_run_id: Mapped[int] = mapped_column(
        ForeignKey("grading_dispatch_runs.id", ondelete="CASCADE"), nullable=False
    )
    queue_item_id: Mapped[int] = mapped_column(
        ForeignKey("grading_queue_items.id", ondelete="CASCADE"), nullable=False
    )
    answer_region_id: Mapped[int] = mapped_column(
        ForeignKey("answer_regions.id", ondelete="CASCADE"), nullable=False
    )
    grading_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("grading_jobs.id", ondelete="SET NULL"), nullable=True
    )
    rubric_id: Mapped[int] = mapped_column(
        ForeignKey("rubrics.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    rubric_snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dispatch_run: Mapped[GradingDispatchRun] = relationship(back_populates="items")


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
