import time
from decimal import Decimal
from typing import Any

from packages.brain.mock_provider import MockBrainProvider
from packages.brain.prompt_registry import get_prompt_version
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


class BrainAdapter:
    def __init__(self, provider: BrainProvider | None = None) -> None:
        self.provider = provider or MockBrainProvider()

    def grade_answer_region(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        policy: ModelPolicy = ModelPolicy.MOCK_GRADING,
    ) -> GradeSuggestionOutput:
        prompt_version = get_prompt_version(policy)
        start = time.perf_counter()
        output = self.provider.grade(
            question_text=question_text,
            question_total_marks=question_total_marks,
            rubric_json=rubric_json,
            answer_image_path=answer_image_path,
            prompt_version=prompt_version,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        validated = GradeSuggestionOutput.model_validate(output.model_dump())
        return validated.model_copy(update={"latency_ms": latency_ms})
