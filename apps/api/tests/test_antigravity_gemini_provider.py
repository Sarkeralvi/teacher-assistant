"""Tests for AntigravityGeminiVisionProvider."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from packages.brain.adapter import BrainAdapter
from packages.brain.antigravity_gemini_vision_provider import (
    PROVIDER_NAME,
    AntigravityGeminiVisionProvider,
)
from packages.brain.capabilities import BrainCapability


@pytest.fixture
def provider(tmp_path):
    """Create a provider instance with an isolated temp-image directory."""
    return AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=120,
        repository_root=tmp_path,
    )


def test_provider_initialization(tmp_path):
    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=120,
        repository_root=tmp_path,
    )
    assert provider.model_name == "gemini-3.8-flash-high"
    assert provider.timeout_seconds == 120
    assert provider.provider_name == PROVIDER_NAME


def test_provider_declares_no_capabilities_until_canonical_wrappers_exist(tmp_path):
    """transcribe_image()/read_page() use this provider's own argument shape,
    not the canonical BrainProvider contract, so declaring these capabilities
    would let BrainAdapter construct and then crash on first real call."""
    provider = AntigravityGeminiVisionProvider(repository_root=tmp_path)
    assert provider.capabilities == frozenset()
    assert BrainCapability.VISUAL_TRANSCRIPTION not in provider.capabilities
    assert BrainCapability.VISUAL_PAGE_READ not in provider.capabilities


def test_brain_adapter_constructs_with_no_declared_capabilities(tmp_path):
    provider = AntigravityGeminiVisionProvider(repository_root=tmp_path)
    adapter = BrainAdapter(provider)
    assert adapter.runtime.capabilities == frozenset()


def test_transcribe_image_with_mocked_agy(provider):
    """transcribe_image writes a temp file, calls agy, deletes the temp file, and
    fills in provider-computed metadata that the draft schema never asked the
    model for."""
    image_bytes = b"fake-image-data"

    mock_response = {
        "status": "SUCCESS",
        "response": json.dumps(
            {
                "draft_text": "The answer is 42",
                "uncertain_glyphs": [],
                "editing_marks": [],
                "cancellation_detected": False,
                "replacement_detected": False,
                "uncertain_correction_detected": False,
                "is_blank": False,
                "is_irrelevant": False,
                "confidence": 0.95,
            }
        ),
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

    captured_paths = []

    def fake_run(cmd, **kwargs):
        # The prompt (cmd[2]) must reference an absolute, forward-slash path
        # to a file that actually exists at call time, then get cleaned up.
        prompt = cmd[2]
        assert "view_file" in prompt
        assert "\\" not in prompt.split("absolute path ")[1].split(" ")[0]
        captured_paths.append(prompt)
        return SimpleNamespace(returncode=0, stdout=json.dumps(mock_response), stderr="")

    with patch("subprocess.run", side_effect=fake_run) as mock_run:
        result = provider.transcribe_image(
            image_bytes=image_bytes,
            source_image_sha256="a" * 64,
            prompt_version="v1",
        )

    assert result.draft_text == "The answer is 42"
    assert result.needs_review is True
    assert float(result.confidence) == 0.95
    assert result.model_provider == "antigravity_gemini"
    assert result.model_name == "gemini-3.8-flash-high"
    assert result.image_sha256 == "a" * 64
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    mock_run.assert_called_once()

    # Temp dir must be empty again after the call.
    assert list(provider.temp_dir.glob("*")) == []


def test_read_page_with_mocked_agy(provider):
    image_bytes = b"fake-image-data"
    label_names = ["Question 1", "Question 2"]

    mock_response = {
        "status": "SUCCESS",
        "response": json.dumps(
            {
                "blocks": [
                    {
                        "question_label": "Question 1",
                        "bbox": [100, 100, 400, 200],
                        "text": "Student's answer for Q1",
                        "continues_from_previous": False,
                        "label_source": "heading",
                        "confidence": 0.95,
                    },
                ],
                "is_blank_page": False,
            }
        ),
        "usage": {"input_tokens": 150, "output_tokens": 80},
    }

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps(mock_response), stderr=""
        )

        result = provider.read_page(
            image_bytes=image_bytes,
            source_image_sha256="xyz789",
            prompt_version="v1",
            label_names=label_names,
        )

    assert len(result.blocks) == 1
    assert result.blocks[0].text == "Student's answer for Q1"
    assert result.needs_review is True
    mock_run.assert_called_once()
    assert list(provider.temp_dir.glob("*")) == []


def test_temp_file_cleaned_up_even_on_failure(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="boom")

        with pytest.raises(RuntimeError, match="exited with code 1"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="exit-test",
                prompt_version="v1",
            )

    assert list(provider.temp_dir.glob("*")) == []


def test_agy_call_with_timeout(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("agy", 120)

        with pytest.raises(RuntimeError, match="timed out after 120s"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="timeout-test",
                prompt_version="v1",
            )


def test_agy_call_nonzero_exit(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=1, stdout="", stderr="Model not found"
        )

        with pytest.raises(RuntimeError, match="exited with code 1"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="exit-test",
                prompt_version="v1",
            )


def test_agy_call_error_status(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        error_response = {"status": "ERROR", "error": "Invalid prompt"}
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps(error_response), stderr=""
        )

        with pytest.raises(RuntimeError, match="Invalid prompt"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="error-test",
                prompt_version="v1",
            )


def test_agy_call_denied_action_surfaces_in_error(provider):
    """A permission denial (agy's real failure mode) must be diagnosable, not silent."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        denied_response = {
            "status": "SUCCESS",
            "response": "",
            "denied_actions": [{"action": "read_file", "display_name": "ViewFile"}],
        }
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps(denied_response), stderr=""
        )

        with pytest.raises(RuntimeError, match="empty response"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="denied-test",
                prompt_version="v1",
            )


def test_agy_call_missing_response_field(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps({"status": "SUCCESS"}), stderr=""
        )

        with pytest.raises(RuntimeError, match="empty response"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="missing-field-test",
                prompt_version="v1",
            )


def test_agy_call_invalid_json(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="not valid json {", stderr="")

        with pytest.raises(RuntimeError, match="Failed to parse agy response JSON"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="bad-json-test",
                prompt_version="v1",
            )


def test_agy_cli_not_found(provider):
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("agy not found")

        with pytest.raises(RuntimeError, match="agy CLI not found in PATH"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="cli-not-found",
                prompt_version="v1",
            )


def test_expected_model_mismatch(provider):
    image_bytes = b"test-image"

    with pytest.raises(ValueError, match="Expected model"):
        provider.transcribe_image(
            image_bytes=image_bytes,
            source_image_sha256="model-mismatch",
            prompt_version="v1",
            expected_model="gemini-3.7-flash-medium",
        )


def test_draft_schema_missing_required_field(provider):
    """The model's own draft omitting a required field must fail loudly, not
    silently pass through as a hallucinated default."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        invalid_response = {
            "status": "SUCCESS",
            "response": json.dumps({"draft_text": "valid text"}),  # missing is_blank etc.
        }
        mock_run.return_value = SimpleNamespace(
            returncode=0, stdout=json.dumps(invalid_response), stderr=""
        )

        with pytest.raises(RuntimeError, match="was not usable"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="validation-fail",
                prompt_version="v1",
            )


def test_different_model_names(tmp_path):
    for model in ["gemini-3.8-flash-high", "gemini-3.7-flash-medium"]:
        provider = AntigravityGeminiVisionProvider(model_name=model, repository_root=tmp_path)
        assert provider.model_name == model


def test_custom_timeout(tmp_path):
    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=300,
        repository_root=tmp_path,
    )
    assert provider.timeout_seconds == 300
