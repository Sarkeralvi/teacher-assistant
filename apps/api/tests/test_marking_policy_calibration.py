from decimal import Decimal

import pytest

from packages.evaluation.marking_policy_calibration import (
    MarkingPolicyCalibrationError,
    MarkingPolicyCalibrationRunner,
    build_synthetic_marking_policy_cases,
    build_synthetic_math_stat_grading_cases,
)


def test_synthetic_marking_policy_cases_are_non_student_examples() -> None:
    cases = build_synthetic_marking_policy_cases()

    assert [case.case_id for case in cases] == [
        "case_a_correct_final_answer_weak_working",
        "case_b_partial_method_one_wrong_step",
        "case_c_minor_notation_issue",
    ]
    assert all("synthetic" in case.description.lower() for case in cases)
    assert all(case.max_score == Decimal("10.00") for case in cases)


def test_fake_marking_policy_calibration_is_monotonic_and_separated() -> None:
    report = MarkingPolicyCalibrationRunner(provider_mode="fake").run()

    assert report["provider_mode"] == "fake"
    assert report["allow_real_provider"] is False
    assert report["call_count"] == 0
    assert report["case_count"] == 3
    assert report["real_provider_used"] is False
    assert report["final_grade_count"] == 0
    assert report["monotonic_ordering"] is True
    assert report["meaningful_separation"] is True
    assert report["policy_averages"]["tough"] < report["policy_averages"]["general"]
    assert report["policy_averages"]["general"] < report["policy_averages"]["easy"]
    first_case = report["cases"][0]
    assert first_case["ordering_holds"] is True
    assert first_case["meaningful_separation_holds"] is True
    assert first_case["policy_scores"]["tough"]["needs_review"] is True
    assert first_case["policy_scores"]["tough"]["score"] == Decimal("3.0")
    assert first_case["policy_scores"]["general"]["score"] == Decimal("5.0")
    assert first_case["policy_scores"]["easy"]["score"] == Decimal("7.0")


def test_real_marking_policy_calibration_requires_explicit_enable() -> None:
    runner = MarkingPolicyCalibrationRunner(provider_mode="codex_cli", allow_real_provider=False)

    with pytest.raises(MarkingPolicyCalibrationError, match="TA_EVAL_ALLOW_REAL_PROVIDER=true"):
        runner.run()


def test_synthetic_math_stat_cases_cover_bayes_credit_patterns() -> None:
    cases = build_synthetic_math_stat_grading_cases()

    assert [case.case_id for case in cases] == [
        "math_stat_a_bayes_correct_setup_compact_working",
        "math_stat_b_correct_formula_arithmetic_slip",
        "math_stat_c_wrong_conceptual_setup",
        "math_stat_d_bayes_score_band_near_full_credit",
    ]
    assert all("synthetic" in case.description.lower() for case in cases)
    assert cases[0].max_score == Decimal("6.00")
    assert "Bayes formula present" in cases[0].description
    assert "near full credit" in cases[0].notes


def test_fake_math_stat_calibration_targets_no_severe_underscore_for_bayes_setup() -> None:
    report = MarkingPolicyCalibrationRunner(provider_mode="fake").run()

    math_report = report["math_stat_calibration"]
    assert math_report["real_provider_used"] is False
    assert math_report["call_count"] == 0
    assert math_report["final_grade_count"] == 0
    assert math_report["case_count"] == 4
    assert math_report["cases"][0]["case_id"] == "math_stat_a_bayes_correct_setup_compact_working"
    assert math_report["cases"][0]["expected_behavior"] == "near_full_credit"
    assert math_report["cases"][0]["fake_score"] >= Decimal("5.0")
    assert math_report["cases"][0]["severe_underscore"] is False
    assert math_report["cases"][1]["expected_behavior"] == "meaningful_partial_credit"
    assert math_report["cases"][2]["expected_behavior"] == "low_score"
    score_band_case = math_report["cases"][3]
    assert score_band_case["case_id"] == "math_stat_d_bayes_score_band_near_full_credit"
    assert score_band_case["expected_behavior"] == "bayes_score_band_5_to_6"
    assert Decimal("5.0") <= score_band_case["fake_score"] <= Decimal("6.0")
    assert score_band_case["severe_underscore"] is False
    assert math_report["summary"]["bayes_compact_working_not_severely_under_scored"] is True
    assert math_report["summary"]["bayes_score_band_case_gets_5_to_6"] is True
