from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem
from packages.evaluation.grading_evaluation import (
    EvaluationCase,
    GradingEvaluationError,
    GradingEvaluationRunner,
    calculate_metrics,
    create_synthetic_grading_quality_dataset,
    write_evaluation_artifacts,
)

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    Question,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()


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


def case(
    case_id: str,
    expected: str = "5.00",
    max_score: str = "5.00",
    answer_type: str = "correct",
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        answer_region_id=1,
        question_id=1,
        rubric_id=1,
        expected_score=Decimal(expected),
        max_score=Decimal(max_score),
        teacher_notes="Teacher reference notes.",
        answer_type=answer_type,
    )


def test_metric_calculation_counts_exact_matches() -> None:
    metrics = calculate_metrics(
        [
            {"case": case("case_001"), "suggestion": suggestion(score="5.00")},
        ]
    )

    assert metrics["case_count"] == 1
    assert metrics["exact_match_rate"] == Decimal("1")


def test_metric_calculation_counts_within_1_mark() -> None:
    metrics = calculate_metrics(
        [
            {"case": case("case_001", expected="5.00"), "suggestion": suggestion(score="4.00")},
            {"case": case("case_002", expected="5.00"), "suggestion": suggestion(score="3.50")},
        ]
    )

    assert metrics["within_1_mark_rate"] == Decimal("0.5")


def test_metric_calculation_mean_absolute_error() -> None:
    metrics = calculate_metrics(
        [
            {"case": case("case_001", expected="5.00"), "suggestion": suggestion(score="4.00")},
            {"case": case("case_002", expected="5.00"), "suggestion": suggestion(score="2.00")},
        ]
    )

    assert metrics["mean_absolute_error"] == Decimal("2")


def test_metric_calculation_detects_false_confident_errors() -> None:
    metrics = calculate_metrics(
        [
            {
                "case": case("case_001", expected="5.00"),
                "suggestion": suggestion(score="3.50", confidence="0.8000"),
            },
            {
                "case": case("case_002", expected="5.00"),
                "suggestion": suggestion(score="3.50", confidence="0.7900"),
            },
        ]
    )

    assert metrics["false_confident_error_count"] == 1


def test_evaluation_runner_rejects_real_provider_without_explicit_enable() -> None:
    runner = GradingEvaluationRunner(provider_mode="codex_cli", allow_real_provider=False)

    with pytest.raises(GradingEvaluationError, match="explicitly enabled"):
        runner.validate_provider_mode([case("case_001")])


def test_evaluation_runner_treats_local_qwen_as_a_real_provider() -> None:
    runner = GradingEvaluationRunner(
        provider_mode="llama_cpp_qwen",
        allow_real_provider=False,
    )

    with pytest.raises(GradingEvaluationError, match="explicitly enabled"):
        runner.validate_provider_mode([case("case_001")])


def test_evaluation_runner_enforces_max_real_cases() -> None:
    runner = GradingEvaluationRunner(
        provider_mode="codex_cli", allow_real_provider=True, max_real_cases=1
    )

    with pytest.raises(GradingEvaluationError, match="at most 1 real"):
        runner.validate_provider_mode([case("case_001"), case("case_002")])


def test_metric_calculation_includes_answer_type_and_error_breakdowns() -> None:
    metrics = calculate_metrics(
        [
            {
                "case": case("case_correct", expected="5.00", answer_type="correct"),
                "suggestion": suggestion(score="5.00"),
            },
            {
                "case": case("case_partial", expected="3.00", answer_type="partial"),
                "suggestion": suggestion(score="5.00", confidence="0.9000"),
            },
            {
                "case": case("case_wrong", expected="0.00", answer_type="wrong"),
                "suggestion": suggestion(score="2.00", confidence="0.9000"),
            },
            {
                "case": case("case_blank", expected="0.00", answer_type="blank"),
                "suggestion": suggestion(score="0.00"),
            },
        ]
    )

    assert metrics["severe_error_count"] == 2
    assert metrics["over_score_count"] == 2
    assert metrics["under_score_count"] == 0
    assert metrics["by_answer_type"]["correct"]["case_count"] == 1
    assert metrics["by_answer_type"]["correct"]["exact_match_rate"] == Decimal("1")
    assert metrics["by_answer_type"]["partial"]["mean_absolute_error"] == Decimal("2")


def test_synthetic_grading_quality_dataset_creates_five_non_student_cases(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        cases = create_synthetic_grading_quality_dataset(db_session)
    finally:
        get_settings.cache_clear()

    assert [item.answer_type for item in cases] == [
        "correct",
        "partial",
        "wrong",
        "blank",
        "irrelevant",
    ]
    assert all(item.case_id.startswith("synthetic_grading_") for item in cases)
    assert all(item.answer_region_id > 0 for item in cases)
    assert all(item.generated_fixture_reference for item in cases)
    assert all(
        (tmp_path / "storage" / item.generated_fixture_reference).is_file() for item in cases
    )
    assert {item.expected_score for item in cases} == {
        Decimal("5.00"),
        Decimal("3.00"),
        Decimal("1.00"),
        Decimal("0.00"),
    }


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


def test_evaluation_output_artifact_reports_marking_policy(tmp_path: Path) -> None:
    result = {
        "run_id": "eval-policy-test",
        "provider_mode": "mock",
        "marking_policy": "easy",
        "metrics": {"case_count": 1, "exact_match_rate": Decimal("1")},
        "cases": [
            {
                "case_id": "case_001",
                "expected_score": Decimal("5.00"),
                "ai_score": Decimal("5.00"),
                "absolute_error": Decimal("0"),
                "marking_policy": "easy",
            }
        ],
    }

    paths = write_evaluation_artifacts(result, tmp_path)
    json_text = paths.json_path.read_text(encoding="utf-8")
    markdown_text = paths.markdown_path.read_text(encoding="utf-8")
    assert '"marking_policy": "easy"' in json_text
    assert "Marking policy: `easy`" in markdown_text
    assert "policy easy" in markdown_text
