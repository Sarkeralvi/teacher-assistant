from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

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


class AnswerRegionCreate(BaseModel):
    question_id: int
    x: Decimal = Field(ge=Decimal("0"))
    y: Decimal = Field(ge=Decimal("0"))
    width: Decimal = Field(gt=Decimal("0"))
    height: Decimal = Field(gt=Decimal("0"))


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
    created_at: datetime
    updated_at: datetime


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
    raw_response_json: dict[str, Any]
    score: Decimal | None
    max_score: Decimal
    confidence: Decimal | None
    needs_review: bool
    feedback: str | None
    cost_estimate: Decimal | None
    created_at: datetime


class GradeAnswerRegionResponse(BaseModel):
    job: GradingJobRead
    suggestion: GradeSuggestionRead


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
