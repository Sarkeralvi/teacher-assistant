from decimal import Decimal
from pathlib import Path

from packages.evaluation.answer_mapping_evaluator import (
    AnswerMappingEvalFixture,
    FixtureMappingProvider,
    MappingProviderOutput,
    evaluate_answer_mapping_provider,
    evaluate_mapping_quality_gate,
    load_answer_mapping_eval_fixtures,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "packages/evaluation/fixtures/answer_mapping"

REQUIRED_CASE_IDS = {
    "single_page_complete",
    "multi_page_continuation",
    "near_bottom_no_continuation",
    "ambiguous_possible_continuation",
    "multiple_questions_one_page",
    "wrong_question_trap",
    "blank_low_content_page",
}


def test_loads_required_synthetic_benchmark_cases() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)

    assert {case.case_id for case in cases} == REQUIRED_CASE_IDS
    for case in cases:
        assert case.expected_suggestion_groups is not None
        assert case.expected_full_answer_confirmation_required is True
        assert case.fixture_type == "synthetic"


def test_fixture_provider_evaluation_reports_metrics_and_honest_mock_gaps() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)

    result = evaluate_answer_mapping_provider(
        cases, FixtureMappingProvider("current_mock_provider")
    )

    assert result["provider"] == "current_mock_provider"
    assert result["overall_pass"] is False
    assert result["metrics"]["case_count"] == 7
    assert result["metrics"]["unsafe_auto_accept_count"] == 0
    assert result["metrics"]["grade_suggestion_created_count"] == 0
    assert result["metrics"]["final_grade_created_count"] == 0
    assert result["metrics"]["critical_failure_count"] >= 2

    cases_by_id = {case["case_id"]: case for case in result["cases"]}
    assert cases_by_id["single_page_complete"]["passed"] is True
    assert cases_by_id["multi_page_continuation"]["passed"] is True
    assert cases_by_id["ambiguous_possible_continuation"]["passed"] is True
    assert cases_by_id["multiple_questions_one_page"]["passed"] is False
    assert cases_by_id["wrong_question_trap"]["critical_failure"] is True
    assert cases_by_id["blank_low_content_page"]["critical_failure"] is True


def test_continuation_false_negative_is_critical() -> None:
    case = AnswerMappingEvalFixture.model_validate(
        {
            "case_id": "continuation_false_negative",
            "description": "Expected continuation is missed as a single segment.",
            "fixture_type": "synthetic",
            "classification": "future_real_provider_target",
            "grading_units": [{"question_no": "1(b)(i)", "max_marks": "6.00"}],
            "pages": [
                {"page_ref": "p1", "page_no": 1, "width": 420, "height": 600},
                {"page_ref": "p2", "page_no": 2, "width": 420, "height": 600},
            ],
            "expected_suggestion_groups": [
                {
                    "question_no": "1(b)(i)",
                    "continuation_risk": "continuation_included",
                    "requires_full_answer_confirmation": True,
                    "segments": [
                        {"page_ref": "p1", "order_index": 1, "box": [20, 400, 200, 180]},
                        {"page_ref": "p2", "order_index": 2, "box": [20, 30, 200, 180]},
                    ],
                    "warnings": [],
                    "blockers": [],
                }
            ],
            "expected_full_answer_confirmation_required": True,
            "expected_wrong_question_detected": False,
            "expected_blank_page_handled": False,
            "provider_outputs": {
                "bad_provider": {
                    "provider": "bad_provider",
                    "suggestion_groups": [
                        {
                            "question_no": "1(b)(i)",
                            "continuation_risk": "none",
                            "needs_review": True,
                            "needs_teacher_confirmation": True,
                            "requires_full_answer_confirmation": True,
                            "segments": [
                                {"page_ref": "p1", "order_index": 1, "box": [20, 400, 200, 180]}
                            ],
                            "warnings": [],
                            "blockers": [],
                        }
                    ],
                }
            },
        }
    )

    result = evaluate_answer_mapping_provider([case], FixtureMappingProvider("bad_provider"))

    assert result["overall_pass"] is False
    assert result["metrics"]["continuation_false_negative_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any(
        "continuation false-negative" in reason for reason in result["cases"][0]["failure_reasons"]
    )


def test_wrong_question_mapping_is_critical() -> None:
    case = AnswerMappingEvalFixture.model_validate(
        {
            "case_id": "wrong_question_critical",
            "description": "Provider maps evidence to the neighboring sub-question.",
            "fixture_type": "synthetic",
            "classification": "future_real_provider_target",
            "grading_units": [
                {"question_no": "1(b)(i)", "max_marks": "6.00"},
                {"question_no": "1(b)(ii)", "max_marks": "4.00"},
            ],
            "pages": [{"page_ref": "p1", "page_no": 1, "width": 420, "height": 600}],
            "expected_suggestion_groups": [],
            "expected_full_answer_confirmation_required": True,
            "expected_wrong_question_detected": True,
            "expected_blank_page_handled": False,
            "expected_warnings": ["wrong-question trap must be blocked"],
            "expected_blockers": ["wrong-question trap"],
            "provider_outputs": {
                "bad_provider": {
                    "provider": "bad_provider",
                    "suggestion_groups": [
                        {
                            "question_no": "1(b)(ii)",
                            "continuation_risk": "none",
                            "needs_review": True,
                            "needs_teacher_confirmation": True,
                            "requires_full_answer_confirmation": True,
                            "segments": [
                                {"page_ref": "p1", "order_index": 1, "box": [20, 30, 200, 180]}
                            ],
                            "warnings": [],
                            "blockers": [],
                        }
                    ],
                }
            },
        }
    )

    result = evaluate_answer_mapping_provider([case], FixtureMappingProvider("bad_provider"))

    assert result["metrics"]["wrong_question_detection_accuracy"] == Decimal("0")
    assert result["cases"][0]["critical_failure"] is True
    assert any("wrong-question" in reason for reason in result["cases"][0]["failure_reasons"])


def test_ambiguous_possible_continuation_requires_review_and_confirmation() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)
    ambiguous = [case for case in cases if case.case_id == "ambiguous_possible_continuation"]

    result = evaluate_answer_mapping_provider(
        ambiguous, FixtureMappingProvider("current_mock_provider")
    )

    assert result["overall_pass"] is True
    assert result["metrics"]["possible_continuation_requires_confirmation_count"] == 1
    assert result["metrics"]["unsafe_auto_accept_count"] == 0


def test_blank_page_does_not_create_confident_false_mapping() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)
    blank = [case for case in cases if case.case_id == "blank_low_content_page"]

    result = evaluate_answer_mapping_provider(
        blank, FixtureMappingProvider("current_mock_provider")
    )

    assert result["overall_pass"] is False
    assert result["metrics"]["blank_page_false_mapping_count"] == 1
    assert result["cases"][0]["critical_failure"] is True


def test_evaluator_accepts_direct_provider_output_without_database_side_effects() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)
    single = next(case for case in cases if case.case_id == "single_page_complete")
    output = MappingProviderOutput.model_validate(single.provider_outputs["current_mock_provider"])

    result = evaluate_answer_mapping_provider([single], lambda _case: output)

    assert result["overall_pass"] is True
    assert result["metrics"]["grade_suggestion_created_count"] == 0
    assert result["metrics"]["final_grade_created_count"] == 0


def test_quality_gate_blocks_current_mock_provider_from_real_trial() -> None:
    cases = load_answer_mapping_eval_fixtures(FIXTURE_DIR)
    result = evaluate_answer_mapping_provider(
        cases, FixtureMappingProvider("current_mock_provider")
    )

    policy = evaluate_mapping_quality_gate(result)

    assert policy["eligible_for_real_provider_trial"] is False
    assert any("critical_failure_count" in reason for reason in policy["blocker_reasons"])
    assert any("synthetic benchmark overall pass" in reason for reason in policy["blocker_reasons"])
    assert policy["metrics"]["grade_suggestion_created_count"] == 0
    assert policy["metrics"]["final_grade_created_count"] == 0


def test_quality_gate_allows_zero_critical_failures_and_no_unsafe_counts() -> None:
    passing_result = {
        "provider": "candidate_provider",
        "overall_pass": True,
        "metrics": {
            "critical_failure_count": 0,
            "unsafe_auto_accept_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "continuation_false_negative_count": 0,
            "wrong_question_critical_failure_count": 0,
            "blank_page_false_mapping_count": 0,
            "mandatory_review_confirmation_gap_count": 0,
        },
        "cases": [],
    }

    policy = evaluate_mapping_quality_gate(passing_result)

    assert policy["eligible_for_real_provider_trial"] is True
    assert policy["blocker_reasons"] == []


def test_quality_gate_reviewable_warnings_do_not_block_but_require_confirmation() -> None:
    warning_only_result = {
        "provider": "reviewable_provider",
        "overall_pass": True,
        "metrics": {
            "critical_failure_count": 0,
            "unsafe_auto_accept_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "continuation_false_negative_count": 0,
            "wrong_question_critical_failure_count": 0,
            "blank_page_false_mapping_count": 0,
            "mandatory_review_confirmation_gap_count": 0,
        },
        "cases": [
            {
                "case_id": "near_bottom_no_continuation",
                "passed": True,
                "critical_failure": False,
                "failure_reasons": [],
                "checks": {
                    "continuation_risk_match": True,
                    "full_answer_confirmation_match": True,
                },
            },
            {
                "case_id": "ambiguous_possible_continuation",
                "passed": True,
                "critical_failure": False,
                "failure_reasons": [],
                "checks": {
                    "continuation_risk_match": True,
                    "full_answer_confirmation_match": True,
                },
            },
        ],
    }

    policy = evaluate_mapping_quality_gate(warning_only_result)

    assert policy["eligible_for_real_provider_trial"] is True
    assert policy["blocker_reasons"] == []
    assert any("review" in reason for reason in policy["warning_reasons"])
