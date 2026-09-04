from decimal import Decimal
from typing import Any

from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainTransport,
)
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.schemas_qwen38 import (
    VisualPageMappingOutput,
    VisualPageTranscriptOutput,
    VisualTranscriptionOutput,
)


class BrainProvider:
    provider_name: str
    model_name: str
    capabilities: frozenset[BrainCapability] = frozenset()
    execution_location: BrainExecutionLocation = BrainExecutionLocation.CLOUD
    transport: BrainTransport = BrainTransport.HTTP
    image_input_mode: BrainImageInputMode = BrainImageInputMode.NONE
    managed_local_phase: str | None = None

    def supports(self, capability: BrainCapability) -> bool:
        return capability in self.capabilities

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
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support grading"
        )

    def extract_questions_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support question extraction"
        )

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support rubric extraction"
        )

    def extract_questions_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support OCR-text question extraction"
        )

    def extract_rubric_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support OCR-text rubric extraction"
        )

    def extract_reference_bundle_from_ocr_documents(
        self, documents: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support bundled reference extraction"
        )

    def map_submission_answers_from_ocr_pages(
        self,
        *,
        pages: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support submission answer mapping"
        )

    def prepare_student_answers_from_ocr_candidates(
        self,
        *,
        answers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support OCR answer preparation"
        )

    def extract_reference_bundle_from_images(
        self,
        *,
        documents: dict[str, list[tuple[bytes, str, int]]],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support visual reference extraction"
        )

    def map_page_answer_regions(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        question_labels: list[str],
        question_references: list[dict[str, Any]] | None = None,
        open_continuations: list[str] | None = None,
        boundary_verification: bool = False,
    ) -> VisualPageMappingOutput:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support visual mapping"
        )

    def read_page(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        question_labels: list[str],
        question_references: list[dict[str, Any]] | None = None,
        open_continuations: list[str] | None = None,
    ) -> VisualPageTranscriptOutput:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support visual page reading"
        )

    def transcribe_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support visual transcription"
        )

    def transcribe_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support visual transcription"
        )

    def repair_transcription_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        rejected_transcript: str,
        source_editing_marks: list[dict[str, Any]] | None = None,
    ) -> VisualTranscriptionOutput:
        raise NotImplementedError(
            f"Provider {self.provider_name} does not support transcription repair"
        )

    def verify_available_model(self) -> None:
        """Optionally verify a configured provider without running inference."""
        return None
