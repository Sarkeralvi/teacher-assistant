from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from packages.brain.adapter import (
    BrainAdapter,
    BrainProviderConfigurationError,
    canonical_brain_provider_name,
)
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainProviderRuntime,
)
from packages.brain.provider_base import BrainProvider


@dataclass(frozen=True)
class BrainPolicy:
    adapter: BrainAdapter
    reference_extraction_enabled: bool
    script_preparation_enabled: bool
    single_answer_grading_enabled: bool
    visual_preparation_enabled: bool
    transcription_enabled: bool
    thinking_repair_enabled: bool
    grading_enabled: bool
    bulk_evaluation_enabled: bool
    job_timeout_seconds: int
    model_asset_sha256: str | None
    auxiliary_model_asset_sha256: str | None

    @property
    def provider(self) -> str:
        return self.adapter.runtime.provider

    @property
    def model(self) -> str:
        return self.adapter.runtime.model

    @property
    def location(self) -> BrainExecutionLocation:
        return self.adapter.runtime.location

    def supports(self, capability: BrainCapability) -> bool:
        return self.adapter.runtime.supports(capability)

    def validate_request(
        self,
        *,
        requested_provider: str,
        expected_model: str,
        capability: BrainCapability,
        feature_enabled: bool,
    ) -> None:
        normalized = requested_provider.strip().lower()
        if normalized not in {"", "brain", "active"}:
            normalized = canonical_brain_provider_name(normalized)
        if normalized not in {"", "brain", "active", self.provider.casefold()}:
            raise BrainProviderConfigurationError(
                "Requested provider does not match the configured active brain provider"
            )
        if expected_model != self.model:
            raise BrainProviderConfigurationError(
                "Expected model does not match the configured active brain model"
            )
        if not feature_enabled:
            raise BrainProviderConfigurationError(
                f"The {capability.value} feature is disabled for the active brain provider"
            )
        if not self.supports(capability):
            raise BrainProviderConfigurationError(
                f"Provider {self.provider} does not support {capability.value}"
            )

    def require_data_boundary_confirmation(self, *, confirmed: bool) -> None:
        """Refuse cloud evidence transfer until the teacher confirms it explicitly."""

        if self.location is BrainExecutionLocation.CLOUD and not confirmed:
            raise BrainProviderConfigurationError(
                "Cloud provider data transfer must be explicitly confirmed"
            )


def brain_policy_from_settings(
    settings: Settings,
    *,
    requested_provider: str | None = None,
    adapter_override: Any | None = None,
) -> BrainPolicy:
    resolved_provider = (requested_provider or settings.brain_provider).strip().lower()
    if resolved_provider in {"", "brain", "active"}:
        resolved_provider = settings.brain_provider
    adapter = adapter_override or BrainAdapter.for_provider(settings, resolved_provider)
    adapter = normalize_brain_adapter(
        adapter,
        settings=settings,
        requested_provider=resolved_provider,
    )
    provider = adapter.runtime.provider
    is_qwen38 = provider == "llama_cpp_qwen38"
    vision_transport_enabled = bool(getattr(adapter.provider, "vision_enabled", True))

    reference_enabled = _coalesce(
        settings.brain_reference_extraction_enabled,
        settings.local_reference_extraction_enabled,
    )
    script_enabled = _coalesce(
        settings.brain_script_preparation_enabled,
        settings.local_script_preparation_enabled,
    )
    single_grade_enabled = _coalesce(
        settings.brain_single_answer_grading_enabled,
        settings.local_single_answer_grading_enabled,
    )
    visual_enabled = _coalesce(
        settings.brain_visual_preparation_enabled,
        settings.local_qwen38_visual_preparation_enabled
        if is_qwen38
        else script_enabled or reference_enabled,
    )
    transcription_enabled = _coalesce(
        settings.brain_transcription_enabled,
        settings.local_qwen38_transcription_enabled if is_qwen38 else False,
    )
    thinking_enabled = _coalesce(
        settings.brain_thinking_repair_enabled,
        settings.local_qwen38_thinking_repair_enabled if is_qwen38 else False,
    )
    grading_enabled = _coalesce(
        settings.brain_grading_enabled,
        settings.local_qwen38_grading_enabled if is_qwen38 else single_grade_enabled,
    )
    bulk_enabled = _coalesce(
        settings.brain_bulk_evaluation_enabled,
        settings.bulk_supervised_enabled,
    )
    if not vision_transport_enabled:
        visual_enabled = False
        transcription_enabled = False
        thinking_enabled = False

    timeout = settings.brain_job_timeout_seconds
    if timeout is None:
        timeout = (
            settings.local_qwen38_visual_job_timeout_seconds
            if is_qwen38
            else min(3600, max(300, int(settings.brain_timeout_seconds) + 60))
        )
    model_hash = settings.brain_model_sha256 or (
        settings.local_qwen38_model_sha256 if is_qwen38 else ""
    )
    auxiliary_hash = settings.brain_aux_model_sha256 or (
        settings.local_qwen38_mmproj_sha256 if is_qwen38 else ""
    )
    return BrainPolicy(
        adapter=adapter,
        reference_extraction_enabled=reference_enabled,
        script_preparation_enabled=script_enabled,
        single_answer_grading_enabled=single_grade_enabled,
        visual_preparation_enabled=visual_enabled,
        transcription_enabled=transcription_enabled,
        thinking_repair_enabled=thinking_enabled,
        grading_enabled=grading_enabled,
        bulk_evaluation_enabled=bulk_enabled,
        job_timeout_seconds=timeout,
        model_asset_sha256=model_hash or None,
        auxiliary_model_asset_sha256=auxiliary_hash or None,
    )


def configured_visual_provider(settings: Settings) -> str:
    """Preserve the pre-universal Qwen visual profile when no brain was selected."""

    provider = settings.brain_provider.strip().lower() or "mock"
    if (
        provider == "mock"
        and not settings.brain_model
        and settings.local_qwen38_enabled
    ):
        return "llama_cpp_qwen38"
    return provider


def normalize_brain_adapter(
    adapter: Any,
    *,
    settings: Settings,
    requested_provider: str,
) -> Any:
    """Attach universal runtime metadata to legacy adapters and test doubles."""

    if not hasattr(adapter, "provider"):
        adapter.provider = SimpleNamespace(
            provider_name=requested_provider,
            model_name=settings.brain_model or "mock-grader-v1",
        )
    if not hasattr(adapter, "runtime"):
        adapter.runtime = _legacy_runtime(
            adapter,
            settings=settings,
            requested_provider=requested_provider,
        )
    if not hasattr(adapter, "image_input_enabled"):
        adapter.image_input_enabled = bool(
            getattr(adapter.provider, "image_input_enabled", True)
        )
    return adapter


def _coalesce(value: bool | None, fallback: bool) -> bool:
    return fallback if value is None else value


def _legacy_runtime(
    adapter: BrainAdapter,
    *,
    settings: Settings,
    requested_provider: str,
) -> BrainProviderRuntime:
    """Normalize old injected adapters used by integrations and test harnesses."""

    provider = adapter.provider
    method_capabilities = {
        "grade": BrainCapability.GRADING,
        "extract_questions_from_pdf": BrainCapability.QUESTION_PDF_EXTRACTION,
        "extract_rubric_from_pdf": BrainCapability.RUBRIC_PDF_EXTRACTION,
        "extract_reference_bundle_from_images": BrainCapability.VISUAL_REFERENCE_EXTRACTION,
        "map_page_answer_regions": BrainCapability.VISUAL_MAPPING,
        "transcribe_images": BrainCapability.VISUAL_TRANSCRIPTION,
        "repair_transcription_images": BrainCapability.TRANSCRIPTION_REPAIR,
    }
    declared_capabilities = vars(provider).get(
        "capabilities",
        type(provider).__dict__.get("capabilities"),
    )
    capabilities = set(declared_capabilities or ())
    if declared_capabilities is None:
        capabilities.update(
            capability
            for method, capability in method_capabilities.items()
            if callable(getattr(provider, method, None))
            and (
                not isinstance(provider, BrainProvider)
                or getattr(type(provider), method, None)
                is not getattr(BrainProvider, method, None)
            )
        )
    if callable(getattr(adapter, "grade_answer_region", None)):
        capabilities.add(BrainCapability.GRADING)
    if callable(getattr(adapter, "map_page_answer_regions", None)):
        capabilities.add(BrainCapability.VISUAL_MAPPING)
    if callable(getattr(adapter, "transcribe_images", None)):
        capabilities.add(BrainCapability.VISUAL_TRANSCRIPTION)
    if callable(getattr(adapter, "repair_transcription_images", None)):
        capabilities.add(BrainCapability.TRANSCRIPTION_REPAIR)
    model = str(getattr(provider, "model_name", "") or "")
    if not model and requested_provider == "llama_cpp_qwen38":
        model = settings.local_qwen38_model
    elif not model and requested_provider in {"llama_cpp_qwen", "qwen"}:
        model = settings.local_qwen_model
    elif not model:
        model = settings.brain_model or "mock-grader-v1"
    location = getattr(provider, "execution_location", None)
    if location is None:
        location = (
            BrainExecutionLocation.LOCAL
            if requested_provider.startswith("llama_cpp_")
            else BrainExecutionLocation.CLOUD
        )
    managed_phase = getattr(provider, "managed_local_phase", None)
    if managed_phase is None and requested_provider == "llama_cpp_qwen38":
        managed_phase = "Qwen38"
    elif managed_phase is None and requested_provider in {"llama_cpp_qwen", "qwen"}:
        managed_phase = "Qwen"
    return BrainProviderRuntime(
        provider=str(getattr(provider, "provider_name", "") or requested_provider),
        model=model,
        location=BrainExecutionLocation(location),
        capabilities=frozenset(capabilities),
        image_input_mode=BrainImageInputMode(
            getattr(provider, "image_input_mode", BrainImageInputMode.NONE)
        ),
        managed_local_phase=managed_phase,
    )
