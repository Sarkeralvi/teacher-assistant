"""End-to-end test of AntigravityGeminiVisionProvider with real Gemini API calls.

This test is DISABLED by default (requires agy CLI and Gemini quota).
Run with: ANTIGRAVITY_E2E_TEST=1 pytest tests/test_antigravity_gemini_e2e.py -v
"""

import os
import pytest

# Skip all tests in this module unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.getenv("ANTIGRAVITY_E2E_TEST") != "1",
    reason="E2E test requires real Gemini API; enable with ANTIGRAVITY_E2E_TEST=1",
)


def test_gemini_transcribe_real_image():
    """Test real transcription via Gemini (if E2E enabled and agy available)."""
    from packages.brain.antigravity_gemini_vision_provider import AntigravityGeminiVisionProvider

    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=60,
    )

    # Create a minimal test image (1x1 white pixel PNG)
    # In a real test, this would be a handwritten math answer
    test_image_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\r\xf0\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    image_sha256 = "a" * 64  # Placeholder; would be real SHA256

    result = provider.transcribe_image(
        image_bytes=test_image_bytes,
        source_image_sha256=image_sha256,
        prompt_version="v1",
    )

    # Verify result structure
    assert result.draft_text is not None
    assert result.needs_review is True
    assert hasattr(result, "confidence")
    assert hasattr(result, "model_provider")
    assert result.model_provider == "antigravity_gemini"


def test_gemini_read_page_real_image():
    """Test real page-read via Gemini (if E2E enabled and agy available)."""
    from packages.brain.antigravity_gemini_vision_provider import AntigravityGeminiVisionProvider

    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high",
        timeout_seconds=60,
    )

    # Minimal test image
    test_image_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
        b'\x00\x01\x01\x00\x05\x18\r\xf0\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    image_sha256 = "b" * 64

    result = provider.read_page(
        image_bytes=test_image_bytes,
        source_image_sha256=image_sha256,
        prompt_version="v1",
        label_names=["Q1", "Q2"],
    )

    # Verify result structure
    assert hasattr(result, "blocks")
    assert hasattr(result, "is_blank_page")
    assert result.needs_review is True
    assert isinstance(result.blocks, list)


if __name__ == "__main__":
    # Allow running directly: ANTIGRAVITY_E2E_TEST=1 python -m pytest tests/test_antigravity_gemini_e2e.py -v
    pytest.main([__file__, "-v", "-s"])
