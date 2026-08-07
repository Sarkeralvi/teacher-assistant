from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.local_ai_status_service import LocalAiStatusService
from packages.brain.adapter import BrainAdapter


def test_local_ai_status_defaults_are_disabled_and_do_not_expose_secrets_or_paths() -> None:
    settings = Settings(
        LOCAL_QWEN_API_KEY="qwen-private-key",
        LOCAL_OCR_API_KEY="ocr-private-key",
        LOCAL_STORAGE_ROOT="E:/private/storage",
    )

    payload = LocalAiStatusService(settings).read()
    serialized = json.dumps(payload)

    assert payload["real_providers_allowed"] is False
    assert payload["cohort_model_grading_enabled"] is False
    assert payload["qwen"]["available"] is False
    assert payload["ocr"]["available"] is False
    assert "qwen-private-key" not in serialized
    assert "ocr-private-key" not in serialized
    assert "E:/private/storage" not in serialized


def test_local_ai_status_reports_verified_loopback_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SimpleNamespace(
        provider=SimpleNamespace(client=None),
        verify_available_model=lambda: None,
    )
    monkeypatch.setattr(
        BrainAdapter,
        "for_provider",
        classmethod(lambda cls, settings, provider: adapter),
    )
    ocr_client = SimpleNamespace(
        health=lambda: {
            "status": "ready",
            "model": "PaddleOCR-VL-1.6",
            "layout_model": "PP-DocLayoutV3",
        }
    )
    monkeypatch.setattr(
        "app.services.local_ai_status_service.LocalOcrClient.from_settings",
        classmethod(lambda cls, settings: ocr_client),
    )
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN_ENABLED=True,
        LOCAL_QWEN_API_KEY="qwen-key",
        LOCAL_OCR_ENABLED=True,
        LOCAL_OCR_API_KEY="ocr-key",
        COHORT_MODEL_GRADING_ENABLED=True,
    )

    payload = LocalAiStatusService(settings).read()

    assert payload["qwen"]["available"] is True
    assert payload["ocr"]["available"] is True
    assert payload["cohort_model_grading_enabled"] is True


def test_cohort_provider_retry_count_is_fixed_at_zero() -> None:
    assert Settings().cohort_provider_retry_count == 0
    with pytest.raises(ValidationError):
        Settings(COHORT_PROVIDER_RETRY_COUNT=1)
