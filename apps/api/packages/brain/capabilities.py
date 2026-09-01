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
    MOCK = "mock"
    LOCAL = "local"
    CLOUD = "cloud"
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
    image_input_mode: BrainImageInputMode = BrainImageInputMode.NONE
    managed_local_phase: str | None = None

    def supports(self, capability: BrainCapability) -> bool:
        return capability in self.capabilities

    @property
    def is_real(self) -> bool:
        return self.location is not BrainExecutionLocation.MOCK

    @property
    def is_managed_local(self) -> bool:
        return self.location is BrainExecutionLocation.LOCAL and bool(
            self.managed_local_phase
        )
