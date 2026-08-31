import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import Settings
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainProviderRuntime,
)
from packages.brain.codex_cli_provider import CodexCliProvider
from packages.brain.gemini_provider import GeminiBrainProvider
from packages.brain.image_input import build_image_data_url
from packages.brain.llama_cpp_qwen38_vision_provider import LlamaCppQwen38VisionProvider
from packages.brain.llama_cpp_qwen_provider import LlamaCppQwenProvider
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.openai_provider import OpenAICompatibleProvider
from packages.brain.prompt_registry import (
    MARKING_POLICY_INSTRUCTIONS,
    build_grading_prompt,
    get_prompt_version,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


class BrainProviderConfigurationError(RuntimeError):
    """Raised when provider configuration is incomplete or unsupported."""


@dataclass(frozen=True)
class ProviderBuildResult:
    provider: BrainProvider
    image_input_enabled: bool = False


ProviderFactory = Callable[[Settings, str], ProviderBuildResult]
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}
_PROVIDER_CANONICAL_NAMES: dict[str, str] = {}
_LEGACY_RUNTIME_LOCATIONS = {
    "llama_cpp_qwen": BrainExecutionLocation.LOCAL,
    "qwen": BrainExecutionLocation.LOCAL,
    "llama_cpp_qwen38": BrainExecutionLocation.LOCAL,
    "codex_cli": BrainExecutionLocation.CLI,
}
_LEGACY_MANAGED_LOCAL_PHASES = {
    "llama_cpp_qwen": "Qwen",
    "qwen": "Qwen",
    "llama_cpp_qwen38": "Qwen38",
}


def register_brain_provider(
    name: str,
    factory: ProviderFactory,
    *,
    aliases: tuple[str, ...] = (),
) -> None:
    """Register one provider factory without changing workflow code."""

    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Provider registration requires a name")
    for candidate in (normalized, *(alias.strip().lower() for alias in aliases)):
        if not candidate:
            continue
        existing = _PROVIDER_FACTORIES.get(candidate)
        if existing is not None and existing is not factory:
            raise ValueError(f"Provider name is already registered: {candidate}")
        _PROVIDER_FACTORIES[candidate] = factory
        _PROVIDER_CANONICAL_NAMES[candidate] = normalized


def registered_brain_providers() -> tuple[str, ...]:
    return tuple(sorted(set(_PROVIDER_CANONICAL_NAMES.values())))


def canonical_brain_provider_name(name: str) -> str:
    normalized = name.strip().lower()
    try:
        return _PROVIDER_CANONICAL_NAMES[normalized]
    except KeyError as exc:
        raise BrainProviderConfigurationError(
            f"Unsupported BRAIN_PROVIDER: {normalized}. Registered providers: "
            + ", ".join(registered_brain_providers())
        ) from exc


_API_KEY_PATTERN = re.compile(
    r"(?:sk|key)-[A-Za-z0-9_\-]+|AIza[0-9A-Za-z_\-]{20,}",
    re.IGNORECASE,
)
_AUTH_VALUE_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)([^\s,;]+)"
)
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")


def sanitize_provider_error(
    message: str,
    *,
    secrets: tuple[str, ...] = (),
) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = _API_KEY_PATTERN.sub("[REDACTED]", sanitized)
    sanitized = _AUTH_VALUE_PATTERN.sub(r"\1\2[REDACTED]", sanitized)
    return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", sanitized)


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
        declared_capabilities = vars(self.provider).get(
            "capabilities",
            type(self.provider).__dict__.get("capabilities"),
        )
        capabilities = set(declared_capabilities or ())
        method_capabilities = {
            "grade": BrainCapability.GRADING,
            "extract_questions_from_pdf": BrainCapability.QUESTION_PDF_EXTRACTION,
            "extract_rubric_from_pdf": BrainCapability.RUBRIC_PDF_EXTRACTION,
            "extract_reference_bundle_from_images": (
                BrainCapability.VISUAL_REFERENCE_EXTRACTION
            ),
            "map_page_answer_regions": BrainCapability.VISUAL_MAPPING,
            "transcribe_images": BrainCapability.VISUAL_TRANSCRIPTION,
            "repair_transcription_images": BrainCapability.TRANSCRIPTION_REPAIR,
        }
        if declared_capabilities is None:
            capabilities.update(
                capability
                for method_name, capability in method_capabilities.items()
                if callable(getattr(self.provider, method_name, None))
                and (
                    not isinstance(self.provider, BrainProvider)
                    or getattr(type(self.provider), method_name, None)
                    is not getattr(BrainProvider, method_name, None)
                )
            )
        provider_name = str(self.provider.provider_name)
        self.runtime = BrainProviderRuntime(
            provider=provider_name,
            model=self.provider.model_name,
            location=_runtime_location(self.provider, provider_name),
            capabilities=frozenset(capabilities),
            image_input_mode=BrainImageInputMode(
                getattr(self.provider, "image_input_mode", BrainImageInputMode.NONE)
            ),
            managed_local_phase=_managed_local_phase(self.provider, provider_name),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "BrainAdapter":
        return cls.for_provider(settings, settings.brain_provider)

    @classmethod
    def for_provider(cls, settings: Settings, requested_provider: str) -> "BrainAdapter":
        provider_name = requested_provider.strip().lower() or "mock"
        factory = _PROVIDER_FACTORIES.get(provider_name)
        if factory is None:
            raise BrainProviderConfigurationError(
                f"Unsupported BRAIN_PROVIDER: {provider_name}. Registered providers: "
                + ", ".join(registered_brain_providers())
            )
        canonical_name = _PROVIDER_CANONICAL_NAMES[provider_name]
        if not settings.brain_allow_real_providers:
            mock_factory = _PROVIDER_FACTORIES.get("mock")
            if factory is not mock_factory:
                raise BrainProviderConfigurationError(
                    "BRAIN_ALLOW_REAL_PROVIDERS must be true before a non-mock provider "
                    "can initialize"
                )
        try:
            built = factory(settings, canonical_name)
        except BrainProviderConfigurationError:
            raise
        except (TypeError, ValueError) as exc:
            raise BrainProviderConfigurationError(str(exc)) from exc
        return cls(
            built.provider,
            image_input_enabled=built.image_input_enabled,
            storage_root=settings.local_storage_root,
        )

    def supports(self, capability: BrainCapability) -> bool:
        return self.runtime.supports(capability)

    def require_capability(self, capability: BrainCapability) -> None:
        if not self.supports(capability):
            raise BrainProviderConfigurationError(
                f"Provider {self.runtime.provider} does not support {capability.value}"
            )

    def grade_answer_region(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        student_answer_text: str | None = None,
        policy: ModelPolicy | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        self.require_capability(BrainCapability.GRADING)
        normalized_marking_policy = marking_policy.strip().lower()
        if normalized_marking_policy not in MARKING_POLICY_INSTRUCTIONS:
            normalized_marking_policy = "general"
        resolved_policy = policy or (
            ModelPolicy.REAL_GRADING if self.runtime.is_real else ModelPolicy.MOCK_GRADING
        )
        should_send_image = bool(
            self.runtime.is_real
            and self.image_input_enabled
            and self.runtime.image_input_mode is not BrainImageInputMode.NONE
        )
        prompt_answer_image_path = (
            answer_image_path if should_send_image else "[image input disabled]"
        )
        prompt_version = get_prompt_version(resolved_policy)
        messages = build_grading_prompt(
            question_text=question_text,
            rubric_json=rubric_json,
            answer_image_path=prompt_answer_image_path,
            student_answer_text=student_answer_text,
            image_input_enabled=should_send_image,
            marking_policy=normalized_marking_policy,
        )
        image_data_url = None
        provider_answer_image_path = prompt_answer_image_path
        if should_send_image and self.runtime.image_input_mode is BrainImageInputMode.DATA_URL:
            image_data_url = build_image_data_url(
                image_path=answer_image_path,
                storage_root=self.storage_root,
            )
        elif should_send_image and self.runtime.image_input_mode is BrainImageInputMode.FILE_PATH:
            provider_answer_image_path = str(Path(self.storage_root) / answer_image_path)
        start = time.perf_counter()
        try:
            output = self.provider.grade(
                question_text=question_text,
                question_total_marks=question_total_marks,
                rubric_json=rubric_json,
                answer_image_path=provider_answer_image_path,
                student_answer_text=student_answer_text,
                prompt_version=prompt_version,
                task_name="answer_region_grading",
                model_policy=resolved_policy,
                messages=messages,
                image_data_url=image_data_url,
                marking_policy=normalized_marking_policy,
            )
        except Exception as exc:
            sanitized = self._sanitize_error(str(exc))
            raise RuntimeError(sanitized) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        validated = GradeSuggestionOutput.model_validate(output.model_dump())
        # Marking policy is authorization metadata, not model-authored prose.
        # Persist it deterministically even when a provider abbreviates or
        # omits the requested review flag.
        review_flags = list(validated.review_flags)
        policy_flag = f"marking_policy:{normalized_marking_policy}"
        if policy_flag not in review_flags:
            review_flags.append(policy_flag)
        return validated.model_copy(update={"latency_ms": latency_ms, "review_flags": review_flags})

    def extract_questions_from_document(self, file_path: str) -> dict[str, Any]:
        self.require_capability(BrainCapability.QUESTION_PDF_EXTRACTION)
        try:
            return self.provider.extract_questions_from_pdf(file_path)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def extract_rubric_from_document(self, file_path: str) -> dict[str, Any]:
        self.require_capability(BrainCapability.RUBRIC_PDF_EXTRACTION)
        try:
            return self.provider.extract_rubric_from_pdf(file_path)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def extract_questions_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        self.require_capability(BrainCapability.OCR_REFERENCE_EXTRACTION)
        try:
            return self.provider.extract_questions_from_ocr_pages(pages)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def extract_rubric_from_ocr_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        self.require_capability(BrainCapability.OCR_REFERENCE_EXTRACTION)
        try:
            return self.provider.extract_rubric_from_ocr_pages(pages)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def extract_reference_bundle_from_ocr_documents(
        self, documents: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        self.require_capability(BrainCapability.OCR_REFERENCE_EXTRACTION)
        try:
            return self.provider.extract_reference_bundle_from_ocr_documents(documents)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def map_submission_answers_from_ocr_pages(
        self,
        *,
        pages: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.require_capability(BrainCapability.OCR_ANSWER_MAPPING)
        try:
            return self.provider.map_submission_answers_from_ocr_pages(
                pages=pages,
                questions=questions,
            )
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def prepare_student_answers_from_ocr_candidates(
        self,
        *,
        answers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.require_capability(BrainCapability.OCR_ANSWER_PREPARATION)
        try:
            return self.provider.prepare_student_answers_from_ocr_candidates(
                answers=answers,
            )
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def map_page_answer_regions(self, **kwargs: Any) -> Any:
        return self._call_capability(
            BrainCapability.VISUAL_MAPPING,
            "map_page_answer_regions",
            **kwargs,
        )

    def transcribe_image(self, **kwargs: Any) -> Any:
        return self._call_capability(
            BrainCapability.VISUAL_TRANSCRIPTION,
            "transcribe_image",
            **kwargs,
        )

    def transcribe_images(self, **kwargs: Any) -> Any:
        return self._call_capability(
            BrainCapability.VISUAL_TRANSCRIPTION,
            "transcribe_images",
            **kwargs,
        )

    def repair_transcription_images(self, **kwargs: Any) -> Any:
        return self._call_capability(
            BrainCapability.TRANSCRIPTION_REPAIR,
            "repair_transcription_images",
            **kwargs,
        )

    def extract_reference_bundle_from_images(self, **kwargs: Any) -> dict[str, Any]:
        return self._call_capability(
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
            "extract_reference_bundle_from_images",
            **kwargs,
        )

    def _call_capability(
        self,
        capability: BrainCapability,
        method_name: str,
        **kwargs: Any,
    ) -> Any:
        self.require_capability(capability)
        method = getattr(self.provider, method_name, None)
        if method is None:
            raise BrainProviderConfigurationError(
                f"Provider {self.runtime.provider} advertises {capability.value} "
                "but does not implement its contract"
            )
        try:
            return method(**kwargs)
        except (ValueError, NotImplementedError):
            raise
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def verify_available_model(self) -> None:
        verify = getattr(self.provider, "verify_available_model", None)
        if not callable(verify):
            return
        try:
            verify()
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

    def _sanitize_error(self, message: str) -> str:
        return sanitize_provider_error(
            message,
            secrets=(str(getattr(self.provider, "api_key", "") or ""),),
        )


def _runtime_location(
    provider: BrainProvider,
    provider_name: str,
) -> BrainExecutionLocation:
    """Resolve legacy injected adapters without misclassifying local Qwen as cloud.

    Concrete providers publish ``execution_location``. Older integration doubles
    often inherit the conservative cloud default from ``BrainProvider`` instead,
    so canonical managed-local names need their established runtime metadata.
    Unknown providers remain cloud by default.
    """

    declared = _runtime_attribute(provider, "execution_location")
    if declared is None:
        return _LEGACY_RUNTIME_LOCATIONS.get(
            provider_name.casefold(), BrainExecutionLocation.CLOUD
        )
    return BrainExecutionLocation(declared)


def _managed_local_phase(provider: BrainProvider, provider_name: str) -> str | None:
    declared = _runtime_attribute(provider, "managed_local_phase")
    if declared is not None:
        return str(declared) or None
    return _LEGACY_MANAGED_LOCAL_PHASES.get(provider_name.casefold())


def _runtime_attribute(provider: BrainProvider, name: str) -> object | None:
    """Read an explicit subclass declaration, but ignore base-class defaults.

    ``BrainProvider`` supplies conservative cloud/empty defaults.  A provider
    subclass that does not override them is an old integration double, while a
    subclass of ``MockBrainProvider`` legitimately inherits its mock location.
    """

    instance_values = vars(provider)
    if name in instance_values:
        return instance_values[name]
    for provider_type in type(provider).__mro__:
        if provider_type is BrainProvider:
            return None
        if name in provider_type.__dict__:
            return provider_type.__dict__[name]
    return None


def _build_mock(_settings: Settings, _requested: str) -> ProviderBuildResult:
    return ProviderBuildResult(MockBrainProvider())


def _build_openai_compatible(
    settings: Settings,
    requested: str,
) -> ProviderBuildResult:
    canonical_name = "openai" if requested == "openai" else "openai_compatible"
    generic_profile = canonical_name == "openai_compatible" or any(
        (settings.brain_model, settings.brain_api_key, settings.brain_base_url)
    )
    api_key = settings.brain_api_key or settings.openai_api_key
    model = settings.brain_model or settings.openai_model or (
        "gpt-4o-mini" if canonical_name == "openai" else ""
    )
    base_url = settings.brain_base_url or settings.openai_base_url or (
        "https://api.openai.com/v1" if canonical_name == "openai" else ""
    )
    timeout = (
        settings.brain_timeout_seconds
        if generic_profile
        else settings.openai_timeout_seconds
    )
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.openai_image_input_enabled
    )
    if not model:
        raise BrainProviderConfigurationError("BRAIN_MODEL is required")
    if not base_url:
        raise BrainProviderConfigurationError(
            "BRAIN_BASE_URL is required for an OpenAI-compatible provider"
        )
    location = _resolve_location(
        settings,
        base_url=base_url,
        default=BrainExecutionLocation.CLOUD,
    )
    if location is BrainExecutionLocation.CLOUD and not api_key:
        key_name = "OPENAI_API_KEY" if canonical_name == "openai" else "BRAIN_API_KEY"
        raise BrainProviderConfigurationError(
            f"{key_name} is required for a cloud OpenAI-compatible provider"
        )
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        model_name=model,
        base_url=base_url,
        timeout_seconds=timeout,
        provider_name=canonical_name,
        execution_location=location,
        image_input_enabled=bool(image_enabled),
        structured_output_mode=settings.brain_structured_output_mode,
        verify_model_on_start=settings.brain_verify_model_on_start,
        managed_local_phase=_resolve_managed_phase(settings, location=location),
    )
    return ProviderBuildResult(provider, image_input_enabled=bool(image_enabled))


def _build_gemini(settings: Settings, _requested: str) -> ProviderBuildResult:
    api_key = settings.brain_api_key or settings.gemini_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "GEMINI_API_KEY or BRAIN_API_KEY is required when BRAIN_PROVIDER=gemini"
        )
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.gemini_image_input_enabled
    )
    provider = GeminiBrainProvider(
        api_key=api_key,
        model_name=settings.brain_model or settings.gemini_model,
        timeout_seconds=settings.brain_timeout_seconds,
        image_input_enabled=bool(image_enabled),
        structured_output_mode=settings.brain_structured_output_mode,
        verify_model_on_start=settings.brain_verify_model_on_start,
    )
    return ProviderBuildResult(provider, image_input_enabled=bool(image_enabled))


def _build_codex_cli(settings: Settings, _requested: str) -> ProviderBuildResult:
    if settings.codex_cli_approval_policy.strip().lower() != "never":
        raise BrainProviderConfigurationError(
            "CODEX_CLI_APPROVAL_POLICY must be never for BRAIN_PROVIDER=codex_cli"
        )
    if settings.codex_cli_sandbox.strip() == "danger-full-access":
        raise BrainProviderConfigurationError(
            "CODEX_CLI_SANDBOX=danger-full-access is not allowed"
        )
    generic_profile = _generic_profile_selected(settings)
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.codex_cli_image_input_enabled
    )
    return ProviderBuildResult(
        CodexCliProvider(
            command=settings.codex_cli_command,
            model_name=settings.brain_model or settings.codex_cli_model,
            timeout_seconds=(
                settings.brain_timeout_seconds
                if generic_profile
                else settings.codex_cli_timeout_seconds
            ),
            sandbox=settings.codex_cli_sandbox,
            use_json=settings.codex_cli_use_json,
            output_last_message=settings.codex_cli_output_last_message,
            image_input_enabled=bool(image_enabled),
            workdir=settings.codex_cli_workdir,
        ),
        image_input_enabled=bool(image_enabled),
    )


def _build_qwen(settings: Settings, _requested: str) -> ProviderBuildResult:
    if not settings.local_qwen_enabled:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN_ENABLED must be true for BRAIN_PROVIDER=llama_cpp_qwen"
        )
    api_key = settings.brain_api_key or settings.local_qwen_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN_API_KEY or BRAIN_API_KEY is required for llama_cpp_qwen"
        )
    provider = LlamaCppQwenProvider(
        api_key=api_key,
        model_name=settings.brain_model or settings.local_qwen_model,
        base_url=settings.brain_base_url or settings.local_qwen_base_url,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.local_qwen_timeout_seconds
        ),
        require_model_lease=True,
    )
    return ProviderBuildResult(provider)


def _build_qwen38(settings: Settings, _requested: str) -> ProviderBuildResult:
    if not settings.local_qwen38_enabled:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN38_ENABLED must be true for BRAIN_PROVIDER=llama_cpp_qwen38"
        )
    api_key = settings.brain_api_key or settings.local_qwen38_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN38_API_KEY or BRAIN_API_KEY is required for llama_cpp_qwen38"
        )
    provider = LlamaCppQwen38VisionProvider(
        api_key=api_key,
        model_name=settings.brain_model or settings.local_qwen38_model,
        base_url=settings.brain_base_url or settings.local_qwen38_base_url,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.local_qwen38_timeout_seconds
        ),
        grading_reasoning_mode=settings.local_qwen38_grading_reasoning_mode,
        context_tokens=settings.local_qwen38_context_tokens,
        require_model_lease=True,
    )
    return ProviderBuildResult(provider)


def _generic_profile_selected(settings: Settings) -> bool:
    return any((settings.brain_model, settings.brain_api_key, settings.brain_base_url))


def _resolve_location(
    settings: Settings,
    *,
    base_url: str,
    default: BrainExecutionLocation,
) -> BrainExecutionLocation:
    configured = settings.brain_endpoint_type.strip().lower()
    if configured not in {"", "auto", "local", "cloud"}:
        raise BrainProviderConfigurationError(
            "An HTTP brain endpoint type must be auto, local, or cloud"
        )
    if configured not in {"", "auto"}:
        return BrainExecutionLocation(configured)
    hostname = (urlparse(base_url).hostname or "").casefold()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return BrainExecutionLocation.LOCAL
    return default


def _resolve_managed_phase(
    settings: Settings,
    *,
    location: BrainExecutionLocation,
) -> str | None:
    value = settings.brain_managed_local_phase.strip()
    if not value:
        return None
    if location is not BrainExecutionLocation.LOCAL:
        raise BrainProviderConfigurationError(
            "BRAIN_MANAGED_LOCAL_PHASE is valid only for a local endpoint"
        )
    aliases = {"qwen": "Qwen", "qwen38": "Qwen38"}
    try:
        return aliases[value.casefold()]
    except KeyError as exc:
        raise BrainProviderConfigurationError(
            "BRAIN_MANAGED_LOCAL_PHASE must be Qwen or Qwen38"
        ) from exc


register_brain_provider("mock", _build_mock, aliases=("fake",))
register_brain_provider("openai", _build_openai_compatible)
register_brain_provider(
    "openai_compatible",
    _build_openai_compatible,
    aliases=("openai-compatible",),
)
register_brain_provider("gemini", _build_gemini)
register_brain_provider("codex_cli", _build_codex_cli)
register_brain_provider("llama_cpp_qwen", _build_qwen)
register_brain_provider("llama_cpp_qwen38", _build_qwen38)
