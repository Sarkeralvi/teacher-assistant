"""
Provider contract definitions.
Routes pass a ProviderContract value. Never pass a model name as a provider name.
"""

import os
from enum import StrEnum


class ProviderContract(StrEnum):
    QUESTION_EXTRACTION = "question_extraction"
    RUBRIC_EXTRACTION = "rubric_extraction"
    GRADING = "grading"


def get_provider():
    """
    Return the correct provider module based on USE_STUB_PROVIDER env var.
    Usage:
        provider = get_provider()
        result = provider.extract_questions_from_pdf(pdf_path)
    """
    use_stub = os.environ.get("USE_STUB_PROVIDER", "false").lower() == "true"
    if use_stub:
        from app.providers import stub_provider

        return stub_provider
    from app.providers import gemini_provider

    return gemini_provider
