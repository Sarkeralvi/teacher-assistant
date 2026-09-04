from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrainCapability(StrEnum):
    GRADING = "grading"
    QUESTION_PDF_EXTRACTION = "question_pdf_extraction"
    RUBRIC_PDF_EXTRACTION = "rubric_pdf_extraction"
    OCR_REFERENCE_EXTRACTION = "ocr_reference_extraction"
    OCR_ANSWER_MAPPING = "ocr_answer_mapping"
    OCR_ANSWER_PREPARATION = "ocr_answer_preparation"
    VISUAL_REFERENCE_EXTRACTION = "visual_reference_extraction"
    VISUAL_MAPPING = "visual_mapping"
    VISUAL_PAGE_READ = "visual_page_read"
    VISUAL_TRANSCRIPTION = "visual_transcription"
    TRANSCRIPTION_REPAIR = "transcription_repair"


class BrainExecutionLocation(StrEnum):
    """Privacy-relevant destination where provider data is processed."""

    MOCK = "mock"
    LOCAL = "local"
    CLOUD = "cloud"


class BrainTransport(StrEnum):
    """Mechanism used to invoke a provider, independent of data destination."""

    IN_PROCESS = "in_process"
    HTTP = "http"
    CLI = "cli"


class BrainImageInputMode(StrEnum):
    NONE = "none"
    DATA_URL = "data_url"
    FILE_PATH = "file_path"


@dataclass(frozen=True)
class BrainProviderRuntime:
    provider: str
    model: str
    location: BrainExecutionLocation
    capabilities: frozenset[BrainCapability]
    transport: BrainTransport = BrainTransport.HTTP
    image_input_mode: BrainImageInputMode = BrainImageInputMode.NONE
    managed_local_phase: str | None = None

    def supports(self, capability: BrainCapability) -> bool:
        return capability in self.capabilities

    @property
    def is_real(self) -> bool:
        return self.location is not BrainExecutionLocation.MOCK

    @property
    def is_cli(self) -> bool:
        return self.transport is BrainTransport.CLI

    @property
    def status_location(self) -> str:
        """Preserve the existing status label while destination is split out."""

        return self.transport.value if self.is_cli else self.location.value

    @property
    def is_managed_local(self) -> bool:
        return self.location is BrainExecutionLocation.LOCAL and bool(
            self.managed_local_phase
        )


BRAIN_CAPABILITY_METHODS: dict[BrainCapability, str] = {
    BrainCapability.GRADING: "grade",
    BrainCapability.QUESTION_PDF_EXTRACTION: "extract_questions_from_pdf",
    BrainCapability.RUBRIC_PDF_EXTRACTION: "extract_rubric_from_pdf",
    BrainCapability.OCR_REFERENCE_EXTRACTION: "extract_reference_bundle_from_ocr_documents",
    BrainCapability.OCR_ANSWER_MAPPING: "map_submission_answers_from_ocr_pages",
    BrainCapability.OCR_ANSWER_PREPARATION: "prepare_student_answers_from_ocr_candidates",
    BrainCapability.VISUAL_REFERENCE_EXTRACTION: "extract_reference_bundle_from_images",
    BrainCapability.VISUAL_MAPPING: "map_page_answer_regions",
    BrainCapability.VISUAL_PAGE_READ: "read_page",
    BrainCapability.VISUAL_TRANSCRIPTION: "transcribe_images",
    BrainCapability.TRANSCRIPTION_REPAIR: "repair_transcription_images",
}
