"""Canonical multimodal brain provider backed by Claude Code print mode."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

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

_MAX_OUTPUT_BYTES = 1_000_000
_DENIED_TOOLS = "Bash,PowerShell,Edit,Write,WebFetch,WebSearch,NotebookEdit"


class _CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., _CompletedProcessLike]
Which = Callable[[str], str | None]


class ClaudeCliProviderError(RuntimeError):
    """Raised when a Claude CLI call cannot satisfy the isolated contract."""


class ClaudeCliProvider(UniversalVisionProviderMixin, BrainProvider):
    provider_name = "claude_cli"
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
        *,
        command: str = "claude",
        model_name: str = "sonnet",
        timeout_seconds: float = 300.0,
        workdir: str = "",
        which: Which = shutil.which,
        runner: Runner = subprocess.run,
    ) -> None:
        self.command = command or "claude"
        self.model_name = model_name or "sonnet"
        self.timeout_seconds = timeout_seconds
        self.workdir = workdir
        self._which = which
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
            raise ValueError("Claude CLI vision calls require at least one image")
        return self._run_structured(prompt=prompt, images=images, response_model=response_model)

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
            raise ClaudeCliProviderError("Claude CLI grading image does not exist")
        prompt = "\n\n".join(
            str(message.get("content", "")) for message in (messages or [])
        )
        prompt += "\nReturn only the requested grade-suggestion JSON object."
        completion = self._run_structured(
            prompt=prompt,
            images=[(image_path.read_bytes(), _mime_type_for_path(image_path))],
            response_model=None,
        )
        return finalize_cli_grade_output(
            completion.payload,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            latency_ms=completion.latency_ms,
            provider_flag="claude_cli_provider",
        )

    def _run_structured(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
    ) -> UniversalVisionCompletion:
        resolved_command = self._which(self.command)
        if resolved_command is None:
            raise ClaudeCliProviderError(f"Claude CLI command not found: {self.command}")
        configured_parent = Path(self.workdir) if self.workdir else None
        parent = (
            str(configured_parent)
            if configured_parent and configured_parent.is_dir()
            else None
        )
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="ta-claude-cli-", dir=parent) as tmp_dir:
            workspace = Path(tmp_dir)
            image_paths = _stage_images(workspace, images)
            schema = (
                response_model.model_json_schema()
                if response_model is not None
                else {"type": "object"}
            )
            image_instruction = ", ".join(path.name for path in image_paths)
            isolated_prompt = (
                f"Use the Read tool to view these images in order: {image_instruction}. "
                "Use no other tool and use only their visible contents.\n\n"
                + prompt
            )
            command = self._build_command(schema, resolved_command=resolved_command)
            try:
                result = self._runner(
                    command,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    input=isolated_prompt,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ClaudeCliProviderError(
                    f"Claude CLI call timed out after {self.timeout_seconds:g}s"
                ) from exc
            _require_bounded_output(result)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "(no output)")[:4000]
                raise ClaudeCliProviderError(
                    f"Claude CLI exited with status {result.returncode}: {detail}"
                )
            payload = _parse_claude_json(result.stdout)
        if response_model is not None:
            try:
                payload = response_model.model_validate(payload).model_dump(mode="json")
            except ValidationError as exc:
                raise ClaudeCliProviderError(
                    f"Claude CLI structured response was not usable: {exc}"
                ) from exc
        return UniversalVisionCompletion(
            payload=payload,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _build_command(
        self, schema: dict[str, Any], *, resolved_command: str | None = None
    ) -> list[str]:
        return [
            resolved_command or self.command,
            "--print",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--model",
            self.model_name,
            "--safe-mode",
            "--restricted",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            "Read",
            "--allowedTools",
            "Read",
            "--disallowedTools",
            _DENIED_TOOLS,
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--no-session-persistence",
            "--disable-slash-commands",
        ]


def _parse_claude_json(text: str) -> dict[str, Any]:
    try:
        outer = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ClaudeCliProviderError("Claude CLI did not return valid JSON") from exc
    if not isinstance(outer, dict):
        raise ClaudeCliProviderError("Claude CLI JSON output must be an object")
    structured = outer.get("structured_output")
    if isinstance(structured, dict):
        return structured
    result = outer.get("result")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ClaudeCliProviderError(
                "Claude CLI result did not contain structured JSON"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    if "type" not in outer and "subtype" not in outer:
        return outer
    raise ClaudeCliProviderError("Claude CLI response omitted structured_output")


def _stage_images(
    workspace: Path, images: list[tuple[bytes, str]]
) -> list[Path]:
    paths: list[Path] = []
    for index, (image_bytes, mime_type) in enumerate(images, start=1):
        suffix = ".png" if mime_type == "image/png" else ".jpg" if mime_type == "image/jpeg" else ""
        if not suffix:
            raise ValueError(f"Unsupported image MIME type: {mime_type}")
        path = workspace / f"input-{index}{suffix}"
        path.write_bytes(image_bytes)
        paths.append(path)
    return paths


def _mime_type_for_path(path: Path) -> str:
    return "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def _require_bounded_output(result: _CompletedProcessLike) -> None:
    for label, value in (("stdout", result.stdout), ("stderr", result.stderr)):
        if len((value or "").encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise ClaudeCliProviderError(f"Claude CLI {label} exceeded the output size limit")
