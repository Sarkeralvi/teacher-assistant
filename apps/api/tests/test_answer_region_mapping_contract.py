from decimal import Decimal
from typing import Literal

import pytest
from pydantic import ValidationError

from app.schemas import (
    AnswerRegionSuggestionAcceptRequest,
    AnswerRegionSuggestionGroupResponse,
    DraftAnswerRegionSuggestionGroup,
    DraftAnswerRegionSuggestionSegment,
)

ContinuationRisk = Literal[
    "none",
    "possible_continuation",
    "continuation_included",
    "continuation_not_needed",
    "ambiguous",
]


def make_segment(
    *,
    page_id: int = 11,
    order_index: int = 1,
    is_primary: bool = False,
    continuation_risk: ContinuationRisk = "none",
) -> DraftAnswerRegionSuggestionSegment:
    return DraftAnswerRegionSuggestionSegment(
        page_id=page_id,
        order_index=order_index,
        x=Decimal("10"),
        y=Decimal("20"),
        width=Decimal("300"),
        height=Decimal("120"),
        is_primary=is_primary,
        confidence=Decimal("0.72"),
        continuation_risk=continuation_risk,
        warnings=[],
    )


def test_multisegment_suggestion_group_can_represent_ordered_segments() -> None:
    group = DraftAnswerRegionSuggestionGroup(
        draft_id="sub-7-q-1b-multisegment",
        suggested_question_id=42,
        suggested_question_no="1(b)",
        provider="deterministic_layout",
        source="deterministic_layout",
        confidence=Decimal("0.68"),
        continuation_risk="possible_continuation",
        segments=[
            make_segment(page_id=11, order_index=1, is_primary=True),
            make_segment(
                page_id=12,
                order_index=2,
                continuation_risk="possible_continuation",
            ),
        ],
        warnings=["possible answer continuation on next page"],
        reason="Question span likely crosses the page break.",
    )

    assert group.needs_review is True
    assert group.needs_teacher_confirmation is True
    assert group.requires_full_answer_confirmation is True
    assert group.continuation_risk == "possible_continuation"
    assert [segment.page_id for segment in group.segments] == [11, 12]
    assert [segment.order_index for segment in group.segments] == [1, 2]
    assert sum(segment.is_primary for segment in group.segments) == 1


def test_multisegment_suggestion_does_not_create_answer_region_until_accepted() -> None:
    response = AnswerRegionSuggestionGroupResponse(
        submission_id=7,
        provider="deterministic_layout",
        source="deterministic_layout",
        message="Draft mapping suggestions generated for teacher review.",
        suggestion_groups=[
            DraftAnswerRegionSuggestionGroup(
                draft_id="sub-7-q-1-draft",
                suggested_question_id=42,
                suggested_question_no="1",
                provider="deterministic_layout",
                source="deterministic_layout",
                confidence=Decimal("0.80"),
                segments=[make_segment(is_primary=True)],
            )
        ],
    )

    dumped = response.model_dump()
    assert response.needs_review is True
    assert "answer_region_id" not in dumped
    assert "final_grade_id" not in dumped
    assert "grade_suggestion_id" not in dumped
    assert dumped["suggestion_groups"][0]["needs_teacher_confirmation"] is True


def test_accepting_multisegment_suggestion_creates_one_logical_region_with_ordered_segments() -> None:  # noqa: E501
    request = AnswerRegionSuggestionAcceptRequest(
        draft_id="sub-7-q-1b-multisegment",
        question_id=42,
        full_answer_confirmed=True,
        segments=[
            make_segment(page_id=11, order_index=1, is_primary=True),
            make_segment(page_id=12, order_index=2),
        ],
    )

    assert request.full_answer_confirmed is True
    assert request.question_id == 42
    assert [segment.order_index for segment in request.segments] == [1, 2]
    assert [segment.page_id for segment in request.segments] == [11, 12]


def test_possible_continuation_requires_full_answer_confirmation_before_grading() -> None:
    group = DraftAnswerRegionSuggestionGroup(
        draft_id="sub-7-q-1b-continuation-risk",
        suggested_question_id=42,
        suggested_question_no="1(b)",
        provider="deterministic_layout",
        source="deterministic_layout",
        confidence=Decimal("0.62"),
        continuation_risk="possible_continuation",
        segments=[
            make_segment(
                page_id=11,
                order_index=1,
                is_primary=True,
                continuation_risk="possible_continuation",
            )
        ],
        warnings=["teacher must confirm whether the answer continues"],
    )

    assert group.continuation_risk == "possible_continuation"
    assert group.requires_full_answer_confirmation is True
    assert group.needs_teacher_confirmation is True
    assert any("continues" in warning for warning in group.warnings)


def test_blank_bottom_page_does_not_force_continuation_blocker() -> None:
    group = DraftAnswerRegionSuggestionGroup(
        draft_id="sub-7-q-2-no-continuation",
        suggested_question_id=43,
        suggested_question_no="2",
        provider="deterministic_layout",
        source="deterministic_layout",
        confidence=Decimal("0.76"),
        continuation_risk="continuation_not_needed",
        segments=[
            make_segment(
                page_id=13,
                order_index=1,
                is_primary=True,
                continuation_risk="continuation_not_needed",
            )
        ],
        warnings=[],
    )

    assert group.continuation_risk == "continuation_not_needed"
    assert group.warnings == []


def test_suggestion_group_rejects_duplicate_segment_order_indexes() -> None:
    with pytest.raises(ValidationError, match="order_index values must be unique"):
        DraftAnswerRegionSuggestionGroup(
            draft_id="bad-order",
            suggested_question_id=42,
            suggested_question_no="1",
            confidence=Decimal("0.50"),
            segments=[
                make_segment(order_index=1, is_primary=True),
                make_segment(order_index=1),
            ],
        )


def test_suggestion_group_requires_exactly_one_primary_segment() -> None:
    with pytest.raises(ValidationError, match="exactly one suggestion segment must be primary"):
        DraftAnswerRegionSuggestionGroup(
            draft_id="bad-primary",
            suggested_question_id=42,
            suggested_question_no="1",
            confidence=Decimal("0.50"),
            segments=[make_segment(order_index=1), make_segment(order_index=2)],
        )
