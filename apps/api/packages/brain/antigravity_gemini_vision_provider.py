"""AntigravityGeminiVisionProvider — Gemini multimodal provider via Antigravity CLI.

Architecture
------------
This provider wraps the Antigravity CLI (agy) running in headless mode to call
Gemini vision models using the generous quota available in the antigravity IDE.

``agy`` is an agentic coding CLI, not a raw chat-completion API: there is no
``--image`` flag. The model views an image only through the agent's own
``view_file`` tool, and that tool requires a permission rule scoped to the
directory the file lives in (see ``.gemini/antigravity-cli/settings.json``,
which must contain
``read_file(<repo>/.local-ai/antigravity-temp/)`` — forward slashes, a
directory prefix, no trailing wildcard; other forms were tested and silently
do not match). The prompt must reference the file by absolute path with
forward slashes and explicitly say to use ``view_file`` — a Windows backslash
path or an embedded base64 blob does not get treated as an image at all; the
agent instead wanders off trying ``find_by_name``/``run_command`` to locate a
file it already has the path to.

Two main operations are exposed:

1. ``transcribe_image()``
   Accepts application-owned PNG/JPEG bytes, writes them to a private temp
   file, calls Gemini via agy with a structured prompt, and returns a
   ``VisualTranscriptionOutput`` draft. The temp file is always deleted
   afterward, success or failure.

2. ``read_page()``
   Calls Gemini once per page and returns text + geometry in a single
   response.

Schema note
-----------
The full ``VisualTranscriptionOutput``/``VisualPageTranscriptOutput`` Pydantic
schemas use ``Decimal`` fields, whose JSON Schema form includes a regex
``pattern`` with a negative lookahead (``(?!...)``). agy validates
``--json-schema`` against strict JSON Schema 2020-12 using a Go regex engine,
which does not support lookaheads, and the call fails outright. This provider
therefore asks the model for a stripped-down draft schema (``float``
confidence, only the fields the model itself can know) and fills in the
provider-computed metadata (model_provider, model_name, image_sha256,
latency_ms, provider_calls_used) itself before validating against the full
output schema — the same division the Qwen38 provider uses internally.

Safety invariants
-----------------
* Subprocess calls use strict timeout handling.
* JSON schema enforcement via --json-schema flag on a minimal draft schema.
* Structured output parsing and full validation via Pydantic models.
* Temp image files live under a single dedicated, gitignored directory and
  are deleted immediately after each call, success or failure.
* No API key exposure in logs (agy manages its own auth; nothing is logged
  here beyond the sanitized command shape).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.brain.capabilities import BrainCapability, BrainExecutionLocation
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas_qwen38 import (
    EditingMark,
    UncertainGlyph,
    VisualPageBlock,
    VisualPageTranscriptOutput,
    VisualTranscriptionOutput,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "antigravity_gemini"
DEFAULT_MODEL = "gemini-3.8-flash-high"

_TEMP_DIR_NAME = Path(".local-ai") / "antigravity-temp"


class _TranscriptionDraft(BaseModel):
    """What the model itself can know. Metadata is filled in by this provider."""

    model_config = ConfigDict(extra="ignore")

    draft_text: str
    uncertain_glyphs: list[dict[str, Any]] = Field(default_factory=list)
    editing_marks: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    cancellation_detected: bool = False
    replacement_detected: bool = False
    uncertain_correction_detected: bool = False
    is_blank: bool
    is_irrelevant: bool
    confidence: float = Field(ge=0.0, le=1.0)


class _PageBlockDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_label: str | None = None
    bbox: list[int] = Field(min_length=4, max_length=4)
    text: str
    continues_from_previous: bool = False
    label_source: str = "inferred"
    confidence: float = Field(ge=0.0, le=1.0)


class _PageReadDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocks: list[_PageBlockDraft] = Field(default_factory=list)
    is_blank_page: bool = False


class AntigravityGeminiVisionProvider(BrainProvider):
    """Gemini vision provider via Antigravity CLI headless mode."""

    provider_name: str = PROVIDER_NAME
    execution_location: BrainExecutionLocation = BrainExecutionLocation.CLOUD
    capabilities: frozenset[BrainCapability] = frozenset(
        {
            BrainCapability.VISUAL_TRANSCRIPTION,
            BrainCapability.VISUAL_PAGE_READ,
        }
    )

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        timeout_seconds: int = 120,
        *,
        repository_root: Path | None = None,
    ) -> None:
        self.model_name = model_name or DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.repository_root = repository_root or Path(__file__).resolve().parents[4]
        self.temp_dir = self.repository_root / _TEMP_DIR_NAME

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
        self._assert_model_matches(expected_model)
        image_sha256 = source_image_sha256 or hashlib.sha256(image_bytes).hexdigest()

        prompt_body = (
            "Transcribe every visible piece of handwritten student mathematics writing in "
            "this image exactly as written. Preserve mistakes; never solve, correct, or "
            "complete the work. Use LaTeX for mathematics. If a stroke is crossed out but "
            "still legible, transcribe it and record it in editing_marks with status "
            "'cancelled'; do not delete legible crossed-out work. Set is_blank=true only if "
            "there is no student writing at all. Set is_irrelevant=true only if the writing "
            "is clearly not an attempt to answer the question.\n\n"
            'Return exactly this JSON shape with no extra keys: {"draft_text":"string",'
            '"uncertain_glyphs":[],"editing_marks":[],"cancellation_detected":false,'
            '"replacement_detected":false,"uncertain_correction_detected":false,'
            '"is_blank":false,"is_irrelevant":false,"confidence":0.0}'
        )

        start = time.perf_counter()
        with self._temp_image(image_bytes) as image_path:
            prompt = self._view_file_prompt(image_path, prompt_body)
            schema = _TranscriptionDraft.model_json_schema()
            response_text, usage = self._call_agy_structured(prompt, schema)
        latency_ms = int((time.perf_counter() - start) * 1000)

        try:
            raw = json.loads(response_text)
            draft = _TranscriptionDraft.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Gemini transcription response was not usable: {exc}") from exc

        uncertain_glyphs: list[UncertainGlyph] = []
        for item in draft.uncertain_glyphs:
            try:
                uncertain_glyphs.append(UncertainGlyph.model_validate(item))
            except (ValidationError, TypeError):
                continue

        editing_marks: list[EditingMark] = []
        for item in draft.editing_marks:
            try:
                editing_marks.append(EditingMark.model_validate(item))
            except (ValidationError, TypeError):
                continue

        return VisualTranscriptionOutput(
            draft_text=draft.draft_text,
            uncertain_glyphs=uncertain_glyphs,
            editing_marks=editing_marks,
            cancellation_detected=draft.cancellation_detected,
            replacement_detected=draft.replacement_detected,
            uncertain_correction_detected=draft.uncertain_correction_detected,
            is_blank=draft.is_blank,
            is_irrelevant=draft.is_irrelevant,
            confidence=Decimal(str(round(draft.confidence, 4))),
            needs_review=True,
            model_provider=self.provider_name,
            model_name=self.model_name,
            image_sha256=image_sha256,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
        )

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
        self._assert_model_matches(expected_model)
        labels_str = ", ".join(label_names) if label_names else "no fixed labels given"

        prompt_body = (
            "This image is one full page of a student's handwritten exam script. "
            f"Known question labels on this page may include: {labels_str}. "
            "Read the whole page and split it into blocks: one block per contiguous "
            "region of writing. For each block give the visible question_label if one "
            "is written nearby (else null), a normalized bounding box [x1,y1,x2,y2] on a "
            "0-1000 scale, the verbatim transcribed text (LaTeX for mathematics, preserve "
            "mistakes, never solve or correct), whether it continues from the block above "
            "(continues_from_previous), and label_source ('heading' if the label is written "
            "directly above/on the block, 'inferred' if you guessed it from position, "
            "'continuation' if there is no label because it continues the previous block). "
            "Set is_blank_page=true only if the whole page has no student writing.\n\n"
            'Return exactly this JSON shape with no extra keys: {"blocks":['
            '{"question_label":"string or null","bbox":[0,0,1000,1000],"text":"string",'
            '"continues_from_previous":false,"label_source":"heading",'
            '"confidence":0.0}],"is_blank_page":false}'
        )

        start = time.perf_counter()
        with self._temp_image(image_bytes) as image_path:
            prompt = self._view_file_prompt(image_path, prompt_body)
            schema = _PageReadDraft.model_json_schema()
            response_text, usage = self._call_agy_structured(prompt, schema)
        _latency_ms = int((time.perf_counter() - start) * 1000)

        try:
            raw = json.loads(response_text)
            draft = _PageReadDraft.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"Gemini page-read response was not usable: {exc}") from exc

        blocks: list[VisualPageBlock] = []
        for block in draft.blocks:
            try:
                blocks.append(
                    VisualPageBlock(
                        question_label=block.question_label,
                        bbox=block.bbox,
                        text=block.text,
                        continues_from_previous=block.continues_from_previous,
                        label_source=block.label_source,  # type: ignore[arg-type]
                        confidence=Decimal(str(round(block.confidence, 4))),
                    )
                )
            except ValidationError:
                continue

        return VisualPageTranscriptOutput(
            blocks=blocks,
            is_blank_page=draft.is_blank_page,
            needs_review=True,
        )

    def _assert_model_matches(self, expected_model: str) -> None:
        if expected_model and expected_model != self.model_name:
            raise ValueError(
                f"Expected model {expected_model}, configured model is {self.model_name}"
            )

    def _temp_image(self, image_bytes: bytes) -> _TempImageContext:
        return _TempImageContext(self.temp_dir, image_bytes)

    def _view_file_prompt(self, image_path: Path, body: str) -> str:
        forward_slash_path = image_path.as_posix()
        return (
            f"View the image file at absolute path {forward_slash_path} using your "
            "view_file tool. Do not use run_command, find_by_name, or any other tool — "
            "the path is already exact and correct. Then, using only what you see in "
            f"that image:\n\n{body}"
        )

    def _call_agy_structured(
        self, prompt: str, schema: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Call agy CLI with a structured prompt and schema. Returns (response_text, usage)."""
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
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"agy call timed out after {self.timeout_seconds}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("agy CLI not found in PATH") from exc

        if result.returncode != 0:
            stderr = result.stderr or "(no stderr)"
            raise RuntimeError(f"agy exited with code {result.returncode}: {stderr}")

        try:
            response_obj = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse agy response JSON: {exc}") from exc

        if response_obj.get("status") != "SUCCESS":
            error_msg = response_obj.get("error", "unknown error")
            denied = response_obj.get("denied_actions")
            if denied:
                error_msg = f"{error_msg} (denied actions: {denied})"
            raise RuntimeError(f"agy returned status {response_obj.get('status')}: {error_msg}")

        response_text = response_obj.get("response", "")
        if not response_text.strip():
            raise RuntimeError("agy returned an empty response with SUCCESS status")

        return _extract_first_json_object(response_text), response_obj.get("usage", {})


def _extract_first_json_object(text: str) -> str:
    """Return the first complete JSON object found in ``text``, re-serialized.

    agy's headless agent reliably returns *valid* JSON for the schema it was
    asked for, but real runs were observed appending harmless trailing keys
    (``toolAction``, ``toolSummary``) or, occasionally, a second JSON-ish
    fragment after the real object (e.g. a self-directed "finishing task"
    turn). ``extra="ignore"`` on the draft models already tolerates extra
    *keys inside* the object; this handles extra *content after* it, so one
    stray trailing fragment does not fail an otherwise-correct read.
    """
    start = text.find("{")
    if start == -1:
        raise RuntimeError(f"agy response contained no JSON object: {text[:200]!r}")
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"agy response was not valid JSON: {exc}") from exc
    return json.dumps(obj)


class _TempImageContext:
    """Writes image bytes to a private temp file and always deletes it afterward."""

    def __init__(self, temp_dir: Path, image_bytes: bytes) -> None:
        self.temp_dir = temp_dir
        self.image_bytes = image_bytes
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.temp_dir / f"{uuid.uuid4().hex}.png"
        self.path.write_bytes(self.image_bytes)
        return self.path

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)
