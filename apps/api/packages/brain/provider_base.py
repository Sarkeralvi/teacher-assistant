from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from packages.brain.schemas import GradeSuggestionOutput


class BrainProvider(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
    ) -> GradeSuggestionOutput:
        """Return a validated structured grading suggestion."""
