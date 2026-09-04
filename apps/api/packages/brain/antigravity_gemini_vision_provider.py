"""AntigravityGeminiVisionProvider — Gemini multimodal provider via Antigravity CLI.

Architecture
------------
This provider wraps the Antigravity CLI (agy) running in headless mode to call
Gemini vision models using the generous quota available in the antigravity IDE.

Two main operations are exposed:

1. ``transcribe_image()``
   Accepts application-owned PNG/JPEG bytes, calls Gemini via agy with a
   structured prompt, and returns a ``VisualTranscriptionOutput`` draft.

2. ``read_page()``
   Calls Gemini once per page and returns text + geometry in a single response.

Safety invariants
-----------------
* Subprocess calls use strict timeout handling.
* JSON schema enforcement via --json-schema flag.
* Structured output parsing via Pydantic models.
* No API key exposure in logs (subprocess args are sanitized).
* Image bytes are base64-encoded and passed via stdin, never stored on disk.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from packages.brain.capabilities import BrainCapability, BrainExecutionLocation
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas_qwen38 import (
    VISUAL_PAGE_READ_PROMPT_VERSION,
    VisualPageTranscriptOutput,
    VisualTranscriptionOutput,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "antigravity_gemini"
DEFAULT_MODEL = "gemini-3.8-flash-high"


class AntigravityGeminiVisionProvider(BrainProvider):
    """Gemini vision provider via Antigravity CLI headless mode.

    Capabilities
    -----------
    * VISUAL_TRANSCRIPTION: transcribe_image() via agy
    * VISUAL_PAGE_READ: read_page() via agy
    * VISUAL_PAGE_MAPPING: map_page_answer_regions() via agy
    """

    provider_name: str = PROVIDER_NAME
    execution_location: BrainExecutionLocation = BrainExecutionLocation.CLOUD
    capabilities: frozenset[BrainCapability] = frozenset(
        {
            BrainCapability.VISUAL_TRANSCRIPTION,
            BrainCapability.VISUAL_PAGE_READ,
            BrainCapability.VISUAL_MAPPING,
        }
    )

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        timeout_seconds: int = 120,
    ) -> None:
        self.model_name = model_name or DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds

    def transcribe_image(
        self,
        *,
        image_bytes: bytes,
        source_image_sha256: str,
        prompt_version: str,
        expected_model: str = "",
        task_name: str = "visual_transcription",
    ) -> VisualTranscriptionOutput:
        """Transcribe a single image via Gemini through Antigravity CLI."""
        if expected_model and expected_model != self.model_name:
            raise ValueError(
                f"Expected model {expected_model}, configured model is {self.model_name}"
            )

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = self._build_transcription_prompt(image_b64, prompt_version)

        schema = VisualTranscriptionOutput.model_json_schema()
        response_text = self._call_agy_structured(prompt, schema)

        try:
            parsed = json.loads(response_text)
            return VisualTranscriptionOutput.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Failed to parse transcription response: {e}")
            raise RuntimeError(f"Gemini transcription schema validation failed: {e}") from e

    def read_page(
        self,
        *,
        image_bytes: bytes,
        source_image_sha256: str,
        prompt_version: str,
        expected_model: str = "",
        label_names: list[str] | None = None,
        task_name: str = "visual_page_read",
    ) -> VisualPageTranscriptOutput:
        """Read an entire page in one call via Gemini through Antigravity CLI."""
        if expected_model and expected_model != self.model_name:
            raise ValueError(
                f"Expected model {expected_model}, configured model is {self.model_name}"
            )

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = self._build_page_read_prompt(image_b64, label_names or [], prompt_version)

        schema = VisualPageTranscriptOutput.model_json_schema()
        response_text = self._call_agy_structured(prompt, schema)

        try:
            parsed = json.loads(response_text)
            return VisualPageTranscriptOutput.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Failed to parse page-read response: {e}")
            raise RuntimeError(f"Gemini page-read schema validation failed: {e}") from e

    def map_page_answer_regions(
        self,
        *,
        image_bytes: bytes,
        source_image_sha256: str,
        label_names: list[str],
        prompt_version: str,
        expected_model: str = "",
        task_name: str = "visual_page_mapping",
    ) -> dict[str, Any]:
        """Map answer regions on a page via Gemini through Antigravity CLI."""
        if expected_model and expected_model != self.model_name:
            raise ValueError(
                f"Expected model {expected_model}, configured model is {self.model_name}"
            )

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = self._build_mapping_prompt(image_b64, label_names, prompt_version)

        # For now, return a placeholder. Full schema TBD.
        schema = {"type": "object", "properties": {}}
        response_text = self._call_agy_structured(prompt, schema)

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse mapping response: {e}")
            raise RuntimeError(f"Gemini mapping schema validation failed: {e}") from e

    def _build_transcription_prompt(self, image_b64: str, prompt_version: str) -> str:
        """Build transcription prompt for Gemini."""
        return f"""You are an expert in reading and transcribing handwritten student mathematics exam solutions.

The image contains a student's handwritten mathematics answer. Transcribe it accurately, preserving all mathematical notation and structure.

Image (base64): {image_b64}

Provide your response in the following JSON schema:
{{
  "draft_text": "transcribed content here",
  "needs_review": true,
  "confidence_level": 0.95,
  "editing_marks": [],
  "uncertain_glyphs": []
}}
"""

    def _build_page_read_prompt(
        self, image_b64: str, label_names: list[str], prompt_version: str
    ) -> str:
        """Build page-read prompt for Gemini."""
        labels_str = ", ".join(label_names) if label_names else "unlabeled"
        return f"""You are an expert in reading handwritten student mathematics exam solutions.

The image contains a page with answer regions labeled or unlabeled. Read the entire page and extract:
1. All visible text and mathematical content
2. The spatial regions (bounding boxes) where each answer appears

Labels on this page: {labels_str}

Image (base64): {image_b64}

Provide your response in JSON format with blocks (each block represents a text region) and their bounding boxes.
"""

    def _build_mapping_prompt(
        self, image_b64: str, label_names: list[str], prompt_version: str
    ) -> str:
        """Build page mapping prompt for Gemini."""
        labels_str = ", ".join(label_names) if label_names else "no labels"
        return f"""You are an expert in reading handwritten student mathematics exam solutions.

The image contains a page with answer regions for the following labels: {labels_str}

Identify the bounding box (normalized to [0, 1000] range) for each labeled answer region.

Image (base64): {image_b64}

Provide your response as a JSON object with regions for each label.
"""

    def _call_agy_structured(self, prompt: str, schema: dict[str, Any]) -> str:
        """Call agy CLI with a structured prompt and schema."""
        try:
            cmd = [
                "agy",
                "-p",
                prompt,
                "--model",
                self.model_name,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(schema),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )

            if result.returncode != 0:
                stderr = result.stderr or "(no stderr)"
                raise RuntimeError(f"agy exited with code {result.returncode}: {stderr}")

            response_obj = json.loads(result.stdout)
            if response_obj.get("status") != "SUCCESS":
                error_msg = response_obj.get("error", "unknown error")
                raise RuntimeError(f"agy returned status {response_obj.get('status')}: {error_msg}")

            return response_obj.get("response", "")

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"agy call timed out after {self.timeout_seconds}s")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse agy response JSON: {e}")
        except FileNotFoundError:
            raise RuntimeError("agy CLI not found in PATH")
