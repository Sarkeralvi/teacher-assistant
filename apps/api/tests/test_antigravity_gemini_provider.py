"""Tests for AntigravityGeminiVisionProvider."""

import json
import subprocess
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

from packages.brain.antigravity_gemini_vision_provider import (
    AntigravityGeminiVisionProvider,
    PROVIDER_NAME,
)
from packages.brain.capabilities import BrainCapability


@pytest.fixture
def provider():
    """Create a provider instance for testing."""
    return AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=120,
    )


def test_provider_initialization():
    """Test that provider initializes with correct settings."""
    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=120,
    )
    assert provider.model_name == "gemini-3.8-flash-high"
    assert provider.timeout_seconds == 120
    assert provider.provider_name == PROVIDER_NAME


def test_provider_capabilities():
    """Test that provider advertises correct capabilities."""
    provider = AntigravityGeminiVisionProvider()
    assert BrainCapability.VISUAL_TRANSCRIPTION in provider.capabilities
    assert BrainCapability.VISUAL_PAGE_READ in provider.capabilities
    assert BrainCapability.VISUAL_MAPPING in provider.capabilities


def test_transcribe_image_with_mocked_agy(provider):
    """Test transcribe_image with mocked agy subprocess."""
    image_bytes = b"fake-image-data"
    image_sha256 = "a" * 64  # 64-char hex string

    # Mock response with all required fields for VisualTranscriptionOutput
    mock_response = {
        "status": "SUCCESS",
        "response": json.dumps({
            "draft_text": "The answer is 42",
            "uncertain_glyphs": [],
            "editing_marks": [],
            "cancellation_detected": False,
            "replacement_detected": False,
            "uncertain_correction_detected": False,
            "requires_thinking_repair": False,
            "is_blank": False,
            "is_irrelevant": False,
            "confidence": 0.95,
            "needs_review": True,
            "model_provider": "antigravity_gemini",
            "model_name": "gemini-3.8-flash-high",
            "image_sha256": image_sha256,
            "latency_ms": 2500,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "provider_calls_used": 1,
        }),
    }

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(mock_response),
            stderr="",
        )

        result = provider.transcribe_image(
            image_bytes=image_bytes,
            source_image_sha256=image_sha256,
            prompt_version="v1",
        )

        assert result.draft_text == "The answer is 42"
        assert result.needs_review is True
        assert float(result.confidence) == 0.95

        # Verify agy was called with correct args
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0][0] == "agy"
        assert args[0][1] == "-p"  # prompt flag
        assert "--model" in args[0]
        assert "gemini-3.8-flash-high" in args[0]
        assert "--json-schema" in args[0]


def test_read_page_with_mocked_agy(provider):
    """Test read_page with mocked agy subprocess."""
    image_bytes = b"fake-image-data"
    label_names = ["Question 1", "Question 2"]

    # Mock response with all required fields for VisualPageTranscriptOutput
    mock_response = {
        "status": "SUCCESS",
        "response": json.dumps({
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
            "needs_review": True,
        }),
    }

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(mock_response),
            stderr="",
        )

        result = provider.read_page(
            image_bytes=image_bytes,
            source_image_sha256="xyz789",
            prompt_version="v1",
            label_names=label_names,
        )

        # Verify the result has expected structure
        assert hasattr(result, "blocks")
        assert len(result.blocks) == 1
        assert result.blocks[0].text == "Student's answer for Q1"
        mock_run.assert_called_once()


def test_agy_call_with_timeout(provider):
    """Test that agy calls respect timeout."""
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
    """Test handling of agy non-zero exit codes."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Model not found",
        )

        with pytest.raises(RuntimeError, match="exited with code 1"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="exit-test",
                prompt_version="v1",
            )


def test_agy_call_error_status(provider):
    """Test handling of agy ERROR status."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        error_response = {
            "status": "ERROR",
            "error": "Invalid prompt",
        }
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(error_response),
            stderr="",
        )

        with pytest.raises(RuntimeError, match="Invalid prompt"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="error-test",
                prompt_version="v1",
            )


def test_agy_call_missing_response_field(provider):
    """Test handling of missing response field in agy output."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "SUCCESS"}),  # missing 'response'
            stderr="",
        )

        with pytest.raises(RuntimeError, match="schema validation failed"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="missing-field-test",
                prompt_version="v1",
            )


def test_agy_call_invalid_json(provider):
    """Test handling of invalid JSON from agy."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="not valid json {",
            stderr="",
        )

        with pytest.raises(RuntimeError, match="Failed to parse agy response JSON"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="bad-json-test",
                prompt_version="v1",
            )


def test_agy_cli_not_found(provider):
    """Test error handling when agy CLI is not available."""
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
    """Test that expected model must match configured model."""
    image_bytes = b"test-image"

    with pytest.raises(ValueError, match="Expected model"):
        provider.transcribe_image(
            image_bytes=image_bytes,
            source_image_sha256="model-mismatch",
            prompt_version="v1",
            expected_model="gemini-3.7-flash-medium",  # Different from configured
        )


def test_schema_validation_failure(provider):
    """Test that invalid schema in response is caught."""
    image_bytes = b"test-image"

    with patch("subprocess.run") as mock_run:
        # Response missing required fields
        invalid_response = {
            "status": "SUCCESS",
            "response": json.dumps({
                "draft_text": "valid text",
                # missing other required fields
            }),
        }
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(invalid_response),
            stderr="",
        )

        with pytest.raises(RuntimeError, match="schema validation failed"):
            provider.transcribe_image(
                image_bytes=image_bytes,
                source_image_sha256="validation-fail",
                prompt_version="v1",
            )


def test_different_model_names():
    """Test provider works with different Gemini model names."""
    for model in ["gemini-3.8-flash-high", "gemini-3.7-flash-medium"]:
        provider = AntigravityGeminiVisionProvider(model_name=model)
        assert provider.model_name == model


def test_custom_timeout():
    """Test provider respects custom timeout settings."""
    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=300,
    )
    assert provider.timeout_seconds == 300
