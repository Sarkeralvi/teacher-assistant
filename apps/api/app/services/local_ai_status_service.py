from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from packages.brain.adapter import BrainAdapter


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
                or self.settings.local_qwen38_grading_enabled
            ),
            "qwen": self._qwen_status(),
            "qwen38": self._qwen38_status(),
        }

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
        if (
            not self.settings.local_qwen38_visual_preparation_enabled
            and not self.settings.local_qwen38_grading_enabled
        ):
            base["detail"] = "ready_features_disabled"
        elif self.settings.local_qwen38_visual_preparation_enabled:
            base["detail"] = "ready"
        else:
            base["detail"] = "ready_grading_only"
        return base
