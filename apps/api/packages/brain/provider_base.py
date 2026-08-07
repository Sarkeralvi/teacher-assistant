from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


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
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.MOCK_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        """Return a validated structured grading suggestion."""

    def extract_questions_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support question extraction"
        )

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support rubric extraction"
        )

    def extract_questions_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support OCR-text question extraction"
        )

    def extract_rubric_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support OCR-text rubric extraction"
        )

    def verify_available_model(self) -> None:
        """Optionally verify a configured provider without running inference."""
        return None
