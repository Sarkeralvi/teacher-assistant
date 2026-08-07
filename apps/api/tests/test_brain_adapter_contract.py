from decimal import Decimal

import pytest

from app.core.config import Settings
from packages.brain.adapter import (
    BrainAdapter,
    BrainProviderConfigurationError,
)
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
    assert "marking_policy:general" in validated.review_flags
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


@pytest.mark.parametrize("provider", ["openai", "gemini", "codex_cli", "llama_cpp_qwen"])
def test_real_provider_kill_switch_is_enforced_before_initialization(provider: str) -> None:
    settings = Settings(
        BRAIN_PROVIDER=provider,
        BRAIN_ALLOW_REAL_PROVIDERS=False,
        OPENAI_API_KEY="sk-example",
        GEMINI_API_KEY="key-example",
        LOCAL_QWEN_ENABLED=True,
        LOCAL_QWEN_API_KEY="key-local-example",
    )

    with pytest.raises(
        BrainProviderConfigurationError,
        match="BRAIN_ALLOW_REAL_PROVIDERS must be true",
    ):
        BrainAdapter.from_settings(settings)


def test_marking_policy_prompt_text_is_distinct_for_each_policy() -> None:
    from packages.brain.prompt_registry import build_grading_prompt

    tough_prompt = "\n".join(
        message["content"]
        for message in build_grading_prompt(
            question_text="Explain photosynthesis.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/answer_regions/region.png",
            image_input_enabled=False,
            marking_policy="tough",
        )
    )
    general_prompt = "\n".join(
        message["content"]
        for message in build_grading_prompt(
            question_text="Explain photosynthesis.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/answer_regions/region.png",
            image_input_enabled=False,
            marking_policy="general",
        )
    )
    easy_prompt = "\n".join(
        message["content"]
        for message in build_grading_prompt(
            question_text="Explain photosynthesis.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/answer_regions/region.png",
            image_input_enabled=False,
            marking_policy="easy",
        )
    )

    assert all(
        fragment in tough_prompt
        for fragment in (
            "Apply the rubric criterion-by-criterion",
            "Award full marks only for complete, correct, and well-justified answers.",
            "A correct final answer with little or no working should receive limited credit",
            "bias toward the lower end of the rubric range",
        )
    )
    assert "General marking" in general_prompt
    assert all(
        fragment in general_prompt
        for fragment in (
            "Award marks fairly for correct methods and correct reasoning.",
            "Give partial credit when the method is mostly correct but a step is missing or",
            "choose the middle of the plausible rubric range",
        )
    )
    assert "Easy marking" in easy_prompt
    assert all(
        fragment in easy_prompt
        for fragment in (
            "Award partial credit generously when the answer shows real understanding or visible",
            "Give the benefit of the doubt when reasoning is partially visible",
            "A correct final answer with weak working can receive more credit",
            "bias toward the higher end of the rubric range",
        )
    )


def test_grading_prompt_includes_handwritten_math_statistics_guidance() -> None:
    from packages.brain.prompt_registry import build_grading_prompt

    prompt = "\n".join(
        message["content"]
        for message in build_grading_prompt(
            question_text="Canonical grading unit: 1(b)(i), max marks: 6. Bayes problem.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/answer_regions/region.png",
            image_input_enabled=True,
            marking_policy="general",
        )
    )

    assert "exact canonical grading unit and max marks" in prompt
    assert "active rubric and model answer as primary evidence" in prompt
    assert "formula choice, substitution, and valid final answer" in prompt
    assert "Do not over-penalize messy handwriting" in prompt
    assert "conceptual error" in prompt
    assert "arithmetic slip" in prompt
    assert "notation/presentation issue" in prompt
    assert "correct setup but missing final simplification" in prompt
    assert "Bayes" in prompt
    assert "do not automatically slash the score" in prompt
    assert "Set needs_review=true" in prompt
    assert "Do not create a final grade" in prompt


def test_grading_prompt_includes_bayes_probability_score_band_guidance() -> None:
    from packages.brain.prompt_registry import build_grading_prompt

    prompt = "\n".join(
        message["content"]
        for message in build_grading_prompt(
            question_text="Canonical grading unit: 1(b)(i), max marks: 6. Bayes theorem.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/answer_regions/region.png",
            image_input_enabled=True,
            marking_policy="general",
        )
    )

    assert "Bayes/probability score-band guidance for 6-mark subparts" in prompt
    assert "5-6 marks" in prompt
    assert "Bayes theorem or equivalent conditional-probability formula" in prompt
    assert "correct identification of target event and evidence event" in prompt
    assert "correct denominator/total probability expansion" in prompt
    assert "plausible numerator/substitution or final posterior value/expression" in prompt
    assert "Messy handwriting, compressed arithmetic, or imperfect notation alone" in prompt
    assert "3-4 marks" in prompt
    assert "denominator missing one branch" in prompt
    assert "0-2 marks" in prompt
    assert "wrong conditional direction" in prompt
    assert "do not automatically slash the score" in prompt


def test_codex_cli_prompt_preserves_policy_instruction_without_image_data() -> None:
    from packages.brain.codex_cli_provider import CodexCliProvider
    from packages.brain.prompt_registry import build_grading_prompt

    messages = build_grading_prompt(
        question_text="Explain photosynthesis.",
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/answer_regions/region.png",
        image_input_enabled=False,
        marking_policy="easy",
    )
    prompt = CodexCliProvider()._build_prompt(
        question_text="Explain photosynthesis.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        messages=messages,
        image_input_enabled=False,
        marking_policy="easy",
    )

    assert "Marking policy: easy" in prompt
    assert "Easy marking" in prompt
    assert "Do not change max_score or criterion max_marks because of marking policy." in prompt
    assert "marking_policy:easy" in prompt
    assert "data:image" not in prompt
