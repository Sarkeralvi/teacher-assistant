"""Canonical multimodal brain provider backed by the Antigravity ``agy`` CLI."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.brain.agentic_cli import finalize_cli_grade_output
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainTransport,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.universal_vision import (
    UniversalVisionCompletion,
    UniversalVisionProviderMixin,
)

PROVIDER_NAME = "antigravity_gemini"
DEFAULT_MODEL = "gemini-3.8-flash-high"
_TEMP_DIR_NAME = Path(".local-ai") / "antigravity-temp"
_MAX_OUTPUT_BYTES = 1_000_000
_AGY_PAYLOAD_ARTIFACT_FIELDS = frozenset({"toolAction", "toolSummary"})


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


_Runner = Callable[..., _CompletedProcessLike]


class _AgyUsage(BaseModel):
    # agy adds accounting fields across releases. They are transport metadata;
    # the model-authored payload is validated separately against its strict schema.
    model_config = ConfigDict(extra="ignore")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _AgyResponse(BaseModel):
    # Keep required transport fields typed without coupling this provider to
    # every informational envelope field emitted by one agy release.
    model_config = ConfigDict(extra="ignore")

    status: str
    response: str = ""
    usage: _AgyUsage = Field(default_factory=_AgyUsage)
    error: str | None = None
    denied_actions: list[dict[str, Any]] = Field(default_factory=list)


class AntigravityGeminiVisionProvider(UniversalVisionProviderMixin, BrainProvider):
    """Run canonical grading and vision operations through Antigravity headless mode."""

    provider_name = PROVIDER_NAME
    execution_location = BrainExecutionLocation.CLOUD
    transport = BrainTransport.CLI
    image_input_mode = BrainImageInputMode.FILE_PATH
    capabilities = frozenset(
        {
            BrainCapability.GRADING,
            BrainCapability.QUESTION_PDF_EXTRACTION,
            BrainCapability.RUBRIC_PDF_EXTRACTION,
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
            BrainCapability.VISUAL_MAPPING,
            BrainCapability.VISUAL_PAGE_READ,
            BrainCapability.VISUAL_TRANSCRIPTION,
            BrainCapability.TRANSCRIPTION_REPAIR,
        }
    )

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        timeout_seconds: int = 120,
        *,
        repository_root: Path | None = None,
        runner: _Runner | None = None,
    ) -> None:
        self.model_name = model_name or DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.repository_root = repository_root or Path(__file__).resolve().parents[4]
        self.temp_dir = self.repository_root / _TEMP_DIR_NAME
        self._runner = runner

    def _complete_structured_vision(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
        schema_name: str,
        max_tokens: int | None = None,
    ) -> UniversalVisionCompletion:
        del schema_name, max_tokens
        if not images:
            raise ValueError("Antigravity vision calls require at least one image")
        started = time.perf_counter()
        with _TempImageContext(self.temp_dir, images) as (workspace, image_paths):
            schema = _agy_compatible_schema(
                response_model.model_json_schema()
                if response_model is not None
                else {"type": "object"}
            )
            response_text, usage = self._call_agy_structured(
                self._view_files_prompt(image_paths, prompt), schema, cwd=workspace
            )
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini structured response was not usable: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Gemini structured response must be a JSON object")
        payload = {
            key: value
            for key, value in payload.items()
            if key not in _AGY_PAYLOAD_ARTIFACT_FIELDS
        }
        if response_model is not None:
            try:
                payload = response_model.model_validate(payload).model_dump(mode="json")
            except ValidationError as exc:
                raise RuntimeError(f"Gemini structured response was not usable: {exc}") from exc
        return UniversalVisionCompletion(
            payload=payload,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
        )

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del question_text, question_total_marks, rubric_json, student_answer_text
        del task_name, model_policy, image_data_url, marking_policy
        image_path = Path(answer_image_path)
        if not image_path.is_file():
            raise RuntimeError("Antigravity grading image does not exist")
        prompt = "\n\n".join(
            str(message.get("content", "")) for message in (messages or [])
        )
        prompt += "\nReturn only the requested grade-suggestion JSON object."
        completion = self._complete_structured_vision(
            prompt=prompt,
            images=[(image_path.read_bytes(), _mime_type_for_path(image_path))],
            response_model=None,
            schema_name="grade_suggestion",
        )
        return finalize_cli_grade_output(
            completion.payload,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            latency_ms=completion.latency_ms,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            provider_flag="antigravity_cli_provider",
        )

    def _view_files_prompt(self, image_paths: list[Path], body: str) -> str:
        rendered = ", ".join(path.as_posix() for path in image_paths)
        return (
            f"View each image file in order using view_file: {rendered}. "
            "Do not use run_command, find_by_name, or any other tool. The paths are exact. "
            f"Then use only what is visible in those images.\n\n{body}"
        )

    def _call_agy_structured(
        self, prompt: str, schema: dict[str, Any], *, cwd: Path
    ) -> tuple[str, dict[str, Any]]:
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
            "--sandbox",
        ]
        try:
            result = (self._runner or subprocess.run)(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"agy call timed out after {self.timeout_seconds}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("agy CLI not found in PATH") from exc
        _require_bounded_output(result, "agy")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "(no output)")[:4000]
            raise RuntimeError(f"agy exited with code {result.returncode}: {detail}")
        try:
            response_obj = _AgyResponse.model_validate_json(result.stdout)
        except (ValidationError, ValueError) as exc:
            raise RuntimeError(f"Failed to parse agy response JSON: {exc}") from exc
        if response_obj.status != "SUCCESS":
            error = response_obj.error or "unknown error"
            if response_obj.denied_actions:
                error = f"{error} (denied actions: {response_obj.denied_actions})"
            raise RuntimeError(f"agy returned status {response_obj.status}: {error}")
        if not response_obj.response.strip():
            raise RuntimeError("agy returned an empty response with SUCCESS status")
        return (
            _extract_first_json_object(response_obj.response),
            response_obj.usage.model_dump(),
        )


def _agy_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove regex patterns unsupported by agy's Go JSON-schema validator."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key != "pattern"}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(schema)


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise RuntimeError(f"agy response contained no JSON object: {text[:200]!r}")
    try:
        obj, _end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"agy response was not valid JSON: {exc}") from exc
    return json.dumps(obj)


def _mime_type_for_path(path: Path) -> str:
    return "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def _suffix_for_mime_type(mime_type: str) -> str:
    if mime_type == "image/jpeg":
        return ".jpg"
    if mime_type == "image/png":
        return ".png"
    raise ValueError(f"Unsupported image MIME type: {mime_type}")


def _require_bounded_output(result: _CompletedProcessLike, label: str) -> None:
    for stream_name, value in (("stdout", result.stdout), ("stderr", result.stderr)):
        if len((value or "").encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise RuntimeError(f"{label} {stream_name} exceeded the output size limit")


class _TempImageContext:
    """Create one isolated multi-image workspace and always remove it."""

    def __init__(self, temp_dir: Path, images: list[tuple[bytes, str]]) -> None:
        self.temp_dir = temp_dir
        self.images = images
        self._workspace: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> tuple[Path, list[Path]]:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._workspace = tempfile.TemporaryDirectory(prefix="call-", dir=self.temp_dir)
        workspace = Path(self._workspace.name)
        paths: list[Path] = []
        for index, (image_bytes, mime_type) in enumerate(self.images, start=1):
            path = workspace / f"input-{index}{_suffix_for_mime_type(mime_type)}"
            path.write_bytes(image_bytes)
            paths.append(path)
        return workspace, paths

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._workspace is not None:
            self._workspace.cleanup()
