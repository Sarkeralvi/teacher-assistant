import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from packages.brain.adapter import (
    BrainAdapter,
    BrainProviderConfigurationError,
    ProviderBuildResult,
    register_brain_provider,
)
from packages.brain.capabilities import BrainCapability, BrainExecutionLocation
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.policy import brain_policy_from_settings
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas_qwen38 import VisualPageMappingOutput


def test_openai_compatible_local_endpoint_does_not_require_an_api_key() -> None:
    settings = Settings(
        BRAIN_PROVIDER="openai_compatible",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="local-model",
        BRAIN_BASE_URL="http://127.0.0.1:9000/v1",
        BRAIN_ENDPOINT_TYPE="local",
        BRAIN_IMAGE_INPUT_ENABLED=True,
    )

    adapter = BrainAdapter.from_settings(settings)

    assert adapter.runtime.provider == "openai_compatible"
    assert adapter.runtime.model == "local-model"
    assert adapter.runtime.location is BrainExecutionLocation.LOCAL
    assert adapter.supports(BrainCapability.GRADING)
    assert adapter.supports(BrainCapability.VISUAL_MAPPING)


def test_openai_compatible_cloud_endpoint_requires_an_api_key() -> None:
    settings = Settings(
        BRAIN_PROVIDER="openai_compatible",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="cloud-model",
        BRAIN_BASE_URL="https://models.example.invalid/v1",
        BRAIN_ENDPOINT_TYPE="cloud",
    )

    with pytest.raises(BrainProviderConfigurationError, match="BRAIN_API_KEY"):
        BrainAdapter.from_settings(settings)


def test_gemini_uses_the_universal_key_model_and_capability_policy() -> None:
    settings = Settings(
        BRAIN_PROVIDER="gemini",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_API_KEY="test-only-key",
        BRAIN_MODEL="gemini-test-model",
        BRAIN_IMAGE_INPUT_ENABLED=True,
        BRAIN_REFERENCE_EXTRACTION_ENABLED=True,
        BRAIN_SCRIPT_PREPARATION_ENABLED=True,
        BRAIN_SINGLE_ANSWER_GRADING_ENABLED=True,
        BRAIN_VISUAL_PREPARATION_ENABLED=True,
        BRAIN_TRANSCRIPTION_ENABLED=True,
        BRAIN_THINKING_REPAIR_ENABLED=True,
        BRAIN_GRADING_ENABLED=True,
        BRAIN_BULK_EVALUATION_ENABLED=True,
    )

    policy = brain_policy_from_settings(settings)

    assert policy.provider == "gemini"
    assert policy.model == "gemini-test-model"
    assert policy.location is BrainExecutionLocation.CLOUD
    assert policy.supports(BrainCapability.VISUAL_REFERENCE_EXTRACTION)
    assert policy.supports(BrainCapability.VISUAL_MAPPING)
    assert policy.supports(BrainCapability.VISUAL_TRANSCRIPTION)
    assert policy.supports(BrainCapability.TRANSCRIPTION_REPAIR)
    assert policy.supports(BrainCapability.GRADING)
    assert policy.bulk_evaluation_enabled is True


def test_cloud_policy_requires_explicit_data_boundary_confirmation() -> None:
    policy = brain_policy_from_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_API_KEY="test-only-key",
        )
    )

    with pytest.raises(
        BrainProviderConfigurationError,
        match="Cloud provider data transfer must be explicitly confirmed",
    ):
        policy.require_data_boundary_confirmation(confirmed=False)

    policy.require_data_boundary_confirmation(confirmed=True)


def test_gemini_visual_mapping_uses_the_shared_validated_contract() -> None:
    settings = Settings(
        BRAIN_PROVIDER="gemini",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_API_KEY="test-only-key",
        BRAIN_IMAGE_INPUT_ENABLED=True,
    )
    adapter = BrainAdapter.from_settings(settings)
    response = SimpleNamespace(
        text=json.dumps(
            {
                "regions": [
                    {
                        "question_label": "Q1",
                        "bbox": [10, 20, 900, 800],
                        "continues_from_previous": False,
                        "continues_to_next": False,
                        "confidence": "0.91",
                        "warnings": [],
                    }
                ],
                "needs_review": True,
            }
        ),
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=20,
        ),
    )
    adapter.provider._generate = lambda _contents, **_kwargs: response

    result = adapter.map_page_answer_regions(
        image_bytes=b"not-a-real-image-but-never-decoded",
        mime_type="image/png",
        question_labels=["Q1"],
    )

    assert result.needs_review is True
    assert result.regions[0].question_label == "Q1"


def test_new_provider_can_register_without_workflow_changes() -> None:
    class ExampleProvider(MockBrainProvider):
        provider_name = "example_provider"
        model_name = "example-model"
        execution_location = BrainExecutionLocation.CLOUD

    def build_example(_settings: Settings, _requested: str) -> ProviderBuildResult:
        return ProviderBuildResult(ExampleProvider())

    register_brain_provider("example_provider", build_example)
    adapter = BrainAdapter.for_provider(
        Settings(
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_PROVIDER="example_provider",
        ),
        "example_provider",
    )

    assert adapter.runtime.provider == "example_provider"
    assert adapter.runtime.model == "example-model"
    assert adapter.supports(BrainCapability.GRADING)


def test_capability_only_provider_does_not_need_a_dummy_grading_method() -> None:
    class MappingOnlyProvider(BrainProvider):
        provider_name = "mapping_only_test"
        model_name = "mapping-only-model"
        execution_location = BrainExecutionLocation.LOCAL
        capabilities = frozenset({BrainCapability.VISUAL_MAPPING})

        def map_page_answer_regions(self, **_kwargs: object) -> VisualPageMappingOutput:
            return VisualPageMappingOutput.model_validate(
                {"regions": [], "needs_review": True}
            )

    def build_mapping_only(_settings: Settings, _requested: str) -> ProviderBuildResult:
        return ProviderBuildResult(MappingOnlyProvider(), image_input_enabled=True)

    register_brain_provider("mapping_only_test", build_mapping_only)
    adapter = BrainAdapter.for_provider(
        Settings(
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_PROVIDER="mapping_only_test",
        ),
        "mapping_only_test",
    )

    result = adapter.map_page_answer_regions(
        image_bytes=b"test-image",
        mime_type="image/png",
        question_labels=["Q1"],
    )

    assert result.needs_review is True
    assert adapter.supports(BrainCapability.VISUAL_MAPPING)
    assert not adapter.supports(BrainCapability.GRADING)


def test_legacy_named_local_provider_inherits_its_local_runtime_metadata() -> None:
    class LegacyQwenDouble(BrainProvider):
        provider_name = "llama_cpp_qwen"
        model_name = "legacy-qwen"
        capabilities = frozenset({BrainCapability.GRADING})

    adapter = BrainAdapter(LegacyQwenDouble())

    assert adapter.runtime.location is BrainExecutionLocation.LOCAL
    assert adapter.runtime.managed_local_phase == "Qwen"


def test_registered_alias_validates_against_the_canonical_provider() -> None:
    settings = Settings(
        BRAIN_PROVIDER="openai-compatible",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="local-model",
        BRAIN_BASE_URL="http://127.0.0.1:9000/v1",
        BRAIN_ENDPOINT_TYPE="local",
        BRAIN_GRADING_ENABLED=True,
    )
    policy = brain_policy_from_settings(settings)

    policy.validate_request(
        requested_provider="openai-compatible",
        expected_model="local-model",
        capability=BrainCapability.GRADING,
        feature_enabled=policy.grading_enabled,
    )

    assert policy.provider == "openai_compatible"


def test_http_provider_rejects_cli_endpoint_classification() -> None:
    settings = Settings(
        BRAIN_PROVIDER="openai_compatible",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="remote-model",
        BRAIN_BASE_URL="https://models.example.invalid/v1",
        BRAIN_ENDPOINT_TYPE="cli",
    )

    with pytest.raises(BrainProviderConfigurationError, match="auto, local, or cloud"):
        BrainAdapter.from_settings(settings)


def test_gemini_does_not_advertise_image_capabilities_when_image_input_is_disabled() -> None:
    adapter = BrainAdapter.from_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_API_KEY="test-only-key",
            BRAIN_IMAGE_INPUT_ENABLED=False,
        )
    )

    assert adapter.supports(BrainCapability.GRADING)
    assert not adapter.supports(BrainCapability.QUESTION_PDF_EXTRACTION)
    assert not adapter.supports(BrainCapability.VISUAL_MAPPING)


def test_visual_page_read_is_not_a_default_universal_provider_capability() -> None:
    adapter = BrainAdapter.from_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_API_KEY="test-only-key",
            BRAIN_IMAGE_INPUT_ENABLED=True,
        )
    )

    assert not adapter.supports(BrainCapability.VISUAL_PAGE_READ)


def test_gemini_structured_vision_honors_schema_and_token_budget() -> None:
    class SmallOutput(BaseModel):
        ok: bool

    adapter = BrainAdapter.from_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_API_KEY="test-only-key",
            BRAIN_IMAGE_INPUT_ENABLED=True,
            BRAIN_STRUCTURED_OUTPUT_MODE="json_schema",
        )
    )
    captured: dict[str, object] = {}

    def fake_generate(_contents: list[object], **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=1,
                candidates_token_count=2,
            ),
        )

    adapter.provider._generate = fake_generate
    result = adapter.provider._complete_structured_vision(
        prompt="Return the schema",
        images=[(b"image", "image/png")],
        response_model=SmallOutput,
        schema_name="small_output",
        max_tokens=123,
    )

    config = captured["config"]
    assert isinstance(config, dict)
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == SmallOutput.model_json_schema()
    assert config["max_output_tokens"] == 123
    assert result.payload == {"ok": True}


def test_adapter_redacts_provider_specific_secret_values() -> None:
    secret = "arbitrary-provider-secret-value"
    adapter = BrainAdapter.from_settings(
        Settings(
            BRAIN_PROVIDER="gemini",
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            BRAIN_API_KEY=secret,
            BRAIN_IMAGE_INPUT_ENABLED=True,
        )
    )

    def fail_generate(_contents: list[object], **_kwargs: object) -> object:
        raise RuntimeError(f"upstream rejected credential {secret}")

    adapter.provider._generate = fail_generate
    with pytest.raises(RuntimeError) as exc_info:
        adapter.map_page_answer_regions(
            image_bytes=b"image",
            mime_type="image/png",
            question_labels=["Q1"],
        )

    assert secret not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_env_file_blank_optional_brain_values_use_defaults(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    optional_names = (
        "BRAIN_IMAGE_INPUT_ENABLED",
        "BRAIN_JOB_TIMEOUT_SECONDS",
        "BRAIN_REFERENCE_EXTRACTION_ENABLED",
    )
    for name in optional_names:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "optional-brain.env"
    env_file.write_text(
        "BRAIN_IMAGE_INPUT_ENABLED=\n"
        "BRAIN_JOB_TIMEOUT_SECONDS=\n"
        "BRAIN_REFERENCE_EXTRACTION_ENABLED=\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.brain_image_input_enabled is None
    assert settings.brain_job_timeout_seconds is None
    assert settings.brain_reference_extraction_enabled is None
