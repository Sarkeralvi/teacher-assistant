from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.services.local_script_page_read import (
    LocalScriptPageReadError,
    LocalScriptPageReadService,
)
from packages.brain.policy import brain_policy_for_profile
from packages.brain.profiles import legacy_profile_settings


@pytest.mark.parametrize("active_provider", ["llama_cpp_qwen38", "antigravity_gemini"])
@pytest.mark.parametrize("requested_provider", ["antigravity_gemini", "antigravity"])
def test_antigravity_page_read_uses_selected_profile_model(
    active_provider: str, requested_provider: str,
) -> None:
    settings = Settings(
        _env_file=None,
        BRAIN_PROVIDER=active_provider,
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="Qwen/Qwen3.8-27B",
        BRAIN_TIMEOUT_SECONDS=300,
        BRAIN_SCRIPT_PREPARATION_ENABLED=True,
        ANTIGRAVITY_GEMINI_ENABLED=True,
        ANTIGRAVITY_GEMINI_MODEL="gemini-3.8-flash-high",
        ANTIGRAVITY_GEMINI_TIMEOUT_SECONDS=120,
        ANTIGRAVITY_GEMINI_PAGE_READ_ENABLED=True,
    )
    selected = brain_policy_for_profile(settings, "antigravity_gemini")
    service = LocalScriptPageReadService(MagicMock(), settings=settings)

    policy = service._validate_authorization(
        selected.model, provider=requested_provider,
    )

    assert policy.model == "gemini-3.8-flash-high"
    assert policy.adapter.provider.timeout_seconds == 120
    with pytest.raises(LocalScriptPageReadError, match="Expected model does not match"):
        service._validate_authorization(settings.brain_model, provider=requested_provider)


def test_generic_brain_overrides_do_not_leak_into_local_qwen38() -> None:
    """Regression for TA-DIAG-001.

    A generic BRAIN_BASE_URL/BRAIN_API_KEY/BRAIN_MODEL configured for the
    openai_compatible cloud profile (e.g. AkashML) must never redirect the
    dedicated local-loopback Qwen3.8 profile. Before this fix, selecting
    llama_cpp_qwen38 while those generic vars were set silently overwrote
    LOCAL_QWEN38_BASE_URL/LOCAL_QWEN38_API_KEY/LOCAL_QWEN38_MODEL with the
    cloud values, so every local grading/mapping/transcription call was
    misrouted at a cloud host and rejected by the loopback guard before any
    request was sent.
    """

    settings = Settings(
        BRAIN_PROVIDER="llama_cpp_qwen38",
        BRAIN_MODEL="Qwen/Qwen3.8-27B",
        BRAIN_API_KEY="akml-test-key",
        BRAIN_BASE_URL="https://api.akashml.com/v1",
        LOCAL_QWEN38_BASE_URL="http://127.0.0.1:8085/v1",
        LOCAL_QWEN38_API_KEY="local-loopback-key",
        LOCAL_QWEN38_MODEL="qwen3.8-27b-q4km",
    )

    effective = legacy_profile_settings(settings, "llama_cpp_qwen38")

    assert effective.local_qwen38_base_url == "http://127.0.0.1:8085/v1"
    assert effective.local_qwen38_api_key == "local-loopback-key"
    assert effective.local_qwen38_model == "qwen3.8-27b-q4km"


def test_generic_brain_overrides_do_not_leak_into_local_qwen36() -> None:
    settings = Settings(
        BRAIN_PROVIDER="llama_cpp_qwen",
        BRAIN_MODEL="Qwen/Qwen3.8-27B",
        BRAIN_API_KEY="akml-test-key",
        BRAIN_BASE_URL="https://api.akashml.com/v1",
        LOCAL_QWEN_BASE_URL="http://127.0.0.1:8086/v1",
        LOCAL_QWEN_API_KEY="local-loopback-key",
        LOCAL_QWEN_MODEL="qwen3.6-35b-a3b-q4km",
    )

    effective = legacy_profile_settings(settings, "llama_cpp_qwen")

    assert effective.local_qwen_base_url == "http://127.0.0.1:8086/v1"
    assert effective.local_qwen_api_key == "local-loopback-key"
    assert effective.local_qwen_model == "qwen3.6-35b-a3b-q4km"


def test_generic_brain_overrides_still_apply_to_openai_and_gemini() -> None:
    """Existing legacy-profile override behaviour must be unchanged."""

    openai_settings = legacy_profile_settings(
        Settings(
            BRAIN_PROVIDER="openai",
            BRAIN_MODEL="gpt-test",
            BRAIN_API_KEY="openai-test-key",
            BRAIN_BASE_URL="https://api.openai.example/v1",
        ),
        "openai",
    )
    assert openai_settings.openai_model == "gpt-test"
    assert openai_settings.openai_api_key == "openai-test-key"
    assert openai_settings.openai_base_url == "https://api.openai.example/v1"

    gemini_settings = legacy_profile_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_MODEL="gemini-test",
            BRAIN_API_KEY="gemini-test-key",
        ),
        "gemini",
    )
    assert gemini_settings.gemini_model == "gemini-test"
    assert gemini_settings.gemini_api_key == "gemini-test-key"


def test_generic_brain_timeout_does_not_replace_the_local_qwen38_timeout() -> None:
    """RC-54: LOCAL_QWEN38_TIMEOUT_SECONDS is the effective per-call timeout of the profile."""

    settings = Settings(
        BRAIN_PROVIDER="llama_cpp_qwen38",
        BRAIN_MODEL="Qwen/Qwen3.8-27B",
        BRAIN_TIMEOUT_SECONDS=600,
        LOCAL_QWEN38_TIMEOUT_SECONDS=900,
    )

    effective = legacy_profile_settings(settings, "llama_cpp_qwen38")

    assert effective.local_qwen38_timeout_seconds == 900


def test_the_managed_local_call_timeout_stays_below_the_model_lease() -> None:
    """A call may never outlive the model lease it holds (refreshed only around the call)."""

    from app.services.local_model_lease_service import DEFAULT_LEASE_SECONDS
    from packages.brain.profiles import (
        MANAGED_LOCAL_CALL_TIMEOUT_CEILING_SECONDS,
        _qwen38_configuration,
    )

    assert MANAGED_LOCAL_CALL_TIMEOUT_CEILING_SECONDS <= DEFAULT_LEASE_SECONDS - 300
    long = _qwen38_configuration(Settings(LOCAL_QWEN38_TIMEOUT_SECONDS=1800))
    short = _qwen38_configuration(Settings(LOCAL_QWEN38_TIMEOUT_SECONDS=600))
    assert long.timeout_seconds == MANAGED_LOCAL_CALL_TIMEOUT_CEILING_SECONDS
    assert short.timeout_seconds == 600
