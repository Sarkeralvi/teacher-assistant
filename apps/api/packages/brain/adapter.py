import re
import time
from decimal import Decimal
from typing import Any

from app.core.config import Settings
from packages.brain.image_input import build_image_data_url
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.openai_provider import OpenAICompatibleProvider
from packages.brain.prompt_registry import build_grading_prompt, get_prompt_version
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


class BrainProviderConfigurationError(RuntimeError):
    """Raised when provider configuration is incomplete or unsupported."""


_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")


def sanitize_provider_error(message: str) -> str:
    without_keys = _API_KEY_PATTERN.sub("[REDACTED]", message)
    return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", without_keys)


class BrainAdapter:
    def __init__(
        self,
        provider: BrainProvider | None = None,
        *,
        image_input_enabled: bool = False,
        storage_root: str | None = None,
    ) -> None:
        self.provider = provider or MockBrainProvider()
        self.image_input_enabled = image_input_enabled
        self.storage_root = storage_root or "/data"

    @classmethod
    def from_settings(cls, settings: Settings) -> "BrainAdapter":
        provider_name = settings.brain_provider.strip().lower()
        if provider_name in {"", "mock", "fake"}:
            return cls(MockBrainProvider())
        if provider_name == "openai":
            if not settings.openai_api_key:
                raise BrainProviderConfigurationError(
                    "OPENAI_API_KEY is required when BRAIN_PROVIDER=openai"
                )
            return cls(
                OpenAICompatibleProvider(
                    api_key=settings.openai_api_key,
                    model_name=settings.openai_model or "gpt-4o-mini",
                    base_url=settings.openai_base_url or None,
                    timeout_seconds=settings.openai_timeout_seconds,
                ),
                image_input_enabled=settings.openai_image_input_enabled,
                storage_root=settings.local_storage_root,
            )
        raise BrainProviderConfigurationError(f"Unsupported BRAIN_PROVIDER: {provider_name}")

    def grade_answer_region(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        policy: ModelPolicy | None = None,
    ) -> GradeSuggestionOutput:
        resolved_policy = policy or (
            ModelPolicy.REAL_GRADING
            if self.provider.provider_name == "openai"
            else ModelPolicy.MOCK_GRADING
        )
        should_send_image = (
            self.provider.provider_name == "openai" and self.image_input_enabled
        )
        prompt_version = get_prompt_version(resolved_policy)
        messages = build_grading_prompt(
            question_text=question_text,
            rubric_json=rubric_json,
            answer_image_path=answer_image_path,
            image_input_enabled=should_send_image,
        )
        image_data_url = None
        if should_send_image:
            image_data_url = build_image_data_url(
                image_path=answer_image_path,
                storage_root=self.storage_root,
            )
        start = time.perf_counter()
        try:
            output = self.provider.grade(
                question_text=question_text,
                question_total_marks=question_total_marks,
                rubric_json=rubric_json,
                answer_image_path=answer_image_path,
                prompt_version=prompt_version,
                task_name="answer_region_grading",
                model_policy=resolved_policy,
                messages=messages,
                image_data_url=image_data_url,
            )
        except Exception as exc:
            sanitized = sanitize_provider_error(str(exc))
            raise RuntimeError(sanitized) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        validated = GradeSuggestionOutput.model_validate(output.model_dump())
        return validated.model_copy(update={"latency_ms": latency_ms})
