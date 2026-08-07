from decimal import Decimal

from sqlalchemy import ForeignKeyConstraint, Index, Numeric
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    BatchEvidencePrepRun,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    GradingRun,
    Question,
    QuestionImportJob,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)

EXPECTED_TABLES = {
    "users",
    "courses",
    "assessments",
    "questions",
    "question_import_jobs",
    "grading_runs",
    "batch_evidence_prep_runs",
    "grading_queue_runs",
    "grading_queue_items",
    "rubrics",
    "submissions",
    "submission_pages",
    "answer_regions",
    "answer_region_segments",
    "answer_region_mappings",
    "grading_jobs",
    "grade_suggestions",
    "final_grades",
    "audit_logs",
}

EXPECTED_COLUMNS = {
    "users": {
        "id",
        "name",
        "email",
        "password_hash",
        "role",
        "created_at",
        "updated_at",
    },
    "courses": {
        "id",
        "teacher_id",
        "code",
        "title",
        "department",
        "semester",
        "created_at",
        "updated_at",
    },
    "assessments": {
        "id",
        "course_id",
        "title",
        "assessment_type",
        "total_marks",
        "status",
        "created_at",
        "updated_at",
    },
    "questions": {
        "id",
        "assessment_id",
        "question_no",
        "question_text",
        "model_answer",
        "total_marks",
        "created_at",
        "updated_at",
    },
    "question_import_jobs": {
        "id",
        "assessment_id",
        "status",
        "original_filename",
        "content_type",
        "file_path",
        "provider",
        "draft_questions",
        "provider_warnings",
        "error",
        "created_at",
        "updated_at",
    },
    "grading_runs": {
        "id",
        "assessment_id",
        "created_by_teacher_id",
        "mode",
        "status",
        "marking_policy",
        "question_pdf_path",
        "solution_pdf_path",
        "rubric_pdf_path",
        "question_pdf_name",
        "solution_pdf_name",
        "rubric_pdf_name",
        "materials_confirmed_at",
        "questions_confirmed_at",
        "rubrics_confirmed_at",
        "reference_extraction_status",
        "reference_extraction_stage",
        "reference_extraction_error",
        "reference_extraction_warnings",
        "reference_material_hashes",
        "reference_question_run_id",
        "reference_rubric_run_id",
        "reference_ocr_call_count",
        "reference_qwen_call_count",
        "reference_extraction_started_at",
        "reference_extraction_completed_at",
        "notes",
        "created_at",
        "updated_at",
    },
    "batch_evidence_prep_runs": {
        "id",
        "assessment_id",
        "created_by_teacher_id",
        "status",
        "total_submissions",
        "total_expected_packets",
        "ready_packet_count",
        "blocked_packet_count",
        "warning_packet_count",
        "blank_packet_count",
        "partial_packet_count",
        "error",
        "created_at",
        "updated_at",
    },
    "grading_queue_runs": {
        "id",
        "assessment_id",
        "evidence_prep_run_id",
        "created_by_teacher_id",
        "status",
        "total_candidate_packets",
        "queued_item_count",
        "refused_item_count",
        "error",
        "created_at",
        "updated_at",
    },
    "grading_queue_items": {
        "id",
        "queue_run_id",
        "assessment_id",
        "submission_id",
        "student_identifier",
        "question_id",
        "grading_unit_id",
        "grading_unit_label",
        "max_marks",
        "answer_region_id",
        "segment_count",
        "pages_covered",
        "evidence_status",
        "continuation_check_status",
        "queue_status",
        "provider_allowed",
        "evidence_snapshot_hash",
        "readiness_snapshot_json",
        "created_at",
        "updated_at",
    },
    "rubrics": {
        "id",
        "question_id",
        "version",
        "rubric_json",
        "is_active",
        "created_at",
        "updated_at",
    },
    "submissions": {
        "id",
        "assessment_id",
        "student_identifier",
        "student_name",
        "status",
        "created_at",
        "updated_at",
    },
    "submission_pages": {
        "id",
        "submission_id",
        "page_no",
        "image_path",
        "quality_score",
        "created_at",
        "updated_at",
    },
    "answer_regions": {
        "id",
        "submission_id",
        "question_id",
        "question_node_id",
        "page_id",
        "x",
        "y",
        "width",
        "height",
        "image_path",
        "manual_answer_text",
        "full_answer_confirmed",
        "evidence_status",
        "continuation_check_status",
        "created_at",
        "updated_at",
    },
    "answer_region_segments": {
        "id",
        "answer_region_id",
        "submission_page_id",
        "order_index",
        "x",
        "y",
        "width",
        "height",
        "image_path",
        "source",
        "confirmed",
        "is_primary",
        "created_at",
        "updated_at",
    },
    "answer_region_mappings": {
        "id",
        "assessment_id",
        "submission_id",
        "question_node_id",
        "question_id",
        "answer_region_id",
        "source_page",
        "source_reference",
        "confidence",
        "mapping_status",
        "blocker_reason",
        "provider",
        "teacher_confirmed",
        "created_at",
        "updated_at",
    },
    "grading_jobs": {
        "id",
        "answer_region_id",
        "status",
        "error",
        "created_at",
        "completed_at",
    },
    "grade_suggestions": {
        "id",
        "grading_job_id",
        "answer_region_id",
        "question_id",
        "rubric_id",
        "model_provider",
        "model_name",
        "prompt_version",
        "marking_policy",
        "raw_response_json",
        "score",
        "max_score",
        "confidence",
        "needs_review",
        "feedback",
        "cost_estimate",
        "created_at",
    },
    "final_grades": {
        "id",
        "answer_region_id",
        "teacher_id",
        "suggestion_id",
        "final_score",
        "teacher_comment",
        "approval_status",
        "created_at",
        "updated_at",
    },
    "audit_logs": {
        "id",
        "actor_type",
        "actor_id",
        "event_type",
        "entity_type",
        "entity_id",
        "payload_json",
        "created_at",
    },
}

EXPECTED_INDEX_COLUMNS = {
    "users": {"email"},
    "courses": {"teacher_id"},
    "assessments": {"course_id"},
    "questions": {"assessment_id"},
    "question_import_jobs": {"assessment_id"},
    "grading_runs": {"assessment_id"},
    "batch_evidence_prep_runs": {"assessment_id"},
    "grading_queue_runs": {"assessment_id", "evidence_prep_run_id"},
    "grading_queue_items": {"queue_run_id", "answer_region_id"},
    "rubrics": {"question_id"},
    "submissions": {"assessment_id"},
    "answer_regions": {"question_id"},
    "answer_region_mappings": {"assessment_id", "submission_id", "question_node_id"},
    "answer_region_segments": {"answer_region_id"},
    "grade_suggestions": {"answer_region_id"},
    "final_grades": {"answer_region_id"},
}


def test_all_required_models_are_registered_with_expected_tables_and_columns() -> None:
    models = [
        User,
        Course,
        Assessment,
        Question,
        QuestionImportJob,
        GradingRun,
        BatchEvidencePrepRun,
        GradingQueueRun,
        GradingQueueItem,
        Rubric,
        Submission,
        SubmissionPage,
        AnswerRegion,
        AnswerRegionSegment,
        AnswerRegionMapping,
        GradingJob,
        GradeSuggestion,
        FinalGrade,
        AuditLog,
    ]

    assert {model.__tablename__ for model in models} <= set(Base.metadata.tables)
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    for table_name, column_names in EXPECTED_COLUMNS.items():
        table_columns = {column.name for column in Base.metadata.tables[table_name].columns}
        assert table_columns == column_names


def test_required_foreign_keys_and_indexes_exist() -> None:
    for table_name in EXPECTED_TABLES - {"users", "audit_logs"}:
        table = Base.metadata.tables[table_name]
        has_foreign_key = any(
            isinstance(constraint, ForeignKeyConstraint) for constraint in table.constraints
        )
        assert has_foreign_key, table_name

    for table_name, expected_columns in EXPECTED_INDEX_COLUMNS.items():
        indexed_columns: set[str] = set()
        table = Base.metadata.tables[table_name]
        for index in table.indexes:
            assert isinstance(index, Index)
            indexed_columns.update(column.name for column in index.columns)
        assert expected_columns <= indexed_columns


def test_numeric_and_json_fields_use_postgresql_friendly_types() -> None:
    numeric_columns = [
        Assessment.total_marks,
        Question.total_marks,
        SubmissionPage.quality_score,
        AnswerRegion.x,
        AnswerRegion.y,
        AnswerRegion.width,
        AnswerRegion.height,
        GradeSuggestion.score,
        GradeSuggestion.max_score,
        GradeSuggestion.confidence,
        GradeSuggestion.cost_estimate,
        FinalGrade.final_score,
        GradingQueueItem.max_marks,
    ]
    for column in numeric_columns:
        assert isinstance(column.property.columns[0].type, Numeric)

    assert isinstance(Rubric.rubric_json.property.columns[0].type, JSONB)
    assert isinstance(QuestionImportJob.draft_questions.property.columns[0].type, JSONB)
    assert isinstance(QuestionImportJob.provider_warnings.property.columns[0].type, JSONB)
    assert isinstance(GradeSuggestion.raw_response_json.property.columns[0].type, JSONB)
    assert isinstance(GradingQueueItem.pages_covered.property.columns[0].type, JSONB)
    assert isinstance(
        GradingQueueItem.readiness_snapshot_json.property.columns[0].type, JSONB
    )
    assert isinstance(AnswerRegionMapping.source_reference.property.columns[0].type, JSONB)
    assert isinstance(AuditLog.payload_json.property.columns[0].type, JSONB)

    suggestion = GradeSuggestion(score=Decimal("8.50"), max_score=Decimal("10.00"))
    assert suggestion.score == Decimal("8.50")
