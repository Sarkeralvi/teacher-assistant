from app.core.config import Settings
from packages.brain.profiles import legacy_profile_settings


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
