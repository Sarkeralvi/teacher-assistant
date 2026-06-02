from decimal import Decimal

import pytest

from packages.evaluation.marking_policy_calibration import (
    MarkingPolicyCalibrationError,
    MarkingPolicyCalibrationRunner,
    build_synthetic_marking_policy_cases,
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
