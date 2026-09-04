from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.core.config import Settings
from packages.brain.antigravity_gemini_vision_provider import (
    AntigravityGeminiVisionProvider,
)
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainTransport,
)
from packages.brain.codex_cli_provider import CodexCliProvider
from packages.brain.gemini_provider import GeminiBrainProvider
from packages.brain.llama_cpp_qwen38_vision_provider import (
    LlamaCppQwen38VisionProvider,
)
from packages.brain.llama_cpp_qwen_provider import LlamaCppQwenProvider
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.openai_provider import OpenAICompatibleProvider
from packages.brain.provider_base import BrainProvider


class BrainProviderConfigurationError(RuntimeError):
    """Raised when provider configuration is incomplete or unsupported."""


@dataclass(frozen=True)
class ProviderBuildResult:
    provider: BrainProvider
    image_input_enabled: bool = False


@dataclass(frozen=True)
class BrainProviderProfileConfiguration:
    profile_id: str
    display_name: str
    vendor: str
    transport: BrainTransport
    model: str
    endpoint: str
    capabilities: frozenset[BrainCapability]
    destination: BrainExecutionLocation
    timeout_seconds: float
    structured_output_mode: str
    secret_reference: str
    enabled: bool

    @property
    def safe_endpoint(self) -> str:
        if self.endpoint == "n/a":
            return self.endpoint
        parsed = urlparse(self.endpoint)
        if not parsed.scheme or not parsed.hostname:
            return self.endpoint
        host = parsed.hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunparse((parsed.scheme, host, parsed.path, "", "", ""))


@dataclass(frozen=True)
class BrainProviderProfile:
    profile_id: str
    display_name: str
    vendor: str
    transport: BrainTransport
    model: str
    endpoint: str
    capabilities: frozenset[BrainCapability]
    destination: BrainExecutionLocation
    timeout_seconds: float
    structured_output_mode: str
    secret_reference: str
    enabled: bool
    ready: bool
    readiness_detail: str


ProfileResolver = Callable[[Settings], BrainProviderProfileConfiguration]
ProviderConstructor = Callable[..., BrainProvider]
ProfileBuilder = Callable[
    [Settings, BrainProviderProfileConfiguration, ProviderConstructor],
    ProviderBuildResult,
]


@dataclass(frozen=True)
class BrainProviderProfileDefinition:
    profile_id: str
    aliases: tuple[str, ...]
    resolve: ProfileResolver
    build: ProfileBuilder
    provider_constructor: ProviderConstructor


_UNIVERSAL_VISION_CAPABILITIES = frozenset(
    {
        BrainCapability.QUESTION_PDF_EXTRACTION,
        BrainCapability.RUBRIC_PDF_EXTRACTION,
        BrainCapability.VISUAL_REFERENCE_EXTRACTION,
        BrainCapability.VISUAL_MAPPING,
        BrainCapability.VISUAL_TRANSCRIPTION,
        BrainCapability.TRANSCRIPTION_REPAIR,
    }
)


def _generic_profile_selected(settings: Settings) -> bool:
    return any((settings.brain_model, settings.brain_api_key, settings.brain_base_url))


def _image_capabilities(enabled: bool) -> frozenset[BrainCapability]:
    capabilities = {BrainCapability.GRADING}
    if enabled:
        capabilities.update(_UNIVERSAL_VISION_CAPABILITIES)
    return frozenset(capabilities)


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


def _mock_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    del settings
    return BrainProviderProfileConfiguration(
        profile_id="mock",
        display_name="Mock (deterministic)",
        vendor="Built-in",
        transport=BrainTransport.IN_PROCESS,
        model=MockBrainProvider.model_name,
        endpoint="n/a",
        capabilities=MockBrainProvider.capabilities,
        destination=BrainExecutionLocation.MOCK,
        timeout_seconds=0,
        structured_output_mode="deterministic",
        secret_reference="n/a",
        enabled=True,
    )


def _build_mock(
    _settings: Settings,
    _configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    return ProviderBuildResult(provider_constructor())


def _openai_configuration(
    settings: Settings,
    *,
    profile_id: str,
) -> BrainProviderProfileConfiguration:
    generic_profile = profile_id == "openai_compatible" or _generic_profile_selected(
        settings
    )
    model = settings.brain_model or settings.openai_model or (
        "gpt-4o-mini" if profile_id == "openai" else ""
    )
    endpoint = settings.brain_base_url or settings.openai_base_url or (
        "https://api.openai.com/v1" if profile_id == "openai" else ""
    )
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.openai_image_input_enabled
    )
    return BrainProviderProfileConfiguration(
        profile_id=profile_id,
        display_name=(
            "OpenAI API" if profile_id == "openai" else "OpenAI-compatible API"
        ),
        vendor="OpenAI" if profile_id == "openai" else "OpenAI-compatible",
        transport=BrainTransport.HTTP,
        model=model,
        endpoint=endpoint or "n/a",
        capabilities=_image_capabilities(bool(image_enabled)),
        destination=_resolve_location(
            settings,
            base_url=endpoint,
            default=BrainExecutionLocation.CLOUD,
        ),
        timeout_seconds=(
            settings.brain_timeout_seconds
            if generic_profile
            else settings.openai_timeout_seconds
        ),
        structured_output_mode=settings.brain_structured_output_mode,
        secret_reference=(
            "BRAIN_API_KEY or OPENAI_API_KEY"
            if profile_id == "openai"
            else "BRAIN_API_KEY"
        ),
        enabled=settings.brain_allow_real_providers,
    )


def _build_openai_compatible(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    api_key = settings.brain_api_key or settings.openai_api_key
    if not configuration.model:
        raise BrainProviderConfigurationError("BRAIN_MODEL is required")
    if configuration.endpoint == "n/a":
        raise BrainProviderConfigurationError(
            "BRAIN_BASE_URL is required for an OpenAI-compatible provider"
        )
    if configuration.destination is BrainExecutionLocation.CLOUD and not api_key:
        key_name = (
            "OPENAI_API_KEY"
            if configuration.profile_id == "openai"
            else "BRAIN_API_KEY"
        )
        raise BrainProviderConfigurationError(
            f"{key_name} is required for a cloud OpenAI-compatible provider"
        )
    image_enabled = BrainCapability.VISUAL_MAPPING in configuration.capabilities
    provider = provider_constructor(
        api_key=api_key,
        model_name=configuration.model,
        base_url=configuration.endpoint,
        timeout_seconds=configuration.timeout_seconds,
        provider_name=configuration.profile_id,
        execution_location=configuration.destination,
        image_input_enabled=image_enabled,
        structured_output_mode=configuration.structured_output_mode,
        verify_model_on_start=settings.brain_verify_model_on_start,
        managed_local_phase=_resolve_managed_phase(
            settings,
            location=configuration.destination,
        ),
    )
    return ProviderBuildResult(provider, image_input_enabled=image_enabled)


def _gemini_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.gemini_image_input_enabled
    )
    return BrainProviderProfileConfiguration(
        profile_id="gemini",
        display_name="Google Gemini API",
        vendor="Google",
        transport=BrainTransport.HTTP,
        model=settings.brain_model or settings.gemini_model,
        endpoint="https://generativelanguage.googleapis.com",
        capabilities=_image_capabilities(bool(image_enabled)),
        destination=BrainExecutionLocation.CLOUD,
        timeout_seconds=settings.brain_timeout_seconds,
        structured_output_mode=settings.brain_structured_output_mode,
        secret_reference="BRAIN_API_KEY or GEMINI_API_KEY",
        enabled=settings.brain_allow_real_providers,
    )


def _build_gemini(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    api_key = settings.brain_api_key or settings.gemini_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "GEMINI_API_KEY or BRAIN_API_KEY is required when BRAIN_PROVIDER=gemini"
        )
    image_enabled = BrainCapability.VISUAL_MAPPING in configuration.capabilities
    provider = provider_constructor(
        api_key=api_key,
        model_name=configuration.model,
        timeout_seconds=configuration.timeout_seconds,
        image_input_enabled=image_enabled,
        structured_output_mode=configuration.structured_output_mode,
        verify_model_on_start=settings.brain_verify_model_on_start,
    )
    return ProviderBuildResult(provider, image_input_enabled=image_enabled)


def _codex_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    return BrainProviderProfileConfiguration(
        profile_id="codex_cli",
        display_name="Codex CLI",
        vendor="OpenAI",
        transport=BrainTransport.CLI,
        model=settings.brain_model or settings.codex_cli_model,
        endpoint="n/a",
        capabilities=CodexCliProvider.capabilities,
        destination=BrainExecutionLocation.CLOUD,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.codex_cli_timeout_seconds
        ),
        structured_output_mode="json" if settings.codex_cli_use_json else "text",
        secret_reference="CLI-managed authentication",
        enabled=settings.brain_allow_real_providers,
    )


def _build_codex_cli(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    if settings.codex_cli_approval_policy.strip().lower() != "never":
        raise BrainProviderConfigurationError(
            "CODEX_CLI_APPROVAL_POLICY must be never for BRAIN_PROVIDER=codex_cli"
        )
    if settings.codex_cli_sandbox.strip() == "danger-full-access":
        raise BrainProviderConfigurationError(
            "CODEX_CLI_SANDBOX=danger-full-access is not allowed"
        )
    image_enabled = (
        settings.brain_image_input_enabled
        if settings.brain_image_input_enabled is not None
        else settings.codex_cli_image_input_enabled
    )
    return ProviderBuildResult(
        provider_constructor(
            command=settings.codex_cli_command,
            model_name=configuration.model,
            timeout_seconds=configuration.timeout_seconds,
            sandbox=settings.codex_cli_sandbox,
            use_json=settings.codex_cli_use_json,
            output_last_message=settings.codex_cli_output_last_message,
            image_input_enabled=bool(image_enabled),
            workdir=settings.codex_cli_workdir,
        ),
        image_input_enabled=bool(image_enabled),
    )


def _qwen_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    return BrainProviderProfileConfiguration(
        profile_id="llama_cpp_qwen",
        display_name="Local Qwen 3.6",
        vendor="llama.cpp",
        transport=BrainTransport.HTTP,
        model=settings.brain_model or settings.local_qwen_model,
        endpoint=settings.brain_base_url or settings.local_qwen_base_url,
        capabilities=LlamaCppQwenProvider.capabilities,
        destination=BrainExecutionLocation.LOCAL,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.local_qwen_timeout_seconds
        ),
        structured_output_mode="json_schema",
        secret_reference="BRAIN_API_KEY or LOCAL_QWEN_API_KEY",
        enabled=(
            settings.brain_allow_real_providers and settings.local_qwen_enabled
        ),
    )


def _build_qwen(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    if not settings.local_qwen_enabled:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN_ENABLED must be true for BRAIN_PROVIDER=llama_cpp_qwen"
        )
    api_key = settings.brain_api_key or settings.local_qwen_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN_API_KEY or BRAIN_API_KEY is required for llama_cpp_qwen"
        )
    provider = provider_constructor(
        api_key=api_key,
        model_name=configuration.model,
        base_url=configuration.endpoint,
        timeout_seconds=configuration.timeout_seconds,
        require_model_lease=True,
    )
    return ProviderBuildResult(provider)


def _qwen38_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    return BrainProviderProfileConfiguration(
        profile_id="llama_cpp_qwen38",
        display_name="Local Qwen 3.8 Vision",
        vendor="llama.cpp",
        transport=BrainTransport.HTTP,
        model=settings.brain_model or settings.local_qwen38_model,
        endpoint=settings.brain_base_url or settings.local_qwen38_base_url,
        capabilities=LlamaCppQwen38VisionProvider.capabilities,
        destination=BrainExecutionLocation.LOCAL,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.local_qwen38_timeout_seconds
        ),
        structured_output_mode="json_schema",
        secret_reference="BRAIN_API_KEY or LOCAL_QWEN38_API_KEY",
        enabled=(
            settings.brain_allow_real_providers and settings.local_qwen38_enabled
        ),
    )


def _build_qwen38(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    if not settings.local_qwen38_enabled:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN38_ENABLED must be true for BRAIN_PROVIDER=llama_cpp_qwen38"
        )
    api_key = settings.brain_api_key or settings.local_qwen38_api_key
    if not api_key:
        raise BrainProviderConfigurationError(
            "LOCAL_QWEN38_API_KEY or BRAIN_API_KEY is required for llama_cpp_qwen38"
        )
    provider = provider_constructor(
        api_key=api_key,
        model_name=configuration.model,
        base_url=configuration.endpoint,
        timeout_seconds=configuration.timeout_seconds,
        grading_reasoning_mode=settings.local_qwen38_grading_reasoning_mode,
        context_tokens=settings.local_qwen38_context_tokens,
        require_model_lease=True,
    )
    return ProviderBuildResult(provider)


def _antigravity_configuration(settings: Settings) -> BrainProviderProfileConfiguration:
    return BrainProviderProfileConfiguration(
        profile_id="antigravity_gemini",
        display_name="Antigravity Gemini CLI",
        vendor="Google",
        transport=BrainTransport.CLI,
        model=settings.brain_model or settings.antigravity_gemini_model,
        endpoint="n/a",
        capabilities=AntigravityGeminiVisionProvider.capabilities,
        destination=BrainExecutionLocation.CLOUD,
        timeout_seconds=(
            settings.brain_timeout_seconds
            if _generic_profile_selected(settings)
            else settings.antigravity_gemini_timeout_seconds
        ),
        structured_output_mode="agy_schema",
        secret_reference="CLI-managed authentication",
        enabled=(
            settings.brain_allow_real_providers
            and settings.antigravity_gemini_enabled
        ),
    )


def _build_antigravity_gemini(
    settings: Settings,
    configuration: BrainProviderProfileConfiguration,
    provider_constructor: ProviderConstructor,
) -> ProviderBuildResult:
    if not settings.antigravity_gemini_enabled:
        raise BrainProviderConfigurationError(
            "ANTIGRAVITY_GEMINI_ENABLED must be true for "
            "BRAIN_PROVIDER=antigravity_gemini"
        )
    provider = provider_constructor(
        model_name=configuration.model,
        timeout_seconds=int(configuration.timeout_seconds),
    )
    return ProviderBuildResult(provider, image_input_enabled=True)


BUILTIN_BRAIN_PROFILES: tuple[BrainProviderProfileDefinition, ...] = (
    BrainProviderProfileDefinition(
        "mock",
        ("fake",),
        _mock_configuration,
        _build_mock,
        MockBrainProvider,
    ),
    BrainProviderProfileDefinition(
        "openai",
        (),
        lambda settings: _openai_configuration(settings, profile_id="openai"),
        _build_openai_compatible,
        OpenAICompatibleProvider,
    ),
    BrainProviderProfileDefinition(
        "openai_compatible",
        ("openai-compatible",),
        lambda settings: _openai_configuration(
            settings,
            profile_id="openai_compatible",
        ),
        _build_openai_compatible,
        OpenAICompatibleProvider,
    ),
    BrainProviderProfileDefinition(
        "gemini",
        (),
        _gemini_configuration,
        _build_gemini,
        GeminiBrainProvider,
    ),
    BrainProviderProfileDefinition(
        "codex_cli",
        (),
        _codex_configuration,
        _build_codex_cli,
        CodexCliProvider,
    ),
    BrainProviderProfileDefinition(
        "llama_cpp_qwen",
        (),
        _qwen_configuration,
        _build_qwen,
        LlamaCppQwenProvider,
    ),
    BrainProviderProfileDefinition(
        "llama_cpp_qwen38",
        (),
        _qwen38_configuration,
        _build_qwen38,
        LlamaCppQwen38VisionProvider,
    ),
    BrainProviderProfileDefinition(
        "antigravity_gemini",
        ("antigravity",),
        _antigravity_configuration,
        _build_antigravity_gemini,
        AntigravityGeminiVisionProvider,
    ),
)
