from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.main import app
from app.schemas import LocalAiStatusRead
from app.services.local_ai_status_service import LocalAiStatusService
from packages.brain.adapter import BrainAdapter


def test_brain_status_alias_exposes_the_provider_neutral_runtime_contract() -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    try:
        response = TestClient(app).get("/brain/status")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    brain = response.json()["brain"]
    assert {"provider", "model", "location", "capabilities", "configured"} <= set(
        brain
    )


def test_brain_profiles_route_lists_all_registered_profiles_without_secrets() -> None:
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=False,
        BRAIN_API_KEY="catalog-secret-value",
        OPENAI_API_KEY="openai-secret-value",
        GEMINI_API_KEY="gemini-secret-value",
        LOCAL_QWEN_API_KEY="qwen-secret-value",
        LOCAL_QWEN38_API_KEY="qwen38-secret-value",
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app).get("/brain/profiles")
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    profiles = response.json()
    assert {profile["id"] for profile in profiles} == {
        "mock",
        "openai",
        "openai_compatible",
        "gemini",
        "codex_cli",
        "claude_cli",
        "llama_cpp_qwen",
        "llama_cpp_qwen38",
        "antigravity_gemini",
    }
    by_id = {profile["id"]: profile for profile in profiles}
    assert by_id["mock"]["ready"] is True
    assert by_id["llama_cpp_qwen"]["ready"] is False
    assert by_id["llama_cpp_qwen38"]["ready"] is False
    assert by_id["codex_cli"]["transport"] == "cli"
    assert by_id["codex_cli"]["data_destination"] == "cloud"
    assert "visual_mapping" in by_id["antigravity_gemini"]["capabilities"]
    assert "grading" in by_id["claude_cli"]["capabilities"]
    serialized = json.dumps(profiles)
    assert "catalog-secret-value" not in serialized
    assert "openai-secret-value" not in serialized
    assert "gemini-secret-value" not in serialized
    assert "qwen-secret-value" not in serialized
    assert "qwen38-secret-value" not in serialized


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

    public_payload = LocalAiStatusRead.model_validate(payload).model_dump()
    assert public_payload["qwen38"]["visual_preparation_enabled"] is True
    assert public_payload["qwen38"]["transcription_enabled"] is False
    assert public_payload["qwen38"]["thinking_repair_enabled"] is False
    assert public_payload["qwen38"]["grading_enabled"] is False


def test_cohort_provider_retry_count_is_fixed_at_zero() -> None:
    assert Settings().cohort_provider_retry_count == 0
    with pytest.raises(ValidationError):
        Settings(COHORT_PROVIDER_RETRY_COUNT=1)
