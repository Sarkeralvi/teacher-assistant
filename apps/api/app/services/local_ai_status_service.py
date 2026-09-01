from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.local_ocr_client import LocalOcrClient
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.policy import brain_policy_from_settings, configured_visual_provider


class LocalAiStatusService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def read(self) -> dict[str, Any]:
        return {
            "real_providers_allowed": self.settings.brain_allow_real_providers,
            "cohort_model_grading_enabled": self.settings.cohort_model_grading_enabled,
            "local_script_preparation_enabled": (self.settings.local_script_preparation_enabled),
            "local_single_answer_grading_enabled": (
                self.settings.local_single_answer_grading_enabled
            ),
            "brain": self._brain_status(),
            "paddle_ocr": self._paddle_ocr_status(),
            "qwen": self._qwen_status(),
            "qwen38": self._qwen38_status(),
        }

    def _brain_status(self) -> dict[str, Any]:
        """Describe the configured brain without contacting an external endpoint."""

        provider = configured_visual_provider(self.settings)
        base: dict[str, Any] = {
            "enabled": provider == "mock" or self.settings.brain_allow_real_providers,
            "configured": False,
            "available": False,
            "provider": provider,
            "model": self.settings.brain_model or "",
            "layout_model": None,
            "device": self.settings.brain_endpoint_type,
            "location": self.settings.brain_endpoint_type,
            "detail": None,
            "models": [self.settings.brain_model] if self.settings.brain_model else [],
            "capabilities": [],
        }
        if provider != "mock" and not self.settings.brain_allow_real_providers:
            base["detail"] = "blocked_by_provider_kill_switch"
            return base
        try:
            policy = brain_policy_from_settings(
                self.settings,
                requested_provider=provider,
            )
        except BrainProviderConfigurationError as exc:
            base["detail"] = str(exc)
            return base
        except Exception:
            # Status remains fail-closed if a provider plugin cannot expose its
            # runtime metadata. Legacy daemon status is still reported below.
            base["detail"] = "provider_metadata_unavailable"
            return base
        runtime = policy.adapter.runtime
        base.update(
            {
                "enabled": True,
                "configured": True,
                # This is configuration readiness, not a live endpoint probe.
                "available": True,
                "provider": runtime.provider,
                "model": runtime.model,
                "device": runtime.location.value,
                "location": runtime.location.value,
                "detail": "configured",
                "models": [runtime.model],
                "capabilities": sorted(item.value for item in runtime.capabilities),
                "visual_preparation_enabled": policy.visual_preparation_enabled,
                "page_read_enabled": policy.page_read_enabled,
                "transcription_enabled": policy.transcription_enabled,
                "thinking_repair_enabled": policy.thinking_repair_enabled,
                "grading_enabled": policy.grading_enabled,
                "reference_extraction_enabled": policy.reference_extraction_enabled,
                "script_preparation_enabled": policy.script_preparation_enabled,
                "bulk_evaluation_enabled": policy.bulk_evaluation_enabled,
            }
        )
        return base

    def _paddle_ocr_status(self) -> dict[str, Any]:
        base = {
            "enabled": self.settings.local_paddle_ocr_enabled,
            "available": False,
            "provider": "local_paddle_qwen",
            "model": self.settings.local_paddle_ocr_model,
            "layout_model": self.settings.local_paddle_ocr_layout_model,
            "device": "gpu_exclusive_phase",
            "detail": None,
            "models": [
                self.settings.local_paddle_ocr_model,
                self.settings.local_paddle_ocr_layout_model,
            ],
        }
        if not self.settings.local_paddle_ocr_enabled:
            base["detail"] = "disabled"
            return base
        if not self.settings.brain_allow_real_providers:
            base["detail"] = "blocked_by_provider_kill_switch"
            return base
        if not self.settings.local_paddle_ocr_api_key:
            base["detail"] = "missing_api_key"
            return base
        try:
            LocalOcrClient.from_settings(self.settings).health()
        except Exception:
            base["detail"] = "unavailable_or_model_mismatch"
            return base
        base["available"] = True
        base["detail"] = "ready"
        return base

    def _qwen_status(self) -> dict[str, Any]:
        base = {
            "enabled": self.settings.local_qwen_enabled,
            "available": False,
            "provider": "llama_cpp_qwen",
            "model": self.settings.local_qwen_model,
            "layout_model": None,
            "device": "gpu_hybrid",
            "detail": None,
            "models": [self.settings.local_qwen_model],
        }
        if not self.settings.local_qwen_enabled:
            base["detail"] = "disabled"
            return base
        if not self.settings.brain_allow_real_providers:
            base["detail"] = "blocked_by_provider_kill_switch"
            return base
        if not self.settings.local_qwen_api_key:
            base["detail"] = "missing_api_key"
            return base
        try:
            adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen")
            with httpx.Client(
                base_url=self.settings.local_qwen_base_url.rstrip("/") + "/",
                timeout=min(self.settings.local_qwen_timeout_seconds, 5.0),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                adapter.provider.client = client
                adapter.verify_available_model()
        except Exception:
            base["detail"] = "unavailable_or_model_mismatch"
            return base
        base["available"] = True
        base["detail"] = "ready"
        return base

    def _qwen38_status(self) -> dict[str, Any]:
        base = {
            "enabled": self.settings.local_qwen38_enabled,
            "available": False,
            "provider": "llama_cpp_qwen38",
            "model": self.settings.local_qwen38_model,
            "layout_model": None,
            "device": "gpu_hybrid_single_slot",
            "detail": None,
            "models": [self.settings.local_qwen38_model],
            "visual_preparation_enabled": self.settings.local_qwen38_visual_preparation_enabled,
            "page_read_enabled": self.settings.local_qwen38_page_read_enabled,
            "transcription_enabled": self.settings.local_qwen38_transcription_enabled,
            "thinking_repair_enabled": self.settings.local_qwen38_thinking_repair_enabled,
            "grading_enabled": self.settings.local_qwen38_grading_enabled,
        }
        if not self.settings.local_qwen38_enabled:
            base["detail"] = "disabled"
            return base
        if not self.settings.brain_allow_real_providers:
            base["detail"] = "blocked_by_provider_kill_switch"
            return base
        if not self.settings.local_qwen38_api_key:
            base["detail"] = "missing_api_key"
            return base
        try:
            adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen38")
            with httpx.Client(
                base_url=self.settings.local_qwen38_base_url.rstrip("/") + "/",
                timeout=min(self.settings.local_qwen38_timeout_seconds, 5.0),
                trust_env=False,
                follow_redirects=False,
            ) as client:
                adapter.provider.client = client
                adapter.verify_available_model()
        except Exception:
            base["detail"] = "unavailable_or_model_mismatch"
            return base
        base["available"] = True
        if not (
            self.settings.local_qwen38_transcription_enabled
            or self.settings.local_qwen38_thinking_repair_enabled
            or self.settings.local_qwen38_visual_preparation_enabled
            or self.settings.local_qwen38_page_read_enabled
        ):
            base["detail"] = "ready_features_disabled"
        else:
            base["detail"] = "ready"
        return base
