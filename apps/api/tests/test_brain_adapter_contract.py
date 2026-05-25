from decimal import Decimal

from packages.brain.adapter import BrainAdapter
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.prompt_registry import get_prompt_version
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


def rubric_payload() -> dict[str, object]:
    return {
        "total_marks": "10.00",
        "criteria": [
            {
                "id": "concept",
                "name": "Core concept",
                "description": "Identifies the correct principle or idea.",
                "max_marks": "3.00",
            },
            {
                "id": "working",
                "name": "Working",
                "description": "Shows valid working.",
                "max_marks": "7.00",
            },
        ],
    }


def test_mock_brain_adapter_returns_schema_valid_mock_grade_suggestion() -> None:
    adapter = BrainAdapter(provider=MockBrainProvider())

    result = adapter.grade_answer_region(
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/answer_regions/submission_1/region_mock.png",
    )

    validated = GradeSuggestionOutput.model_validate(result.model_dump())
    assert validated.score == Decimal("0")
    assert validated.max_score == Decimal("10.00")
    assert validated.confidence == Decimal("0")
    assert validated.needs_review is True
    assert validated.model_provider == "mock"
    assert validated.model_name == "mock-grader-v1"
    assert validated.prompt_version == get_prompt_version(ModelPolicy.MOCK_GRADING)
    assert "mock_provider" in validated.review_flags
    assert "teacher_review_required" in validated.review_flags
    assert "No real answer understanding" in validated.detected_answer_summary
    assert [item.criterion_id for item in validated.rubric_breakdown] == ["concept", "working"]
    awarded_marks = [item.awarded_marks for item in validated.rubric_breakdown]
    assert awarded_marks == [Decimal("0"), Decimal("0")]


def test_mock_output_cannot_be_mistaken_for_real_grading() -> None:
    output = MockBrainProvider().grade(
        question_text="What is 2+2?",
        question_total_marks=Decimal("4.00"),
        rubric_json={
            "total_marks": "4.00",
            "criteria": [
                {
                    "id": "answer",
                    "name": "Answer",
                    "description": "Correct answer.",
                    "max_marks": "4.00",
                }
            ],
        },
        answer_image_path="unused.png",
        prompt_version="mock-grading-v1",
    )

    assert output.model_provider == "mock"
    assert output.model_name == "mock-grader-v1"
    assert output.confidence == Decimal("0")
    assert output.needs_review is True
    assert output.score == Decimal("0")
    assert (
        output.feedback_to_student
        == "This is a mock grading suggestion for pipeline validation only."
    )
    assert "mock_provider" in output.review_flags
