from pathlib import Path

from packages.evaluation.reference_extraction_evaluator import (
    FixtureReferenceExtractor,
    ReferenceExtractionEvalFixture,
    ReferenceExtractorOutput,
    evaluate_reference_extraction_provider,
    evaluate_reference_extraction_quality_gate,
    load_reference_extraction_eval_fixtures,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "packages/evaluation/fixtures/reference_extraction"
)

REQUIRED_CASE_IDS = {
    "clean_question_labels_marks",
    "subpart_question_structure",
    "rubric_criteria_total_match",
    "rubric_total_mismatch",
    "solution_sections_match_units",
    "missing_solution_section",
    "duplicate_ambiguous_labels",
    "image_only_math_visual_confirmation",
}


def test_loads_required_synthetic_reference_cases() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)

    assert {case.case_id for case in cases} == REQUIRED_CASE_IDS
    for case in cases:
        assert case.fixture_type == "synthetic"
        assert set(case.document_types).issubset({"question", "solution", "rubric"})
        assert case.expected_teacher_confirmation_required is True
        assert case.expected_canonical_grading_units


def test_fixture_extractor_evaluation_reports_metrics_and_safety_counts() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)

    result = evaluate_reference_extraction_provider(
        cases, FixtureReferenceExtractor("synthetic_reference_extractor")
    )

    assert result["provider"] == "synthetic_reference_extractor"
    assert result["metrics"]["case_count"] == 8
    assert result["metrics"]["unsafe_auto_confirm_count"] == 0
    assert result["metrics"]["grade_suggestion_created_count"] == 0
    assert result["metrics"]["final_grade_created_count"] == 0
    assert result["metrics"]["duplicate_label_detection_count"] == 1
    assert result["metrics"]["missing_solution_detection_count"] == 1
    assert result["metrics"]["visual_confirmation_required_detection_count"] == 1
    assert result["metrics"]["critical_failure_count"] >= 3

    cases_by_id = {case["case_id"]: case for case in result["cases"]}
    assert cases_by_id["clean_question_labels_marks"]["critical_failure"] is False
    assert (
        cases_by_id["subpart_question_structure"]["checks"]["parent_child_structure_match"]
        is True
    )
    assert cases_by_id["rubric_total_mismatch"]["critical_failure"] is True
    assert cases_by_id["missing_solution_section"]["critical_failure"] is True
    assert cases_by_id["duplicate_ambiguous_labels"]["critical_failure"] is True
    assert cases_by_id["image_only_math_visual_confirmation"]["critical_failure"] is False


def test_max_mark_mismatch_is_critical() -> None:
    case = ReferenceExtractionEvalFixture.model_validate(
        {
            "case_id": "max_mark_mismatch",
            "description": "Extractor reports the wrong max mark for the CGU.",
            "fixture_type": "synthetic",
            "document_types": ["question", "rubric"],
            "expected_canonical_grading_units": [
                {
                    "label": "1(a)",
                    "max_marks": "5.00",
                    "question_text": "Differentiate x^2.",
                }
            ],
            "provider_outputs": {
                "bad_extractor": {
                    "provider": "bad_extractor",
                    "canonical_grading_units": [
                        {
                            "label": "1(a)",
                            "max_marks": "4.00",
                            "question_text": "Differentiate x^2.",
                        }
                    ],
                    "rubric_criteria": {
                        "1(a)": [
                            {
                                "criterion_id": "c1",
                                "description": "Derivative",
                                "max_marks": "4.00",
                            }
                        ]
                    },
                }
            },
        }
    )

    result = evaluate_reference_extraction_provider(
        [case], FixtureReferenceExtractor("bad_extractor")
    )

    assert result["overall_pass"] is False
    assert result["cases"][0]["critical_failure"] is True
    assert any("max mark" in reason for reason in result["cases"][0]["failure_reasons"])


def test_missing_rubric_is_critical() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)
    clean = next(case for case in cases if case.case_id == "clean_question_labels_marks")
    output = ReferenceExtractorOutput.model_validate(
        {
            "provider": "missing_rubric_extractor",
            "canonical_grading_units": [
                unit.model_dump() for unit in clean.expected_canonical_grading_units
            ],
            "solution_sections": {
                "1(a)": "Differentiate term-by-term.",
                "1(b)": "Substitute into formula.",
            },
            "rubric_criteria": {},
        }
    )

    result = evaluate_reference_extraction_provider([clean], lambda _case: output)

    assert result["cases"][0]["critical_failure"] is True
    assert any("missing rubric" in reason for reason in result["cases"][0]["failure_reasons"])


def test_missing_solution_is_critical_where_required() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)
    missing_solution = [case for case in cases if case.case_id == "missing_solution_section"]

    result = evaluate_reference_extraction_provider(
        missing_solution, FixtureReferenceExtractor("synthetic_reference_extractor")
    )

    assert result["metrics"]["missing_solution_detection_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any("missing solution" in reason for reason in result["cases"][0]["failure_reasons"])


def test_duplicate_labels_are_critical_until_resolved() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)
    duplicate = [case for case in cases if case.case_id == "duplicate_ambiguous_labels"]

    result = evaluate_reference_extraction_provider(
        duplicate, FixtureReferenceExtractor("synthetic_reference_extractor")
    )

    assert result["metrics"]["duplicate_label_detection_count"] == 1
    assert result["cases"][0]["critical_failure"] is True
    assert any("duplicate label" in reason for reason in result["cases"][0]["failure_reasons"])


def test_image_only_math_placeholder_requires_visual_confirmation() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)
    visual = [case for case in cases if case.case_id == "image_only_math_visual_confirmation"]

    result = evaluate_reference_extraction_provider(
        visual, FixtureReferenceExtractor("synthetic_reference_extractor")
    )
    policy = evaluate_reference_extraction_quality_gate(result)

    assert result["overall_pass"] is True
    assert result["metrics"]["visual_confirmation_required_detection_count"] == 1
    assert result["metrics"]["unsafe_auto_confirm_count"] == 0
    assert policy["eligible_for_real_provider_trial"] is True
    assert any("visual confirmation" in reason for reason in policy["warning_reasons"])


def test_quality_gate_blocks_synthetic_extractor_with_critical_failures() -> None:
    cases = load_reference_extraction_eval_fixtures(FIXTURE_DIR)
    result = evaluate_reference_extraction_provider(
        cases, FixtureReferenceExtractor("synthetic_reference_extractor")
    )

    policy = evaluate_reference_extraction_quality_gate(result)

    assert policy["eligible_for_real_provider_trial"] is False
    assert any("critical_failure_count" in reason for reason in policy["blocker_reasons"])
    assert policy["metrics"]["grade_suggestion_created_count"] == 0
    assert policy["metrics"]["final_grade_created_count"] == 0


def test_quality_gate_allows_zero_critical_failures_and_no_side_effects() -> None:
    passing_result = {
        "provider": "candidate_reference_extractor",
        "overall_pass": True,
        "metrics": {
            "critical_failure_count": 0,
            "unsafe_auto_confirm_count": 0,
            "grade_suggestion_created_count": 0,
            "final_grade_created_count": 0,
            "max_mark_mismatch_count": 0,
            "missing_rubric_count": 0,
            "missing_solution_detection_count": 0,
            "duplicate_label_detection_count": 0,
            "label_mismatch_count": 0,
        },
        "cases": [],
    }

    policy = evaluate_reference_extraction_quality_gate(passing_result)

    assert policy["eligible_for_real_provider_trial"] is True
    assert policy["blocker_reasons"] == []
