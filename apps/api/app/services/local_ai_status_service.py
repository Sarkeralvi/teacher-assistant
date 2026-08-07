from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.local_ocr_client import LocalOcrClient
from packages.brain.adapter import BrainAdapter


class LocalAiStatusService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def read(self) -> dict[str, Any]:
        return {
            "real_providers_allowed": self.settings.brain_allow_real_providers,
            "cohort_model_grading_enabled": self.settings.cohort_model_grading_enabled,
            "qwen": self._qwen_status(),
            "ocr": self._ocr_status(),
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

    def _ocr_status(self) -> dict[str, Any]:
        base = {
            "enabled": self.settings.local_ocr_enabled,
            "available": False,
            "provider": "local_paddle_qwen",
            "model": "PaddleOCR-VL-1.6",
            "layout_model": "PP-DocLayoutV3",
            "device": "cpu",
            "detail": None,
        }
        if not self.settings.local_ocr_enabled:
            base["detail"] = "disabled"
            return base
        if not self.settings.brain_allow_real_providers:
            base["detail"] = "blocked_by_provider_kill_switch"
            return base
        try:
            health = LocalOcrClient.from_settings(self.settings).health()
        except Exception:
            base["detail"] = "unavailable"
            return base
        base["available"] = health.get("status") == "ready"
        base["model"] = str(health.get("model") or base["model"])
        base["layout_model"] = str(health.get("layout_model") or base["layout_model"])
        base["detail"] = "ready" if base["available"] else "unavailable"
        return base
