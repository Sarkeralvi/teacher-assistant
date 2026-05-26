from decimal import Decimal
from pathlib import Path

import pytest

from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem
from packages.evaluation.grading_evaluation import (
    EvaluationCase,
    GradingEvaluationError,
    GradingEvaluationRunner,
    calculate_metrics,
    write_evaluation_artifacts,
)


def suggestion(
    *, score: str, max_score: str = "5.00", confidence: str = "0.5000"
) -> GradeSuggestionOutput:
    return GradeSuggestionOutput(
        score=Decimal(score),
        max_score=Decimal(max_score),
        confidence=Decimal(confidence),
        needs_review=True,
        rubric_breakdown=[
            RubricBreakdownItem(
                criterion_id="c1",
                criterion="Criterion",
                max_marks=Decimal(max_score),
                awarded_marks=Decimal(score),
                reason="Reason",
                evidence="Evidence",
                confidence=Decimal(confidence),
            )
        ],
        detected_answer_summary="summary",
        major_errors=[],
        feedback_to_student="feedback",
        review_flags=["teacher_review_required"],
        model_provider="mock",
        model_name="mock-grader-v1",
        prompt_version="test_prompt",
        cost_estimate=Decimal("0"),
    )


def case(case_id: str, expected: str = "5.00", max_score: str = "5.00") -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        answer_region_id=1,
        question_id=1,
        rubric_id=1,
        expected_score=Decimal(expected),
        max_score=Decimal(max_score),
        teacher_notes="Teacher reference notes.",
    )


def test_metric_calculation_counts_exact_matches() -> None:
    metrics = calculate_metrics([
        {"case": case("case_001"), "suggestion": suggestion(score="5.00")},
    ])

    assert metrics["case_count"] == 1
    assert metrics["exact_match_rate"] == Decimal("1")


def test_metric_calculation_counts_within_1_mark() -> None:
    metrics = calculate_metrics([
        {"case": case("case_001", expected="5.00"), "suggestion": suggestion(score="4.00")},
        {"case": case("case_002", expected="5.00"), "suggestion": suggestion(score="3.50")},
    ])

    assert metrics["within_1_mark_rate"] == Decimal("0.5")


def test_metric_calculation_mean_absolute_error() -> None:
    metrics = calculate_metrics([
        {"case": case("case_001", expected="5.00"), "suggestion": suggestion(score="4.00")},
        {"case": case("case_002", expected="5.00"), "suggestion": suggestion(score="2.00")},
    ])

    assert metrics["mean_absolute_error"] == Decimal("2")


def test_metric_calculation_detects_false_confident_errors() -> None:
    metrics = calculate_metrics([
        {
            "case": case("case_001", expected="5.00"),
            "suggestion": suggestion(score="3.50", confidence="0.8000"),
        },
        {
            "case": case("case_002", expected="5.00"),
            "suggestion": suggestion(score="3.50", confidence="0.7900"),
        },
    ])

    assert metrics["false_confident_error_count"] == 1


def test_evaluation_runner_rejects_real_provider_without_explicit_enable() -> None:
    runner = GradingEvaluationRunner(provider_mode="codex_cli", allow_real_provider=False)

    with pytest.raises(GradingEvaluationError, match="explicitly enabled"):
        runner.validate_provider_mode([case("case_001")])


def test_evaluation_runner_enforces_max_real_cases() -> None:
    runner = GradingEvaluationRunner(
        provider_mode="codex_cli", allow_real_provider=True, max_real_cases=1
    )

    with pytest.raises(GradingEvaluationError, match="at most 1 real"):
        runner.validate_provider_mode([case("case_001"), case("case_002")])


def test_evaluation_output_artifact_is_written(tmp_path: Path) -> None:
    result = {
        "run_id": "eval-test",
        "provider_mode": "mock",
        "metrics": {"case_count": 1, "exact_match_rate": Decimal("1")},
        "cases": [
            {
                "case_id": "case_001",
                "expected_score": Decimal("5.00"),
                "ai_score": Decimal("5.00"),
                "absolute_error": Decimal("0"),
            }
        ],
    }

    paths = write_evaluation_artifacts(result, tmp_path)

    assert paths.json_path.is_file()
    assert paths.markdown_path.is_file()
    assert paths.json_path.parent == tmp_path
    assert "exact_match_rate" in paths.json_path.read_text(encoding="utf-8")
    assert "case_001" in paths.markdown_path.read_text(encoding="utf-8")
