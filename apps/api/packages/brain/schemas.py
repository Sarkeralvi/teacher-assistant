from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelPolicy(StrEnum):
    MOCK_GRADING = "mock_grading"


class RubricBreakdownItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    max_marks: Decimal = Field(ge=Decimal("0"))
    awarded_marks: Decimal = Field(ge=Decimal("0"))
    reason: str = Field(min_length=1)
    evidence: str | None = None
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def awarded_marks_must_not_exceed_max(self) -> "RubricBreakdownItem":
        if self.awarded_marks > self.max_marks:
            raise ValueError("awarded_marks cannot exceed max_marks")
        return self


class GradeSuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: bool
    rubric_breakdown: list[RubricBreakdownItem] = Field(min_length=1)
    detected_answer_summary: str = Field(min_length=1)
    major_errors: list[str]
    feedback_to_student: str = Field(min_length=1)
    review_flags: list[str] = Field(min_length=1)
    model_provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    cost_estimate: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    latency_ms: int = Field(default=0, ge=0)

    @field_validator("review_flags")
    @classmethod
    def review_flags_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("review_flags must be unique")
        return value

    @model_validator(mode="after")
    def score_and_breakdown_must_fit_max_score(self) -> "GradeSuggestionOutput":
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        breakdown_total = sum((item.awarded_marks for item in self.rubric_breakdown), Decimal("0"))
        if breakdown_total != self.score:
            raise ValueError("rubric breakdown awarded marks must sum to score")
        return self
