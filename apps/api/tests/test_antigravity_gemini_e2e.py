"""End-to-end test of AntigravityGeminiVisionProvider with real Gemini API calls.

This test is DISABLED by default (requires agy CLI, a Gemini quota, and the
read_file permission rule below). Run with:

    ANTIGRAVITY_E2E_TEST=1 python -m pytest tests/test_antigravity_gemini_e2e.py -v -s

Requires ``%USERPROFILE%\\.gemini\\antigravity-cli\\settings.json`` to contain:

    {
      "permissions": {
        "allow": ["read_file(<repo-path-forward-slashes>/.local-ai/antigravity-temp/)"]
      }
    }

(Forward slashes, a directory prefix, no trailing wildcard — other forms were
tried and silently do not match.)
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("ANTIGRAVITY_E2E_TEST") != "1",
    reason="E2E test requires real Gemini API; enable with ANTIGRAVITY_E2E_TEST=1",
)


def _render_text_image(text: str) -> bytes:
    """Render real, legible text into a PNG so the model has something
    genuine to read rather than a blank pixel it could hallucinate about."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (500, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_gemini_transcribe_real_image():
    """Real transcription via Gemini: verifies the model actually reads the
    pixels (not just returns something schema-shaped)."""
    from packages.brain.antigravity_gemini_vision_provider import (
        AntigravityGeminiVisionProvider,
    )

    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high", timeout_seconds=90
    )
    image_bytes = _render_text_image("The answer is x = 7")

    result = provider.transcribe_image(
        image_bytes=image_bytes,
        source_image_sha256="a" * 64,
        prompt_version="v1",
    )

    assert result.needs_review is True
    assert result.model_provider == "antigravity_gemini"
    assert result.is_blank is False
    # The core proof this actually works: the transcribed text must contain
    # the real content, not a hallucination or a schema-shaped placeholder.
    assert "7" in result.draft_text or "seven" in result.draft_text.lower()
    print(f"\nTranscribed text: {result.draft_text!r}")
    print(f"Confidence: {result.confidence}, latency_ms: {result.latency_ms}")


def test_gemini_read_page_real_image():
    """Real page-read via Gemini with a labeled question."""
    from packages.brain.antigravity_gemini_vision_provider import (
        AntigravityGeminiVisionProvider,
    )

    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high", timeout_seconds=90
    )
    image_bytes = _render_text_image("Q1: The answer is 12")

    result = provider.read_page(
        image_bytes=image_bytes,
        source_image_sha256="b" * 64,
        prompt_version="v1",
        label_names=["Q1"],
    )

    assert result.needs_review is True
    assert result.is_blank_page is False
    assert len(result.blocks) >= 1
    combined_text = " ".join(block.text for block in result.blocks)
    assert "12" in combined_text
    print(f"\nBlocks: {[(b.question_label, b.text) for b in result.blocks]}")


def test_gemini_transcribe_blank_image():
    """A genuinely blank image must be reported as blank, not hallucinated content."""
    import io

    from PIL import Image

    from packages.brain.antigravity_gemini_vision_provider import (
        AntigravityGeminiVisionProvider,
    )

    provider = AntigravityGeminiVisionProvider(
        model_name="gemini-3.8-flash-high", timeout_seconds=90
    )
    img = Image.new("RGB", (500, 200), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    result = provider.transcribe_image(
        image_bytes=buf.getvalue(),
        source_image_sha256="c" * 64,
        prompt_version="v1",
    )

    print(f"\nBlank-image result: is_blank={result.is_blank}, draft_text={result.draft_text!r}")
    assert result.is_blank is True
    assert result.draft_text == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
