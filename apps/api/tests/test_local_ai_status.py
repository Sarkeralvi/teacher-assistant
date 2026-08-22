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
        LOCAL_STORAGE_ROOT="E:/private/storage",
    )

    payload = LocalAiStatusService(settings).read()
    serialized = json.dumps(payload)

    assert payload["real_providers_allowed"] is False
    assert payload["cohort_model_grading_enabled"] is False
    assert payload["qwen"]["available"] is False
    assert "qwen-private-key" not in serialized
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
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN_ENABLED=True,
        LOCAL_QWEN_API_KEY="qwen-key",
        COHORT_MODEL_GRADING_ENABLED=True,
    )

    payload = LocalAiStatusService(settings).read()

    assert payload["qwen"]["available"] is True
    assert payload["cohort_model_grading_enabled"] is True


def test_qwen38_visual_status_is_available_without_grading_enabled(
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
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN38_ENABLED=True,
        LOCAL_QWEN38_API_KEY="qwen38-key",
        LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=True,
        LOCAL_QWEN38_GRADING_ENABLED=False,
    )

    payload = LocalAiStatusService(settings).read()

    assert payload["qwen38"]["available"] is True
    assert payload["qwen38"]["detail"] == "ready"
    assert payload["qwen38"]["visual_preparation_enabled"] is True
    assert payload["qwen38"]["grading_enabled"] is False


def test_cohort_provider_retry_count_is_fixed_at_zero() -> None:
    assert Settings().cohort_provider_retry_count == 0
    with pytest.raises(ValidationError):
        Settings(COHORT_PROVIDER_RETRY_COUNT=1)
