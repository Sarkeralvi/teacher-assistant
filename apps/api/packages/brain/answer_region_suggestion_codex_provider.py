from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from packages.brain.schemas import AnswerRegionSuggestionOutput

CODEX_ANSWER_REGION_SUGGESTION_PROMPT_VERSION = "codex_cli_answer_region_suggestion_v1"
_REQUIRED_EXEC_FLAGS = ("--output-last-message", "--cd", "--sandbox")
_IMAGE_FLAGS = ("--image", "-i")
_MAX_CAPTURE_CHARS = 4000
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")


class CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., CompletedProcessLike]
Which = Callable[[str], str | None]


class CodexAnswerRegionSuggestionProviderError(RuntimeError):
    """Raised when Codex-backed answer-region suggestion setup or execution fails."""


class CodexAnswerRegionSuggestionProvider:
    provider_name = "codex_cli_answer_region_suggester"

    def __init__(
        self,
        *,
        command: str = "codex",
        model_name: str = "",
        timeout_seconds: float = 300.0,
        sandbox: str = "read-only",
        use_json: bool = True,
        output_last_message: bool = True,
        image_input_enabled: bool = False,
        workdir: str = "/home/newton/teacher-assistant",
        skip_git_repo_check: bool = False,
        which: Which = shutil.which,
        runner: Runner = subprocess.run,
    ) -> None:
        self.command = command or "codex"
        self.model_name = model_name or "codex-cli"
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox or "read-only"
        self.use_json = use_json
        self.output_last_message = output_last_message
        self.image_input_enabled = image_input_enabled
        self.workdir = workdir or "/home/newton/teacher-assistant"
        self.skip_git_repo_check = skip_git_repo_check
        self._which = which
        self._runner = runner
        self._help_text: str | None = None

    def suggest(
        self,
        *,
        page_image_path: str,
        page_width: int,
        page_height: int,
        questions: list[dict[str, Any]],
        provider_warnings: list[str] | None = None,
    ) -> AnswerRegionSuggestionOutput:
        self._preflight(require_image_input=True)
        with tempfile.TemporaryDirectory(prefix="ta-codex-answer-region-") as tmp_dir:
            output_file = Path(tmp_dir) / "last-message.json"
            prompt = self._build_prompt(
                page_width=page_width,
                page_height=page_height,
                questions=questions,
                page_image_path=page_image_path,
            )
            command = self._build_command(output_file=output_file, page_image_path=page_image_path)
            try:
                completed = self._runner(
                    command,
                    cwd=self.workdir,
                    capture_output=True,
                    text=True,
                    input=prompt,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexAnswerRegionSuggestionProviderError(
                    f"Codex CLI answer-region suggestion timed out after {self.timeout_seconds:g}s"
                ) from exc
            if completed.returncode != 0:
                stderr = self._sanitize((completed.stderr or completed.stdout or "").strip())
                raise CodexAnswerRegionSuggestionProviderError(
                    f"Codex CLI exited with status {completed.returncode}: "
                    f"{stderr[:_MAX_CAPTURE_CHARS]}"
                )
            raw_payload = self._read_json_output(output_file)
        if provider_warnings:
            payload_warnings = list(raw_payload.get("provider_warnings") or [])
            for warning in provider_warnings:
                if warning not in payload_warnings:
                    payload_warnings.append(warning)
            raw_payload["provider_warnings"] = payload_warnings
        try:
            validated = AnswerRegionSuggestionOutput.model_validate(raw_payload)
        except ValidationError as exc:
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI JSON did not match the strict answer-region schema: "
                f"{self._sanitize(str(exc))[:_MAX_CAPTURE_CHARS]}"
            ) from exc
        return validated

    def _preflight(self, *, require_image_input: bool) -> None:
        if self._which(self.command) is None:
            raise CodexAnswerRegionSuggestionProviderError(
                f"codex command not found: {self.command}"
            )
        version = self._run_preflight_command([self.command, "--version"], "codex --version")
        if not version.strip():
            raise CodexAnswerRegionSuggestionProviderError("codex --version returned no output")
        help_text = self._run_preflight_command(
            [self.command, "exec", "--help"], "codex exec --help"
        )
        self._help_text = help_text
        for flag in _REQUIRED_EXEC_FLAGS:
            if flag not in help_text:
                raise CodexAnswerRegionSuggestionProviderError(
                    f"Codex CLI exec does not support required flag {flag}"
                )
        if self.output_last_message is False:
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI answer-region provider requires --output-last-message"
            )
        if require_image_input and not self._supported_image_flag():
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI image input is not supported by this installed version."
            )
        if self.sandbox == "danger-full-access":
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI provider refuses danger-full-access sandbox"
            )

    def _run_preflight_command(self, command: list[str], label: str) -> str:
        try:
            completed = self._runner(
                command,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=min(self.timeout_seconds, 30),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexAnswerRegionSuggestionProviderError(f"{label} timed out") from exc
        if completed.returncode != 0:
            detail = self._sanitize((completed.stderr or completed.stdout or "").strip())
            raise CodexAnswerRegionSuggestionProviderError(
                f"{label} failed: {detail[:_MAX_CAPTURE_CHARS]}"
            )
        return completed.stdout or completed.stderr or ""

    def _build_command(self, *, output_file: Path, page_image_path: str) -> list[str]:
        command = [self.command, "exec"]
        if self.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        command.extend(
            [
                "--cd",
                self.workdir,
                "--sandbox",
                self.sandbox,
                "--output-last-message",
                str(output_file),
            ]
        )
        if self.use_json and self._help_text and "--json" in self._help_text:
            command.append("--json")
        if self.model_name and self.model_name != "codex-cli":
            command.extend(["--model", self.model_name])
        image_flag = self._supported_image_flag()
        if image_flag is None:
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI image input is not supported by this installed version."
            )
        command.extend([image_flag, page_image_path])
        return command

    def _supported_image_flag(self) -> str | None:
        help_text = self._help_text or ""
        for flag in _IMAGE_FLAGS:
            if flag in help_text:
                return flag
        return None

    def _read_json_output(self, output_file: Path) -> dict[str, Any]:
        if not output_file.is_file():
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI did not write --output-last-message file"
            )
        text = output_file.read_text(encoding="utf-8")
        if not text.strip():
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI --output-last-message file was empty"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI output-last-message did not contain exact valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise CodexAnswerRegionSuggestionProviderError(
                "Codex CLI JSON output must be an object"
            )
        return payload

    def _build_prompt(
        self,
        *,
        page_width: int,
        page_height: int,
        questions: list[dict[str, Any]],
        page_image_path: str,
    ) -> str:
        return f"""You are proposing draft answer regions for a teacher review workflow.
Return ONLY valid JSON. No markdown. No code fences. No prose outside JSON.
Do not modify files. Do not run commands. Do not ask for approval.
This is a draft suggestion only. Teacher confirmation is required before grading.
Every suggestion must set needs_review=true.
Use pixel coordinates in the same coordinate system as the page image.
Origin is top-left. x/y are in pixels. width/height are in pixels.
Do not use normalized coordinates.
Do not include base64 or any raw image data.
Do not include any keys other than those described below.

Return JSON matching this shape exactly:
{{
  "provider_warnings": ["..."],
  "suggestions": [
    {{
      "question_id": 123,
      "question_no": "1",
      "x": 120,
      "y": 240,
      "width": 480,
      "height": 160,
      "confidence": 0.82,
      "notes": "short note",
      "warnings": ["optional warning"]
    }}
  ]
}}

Confirmed questions for this assessment:
{json.dumps(questions, ensure_ascii=False, default=str)}

Page dimensions in pixels:
{{"width": {page_width}, "height": {page_height}}}

Page image path:
{page_image_path}

Rules:
- Return 0 or more suggestions.
- If you cannot confidently identify a region, omit that question instead of inventing one.
- question_id must refer to a confirmed question in the list above.
- question_no must match the linked question if provided.
- confidence must be between 0 and 1.
- Keep provider_warnings concise and only about limitations or ambiguity.
"""

    @staticmethod
    def _sanitize(message: str) -> str:
        without_keys = _API_KEY_PATTERN.sub("[REDACTED]", message)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", without_keys)
