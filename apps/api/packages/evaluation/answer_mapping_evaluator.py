from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ContinuationRisk = Literal[
    "none",
    "possible_continuation",
    "continuation_included",
    "continuation_not_needed",
    "ambiguous",
]
FixtureClassification = Literal[
    "current_mock_provider_pass",
    "current_mock_provider_gap",
    "future_real_provider_target",
    "harness_only_case",
]


class AnswerMappingEvaluationError(RuntimeError):
    """Raised when answer-mapping evaluation fixtures or provider output are invalid."""


class GradingUnitFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(min_length=1)
    max_marks: Decimal = Field(gt=Decimal("0"))
    label: str | None = None


class PageFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ref: str = Field(min_length=1)
    page_no: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_notes: str = ""
    low_content: bool = False


class MappingSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ref: str = Field(min_length=1)
    order_index: int = Field(ge=1)
    box: tuple[Decimal, Decimal, Decimal, Decimal]

    @field_validator("box", mode="before")
    @classmethod
    def validate_box(cls, value: object) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("box must be [x, y, width, height]")
        x, y, width, height = [Decimal(str(item)) for item in value]
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("box must have non-negative x/y and positive width/height")
        return (x, y, width, height)


class ExpectedSuggestionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(min_length=1)
    continuation_risk: ContinuationRisk = "none"
    segments: list[MappingSegment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    requires_full_answer_confirmation: bool = True


class ProviderSuggestionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(min_length=1)
    continuation_risk: ContinuationRisk = "none"
    segments: list[MappingSegment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    needs_review: bool = True
    needs_teacher_confirmation: bool = True
    requires_full_answer_confirmation: bool = True
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))


class MappingProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    suggestion_groups: list[ProviderSuggestionGroup] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    grade_suggestion_created_count: int = Field(default=0, ge=0)
    final_grade_created_count: int = Field(default=0, ge=0)


class AnswerMappingEvalFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    fixture_type: Literal["synthetic"] = "synthetic"
    classification: FixtureClassification
    grading_units: list[GradingUnitFixture] = Field(min_length=1)
    pages: list[PageFixture] = Field(min_length=1)
    expected_suggestion_groups: list[ExpectedSuggestionGroup] = Field(default_factory=list)
    expected_warnings: list[str] = Field(default_factory=list)
    expected_blockers: list[str] = Field(default_factory=list)
    expected_full_answer_confirmation_required: bool = True
    expected_wrong_question_detected: bool = False
    expected_blank_page_handled: bool = False
    provider_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


MappingProvider = Callable[[AnswerMappingEvalFixture], MappingProviderOutput]


class FixtureMappingProvider:
    """Provider that evaluates saved synthetic output for a named provider key.

    This is intentionally not a smart provider. It makes the current deterministic/mock
    outputs measurable without improving them just to pass benchmark cases.
    """

    def __init__(self, provider_key: str) -> None:
        self.provider_key = provider_key

    def __call__(self, fixture: AnswerMappingEvalFixture) -> MappingProviderOutput:
        payload = fixture.provider_outputs.get(self.provider_key)
        if payload is None:
            return MappingProviderOutput(
                provider=self.provider_key,
                warnings=[f"No provider output recorded for {fixture.case_id}."],
            )
        return MappingProviderOutput.model_validate(payload)


def load_answer_mapping_eval_fixtures(path: Path) -> list[AnswerMappingEvalFixture]:
    if path.is_dir():
        cases: list[AnswerMappingEvalFixture] = []
        for fixture_path in sorted(path.glob("*.json")):
            cases.extend(load_answer_mapping_eval_fixtures(fixture_path))
        if not cases:
            raise AnswerMappingEvaluationError(f"No JSON answer-mapping fixtures found: {path}")
        return cases

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
        payloads = loaded["cases"] if isinstance(loaded, dict) and "cases" in loaded else loaded
    if isinstance(payloads, dict):
        payloads = [payloads]
    if not isinstance(payloads, list):
        raise AnswerMappingEvaluationError(
            "Answer-mapping eval dataset must be a JSON object, JSON array, or JSONL objects"
        )
    return [AnswerMappingEvalFixture.model_validate(item) for item in payloads]


def evaluate_answer_mapping_provider(
    cases: list[AnswerMappingEvalFixture], provider: MappingProvider
) -> dict[str, Any]:
    rows = []
    provider_name = getattr(provider, "provider_key", provider.__class__.__name__)
    for eval_case in cases:
        try:
            output = provider(eval_case)
        except Exception as exc:  # noqa: BLE001 - provider failures are per-case eval data
            output = MappingProviderOutput(provider=str(provider_name), blockers=[str(exc)])
        rows.append(_evaluate_case(eval_case, output))
    metrics = _calculate_metrics(rows)
    return {
        "run_id": datetime.now(UTC).strftime("answer-mapping-eval-%Y%m%dT%H%M%SZ"),
        "created_at": datetime.now(UTC).isoformat(),
        "provider": str(provider_name),
        "overall_pass": bool(rows) and all(row["passed"] for row in rows),
        "metrics": metrics,
        "cases": rows,
    }


def _evaluate_case(
    eval_case: AnswerMappingEvalFixture, output: MappingProviderOutput
) -> dict[str, Any]:
    expected = eval_case.expected_suggestion_groups
    actual = output.suggestion_groups
    reasons: list[str] = []

    group_count_match = len(expected) == len(actual)
    if not group_count_match:
        reasons.append(
            f"suggestion group count mismatch: expected {len(expected)}, got {len(actual)}"
        )

    question_label_match = [group.question_no for group in expected] == [
        group.question_no for group in actual
    ]
    if not question_label_match:
        reasons.append("question-label mismatch")

    segment_count_match = [_segment_count(group) for group in expected] == [
        _segment_count(group) for group in actual
    ]
    if not segment_count_match:
        reasons.append("segment count mismatch")

    segment_order_match = [_segment_order(group) for group in expected] == [
        _segment_order(group) for group in actual
    ]
    if not segment_order_match:
        reasons.append("segment order mismatch")

    page_coverage_match = [_page_coverage(group) for group in expected] == [
        _page_coverage(group) for group in actual
    ]
    if not page_coverage_match:
        reasons.append("page coverage mismatch")

    continuation_risk_match = [group.continuation_risk for group in expected] == [
        group.continuation_risk for group in actual
    ]
    if not continuation_risk_match:
        reasons.append("continuation-risk mismatch")

    full_answer_confirmation_match = all(
        group.needs_review
        and group.needs_teacher_confirmation
        and group.requires_full_answer_confirmation
        for group in actual
    )
    if actual and not full_answer_confirmation_match:
        reasons.append(
            "provider output allows unsafe auto-accept or skips full-answer confirmation"
        )

    warning_text = _combined_text(
        output.warnings,
        output.blockers,
        *(group.warnings for group in actual),
        *(group.blockers for group in actual),
    )
    expected_wrong_detection = eval_case.expected_wrong_question_detected
    wrong_question_detected = "wrong-question" in warning_text or "wrong question" in warning_text
    wrong_question_detection_match = wrong_question_detected == expected_wrong_detection
    if not wrong_question_detection_match:
        reasons.append("wrong-question detection mismatch")

    blank_page_handled = not actual or "blank" in warning_text or "low-content" in warning_text
    blank_page_handling_match = (
        blank_page_handled == eval_case.expected_blank_page_handled
        if eval_case.expected_blank_page_handled
        else True
    )
    if eval_case.expected_blank_page_handled and not blank_page_handling_match:
        reasons.append("blank/low-content page produced a confident mapping")

    continuation_false_negative = any(
        expected_group.continuation_risk
        in {"continuation_included", "possible_continuation", "ambiguous"}
        and (index >= len(actual) or actual[index].continuation_risk == "none")
        for index, expected_group in enumerate(expected)
    )
    if continuation_false_negative:
        reasons.append("continuation false-negative: expected continuation risk was missed")

    unsafe_auto_accept_count = sum(
        1
        for group in actual
        if not group.needs_review
        or not group.needs_teacher_confirmation
        or not group.requires_full_answer_confirmation
    )
    if output.grade_suggestion_created_count:
        reasons.append("GradeSuggestion creation reported during mapping evaluation")
    if output.final_grade_created_count:
        reasons.append("FinalGrade creation reported during mapping evaluation")

    critical_failure = bool(
        continuation_false_negative
        or (eval_case.expected_wrong_question_detected and not wrong_question_detected)
        or (eval_case.expected_blank_page_handled and not blank_page_handled)
        or unsafe_auto_accept_count
        or output.grade_suggestion_created_count
        or output.final_grade_created_count
    )
    passed = not reasons and not critical_failure

    return {
        "case_id": eval_case.case_id,
        "description": eval_case.description,
        "classification": eval_case.classification,
        "provider": output.provider,
        "passed": passed,
        "critical_failure": critical_failure,
        "failure_reasons": reasons,
        "checks": {
            "suggestion_group_count_match": group_count_match,
            "question_label_match": question_label_match,
            "segment_count_match": segment_count_match,
            "segment_order_match": segment_order_match,
            "page_coverage_match": page_coverage_match,
            "continuation_risk_match": continuation_risk_match,
            "wrong_question_detection_match": wrong_question_detection_match,
            "blank_page_handling_match": blank_page_handling_match,
            "full_answer_confirmation_match": full_answer_confirmation_match,
        },
        "safety_counts": {
            "unsafe_auto_accept_count": unsafe_auto_accept_count,
            "grade_suggestion_created_count": output.grade_suggestion_created_count,
            "final_grade_created_count": output.final_grade_created_count,
        },
    }


def _calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    case_count = len(rows)
    if case_count == 0:
        return {
            "case_count": 0,
            "passed_case_count": 0,
            "critical_failure_count": 0,
            "suggestion_group_count_accuracy": Decimal("0"),
            "question_label_accuracy": Decimal("0"),
            "segment_count_accuracy": Decimal("0"),
            "segment_order_accuracy": Decimal("0"),
            "page_coverage_accuracy": Decimal("0"),
            "continuation_risk_accuracy": Decimal("0"),
            "wrong_question_detection_accuracy": Decimal("0"),
            "blank_page_handling_accuracy": Decimal("0"),
            "complete_answer_packet_success": Decimal("0"),
            "unsafe_auto_accept_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "continuation_false_negative_count": 0,
            "blank_page_false_mapping_count": 0,
            "possible_continuation_requires_confirmation_count": 0,
        }

    def check_count(name: str) -> int:
        return sum(1 for row in rows if row["checks"][name])

    unsafe_auto_accept_count = sum(row["safety_counts"]["unsafe_auto_accept_count"] for row in rows)
    grade_suggestion_count = sum(
        row["safety_counts"]["grade_suggestion_created_count"] for row in rows
    )
    final_grade_count = sum(row["safety_counts"]["final_grade_created_count"] for row in rows)
    return {
        "case_count": case_count,
        "passed_case_count": sum(1 for row in rows if row["passed"]),
        "critical_failure_count": sum(1 for row in rows if row["critical_failure"]),
        "suggestion_group_count_accuracy": _rate(
            check_count("suggestion_group_count_match"), case_count
        ),
        "question_label_accuracy": _rate(check_count("question_label_match"), case_count),
        "segment_count_accuracy": _rate(check_count("segment_count_match"), case_count),
        "segment_order_accuracy": _rate(check_count("segment_order_match"), case_count),
        "page_coverage_accuracy": _rate(check_count("page_coverage_match"), case_count),
        "continuation_risk_accuracy": _rate(check_count("continuation_risk_match"), case_count),
        "wrong_question_detection_accuracy": _rate(
            check_count("wrong_question_detection_match"), case_count
        ),
        "blank_page_handling_accuracy": _rate(check_count("blank_page_handling_match"), case_count),
        "complete_answer_packet_success": _rate(
            sum(1 for row in rows if row["passed"]), case_count
        ),
        "unsafe_auto_accept_count": unsafe_auto_accept_count,
        "grade_suggestion_created_count": grade_suggestion_count,
        "final_grade_created_count": final_grade_count,
        "continuation_false_negative_count": sum(
            1
            for row in rows
            if any("continuation false-negative" in reason for reason in row["failure_reasons"])
        ),
        "blank_page_false_mapping_count": sum(
            1
            for row in rows
            if any("blank/low-content" in reason for reason in row["failure_reasons"])
        ),
        "possible_continuation_requires_confirmation_count": sum(
            1
            for row in rows
            if row["passed"]
            and row["checks"]["continuation_risk_match"]
            and row["checks"]["full_answer_confirmation_match"]
            and "ambiguous_possible_continuation" in row["case_id"]
        ),
    }


def _segment_count(group: ExpectedSuggestionGroup | ProviderSuggestionGroup) -> int:
    return len(group.segments)


def _segment_order(group: ExpectedSuggestionGroup | ProviderSuggestionGroup) -> list[int]:
    return [segment.order_index for segment in group.segments]


def _page_coverage(group: ExpectedSuggestionGroup | ProviderSuggestionGroup) -> list[str]:
    return [segment.page_ref for segment in group.segments]


def _combined_text(*parts: list[str]) -> str:
    return " ".join(item for part in parts for item in part).lower()


def _rate(count: int, total: int) -> Decimal:
    return Decimal(count) / Decimal(total) if total else Decimal("0")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate synthetic answer-mapping fixtures.")
    parser.add_argument("fixture_path", type=Path)
    parser.add_argument("--provider-output-key", default="current_mock_provider")
    args = parser.parse_args()
    cases = load_answer_mapping_eval_fixtures(args.fixture_path)
    result = evaluate_answer_mapping_provider(
        cases, FixtureMappingProvider(args.provider_output_key)
    )
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
