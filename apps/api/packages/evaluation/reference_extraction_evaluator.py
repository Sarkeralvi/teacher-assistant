from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["question", "solution", "rubric"]


class ReferenceExtractionEvaluationError(RuntimeError):
    """Raised when reference-extraction evaluation fixtures are invalid."""


class CanonicalGradingUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    max_marks: Decimal = Field(gt=Decimal("0"))
    question_text: str = ""
    parent_label: str | None = None
    requires_solution: bool = True
    requires_visual_confirmation: bool = False


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    max_marks: Decimal = Field(gt=Decimal("0"))


class ReferenceExtractorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    canonical_grading_units: list[CanonicalGradingUnit] = Field(default_factory=list)
    solution_sections: dict[str, str] = Field(default_factory=dict)
    rubric_criteria: dict[str, list[RubricCriterion]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    needs_teacher_confirmation: bool = True
    unsafe_auto_confirm_count: int = Field(default=0, ge=0)
    grade_suggestion_created_count: int = Field(default=0, ge=0)
    final_grade_created_count: int = Field(default=0, ge=0)


class ReferenceExtractionEvalFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    fixture_type: Literal["synthetic"] = "synthetic"
    document_types: list[DocumentType] = Field(min_length=1)
    expected_canonical_grading_units: list[CanonicalGradingUnit] = Field(min_length=1)
    expected_solution_sections: dict[str, str] = Field(default_factory=dict)
    expected_rubric_criteria: dict[str, list[RubricCriterion]] = Field(default_factory=dict)
    expected_total_mark_validation_result: bool = True
    expected_blockers: list[str] = Field(default_factory=list)
    expected_warnings: list[str] = Field(default_factory=list)
    expected_teacher_confirmation_required: bool = True
    provider_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


ReferenceExtractor = Callable[[ReferenceExtractionEvalFixture], ReferenceExtractorOutput]


class FixtureReferenceExtractor:
    """Extractor that replays saved synthetic provider output for evaluation."""

    def __init__(self, provider_key: str) -> None:
        self.provider_key = provider_key

    def __call__(self, fixture: ReferenceExtractionEvalFixture) -> ReferenceExtractorOutput:
        payload = fixture.provider_outputs.get(self.provider_key)
        if payload is None:
            return ReferenceExtractorOutput(
                provider=self.provider_key,
                blockers=[f"No provider output recorded for {fixture.case_id}."],
            )
        return ReferenceExtractorOutput.model_validate(payload)


def load_reference_extraction_eval_fixtures(path: Path) -> list[ReferenceExtractionEvalFixture]:
    if path.is_dir():
        cases: list[ReferenceExtractionEvalFixture] = []
        for fixture_path in sorted(path.glob("*.json")):
            cases.extend(load_reference_extraction_eval_fixtures(fixture_path))
        if not cases:
            raise ReferenceExtractionEvaluationError(
                f"No JSON reference-extraction fixtures found: {path}"
            )
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
        raise ReferenceExtractionEvaluationError(
            "Reference-extraction eval dataset must be a JSON object, array, or JSONL objects"
        )
    return [ReferenceExtractionEvalFixture.model_validate(item) for item in payloads]


def evaluate_reference_extraction_provider(
    cases: list[ReferenceExtractionEvalFixture], extractor: ReferenceExtractor
) -> dict[str, Any]:
    rows = []
    provider_name = getattr(extractor, "provider_key", extractor.__class__.__name__)
    for eval_case in cases:
        try:
            output = extractor(eval_case)
        except Exception as exc:  # noqa: BLE001 - extractor failures are per-case eval data
            output = ReferenceExtractorOutput(provider=str(provider_name), blockers=[str(exc)])
        rows.append(_evaluate_case(eval_case, output))
    metrics = _calculate_metrics(rows)
    return {
        "run_id": datetime.now(UTC).strftime("reference-extraction-eval-%Y%m%dT%H%M%SZ"),
        "created_at": datetime.now(UTC).isoformat(),
        "provider": str(provider_name),
        "overall_pass": bool(rows) and all(row["passed"] for row in rows),
        "metrics": metrics,
        "cases": rows,
    }


def _evaluate_case(
    eval_case: ReferenceExtractionEvalFixture, output: ReferenceExtractorOutput
) -> dict[str, Any]:
    expected_units = eval_case.expected_canonical_grading_units
    actual_units = output.canonical_grading_units
    reasons: list[str] = []

    expected_labels = [unit.label for unit in expected_units]
    actual_labels = [unit.label for unit in actual_units]
    label_match = expected_labels == actual_labels
    if not label_match:
        reasons.append("extracted label not matching expected CGU")

    max_mark_match = [unit.max_marks for unit in expected_units] == [
        unit.max_marks for unit in actual_units
    ]
    if not max_mark_match:
        reasons.append("max mark mismatch")

    parent_child_match = [unit.parent_label for unit in expected_units] == [
        unit.parent_label for unit in actual_units
    ]
    if not parent_child_match:
        reasons.append("parent/child structure mismatch")

    question_text_match = all(unit.question_text.strip() for unit in actual_units) and [
        _norm(unit.question_text) for unit in expected_units
    ] == [_norm(unit.question_text) for unit in actual_units]
    if not question_text_match:
        reasons.append("question text missing or incomplete")

    expected_solution_labels = {
        unit.label
        for unit in expected_units
        if unit.requires_solution and unit.label in expected_labels
    }
    actual_solution_labels = {
        label for label, text in output.solution_sections.items() if text.strip()
    }
    missing_solution_labels = sorted(expected_solution_labels - actual_solution_labels)
    solution_mapping_match = not missing_solution_labels
    if missing_solution_labels:
        reasons.append(f"missing solution/model answer for {', '.join(missing_solution_labels)}")

    expected_rubric_labels = set(expected_labels)
    actual_rubric_labels = {
        label for label, criteria in output.rubric_criteria.items() if criteria
    }
    missing_rubric_labels = sorted(expected_rubric_labels - actual_rubric_labels)
    missing_rubric = bool(missing_rubric_labels)
    if missing_rubric:
        reasons.append(f"missing rubric for {', '.join(missing_rubric_labels)}")

    expected_rubric_signature = _rubric_signature(eval_case.expected_rubric_criteria)
    actual_rubric_signature = _rubric_signature(output.rubric_criteria)
    rubric_criteria_match = expected_rubric_signature == actual_rubric_signature
    if eval_case.expected_rubric_criteria and not rubric_criteria_match:
        reasons.append("rubric criteria extraction mismatch")

    rubric_total_match = _rubric_total_validation(actual_units, output.rubric_criteria)
    expected_total_valid = eval_case.expected_total_mark_validation_result
    rubric_total_validation_match = rubric_total_match == expected_total_valid
    if not rubric_total_validation_match or not rubric_total_match:
        reasons.append("rubric total/max mark mismatch")

    duplicate_label_detected = len(set(actual_labels)) != len(actual_labels)
    duplicate_expected_or_detected = duplicate_label_detected or any(
        "duplicate" in item.lower() for item in eval_case.expected_blockers + output.blockers
    )
    if duplicate_expected_or_detected:
        reasons.append("duplicate label unresolved")

    combined_text = _combined_text(output.warnings, output.blockers)
    visual_required = any(unit.requires_visual_confirmation for unit in expected_units)
    visual_confirmation_detected = (
        not visual_required
        or (
            "visual" in combined_text
            and output.needs_teacher_confirmation
            and output.unsafe_auto_confirm_count == 0
        )
    )
    if visual_required and not visual_confirmation_detected:
        reasons.append("visual confirmation required but not detected")

    unsafe_auto_confirm_count = output.unsafe_auto_confirm_count
    if not output.needs_teacher_confirmation:
        unsafe_auto_confirm_count += 1
    if unsafe_auto_confirm_count:
        reasons.append("unsafe auto-confirm during reference extraction")
    if output.grade_suggestion_created_count:
        reasons.append("GradeSuggestion creation reported during reference extraction")
    if output.final_grade_created_count:
        reasons.append("FinalGrade creation reported during reference extraction")

    critical_failure = bool(
        not label_match
        or not max_mark_match
        or missing_rubric
        or missing_solution_labels
        or duplicate_expected_or_detected
        or not rubric_total_match
        or unsafe_auto_confirm_count
        or output.grade_suggestion_created_count
        or output.final_grade_created_count
    )
    passed = not critical_failure and not any(
        reason
        for reason in reasons
        if "visual confirmation" not in reason and "low OCR" not in reason
    )

    return {
        "case_id": eval_case.case_id,
        "description": eval_case.description,
        "provider": output.provider,
        "passed": passed,
        "critical_failure": critical_failure,
        "failure_reasons": reasons,
        "warning_reasons": [
            reason
            for reason in output.warnings + eval_case.expected_warnings
            if reason not in output.blockers
        ],
        "checks": {
            "label_exact_match": label_match,
            "max_mark_exact_match": max_mark_match,
            "parent_child_structure_match": parent_child_match,
            "question_text_complete": question_text_match,
            "solution_section_mapping_match": solution_mapping_match,
            "rubric_criteria_match": rubric_criteria_match,
            "rubric_total_match": rubric_total_match,
            "rubric_total_validation_match": rubric_total_validation_match,
            "duplicate_label_detected": duplicate_expected_or_detected,
            "missing_solution_detected": bool(missing_solution_labels),
            "missing_rubric_detected": missing_rubric,
            "visual_confirmation_required_detected": visual_required
            and visual_confirmation_detected,
            "teacher_confirmation_required": output.needs_teacher_confirmation,
        },
        "safety_counts": {
            "unsafe_auto_confirm_count": unsafe_auto_confirm_count,
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
            "grading_unit_label_exact_match_accuracy": Decimal("0"),
            "max_mark_exact_match_accuracy": Decimal("0"),
            "parent_child_structure_accuracy": Decimal("0"),
            "question_text_presence_completeness_accuracy": Decimal("0"),
            "solution_section_mapping_accuracy": Decimal("0"),
            "rubric_criteria_extraction_accuracy": Decimal("0"),
            "rubric_total_match_accuracy": Decimal("0"),
            "duplicate_label_detection_count": 0,
            "missing_solution_detection_count": 0,
            "missing_rubric_count": 0,
            "visual_confirmation_required_detection_count": 0,
            "unsafe_auto_confirm_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "max_mark_mismatch_count": 0,
            "label_mismatch_count": 0,
        }

    def check_count(name: str) -> int:
        return sum(1 for row in rows if row["checks"][name])

    return {
        "case_count": case_count,
        "passed_case_count": sum(1 for row in rows if row["passed"]),
        "critical_failure_count": sum(1 for row in rows if row["critical_failure"]),
        "grading_unit_label_exact_match_accuracy": _rate(
            check_count("label_exact_match"), case_count
        ),
        "max_mark_exact_match_accuracy": _rate(check_count("max_mark_exact_match"), case_count),
        "parent_child_structure_accuracy": _rate(
            check_count("parent_child_structure_match"), case_count
        ),
        "question_text_presence_completeness_accuracy": _rate(
            check_count("question_text_complete"), case_count
        ),
        "solution_section_mapping_accuracy": _rate(
            check_count("solution_section_mapping_match"), case_count
        ),
        "rubric_criteria_extraction_accuracy": _rate(
            check_count("rubric_criteria_match"), case_count
        ),
        "rubric_total_match_accuracy": _rate(check_count("rubric_total_match"), case_count),
        "duplicate_label_detection_count": check_count("duplicate_label_detected"),
        "missing_solution_detection_count": check_count("missing_solution_detected"),
        "missing_rubric_count": check_count("missing_rubric_detected"),
        "visual_confirmation_required_detection_count": check_count(
            "visual_confirmation_required_detected"
        ),
        "unsafe_auto_confirm_count": sum(
            row["safety_counts"]["unsafe_auto_confirm_count"] for row in rows
        ),
        "grade_suggestion_created_count": sum(
            row["safety_counts"]["grade_suggestion_created_count"] for row in rows
        ),
        "final_grade_created_count": sum(
            row["safety_counts"]["final_grade_created_count"] for row in rows
        ),
        "max_mark_mismatch_count": sum(
            1 for row in rows if not row["checks"]["max_mark_exact_match"]
        ),
        "label_mismatch_count": sum(
            1 for row in rows if not row["checks"]["label_exact_match"]
        ),
    }


def evaluate_reference_extraction_quality_gate(evaluation_result: dict[str, Any]) -> dict[str, Any]:
    """Apply the TA-REF-001 synthetic quality gate policy to an eval result."""
    metrics = evaluation_result.get("metrics", {})
    cases = evaluation_result.get("cases", [])
    blocker_reasons: list[str] = []
    warning_reasons: list[str] = []

    blocker_checks = {
        "critical_failure_count": "critical reference failures must be zero",
        "unsafe_auto_confirm_count": "unsafe auto-confirm count must be zero",
        "grade_suggestion_created_count": "GradeSuggestion count must be zero",
        "final_grade_created_count": "FinalGrade count must be zero",
        "max_mark_mismatch_count": "max mark mismatches must be zero",
        "missing_rubric_count": "missing rubric count must be zero",
        "missing_solution_detection_count": "missing required solution count must be zero",
        "duplicate_label_detection_count": (
            "duplicate labels must be resolved before provider trial"
        ),
        "label_mismatch_count": "extracted labels must match expected CGUs",
    }
    for metric_name, rule in blocker_checks.items():
        value = int(metrics.get(metric_name, 0) or 0)
        if value:
            blocker_reasons.append(f"{metric_name}={value}; {rule}")

    if not evaluation_result.get("overall_pass", False) and not blocker_reasons:
        blocker_reasons.append("synthetic reference benchmark overall pass is required")

    for row in cases:
        if row.get("checks", {}).get("visual_confirmation_required_detected"):
            warning_reasons.append(
                f"{row.get('case_id')} requires visual confirmation before reference acceptance"
            )
        warning_reasons.extend(row.get("warning_reasons", []))

    return {
        "eligible_for_real_provider_trial": not blocker_reasons,
        "blocker_reasons": blocker_reasons,
        "warning_reasons": warning_reasons,
        "metrics": metrics,
    }


def _rubric_signature(
    criteria_by_label: dict[str, list[RubricCriterion]],
) -> dict[str, list[tuple[str, str, Decimal]]]:
    return {
        label: [
            (criterion.criterion_id, _norm(criterion.description), criterion.max_marks)
            for criterion in criteria
        ]
        for label, criteria in criteria_by_label.items()
    }


def _rubric_total_validation(
    units: list[CanonicalGradingUnit], criteria_by_label: dict[str, list[RubricCriterion]]
) -> bool:
    unit_marks = {unit.label: unit.max_marks for unit in units}
    for label, criteria in criteria_by_label.items():
        if label not in unit_marks:
            return False
        if sum((criterion.max_marks for criterion in criteria), Decimal("0")) != unit_marks[label]:
            return False
    return bool(criteria_by_label) and all(label in criteria_by_label for label in unit_marks)


def _combined_text(*parts: list[str]) -> str:
    return " ".join(item for part in parts for item in part).lower()


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


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
    parser = argparse.ArgumentParser(
        description="Evaluate synthetic reference extraction fixtures."
    )
    parser.add_argument("fixture_path", type=Path)
    parser.add_argument("--provider-output-key", default="synthetic_reference_extractor")
    args = parser.parse_args()
    cases = load_reference_extraction_eval_fixtures(args.fixture_path)
    result = evaluate_reference_extraction_provider(
        cases, FixtureReferenceExtractor(args.provider_output_key)
    )
    result["quality_gate"] = evaluate_reference_extraction_quality_gate(result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
