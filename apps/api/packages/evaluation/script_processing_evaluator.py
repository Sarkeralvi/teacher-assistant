from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ContinuationSignal = Literal[
    "none",
    "possible_continuation",
    "continuation_included",
    "continuation_not_needed",
    "ambiguous",
]
PageKind = Literal["answer", "blank", "cover", "unknown"]


class ScriptProcessingEvaluationError(RuntimeError):
    """Raised when script-processing evaluation fixtures are invalid."""


class ScriptPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ref: str = Field(min_length=1)
    source_index: int = Field(gt=0)
    logical_page_no: int | None = Field(default=None, gt=0)
    page_kind: PageKind = "answer"
    content_notes: str = ""


class BoundarySegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ref: str = Field(min_length=1)
    order_index: int = Field(ge=1)


class ScriptBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    segments: list[BoundarySegment] = Field(default_factory=list)
    continuation_signal: ContinuationSignal = "none"
    confidence: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    needs_teacher_confirmation: bool = True


class ScriptProcessorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    logical_order: list[str] = Field(default_factory=list)
    detected_labels: list[str] = Field(default_factory=list)
    blank_cover_page_refs: list[str] = Field(default_factory=list)
    missing_page_refs: list[str] = Field(default_factory=list)
    duplicate_page_refs: list[str] = Field(default_factory=list)
    answer_boundaries: list[ScriptBoundary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    needs_teacher_confirmation: bool = True
    unsafe_auto_confirm_count: int = Field(default=0, ge=0)
    grade_suggestion_created_count: int = Field(default=0, ge=0)
    final_grade_created_count: int = Field(default=0, ge=0)


class ScriptProcessingEvalFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    fixture_type: Literal["synthetic"] = "synthetic"
    pages: list[ScriptPage] = Field(min_length=1)
    source_order: list[str] = Field(min_length=1)
    expected_logical_order: list[str] = Field(min_length=1)
    expected_blank_cover_page_refs: list[str] = Field(default_factory=list)
    expected_detected_labels: list[str] = Field(default_factory=list)
    expected_answer_boundaries: list[ScriptBoundary] = Field(default_factory=list)
    expected_continuation_signals: dict[str, ContinuationSignal] = Field(default_factory=dict)
    expected_missing_page_refs: list[str] = Field(default_factory=list)
    expected_duplicate_page_refs: list[str] = Field(default_factory=list)
    expected_blockers: list[str] = Field(default_factory=list)
    expected_warnings: list[str] = Field(default_factory=list)
    expected_teacher_confirmation_required: bool = True
    provider_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


ScriptProcessor = Callable[[ScriptProcessingEvalFixture], ScriptProcessorOutput]


class FixtureScriptProcessor:
    """Processor that replays saved synthetic script-processing outputs."""

    def __init__(self, provider_key: str) -> None:
        self.provider_key = provider_key

    def __call__(self, fixture: ScriptProcessingEvalFixture) -> ScriptProcessorOutput:
        payload = fixture.provider_outputs.get(self.provider_key)
        if payload is None:
            return ScriptProcessorOutput(
                provider=self.provider_key,
                blockers=[f"No provider output recorded for {fixture.case_id}."],
            )
        return ScriptProcessorOutput.model_validate(payload)


def load_script_processing_eval_fixtures(path: Path) -> list[ScriptProcessingEvalFixture]:
    if path.is_dir():
        cases: list[ScriptProcessingEvalFixture] = []
        for fixture_path in sorted(path.glob("*.json")):
            cases.extend(load_script_processing_eval_fixtures(fixture_path))
        if not cases:
            raise ScriptProcessingEvaluationError(
                f"No JSON script-processing fixtures found: {path}"
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
        raise ScriptProcessingEvaluationError(
            "Script-processing eval dataset must be a JSON object, array, or JSONL objects"
        )
    return [ScriptProcessingEvalFixture.model_validate(item) for item in payloads]


def evaluate_script_processing_provider(
    cases: list[ScriptProcessingEvalFixture], processor: ScriptProcessor
) -> dict[str, Any]:
    rows = []
    provider_name = getattr(processor, "provider_key", processor.__class__.__name__)
    for eval_case in cases:
        try:
            output = processor(eval_case)
        except Exception as exc:  # noqa: BLE001 - processor failures are per-case eval data
            output = ScriptProcessorOutput(provider=str(provider_name), blockers=[str(exc)])
        rows.append(_evaluate_case(eval_case, output))
    metrics = _calculate_metrics(rows)
    result = {
        "run_id": datetime.now(UTC).strftime("script-processing-eval-%Y%m%dT%H%M%SZ"),
        "created_at": datetime.now(UTC).isoformat(),
        "provider": str(provider_name),
        "overall_pass": bool(rows) and all(row["passed"] for row in rows),
        "metrics": metrics,
        "cases": rows,
    }
    result["quality_gate"] = evaluate_script_processing_quality_gate(result)
    return result


def _evaluate_case(
    eval_case: ScriptProcessingEvalFixture, output: ScriptProcessorOutput
) -> dict[str, Any]:
    reasons: list[str] = []

    page_order_match = output.logical_order == eval_case.expected_logical_order
    if not page_order_match:
        reasons.append("wrong page order accepted as ready")

    expected_missing = set(eval_case.expected_missing_page_refs)
    actual_missing = set(output.missing_page_refs)
    missing_page_detected = expected_missing.issubset(actual_missing)
    if expected_missing and not missing_page_detected:
        reasons.append("missing page not detected")
    elif expected_missing:
        reasons.append("missing page detected; script is blocked pending review")

    expected_duplicate = set(eval_case.expected_duplicate_page_refs)
    actual_duplicate = set(output.duplicate_page_refs)
    duplicate_page_detected = expected_duplicate.issubset(actual_duplicate)
    if expected_duplicate and not duplicate_page_detected:
        reasons.append("duplicate page not detected")
    elif expected_duplicate:
        reasons.append("duplicate page detected; script is blocked pending review")

    blank_cover_match = set(output.blank_cover_page_refs) == set(
        eval_case.expected_blank_cover_page_refs
    )
    if not blank_cover_match:
        reasons.append("blank/cover classification mismatch")

    blank_cover_pages = set(eval_case.expected_blank_cover_page_refs)
    blank_confident_mapping = any(
        segment.page_ref in blank_cover_pages
        for boundary in output.answer_boundaries
        for segment in boundary.segments
    )
    if blank_confident_mapping:
        reasons.append("blank/cover page mapped as confident answer")

    label_count_match = len(output.detected_labels) == len(eval_case.expected_detected_labels)
    if not label_count_match:
        reasons.append("detected label count mismatch")

    boundary_count_match = len(output.answer_boundaries) == len(
        eval_case.expected_answer_boundaries
    )
    if not boundary_count_match:
        reasons.append("answer boundary count mismatch")

    expected_signature = _boundary_signature(eval_case.expected_answer_boundaries)
    actual_signature = _boundary_signature(output.answer_boundaries)
    boundary_page_coverage_match = {
        label: pages for label, pages, _orders, _signal in expected_signature
    } == {label: pages for label, pages, _orders, _signal in actual_signature}
    if not boundary_page_coverage_match:
        reasons.append("boundary page coverage mismatch")

    boundary_order_match = {
        label: orders for label, _pages, orders, _signal in expected_signature
    } == {label: orders for label, _pages, orders, _signal in actual_signature}
    if not boundary_order_match:
        reasons.append("boundary order mismatch")

    actual_signals = {
        boundary.label: boundary.continuation_signal for boundary in output.answer_boundaries
    }
    expected_signals = eval_case.expected_continuation_signals or {
        boundary.label: boundary.continuation_signal
        for boundary in eval_case.expected_answer_boundaries
    }
    continuation_signal_match = actual_signals == expected_signals
    if not continuation_signal_match:
        reasons.append("continuation-signal mismatch")

    missed_continuation = any(
        expected in {"possible_continuation", "continuation_included", "ambiguous"}
        and actual_signals.get(label, "none") in {"none", "continuation_not_needed"}
        for label, expected in expected_signals.items()
    )
    if missed_continuation:
        reasons.append("missed continuation")

    false_continuation = any(
        expected in {"none", "continuation_not_needed"}
        and actual_signals.get(label, "none")
        in {"possible_continuation", "continuation_included", "ambiguous"}
        for label, expected in expected_signals.items()
    )
    if false_continuation:
        reasons.append("false continuation signal")

    unsafe_auto_confirm_count = output.unsafe_auto_confirm_count
    if not output.needs_teacher_confirmation:
        unsafe_auto_confirm_count += 1
    unsafe_auto_confirm_count += sum(
        1 for boundary in output.answer_boundaries if not boundary.needs_teacher_confirmation
    )
    if unsafe_auto_confirm_count:
        reasons.append("unsafe auto-confirm during script processing")
    if output.grade_suggestion_created_count:
        reasons.append("GradeSuggestion creation reported during script processing")
    if output.final_grade_created_count:
        reasons.append("FinalGrade creation reported during script processing")

    ambiguous_review = any(
        "ambiguous" in item.lower() or "low confidence" in item.lower()
        for item in output.warnings + eval_case.expected_warnings
    )

    critical_failure = bool(
        missed_continuation
        or (not page_order_match and not output.blockers)
        or bool(expected_missing)
        or bool(expected_duplicate)
        or blank_confident_mapping
        or unsafe_auto_confirm_count
        or output.grade_suggestion_created_count
        or output.final_grade_created_count
    )
    passed = not critical_failure and all(
        [
            page_order_match,
            missing_page_detected,
            duplicate_page_detected,
            blank_cover_match,
            label_count_match,
            boundary_count_match,
            boundary_page_coverage_match,
            boundary_order_match,
            continuation_signal_match,
        ]
    )

    return {
        "case_id": eval_case.case_id,
        "description": eval_case.description,
        "provider": output.provider,
        "passed": passed,
        "critical_failure": critical_failure,
        "failure_reasons": reasons,
        "warning_reasons": output.warnings + eval_case.expected_warnings,
        "checks": {
            "page_order_match": page_order_match,
            "missing_page_detected": bool(expected_missing) and missing_page_detected,
            "duplicate_page_detected": bool(expected_duplicate) and duplicate_page_detected,
            "blank_cover_classification_match": blank_cover_match,
            "label_count_match": label_count_match,
            "boundary_count_match": boundary_count_match,
            "boundary_page_coverage_match": boundary_page_coverage_match,
            "boundary_order_match": boundary_order_match,
            "continuation_signal_match": continuation_signal_match,
            "teacher_confirmation_required": output.needs_teacher_confirmation
            and all(boundary.needs_teacher_confirmation for boundary in output.answer_boundaries),
            "ambiguous_review_required": ambiguous_review and output.needs_teacher_confirmation,
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
            "page_order_accuracy": Decimal("0"),
            "missing_page_detection_count": 0,
            "missing_page_not_detected_count": 0,
            "duplicate_page_detection_count": 0,
            "duplicate_page_not_detected_count": 0,
            "blank_cover_classification_accuracy": Decimal("0"),
            "detected_label_count_accuracy": Decimal("0"),
            "answer_boundary_count_accuracy": Decimal("0"),
            "boundary_page_coverage_accuracy": Decimal("0"),
            "boundary_order_accuracy": Decimal("0"),
            "continuation_signal_accuracy": Decimal("0"),
            "false_continuation_count": 0,
            "missed_continuation_count": 0,
            "wrong_page_order_ready_count": 0,
            "blank_confident_answer_mapping_count": 0,
            "unsafe_auto_confirm_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
        }

    def check_count(name: str) -> int:
        return sum(1 for row in rows if row["checks"][name])

    return {
        "case_count": case_count,
        "passed_case_count": sum(1 for row in rows if row["passed"]),
        "critical_failure_count": sum(1 for row in rows if row["critical_failure"]),
        "page_order_accuracy": _rate(check_count("page_order_match"), case_count),
        "missing_page_detection_count": check_count("missing_page_detected"),
        "missing_page_not_detected_count": sum(
            1
            for row in rows
            if any("missing page not detected" in reason for reason in row["failure_reasons"])
        ),
        "duplicate_page_detection_count": check_count("duplicate_page_detected"),
        "duplicate_page_not_detected_count": sum(
            1
            for row in rows
            if any("duplicate page not detected" in reason for reason in row["failure_reasons"])
        ),
        "blank_cover_classification_accuracy": _rate(
            check_count("blank_cover_classification_match"), case_count
        ),
        "detected_label_count_accuracy": _rate(check_count("label_count_match"), case_count),
        "answer_boundary_count_accuracy": _rate(check_count("boundary_count_match"), case_count),
        "boundary_page_coverage_accuracy": _rate(
            check_count("boundary_page_coverage_match"), case_count
        ),
        "boundary_order_accuracy": _rate(check_count("boundary_order_match"), case_count),
        "continuation_signal_accuracy": _rate(check_count("continuation_signal_match"), case_count),
        "false_continuation_count": sum(
            1
            for row in rows
            if any("false continuation" in reason for reason in row["failure_reasons"])
        ),
        "missed_continuation_count": sum(
            1
            for row in rows
            if any("missed continuation" in reason for reason in row["failure_reasons"])
        ),
        "wrong_page_order_ready_count": sum(
            1
            for row in rows
            if any("wrong page order" in reason for reason in row["failure_reasons"])
        ),
        "blank_confident_answer_mapping_count": sum(
            1
            for row in rows
            if any("blank/cover page mapped" in reason for reason in row["failure_reasons"])
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
    }


def evaluate_script_processing_quality_gate(evaluation_result: dict[str, Any]) -> dict[str, Any]:
    """Apply the TA-SCRIPT-001 synthetic quality gate policy to an eval result."""
    metrics = evaluation_result.get("metrics", {})
    cases = evaluation_result.get("cases", [])
    blocker_reasons: list[str] = []
    warning_reasons: list[str] = []

    blocker_checks = {
        "critical_failure_count": "critical script-processing failures must be zero",
        "unsafe_auto_confirm_count": "unsafe auto-confirm count must be zero",
        "grade_suggestion_created_count": "GradeSuggestion count must be zero",
        "final_grade_created_count": "FinalGrade count must be zero",
        "missed_continuation_count": "missed continuation count must be zero",
        "wrong_page_order_ready_count": "wrong page order cannot be accepted as ready",
        "missing_page_not_detected_count": "missing pages must be detected",
        "duplicate_page_not_detected_count": "duplicate pages must be detected",
        "blank_confident_answer_mapping_count": (
            "blank/cover pages must not be confidently mapped as answers"
        ),
    }
    for metric_name, rule in blocker_checks.items():
        value = int(metrics.get(metric_name, 0) or 0)
        if value:
            blocker_reasons.append(f"{metric_name}={value}; {rule}")

    if not evaluation_result.get("overall_pass", False) and not blocker_reasons:
        blocker_reasons.append("synthetic script-processing benchmark overall pass is required")

    for row in cases:
        if row.get("checks", {}).get("ambiguous_review_required"):
            warning_reasons.append(
                f"{row.get('case_id')} has ambiguous/low-confidence boundary "
                "requiring teacher confirmation"
            )
        warning_reasons.extend(row.get("warning_reasons", []))

    return {
        "eligible_for_real_provider_trial": not blocker_reasons,
        "blocker_reasons": blocker_reasons,
        "warning_reasons": warning_reasons,
        "metrics": metrics,
    }


def _boundary_signature(
    boundaries: list[ScriptBoundary],
) -> list[tuple[str, tuple[str, ...], tuple[int, ...], str]]:
    return [
        (
            boundary.label,
            tuple(segment.page_ref for segment in boundary.segments),
            tuple(segment.order_index for segment in boundary.segments),
            boundary.continuation_signal,
        )
        for boundary in boundaries
    ]


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
    parser = argparse.ArgumentParser(description="Evaluate synthetic script-processing fixtures.")
    parser.add_argument("fixture_path", type=Path)
    parser.add_argument("--provider-output-key", default="synthetic_script_processor")
    args = parser.parse_args()
    cases = load_script_processing_eval_fixtures(args.fixture_path)
    result = evaluate_script_processing_provider(
        cases, FixtureScriptProcessor(args.provider_output_key)
    )
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
