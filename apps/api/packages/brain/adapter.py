import re
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.config import Settings
from packages.brain.antigravity_gemini_vision_provider import (
    AntigravityGeminiVisionProvider,
)
from packages.brain.capabilities import (
    BRAIN_CAPABILITY_METHODS,
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainProviderRuntime,
    BrainTransport,
)
from packages.brain.codex_cli_provider import CodexCliProvider
from packages.brain.gemini_provider import GeminiBrainProvider
from packages.brain.image_input import build_image_data_url
from packages.brain.llama_cpp_qwen38_vision_provider import (
    LlamaCppQwen38VisionProvider,
)
from packages.brain.llama_cpp_qwen_provider import LlamaCppQwenProvider
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.openai_provider import OpenAICompatibleProvider
from packages.brain.profiles import (
    BUILTIN_BRAIN_PROFILES,
    BrainProviderConfigurationError,
    BrainProviderProfile,
    BrainProviderProfileDefinition,
    ProviderBuildResult,
    legacy_profile_settings,
)
from packages.brain.prompt_registry import (
    MARKING_POLICY_INSTRUCTIONS,
    build_grading_prompt,
    get_prompt_version,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.schemas_qwen38 import (
    VisualPageMappingOutput,
    VisualPageTranscriptOutput,
    VisualTranscriptionOutput,
)

ProviderFactory = Callable[[Settings, str], ProviderBuildResult]
_PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}
_PROVIDER_CANONICAL_NAMES: dict[str, str] = {}
_PROFILE_DEFINITIONS: dict[str, BrainProviderProfileDefinition] = {}
_LEGACY_PROVIDER_CONSTRUCTOR_NAMES = frozenset(
    constructor.__name__
    for constructor in (
        AntigravityGeminiVisionProvider,
        CodexCliProvider,
        GeminiBrainProvider,
        LlamaCppQwen38VisionProvider,
        LlamaCppQwenProvider,
        MockBrainProvider,
        OpenAICompatibleProvider,
    )
)
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


def register_brain_profile(definition: BrainProviderProfileDefinition) -> None:
    """Publish a selectable profile and retain its provider-name compatibility path."""

    profile_id = definition.profile_id.strip().lower()
    if not profile_id or profile_id != definition.profile_id:
        raise ValueError("Brain profile ids must be nonempty lowercase safe ids")
    existing = _PROFILE_DEFINITIONS.get(profile_id)
    if existing is not None and existing is not definition:
        raise ValueError(f"Brain profile id is already registered: {profile_id}")
    _PROFILE_DEFINITIONS[profile_id] = definition

    def build_profile(settings: Settings, _requested: str) -> ProviderBuildResult:
        effective_settings = legacy_profile_settings(settings, profile_id)
        configuration = definition.resolve(effective_settings)
        # Preserve the legacy adapter module's constructor patch points until
        # env-selected provider construction is removed in TA-BRAIN-003.
        constructor_name = definition.provider_constructor.__name__
        if constructor_name not in _LEGACY_PROVIDER_CONSTRUCTOR_NAMES:
            raise BrainProviderConfigurationError(
                f"No legacy constructor is registered for profile {profile_id}"
            )
        constructor = globals()[constructor_name]
        return definition.build(effective_settings, configuration, constructor)

    register_brain_provider(
        profile_id,
        build_profile,
        aliases=definition.aliases,
    )


def registered_brain_providers() -> tuple[str, ...]:
    return tuple(sorted(set(_PROVIDER_CANONICAL_NAMES.values())))


def registered_brain_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILE_DEFINITIONS))


def canonical_brain_provider_name(name: str) -> str:
    normalized = name.strip().lower()
    try:
        return _PROVIDER_CANONICAL_NAMES[normalized]
    except KeyError as exc:
        raise BrainProviderConfigurationError(
            f"Unsupported BRAIN_PROVIDER: {normalized}. Registered providers: "
            + ", ".join(registered_brain_providers())
        ) from exc


def configured_brain_profiles(settings: Settings) -> tuple[BrainProviderProfile, ...]:
    """Resolve catalog metadata and construction readiness without probing providers."""

    profiles: list[BrainProviderProfile] = []
    for profile_id in registered_brain_profiles():
        definition = _PROFILE_DEFINITIONS[profile_id]
        configuration = definition.resolve(settings)
        try:
            adapter = BrainAdapter.for_profile(settings, profile_id)
        except BrainProviderConfigurationError as exc:
            ready = False
            readiness_detail = sanitize_provider_error(
                str(exc),
                secrets=_configured_secret_values(settings),
            )
            capabilities = configuration.capabilities
        else:
            ready = True
            readiness_detail = "ready"
            capabilities = adapter.runtime.capabilities
        profiles.append(
            BrainProviderProfile(
                profile_id=configuration.profile_id,
                display_name=configuration.display_name,
                vendor=configuration.vendor,
                transport=configuration.transport,
                model=configuration.model,
                endpoint=configuration.safe_endpoint,
                capabilities=capabilities,
                destination=configuration.destination,
                timeout_seconds=configuration.timeout_seconds,
                structured_output_mode=configuration.structured_output_mode,
                secret_reference=configuration.secret_reference,
                enabled=configuration.enabled,
                ready=ready,
                readiness_detail=readiness_detail,
            )
        )
    return tuple(profiles)


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


def _configured_secret_values(settings: Settings) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            settings.brain_api_key,
            settings.openai_api_key,
            settings.gemini_api_key,
            settings.local_qwen_api_key,
            settings.local_qwen38_api_key,
        )
        if value
    )


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
        capabilities = set(self.provider.capabilities)
        provider_name = str(self.provider.provider_name)
        if capabilities:
            _validate_declared_capabilities(self.provider, provider_name, capabilities)
        self.runtime = BrainProviderRuntime(
            provider=provider_name,
            model=self.provider.model_name,
            location=BrainExecutionLocation(self.provider.execution_location),
            capabilities=frozenset(capabilities),
            transport=BrainTransport(self.provider.transport),
            image_input_mode=BrainImageInputMode(
                getattr(self.provider, "image_input_mode", BrainImageInputMode.NONE)
            ),
            managed_local_phase=self.provider.managed_local_phase,
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

    @classmethod
    def for_profile(cls, settings: Settings, profile_id: str) -> "BrainAdapter":
        normalized = profile_id.strip().lower()
        definition = _PROFILE_DEFINITIONS.get(normalized)
        if definition is None:
            raise BrainProviderConfigurationError(
                f"Unsupported brain profile: {normalized}. Registered profiles: "
                + ", ".join(registered_brain_profiles())
            )
        if not settings.brain_allow_real_providers and normalized != "mock":
            raise BrainProviderConfigurationError(
                "BRAIN_ALLOW_REAL_PROVIDERS must be true before a non-mock profile "
                "can initialize"
            )
        try:
            configuration = definition.resolve(settings)
            built = definition.build(
                settings,
                configuration,
                definition.provider_constructor,
            )
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
        kwargs: dict[str, Any] = {
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "question_labels": question_labels,
        }
        if question_references is not None:
            kwargs["question_references"] = question_references
        if open_continuations is not None:
            kwargs["open_continuations"] = open_continuations
        if boundary_verification:
            kwargs["boundary_verification"] = True
        return self._call_capability(
            BrainCapability.VISUAL_MAPPING,
            "map_page_answer_regions",
            **kwargs,
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
        kwargs: dict[str, Any] = {
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "question_labels": question_labels,
        }
        if question_references is not None:
            kwargs["question_references"] = question_references
        if open_continuations is not None:
            kwargs["open_continuations"] = open_continuations
        return self._call_capability(
            BrainCapability.VISUAL_PAGE_READ,
            "read_page",
            **kwargs,
        )

    def transcribe_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        kwargs: dict[str, Any] = {
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "label": label,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return self._call_capability(
            BrainCapability.VISUAL_TRANSCRIPTION,
            "transcribe_image",
            **kwargs,
        )

    def transcribe_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        label: str,
        max_tokens: int | None = None,
    ) -> VisualTranscriptionOutput:
        kwargs: dict[str, Any] = {"images": images, "label": label}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return self._call_capability(
            BrainCapability.VISUAL_TRANSCRIPTION,
            "transcribe_images",
            **kwargs,
        )

    def repair_transcription_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        rejected_transcript: str,
        source_editing_marks: list[dict[str, Any]] | None = None,
    ) -> VisualTranscriptionOutput:
        kwargs: dict[str, Any] = {
            "images": images,
            "rejected_transcript": rejected_transcript,
        }
        if source_editing_marks is not None:
            kwargs["source_editing_marks"] = source_editing_marks
        return self._call_capability(
            BrainCapability.TRANSCRIPTION_REPAIR,
            "repair_transcription_images",
            **kwargs,
        )

    def extract_reference_bundle_from_images(
        self,
        *,
        documents: dict[str, list[tuple[bytes, str, int]]],
    ) -> dict[str, Any]:
        return self._call_capability(
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
            "extract_reference_bundle_from_images",
            documents=documents,
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


def _validate_declared_capabilities(
    provider: BrainProvider,
    provider_name: str,
    capabilities: set[BrainCapability],
) -> None:
    missing: list[str] = []
    for capability in sorted(capabilities, key=lambda item: item.value):
        method_name = BRAIN_CAPABILITY_METHODS[capability]
        bound_method = getattr(provider, method_name, None)
        implementation = getattr(type(provider), method_name, None)
        base_implementation = getattr(BrainProvider, method_name, None)
        if not callable(bound_method) or implementation is base_implementation:
            missing.append(f"{capability.value} ({method_name})")
    if missing:
        raise BrainProviderConfigurationError(
            f"Provider {provider_name} declares capabilities without implementing their "
            f"contract methods: {', '.join(missing)}"
        )


for _profile_definition in BUILTIN_BRAIN_PROFILES:
    register_brain_profile(_profile_definition)
