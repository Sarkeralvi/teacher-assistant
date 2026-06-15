from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    role: str = "teacher"


class UserRead(ORMBase):
    id: int
    name: str
    email: str = Field(min_length=3, max_length=320)
    role: str
    created_at: datetime
    updated_at: datetime


class AuthRegister(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=255)
    role: Literal["teacher", "admin"] = "teacher"


class AuthLogin(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=255)


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class CourseCreate(BaseModel):
    teacher_id: int | None = None
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    semester: str | None = Field(default=None, max_length=64)


class CourseUpdate(BaseModel):
    teacher_id: int | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    semester: str | None = Field(default=None, max_length=64)


class CourseRead(ORMBase):
    id: int
    teacher_id: int
    code: str
    title: str
    department: str | None
    semester: str | None
    created_at: datetime
    updated_at: datetime


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    assessment_type: str = Field(min_length=1, max_length=64)
    total_marks: Decimal = Field(gt=Decimal("0"))
    status: str = "draft"


class AssessmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    assessment_type: str | None = Field(default=None, min_length=1, max_length=64)
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    status: str | None = None


class AssessmentRead(ORMBase):
    id: int
    course_id: int
    title: str
    assessment_type: str
    total_marks: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


GradingRunStatus = Literal[
    "draft",
    "materials_uploaded",
    "questions_ready",
    "scripts_uploaded",
    "regions_ready",
    "grading_ready",
    "review_ready",
    "completed",
]
MarkingPolicy = Literal["tough", "general", "easy"]
GradingRunMode = Literal["custom_controlled", "semi_automated", "fully_automated"]


class GradingRunCreate(BaseModel):
    mode: GradingRunMode = "custom_controlled"
    notes: str | None = Field(default=None, max_length=4000)
    marking_policy: MarkingPolicy = "general"


class GradingRunUpdate(BaseModel):
    status: GradingRunStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)
    marking_policy: MarkingPolicy | None = None


class GradingRunWorkflowState(BaseModel):
    materials_uploaded: bool
    materials_confirmed: bool
    question_paper_uploaded: bool
    drafts_created: bool
    drafts_confirmed: bool
    questions_confirmed: bool
    rubrics_confirmed: bool
    scripts_uploaded: bool
    answer_regions_created: bool
    grading_ready: bool
    suggestions_created: bool
    review_ready: bool
    final_grades_created: bool
    export_ready: bool
    question_count: int
    rubric_count: int
    submission_count: int
    submission_page_count: int
    answer_region_count: int
    mapped_question_count: int
    mapped_page_count: int
    mapped_submission_count: int
    unmapped_question_count: int
    unmapped_page_count: int
    unmapped_submission_count: int
    grade_suggestion_count: int
    final_grade_count: int
    blockers: list[str]
    next_actions: list[str]
    derived_status: str


class GradingRunRead(ORMBase):
    id: int
    assessment_id: int
    created_by_teacher_id: int
    mode: GradingRunMode
    status: GradingRunStatus
    marking_policy: MarkingPolicy
    question_pdf_path: str | None
    solution_pdf_path: str | None
    rubric_pdf_path: str | None
    materials_confirmed_at: datetime | None
    questions_confirmed_at: datetime | None
    rubrics_confirmed_at: datetime | None
    notes: str | None
    workflow_state: GradingRunWorkflowState
    created_at: datetime
    updated_at: datetime


BatchEvidencePrepRunStatus = Literal[
    "pending", "running", "completed", "completed_with_blockers", "failed"
]


class BatchEvidencePrepPacketSummary(BaseModel):
    submission_id: int
    student_identifier: str | None
    grading_unit_label: str | None
    max_marks: Decimal | None
    evidence_status: str
    continuation_check_status: str
    ready_for_grading: bool
    quarantined: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    segment_count: int
    pages_covered: list[int] = Field(default_factory=list)
    answer_region_id: int | None = None
    question_id: int | None = None
    correction_target: dict[str, int | str | None] = Field(default_factory=dict)


class BatchEvidencePrepRunRead(ORMBase):
    id: int | None = None
    assessment_id: int
    created_by_teacher_id: int | None = None
    status: BatchEvidencePrepRunStatus
    total_submissions: int
    total_expected_packets: int
    ready_packet_count: int
    blocked_packet_count: int
    warning_packet_count: int
    blank_packet_count: int
    partial_packet_count: int
    packets: list[BatchEvidencePrepPacketSummary] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GradingQueueRunCreate(BaseModel):
    evidence_prep_run_id: int | None = None


GradingQueueRunStatus = Literal["pending", "built", "blocked", "failed"]
GradingQueueItemStatus = Literal["pending_review", "ready_for_provider_later", "blocked"]
GradingQueueItemStaleStatus = Literal["fresh", "stale", "evidence_missing", "blocked_now"]


class GradingQueueItemRead(ORMBase):
    id: int
    queue_run_id: int
    assessment_id: int
    submission_id: int
    student_identifier: str | None
    question_id: int
    grading_unit_id: int
    grading_unit_label: str
    max_marks: Decimal
    answer_region_id: int
    segment_count: int
    pages_covered: list[int] = Field(default_factory=list)
    evidence_status: str
    continuation_check_status: str
    queue_status: GradingQueueItemStatus
    provider_allowed: bool
    evidence_snapshot_hash: str | None
    readiness_snapshot_json: dict[str, Any]
    stale_status: GradingQueueItemStaleStatus = "fresh"
    current_evidence_snapshot_hash: str | None = None
    current_refusal_reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GradingQueueRefusedItem(BaseModel):
    submission_id: int
    student_identifier: str | None
    question_id: int | None = None
    grading_unit_id: int | None = None
    grading_unit_label: str | None = None
    answer_region_id: int | None = None
    evidence_status: str
    continuation_check_status: str
    segment_count: int
    pages_covered: list[int] = Field(default_factory=list)
    refusal_reasons: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_hash: str | None = None
    readiness_snapshot_json: dict[str, Any]


class GradingQueueRunRead(ORMBase):
    id: int | None = None
    assessment_id: int
    evidence_prep_run_id: int | None = None
    created_by_teacher_id: int | None = None
    status: GradingQueueRunStatus
    total_candidate_packets: int
    queued_item_count: int
    refused_item_count: int
    items: list[GradingQueueItemRead] = Field(default_factory=list)
    refused_items: list[GradingQueueRefusedItem] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QuestionCreate(BaseModel):
    question_no: str = Field(min_length=1, max_length=32)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    total_marks: Decimal = Field(gt=Decimal("0"))


class QuestionUpdate(BaseModel):
    question_no: str | None = Field(default=None, min_length=1, max_length=32)
    question_text: str | None = Field(default=None, min_length=1)
    model_answer: str | None = None
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))


class QuestionRead(ORMBase):
    id: int
    assessment_id: int
    question_no: str
    question_text: str
    model_answer: str | None
    total_marks: Decimal
    created_at: datetime
    updated_at: datetime


class DraftQuestion(BaseModel):
    draft_id: str
    question_no: str = Field(min_length=1, max_length=32)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))
    confidence: Decimal
    source_page: int
    source_text_excerpt: str
    needs_review: bool = True


class QuestionImportJobRead(ORMBase):
    id: int
    assessment_id: int
    status: str
    original_filename: str
    content_type: str
    file_path: str
    provider: str
    draft_questions: list[DraftQuestion]
    provider_warnings: list[str] = Field(default_factory=list)
    error: str | None
    created_at: datetime
    updated_at: datetime


class DraftQuestionAccept(BaseModel):
    draft_id: str
    question_no: str = Field(min_length=1, max_length=32)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    total_marks: Decimal = Field(gt=Decimal("0"))


class QuestionImportAcceptRequest(BaseModel):
    draft_questions: list[DraftQuestionAccept] = Field(min_length=1)


class QuestionImportAcceptResponse(BaseModel):
    job_id: int
    created_count: int
    questions: list[QuestionRead]


class ExtractionRunRead(ORMBase):
    id: int
    assessment_id: int
    artifact_file_path: str
    original_filename: str
    content_type: str
    extraction_type: str
    provider: str
    status: str
    raw_output: str | None
    normalized_output: dict[str, Any] | None
    blockers: list[str] = Field(default_factory=list)
    error: str | None
    created_at: datetime
    updated_at: datetime


class QuestionNodeRead(ORMBase):
    id: int
    assessment_id: int
    extraction_run_id: int
    question_number: str
    parent_question_number: str | None
    label: str
    text: str
    marks: Decimal | None
    node_type: str
    source_page: int | None
    source_reference: dict[str, Any] | None
    confidence: Decimal | None
    teacher_confirmed: bool
    created_at: datetime
    updated_at: datetime


class RubricExtractionCriterionRead(ORMBase):
    id: int
    assessment_id: int
    extraction_run_id: int
    question_number: str | None
    criterion_label: str
    description: str
    max_marks: Decimal | None
    confidence: Decimal | None
    blocker: str | None
    teacher_confirmed: bool
    created_at: datetime
    updated_at: datetime


class RubricCriterionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    max_marks: Decimal

    @model_validator(mode="before")
    @classmethod
    def require_criterion_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Each criterion must be an object")
        for field_name in ("id", "name", "description", "max_marks"):
            if field_name not in data:
                raise ValueError(f"criterion.{field_name} is required")
        return data

    @field_validator("max_marks")
    @classmethod
    def max_marks_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("criterion.max_marks must be positive")
        return value


class RubricJsonSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_marks: Decimal
    criteria: list[RubricCriterionSchema]

    @model_validator(mode="before")
    @classmethod
    def require_rubric_fields_and_reject_ambiguous_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("rubric_json must be an object")
        if "total_marks" not in data:
            raise ValueError("total_marks is required")
        if "criteria" not in data:
            raise ValueError("criteria is required")
        extra_fields = set(data) - {"total_marks", "criteria"}
        if extra_fields:
            extra_list = ", ".join(sorted(extra_fields))
            raise ValueError(
                f"rubric_json may only include total_marks and criteria; remove: {extra_list}"
            )
        return data

    @field_validator("total_marks")
    @classmethod
    def total_marks_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("rubric_json.total_marks must be positive")
        return value

    @field_validator("criteria")
    @classmethod
    def criteria_must_be_non_empty(
        cls, value: list[RubricCriterionSchema]
    ) -> list[RubricCriterionSchema]:
        if not value:
            raise ValueError("criteria must be a non-empty array")
        ids = [criterion.id for criterion in value]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion.id must be unique within the rubric")
        return value

    @model_validator(mode="after")
    def criteria_sum_must_equal_total_marks(self) -> "RubricJsonSchema":
        marks_sum = sum((criterion.max_marks for criterion in self.criteria), Decimal("0"))
        if marks_sum != self.total_marks:
            raise ValueError("Sum of criterion.max_marks must equal rubric_json.total_marks")
        return self


def validate_rubric_json_schema(rubric_json: Any) -> RubricJsonSchema:
    try:
        return RubricJsonSchema.model_validate(rubric_json)
    except ValidationError as exc:
        messages = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()]
        raise ValueError("; ".join(messages)) from exc


class RubricCreate(BaseModel):
    version: int = Field(ge=1)
    rubric_json: dict[str, Any]
    is_active: bool = True


class RubricUpdate(BaseModel):
    version: int | None = Field(default=None, ge=1)
    rubric_json: dict[str, Any] | None = None
    is_active: bool | None = None


class RubricRead(ORMBase):
    id: int
    question_id: int
    version: int
    rubric_json: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubmissionPageRead(ORMBase):
    id: int
    submission_id: int
    page_no: int
    image_path: str
    quality_score: Decimal | None
    created_at: datetime
    updated_at: datetime


class SubmissionRead(ORMBase):
    id: int
    assessment_id: int
    student_identifier: str
    student_name: str | None
    status: str
    pages: list[SubmissionPageRead]
    created_at: datetime
    updated_at: datetime


class SubmissionZipUploadResponse(BaseModel):
    assessment_id: int
    requested_file_count: int
    imported_count: int
    skipped_count: int
    failed_count: int
    submissions_created: list[SubmissionRead]
    errors: list[str]
    warnings: list[str]


class AnswerRegionCreate(BaseModel):
    question_id: int
    x: Decimal = Field(ge=Decimal("0"))
    y: Decimal = Field(ge=Decimal("0"))
    width: Decimal = Field(gt=Decimal("0"))
    height: Decimal = Field(gt=Decimal("0"))
    manual_answer_text: str | None = Field(default=None, max_length=10000)


AnswerRegionMappingProvider: TypeAlias = Literal[
    "mock",
    "deterministic_layout",
    "codex_cli_answer_region_suggester",
    "codex_cli",
]
AnswerRegionContinuationRisk: TypeAlias = Literal[
    "none",
    "possible_continuation",
    "continuation_included",
    "continuation_not_needed",
    "ambiguous",
]
MappingDeterministicCase: TypeAlias = Literal[
    "single_segment",
    "multi_segment_continuation",
    "possible_continuation",
]


class AnswerRegionSuggestionRequest(BaseModel):
    provider: Literal["mock", "codex_cli_answer_region_suggester", "codex_cli"] | None = None
    question_ids: list[int] | None = None
    question_nos: list[str] | None = None


class AnswerRegionMappingSuggestionRequest(BaseModel):
    provider: AnswerRegionMappingProvider | None = "mock"
    question_ids: list[int] | None = None
    question_nos: list[str] | None = None
    page_ids: list[int] | None = None
    deterministic_case: MappingDeterministicCase = "single_segment"


class AnswerRegionSegmentCreate(BaseModel):
    page_id: int
    x: Decimal = Field(ge=Decimal("0"))
    y: Decimal = Field(ge=Decimal("0"))
    width: Decimal = Field(gt=Decimal("0"))
    height: Decimal = Field(gt=Decimal("0"))
    order_index: int = Field(ge=1)
    source: Literal["manual", "suggestion", "imported"] = "manual"
    confirmed: bool = False


class AnswerRegionFullAnswerConfirmation(BaseModel):
    full_answer_confirmed: bool
    continuation_not_needed: bool = False
    packet_status: Literal["unconfirmed", "complete", "partial", "blank"] | None = None
    manual_answer_text: str | None = Field(default=None, max_length=10000)


class AnswerRegionCorrectionSegmentBox(BaseModel):
    x: Decimal = Field(ge=Decimal("0"))
    y: Decimal = Field(ge=Decimal("0"))
    width: Decimal = Field(gt=Decimal("0"))
    height: Decimal = Field(gt=Decimal("0"))


class AnswerRegionCorrectionSegmentCreate(AnswerRegionCorrectionSegmentBox):
    page_id: int
    order_index: int = Field(ge=1)
    confirmed: bool = True


class AnswerRegionCorrectionSegmentReorder(BaseModel):
    segment_ids: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "AnswerRegionCorrectionSegmentReorder":
        if len(self.segment_ids) != len(set(self.segment_ids)):
            raise ValueError("segment_ids must be unique")
        return self


class AnswerRegionSegmentRead(ORMBase):
    id: int
    answer_region_id: int
    page_id: int
    order_index: int
    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal
    image_path: str
    source: str
    confirmed: bool
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class AnswerRegionRead(ORMBase):
    id: int
    submission_id: int
    question_id: int
    page_id: int
    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal
    image_path: str
    manual_answer_text: str | None = None
    full_answer_confirmed: bool = False
    evidence_status: str = "unconfirmed"
    continuation_check_status: str = "not_checked"
    segments: list[AnswerRegionSegmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AnswerRegionCorrectionResponse(BaseModel):
    correction_type: str
    teacher_id: int
    corrected_at: datetime
    before: dict[str, Any]
    after: dict[str, Any]
    answer_region: AnswerRegionRead


class DraftAnswerRegionSuggestion(BaseModel):
    draft_id: str
    page_id: int
    suggested_question_id: int
    suggested_question_no: str
    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    provider: Literal["mock", "codex_cli_answer_region_suggester", "codex_cli"] = "mock"
    source: str = "mock"
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    notes: str | None = None
    needs_review: bool = True
    needs_teacher_confirmation: bool = True


class AnswerRegionSuggestionResponse(BaseModel):
    page_id: int
    provider: Literal["mock", "codex_cli_answer_region_suggester", "codex_cli"] = "mock"
    source: str = "mock"
    needs_review: bool = True
    message: str
    provider_warnings: list[str] = Field(default_factory=list)
    suggestions: list[DraftAnswerRegionSuggestion]


class DraftAnswerRegionSuggestionSegment(BaseModel):
    page_id: int
    order_index: int = Field(ge=1)
    x: Decimal = Field(ge=Decimal("0"))
    y: Decimal = Field(ge=Decimal("0"))
    width: Decimal = Field(gt=Decimal("0"))
    height: Decimal = Field(gt=Decimal("0"))
    is_primary: bool = False
    source: Literal["manual", "suggestion", "imported"] = "suggestion"
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    continuation_risk: AnswerRegionContinuationRisk = "none"
    warnings: list[str] = Field(default_factory=list)
    notes: str | None = None


class DraftAnswerRegionSuggestionGroup(BaseModel):
    draft_id: str = Field(min_length=1)
    suggested_question_id: int
    suggested_question_no: str = Field(min_length=1, max_length=32)
    provider: AnswerRegionMappingProvider = "mock"
    source: str = "mock"
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    continuation_risk: AnswerRegionContinuationRisk = "none"
    segments: list[DraftAnswerRegionSuggestionSegment] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    reason: str | None = None
    needs_review: bool = True
    needs_teacher_confirmation: bool = True
    requires_full_answer_confirmation: bool = True

    @model_validator(mode="after")
    def validate_segment_order_and_primary(self) -> "DraftAnswerRegionSuggestionGroup":
        order_indexes = [segment.order_index for segment in self.segments]
        if len(order_indexes) != len(set(order_indexes)):
            raise ValueError("suggestion segment order_index values must be unique")
        primary_count = sum(1 for segment in self.segments if segment.is_primary)
        if primary_count != 1:
            raise ValueError("exactly one suggestion segment must be primary")
        return self


class AnswerRegionSuggestionGroupResponse(BaseModel):
    submission_id: int
    provider: AnswerRegionMappingProvider = "mock"
    source: str = "mock"
    needs_review: bool = True
    message: str
    provider_warnings: list[str] = Field(default_factory=list)
    suggestion_groups: list[DraftAnswerRegionSuggestionGroup]


class AnswerRegionSuggestionAcceptRequest(BaseModel):
    draft_id: str = Field(min_length=1)
    question_id: int
    full_answer_confirmed: bool = False
    segments: list[DraftAnswerRegionSuggestionSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_acceptance_segment_order(self) -> "AnswerRegionSuggestionAcceptRequest":
        order_indexes = [segment.order_index for segment in self.segments]
        if len(order_indexes) != len(set(order_indexes)):
            raise ValueError("accepted segment order_index values must be unique")
        return self


class EvidencePacketAssessmentContext(BaseModel):
    assessment_id: int
    submission_id: int
    page_id: int
    answer_region_id: int


class EvidencePacketCanonicalGradingUnit(BaseModel):
    label: str | None
    max_marks: Decimal | None
    active_rubric_present: bool
    model_answer_present: bool
    teacher_founder_confirmed: bool | None = None
    rubric_total_matches_grading_unit: bool | None = None


class EvidencePacketQuestionEvidence(BaseModel):
    question_label: str | None
    question_text: str | None
    max_marks: Decimal | None
    confirmed_status: Literal["unknown", "confirmed", "unconfirmed"] = "unknown"


class EvidencePacketSolutionEvidence(BaseModel):
    solution_model_answer_text_or_reference: str | None
    confirmed_status: Literal["unknown", "confirmed", "unconfirmed"] = "unknown"


class EvidencePacketRubricEvidence(BaseModel):
    criteria_max_marks: list[dict[str, Any]]
    confirmed_status: Literal["unknown", "confirmed", "unconfirmed"] = "unknown"
    total_marks_match_grading_unit_max_marks: bool | None


class EvidencePacketStudentAnswerEvidence(BaseModel):
    answer_region_coordinates: dict[str, Decimal]
    crop_path: str | None
    segment_count: int = 0
    pages_covered: list[int] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    packet_status: Literal["unconfirmed", "complete", "partial", "blank"] = "unconfirmed"
    continuation_check_status: Literal[
        "not_checked",
        "checked_no_continuation",
        "possible_continuation",
        "continuation_confirmed_included",
        "continuation_confirmed_not_needed",
    ] = "not_checked"
    next_page_context_available: bool = False
    teacher_founder_confirmed_full_answer: bool = False
    padded_grading_context_generated: bool
    context_completeness_status: Literal[
        "unknown", "complete", "possibly_incomplete", "incomplete"
    ] = "unknown"
    teacher_founder_confirmed_region: bool | None = None


class EvidencePacketReadinessResult(BaseModel):
    ready_for_grading: bool
    blockers: list[str]
    warnings: list[str]


class GradingEvidencePacketRead(BaseModel):
    assessment_context: EvidencePacketAssessmentContext
    canonical_grading_unit: EvidencePacketCanonicalGradingUnit
    question_evidence: EvidencePacketQuestionEvidence
    solution_model_answer_evidence: EvidencePacketSolutionEvidence
    rubric_evidence: EvidencePacketRubricEvidence
    student_answer_evidence: EvidencePacketStudentAnswerEvidence
    readiness_result: EvidencePacketReadinessResult


class GradingJobRead(ORMBase):
    id: int
    answer_region_id: int
    status: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class GradeSuggestionRead(ORMBase):
    id: int
    grading_job_id: int
    answer_region_id: int
    question_id: int
    model_provider: str
    model_name: str
    prompt_version: str
    marking_policy: MarkingPolicy
    raw_response_json: dict[str, Any]
    score: Decimal | None
    max_score: Decimal
    confidence: Decimal | None
    needs_review: bool
    feedback: str | None
    cost_estimate: Decimal | None
    created_at: datetime


class BrowserCodexGradeSuggestionRead(ORMBase):
    id: int
    grading_job_id: int
    answer_region_id: int
    question_id: int
    model_provider: str
    model_name: str
    prompt_version: str
    marking_policy: MarkingPolicy
    score: Decimal | None
    max_score: Decimal
    confidence: Decimal | None
    needs_review: bool
    feedback: str | None
    cost_estimate: Decimal | None
    review_flags: list[str]
    created_at: datetime


class GradeAnswerRegionResponse(BaseModel):
    job: GradingJobRead
    suggestion: GradeSuggestionRead


class BrowserCodexGradeResponse(BaseModel):
    job: GradingJobRead
    suggestion: BrowserCodexGradeSuggestionRead


class BatchMockGradeResponse(BaseModel):
    assessment_id: int
    total_answer_regions: int
    graded_count: int
    skipped_count: int
    failed_count: int
    created_grade_suggestion_ids: list[int]
    errors: list[str]


class BatchFinalGradeApproveRequest(BaseModel):
    grade_suggestion_ids: list[int]


class BatchFinalGradeApproveResponse(BaseModel):
    requested_count: int
    approved_count: int
    skipped_count: int
    failed_count: int
    final_grade_ids: list[int]
    errors: list[str]


class FinalGradeCreate(BaseModel):
    teacher_id: int | None = None
    final_score: Decimal = Field(ge=0)
    teacher_comment: str | None = None
    approval_status: Literal["approved", "edited", "rejected"]


class FinalGradeApprove(BaseModel):
    teacher_id: int | None = None
    teacher_comment: str | None = None


class FinalGradeEdit(BaseModel):
    teacher_id: int | None = None
    final_score: Decimal = Field(ge=0)
    teacher_comment: str | None = None


class FinalGradeReject(BaseModel):
    teacher_id: int | None = None
    teacher_comment: str | None = None


class FinalGradeRead(ORMBase):
    id: int
    answer_region_id: int
    teacher_id: int
    suggestion_id: int | None
    final_score: Decimal
    teacher_comment: str | None
    approval_status: str
    created_at: datetime
    updated_at: datetime


class ReviewQueueSubmission(BaseModel):
    id: int
    student_identifier: str
    student_name: str | None


class ReviewQueueQuestion(BaseModel):
    id: int
    question_no: str
    question_text: str
    total_marks: Decimal


class ReviewQueueItem(BaseModel):
    answer_region: AnswerRegionRead
    submission: ReviewQueueSubmission
    question: ReviewQueueQuestion
    latest_grade_suggestion: GradeSuggestionRead | None
    final_grade: FinalGradeRead | None
    review_status: Literal["ungraded", "suggested", "finalized"]


class AssessmentSummaryRead(BaseModel):
    assessment_id: int
    course_id: int
    total_submissions: int
    total_answer_regions: int
    total_grade_suggestions: int
    total_final_grades: int
    approved_count: int
    edited_count: int
    rejected_count: int
    pending_review_count: int
    average_final_score: Decimal | None
    max_possible_score: Decimal | None
    generated_at: datetime
