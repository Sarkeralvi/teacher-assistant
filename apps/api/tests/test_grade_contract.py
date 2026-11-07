"""The provider-neutral grade contract enforced by the adapter for every real provider."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from packages.brain.adapter import BrainAdapter
from packages.brain.capabilities import BrainCapability, BrainExecutionLocation
from packages.brain.grade_contract import (
    DEPENDENT_CREDIT_FLAG,
    MAXIMUM_CHANGED_FLAG,
    RUBRIC_SHAPE_FLAG,
    UNSUPPORTED_EVIDENCE_FLAG,
    enforce_grade_contract,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput

RUBRIC: dict[str, Any] = {
    "criteria": [
        {"id": "c1", "name": "Setup", "max_marks": 2},
        {"id": "c2", "name": "Result", "max_marks": 2, "depends_on": ["c1"]},
    ]
}
ANSWER = "Let x = 2\nthen y = 4"


def _grade(**overrides: Any) -> GradeSuggestionOutput:
    breakdown = overrides.pop(
        "breakdown",
        [
            {
                "criterion_id": "c1",
                "criterion": "Setup",
                "max_marks": "2",
                "awarded_marks": "2",
                "reason": "ok",
                "evidence": "Let x = 2",
                "confidence": "0.9",
            },
            {
                "criterion_id": "c2",
                "criterion": "Result",
                "max_marks": "2",
                "awarded_marks": "2",
                "reason": "ok",
                "evidence": "y = 4",
                "confidence": "0.9",
            },
        ],
    )
    payload: dict[str, Any] = {
        "score": str(sum(Decimal(item["awarded_marks"]) for item in breakdown)),
        "max_score": "4",
        "confidence": "0.9",
        "needs_review": True,
        "rubric_breakdown": breakdown,
        "detected_answer_summary": "summary",
        "major_errors": [],
        "feedback_to_student": "feedback",
        "review_flags": ["teacher_review_required"],
        "model_provider": "test",
        "model_name": "test-model",
        "prompt_version": "v",
    }
    payload.update(overrides)
    return GradeSuggestionOutput.model_validate(payload)


def _enforce(output: GradeSuggestionOutput, *, total: str = "4", rubric=RUBRIC, answer=ANSWER):
    return enforce_grade_contract(
        output,
        question_total_marks=Decimal(total),
        rubric_json=rubric,
        student_answer_text=answer,
    )


def test_clean_grade_passes_unchanged() -> None:
    output = _grade()
    assert _enforce(output) is output


def test_changed_question_maximum_is_flagged_and_never_clean() -> None:
    checked = _enforce(_grade(), total="5")
    assert MAXIMUM_CHANGED_FLAG in checked.review_flags
    assert checked.confidence <= Decimal("0.5")


@pytest.mark.parametrize(
    ("criterion_id", "max_marks"),
    [("c9", "2"), ("c2", "3")],
)
def test_changed_rubric_shape_is_flagged_and_never_clean(
    criterion_id: str, max_marks: str
) -> None:
    breakdown = [
        {
            "criterion_id": "c1",
            "criterion": "Setup",
            "max_marks": "2",
            "awarded_marks": "0",
            "reason": "r",
            "evidence": None,
            "confidence": "0.5",
        },
        {
            "criterion_id": criterion_id,
            "criterion": "Result",
            "max_marks": max_marks,
            "awarded_marks": "0",
            "reason": "r",
            "evidence": None,
            "confidence": "0.5",
        },
    ]
    output = _grade(breakdown=breakdown, max_score="4" if max_marks == "2" else "5")
    checked = _enforce(output, total="4" if max_marks == "2" else "5")
    assert RUBRIC_SHAPE_FLAG in checked.review_flags
    assert checked.confidence <= Decimal("0.5")


def test_missing_rubric_criterion_is_flagged() -> None:
    breakdown = [
        {
            "criterion_id": "c1",
            "criterion": "Setup",
            "max_marks": "2",
            "awarded_marks": "2",
            "reason": "r",
            "evidence": "Let x = 2",
            "confidence": "0.9",
        }
    ]
    output = _grade(breakdown=breakdown, max_score="4")
    checked = _enforce(output)
    assert RUBRIC_SHAPE_FLAG in checked.review_flags
    assert checked.score == Decimal("2")


def test_criterion_ids_are_matched_ignoring_case_and_spacing() -> None:
    output = _grade()
    output.rubric_breakdown[0].criterion_id = " C1 "
    checked = _enforce(output)
    assert [item.criterion_id for item in checked.rubric_breakdown] == ["c1", "c2"]


def test_credit_without_verbatim_student_evidence_is_removed() -> None:
    output = _grade()
    output.rubric_breakdown[1].evidence = "y equals four (from the model answer)"
    checked = _enforce(output)
    assert checked.rubric_breakdown[1].awarded_marks == Decimal("0")
    assert checked.score == Decimal("2")
    assert checked.confidence <= Decimal("0.75")
    assert UNSUPPORTED_EVIDENCE_FLAG in checked.review_flags
    # The model's own total stays visible next to the checked score.
    assert "model_score_before_checks:4" in checked.review_flags


def test_dependent_credit_needs_full_prerequisite_marks() -> None:
    output = _grade()
    output.rubric_breakdown[0].awarded_marks = Decimal("1")
    output.score = Decimal("3")
    checked = _enforce(output)
    assert checked.rubric_breakdown[1].awarded_marks == Decimal("0")
    assert checked.score == Decimal("1")
    assert DEPENDENT_CREDIT_FLAG in checked.review_flags


def test_follow_through_rubrics_keep_dependent_credit() -> None:
    rubric = {
        "criteria": [
            {"id": "c1", "max_marks": 2},
            {"id": "c2", "max_marks": 2, "depends_on": ["c1"], "allow_follow_through": True},
        ]
    }
    output = _grade()
    output.rubric_breakdown[0].awarded_marks = Decimal("1")
    output.score = Decimal("3")
    assert _enforce(output, rubric=rubric).score == Decimal("3")


@pytest.mark.parametrize("answer", ["", "   ", None])
def test_text_only_grade_with_no_answer_text_keeps_no_credit(answer: str | None) -> None:
    checked = enforce_grade_contract(
        _grade(),
        question_total_marks=Decimal("4"),
        rubric_json=RUBRIC,
        student_answer_text=answer,
        evidence_text_required=True,
    )
    assert checked.score == Decimal("0")
    assert UNSUPPORTED_EVIDENCE_FLAG in checked.review_flags


def test_image_grade_without_text_is_not_evidence_checked() -> None:
    output = _grade()
    checked = enforce_grade_contract(
        output,
        question_total_marks=Decimal("4"),
        rubric_json=RUBRIC,
        student_answer_text=None,
        evidence_text_required=False,
    )
    assert checked.score == output.score


def test_trivial_quotes_do_not_count_as_evidence() -> None:
    output = _grade()
    output.rubric_breakdown[1].evidence = "4"
    checked = _enforce(output)
    assert checked.rubric_breakdown[1].awarded_marks == Decimal("0")
    short = _grade()
    short.rubric_breakdown[0].evidence = "x=2"
    short.rubric_breakdown[1].evidence = "x=2"
    assert _enforce(short, answer="x=2", rubric={"criteria": []}).score == short.score


def test_contract_never_raises_a_mark() -> None:
    output = _grade()
    output.rubric_breakdown[0].evidence = "not in answer"
    output.rubric_breakdown[1].evidence = "also not in answer"
    checked = _enforce(output)
    assert checked.score <= output.score


# ---------------------------------------------------------------------------
# Adapter integration: real providers only
# ---------------------------------------------------------------------------


class _CloudProvider(BrainProvider):
    provider_name = "fake_cloud"
    model_name = "fake-model"
    execution_location = BrainExecutionLocation.CLOUD
    capabilities = frozenset({BrainCapability.GRADING})

    def __init__(self, output: GradeSuggestionOutput) -> None:
        self._output = output

    def grade(self, **_: Any) -> GradeSuggestionOutput:
        return self._output


def test_adapter_applies_contract_to_real_providers() -> None:
    output = _grade()
    output.rubric_breakdown[1].evidence = "invented"
    adapter = BrainAdapter(_CloudProvider(output))
    result = adapter.grade_answer_region(
        question_text="q",
        question_total_marks=Decimal("4"),
        rubric_json=RUBRIC,
        answer_image_path="[image input disabled]",
        student_answer_text=ANSWER,
    )
    assert result.score == Decimal("2")
    assert UNSUPPORTED_EVIDENCE_FLAG in result.review_flags


def test_adapter_flags_a_real_grade_that_changes_the_maximum() -> None:
    adapter = BrainAdapter(_CloudProvider(_grade()))
    result = adapter.grade_answer_region(
        question_text="q",
        question_total_marks=Decimal("5"),
        rubric_json=RUBRIC,
        answer_image_path="[image input disabled]",
        student_answer_text=ANSWER,
    )
    assert MAXIMUM_CHANGED_FLAG in result.review_flags
    assert result.confidence <= Decimal("0.5")
