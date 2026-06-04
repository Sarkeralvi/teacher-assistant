from pathlib import Path

from packages.evaluation.script_processing_evaluator import (
    FixtureScriptProcessor,
    ScriptBoundary,
    ScriptProcessingEvalFixture,
    ScriptProcessorOutput,
    evaluate_script_processing_provider,
    evaluate_script_processing_quality_gate,
    load_script_processing_eval_fixtures,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "packages/evaluation/fixtures/script_processing"

REQUIRED_CASE_IDS = {
    "ordered_pages",
    "reversed_pages",
    "missing_page_gap",
    "duplicate_page",
    "blank_cover_page",
    "single_page_answer_boundary",
    "multi_question_same_page",
    "near_bottom_continuation",
    "near_bottom_complete_answer",
    "low_confidence_ambiguous_boundary",
}


def test_loads_required_synthetic_script_processing_cases() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)

    assert {case.case_id for case in cases} == REQUIRED_CASE_IDS
    for case in cases:
        assert case.fixture_type == "synthetic"
        assert case.pages
        assert case.source_order
        assert case.expected_logical_order
        assert case.expected_teacher_confirmation_required is True


def test_fixture_processor_evaluation_reports_metrics_and_safety_counts() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)

    result = evaluate_script_processing_provider(
        cases, FixtureScriptProcessor("synthetic_script_processor")
    )

    assert result["provider"] == "synthetic_script_processor"
    assert result["metrics"]["case_count"] == 10
    assert result["metrics"]["unsafe_auto_confirm_count"] == 0
    assert result["metrics"]["grade_suggestion_created_count"] == 0
    assert result["metrics"]["final_grade_created_count"] == 0
    assert result["metrics"]["missing_page_detection_count"] == 1
    assert result["metrics"]["duplicate_page_detection_count"] == 1
    assert result["metrics"]["blank_cover_classification_accuracy"] == 1
    assert result["metrics"]["missed_continuation_count"] == 1
    assert result["metrics"]["false_continuation_count"] == 0
    assert result["metrics"]["critical_failure_count"] >= 3

    cases_by_id = {case["case_id"]: case for case in result["cases"]}
    assert cases_by_id["ordered_pages"]["passed"] is True
    assert cases_by_id["reversed_pages"]["critical_failure"] is True
    assert cases_by_id["missing_page_gap"]["critical_failure"] is True
    assert cases_by_id["duplicate_page"]["critical_failure"] is True
    assert cases_by_id["blank_cover_page"]["critical_failure"] is True
    assert cases_by_id["low_confidence_ambiguous_boundary"]["critical_failure"] is False


def test_missed_continuation_is_critical() -> None:
    case = ScriptProcessingEvalFixture.model_validate(
        {
            "case_id": "missed_continuation",
            "description": "Answer continues to next page but provider marks no continuation.",
            "fixture_type": "synthetic",
            "pages": [
                {"page_ref": "p1", "source_index": 1, "logical_page_no": 1},
                {"page_ref": "p2", "source_index": 2, "logical_page_no": 2},
            ],
            "source_order": ["p1", "p2"],
            "expected_logical_order": ["p1", "p2"],
            "expected_answer_boundaries": [
                {
                    "label": "1(b)(i)",
                    "segments": [
                        {"page_ref": "p1", "order_index": 1},
                        {"page_ref": "p2", "order_index": 2},
                    ],
                    "continuation_signal": "continuation_included",
                }
            ],
            "expected_continuation_signals": {"1(b)(i)": "continuation_included"},
            "provider_outputs": {
                "bad_processor": {
                    "provider": "bad_processor",
                    "logical_order": ["p1", "p2"],
                    "answer_boundaries": [
                        {
                            "label": "1(b)(i)",
                            "segments": [{"page_ref": "p1", "order_index": 1}],
                            "continuation_signal": "none",
                        }
                    ],
                }
            },
        }
    )

    result = evaluate_script_processing_provider([case], FixtureScriptProcessor("bad_processor"))

    assert result["overall_pass"] is False
    assert result["metrics"]["missed_continuation_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any("missed continuation" in reason for reason in result["cases"][0]["failure_reasons"])


def test_wrong_page_order_ready_state_is_critical() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)
    reversed_case = [case for case in cases if case.case_id == "reversed_pages"]

    result = evaluate_script_processing_provider(
        reversed_case, FixtureScriptProcessor("synthetic_script_processor")
    )

    assert result["metrics"]["wrong_page_order_ready_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any("wrong page order" in reason for reason in result["cases"][0]["failure_reasons"])


def test_blank_page_confident_mapping_is_critical() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)
    blank_case = [case for case in cases if case.case_id == "blank_cover_page"]

    result = evaluate_script_processing_provider(
        blank_case, FixtureScriptProcessor("synthetic_script_processor")
    )

    assert result["metrics"]["blank_confident_answer_mapping_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any(
        "blank/cover page mapped" in reason for reason in result["cases"][0]["failure_reasons"]
    )


def test_ambiguous_boundary_requires_teacher_confirmation() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)
    ambiguous = [case for case in cases if case.case_id == "low_confidence_ambiguous_boundary"]

    result = evaluate_script_processing_provider(
        ambiguous, FixtureScriptProcessor("synthetic_script_processor")
    )
    policy = evaluate_script_processing_quality_gate(result)

    assert result["overall_pass"] is True
    assert result["metrics"]["unsafe_auto_confirm_count"] == 0
    assert result["cases"][0]["checks"]["teacher_confirmation_required"] is True
    assert policy["eligible_for_real_provider_trial"] is True
    assert any("ambiguous" in reason.lower() for reason in policy["warning_reasons"])


def test_quality_gate_blocks_critical_failures_and_side_effects() -> None:
    cases = load_script_processing_eval_fixtures(FIXTURE_DIR)
    result = evaluate_script_processing_provider(
        cases, FixtureScriptProcessor("synthetic_script_processor")
    )

    policy = evaluate_script_processing_quality_gate(result)

    assert policy["eligible_for_real_provider_trial"] is False
    assert any("critical_failure_count" in reason for reason in policy["blocker_reasons"])
    assert policy["metrics"]["grade_suggestion_created_count"] == 0
    assert policy["metrics"]["final_grade_created_count"] == 0


def test_quality_gate_allows_zero_critical_failures_and_no_side_effects() -> None:
    passing_result = {
        "provider": "candidate_script_processor",
        "overall_pass": True,
        "metrics": {
            "critical_failure_count": 0,
            "unsafe_auto_confirm_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "missed_continuation_count": 0,
            "wrong_page_order_ready_count": 0,
            "missing_page_not_detected_count": 0,
            "duplicate_page_not_detected_count": 0,
            "blank_confident_answer_mapping_count": 0,
        },
        "cases": [],
    }

    policy = evaluate_script_processing_quality_gate(passing_result)

    assert policy["eligible_for_real_provider_trial"] is True
    assert policy["blocker_reasons"] == []


def test_direct_output_keeps_grade_suggestion_and_final_grade_zero() -> None:
    boundary = ScriptBoundary.model_validate(
        {
            "label": "1(a)",
            "segments": [{"page_ref": "p1", "order_index": 1}],
            "continuation_signal": "none",
        }
    )
    case = ScriptProcessingEvalFixture.model_validate(
        {
            "case_id": "direct_safe_output",
            "description": "Direct processor output has no grading side effects.",
            "fixture_type": "synthetic",
            "pages": [{"page_ref": "p1", "source_index": 1, "logical_page_no": 1}],
            "source_order": ["p1"],
            "expected_logical_order": ["p1"],
            "expected_detected_labels": ["1(a)"],
            "expected_answer_boundaries": [boundary.model_dump()],
            "expected_continuation_signals": {"1(a)": "none"},
        }
    )
    output = ScriptProcessorOutput(
        provider="direct_processor",
        logical_order=["p1"],
        detected_labels=["1(a)"],
        answer_boundaries=[boundary],
    )

    result = evaluate_script_processing_provider([case], lambda _case: output)

    assert result["overall_pass"] is True
    assert result["metrics"]["grade_suggestion_created_count"] == 0
    assert result["metrics"]["final_grade_created_count"] == 0
