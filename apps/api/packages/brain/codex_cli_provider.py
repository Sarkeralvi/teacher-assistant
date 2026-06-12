import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from packages.brain.prompt_registry import (
    build_handwritten_math_stat_guidance,
    build_marking_policy_instruction,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy

CODEX_CLI_PROMPT_VERSION = "codex_cli_grading_v1"
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


class CodexCliProviderError(RuntimeError):
    """Raised when Codex CLI provider setup or execution fails safely."""


class CodexCliProvider(BrainProvider):
    provider_name = "codex_cli"

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
        del prompt_version, task_name, model_policy
        use_image_input = self.image_input_enabled and bool(answer_image_path)
        self._preflight(require_image_input=use_image_input)
        if image_data_url:
            # Codex CLI provider never consumes base64/data URLs. Vision must
            # use a supported CLI image flag, not prompt text or persisted raw data.
            image_data_url = None
        with tempfile.TemporaryDirectory(prefix="ta-codex-cli-") as tmp_dir:
            output_file = Path(tmp_dir) / "last-message.json"
            prompt = self._build_prompt(
                question_text=question_text,
                question_total_marks=question_total_marks,
                rubric_json=rubric_json,
                messages=messages or [],
                image_input_enabled=use_image_input,
                student_answer_text=student_answer_text,
                marking_policy=marking_policy,
            )
            command = self._build_command(
                output_file=output_file,
                answer_image_path=answer_image_path,
                use_image_input=use_image_input,
            )
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
                raise CodexCliProviderError(
                    f"Codex CLI grading timed out after {self.timeout_seconds:g}s"
                ) from exc
            if completed.returncode != 0:
                raise CodexCliProviderError(
                    self._format_process_failure(completed, command=command)
                )
            raw_payload = self._read_json_output(output_file)
        raw_payload["model_provider"] = self.provider_name
        raw_payload["model_name"] = self.model_name
        raw_payload["prompt_version"] = CODEX_CLI_PROMPT_VERSION
        raw_payload["needs_review"] = True
        raw_payload["cost_estimate"] = raw_payload.get("cost_estimate", 0)
        raw_payload.pop("latency_ms", None)
        flags = list(raw_payload.get("review_flags") or [])
        self._append_flag(flags, "teacher_review_required")
        self._append_flag(flags, "codex_cli_provider")
        self._append_flag(
            flags,
            "image_input_used" if use_image_input else "image_input_disabled",
        )
        raw_payload["review_flags"] = flags
        try:
            return GradeSuggestionOutput.model_validate(raw_payload)
        except ValidationError:
            raise

    def _preflight(self, *, require_image_input: bool) -> None:
        if self._which(self.command) is None:
            raise CodexCliProviderError(f"codex command not found: {self.command}")
        version = self._run_preflight_command([self.command, "--version"], "codex --version")
        if not version.strip():
            raise CodexCliProviderError("codex --version returned no output")
        help_text = self._run_preflight_command(
            [self.command, "exec", "--help"], "codex exec --help"
        )
        self._help_text = help_text
        for flag in _REQUIRED_EXEC_FLAGS:
            if flag not in help_text:
                raise CodexCliProviderError(f"Codex CLI exec does not support required flag {flag}")
        if self.output_last_message is False:
            raise CodexCliProviderError("Codex CLI provider requires --output-last-message")
        if require_image_input and not self._supported_image_flag():
            raise CodexCliProviderError(
                "Codex CLI image input is not supported by this installed version."
            )
        if self.sandbox == "danger-full-access":
            raise CodexCliProviderError("Codex CLI provider refuses danger-full-access sandbox")

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
            raise CodexCliProviderError(f"{label} timed out") from exc
        if completed.returncode != 0:
            detail = self._sanitize((completed.stderr or completed.stdout or "").strip())
            raise CodexCliProviderError(f"{label} failed: {detail[:_MAX_CAPTURE_CHARS]}")
        return completed.stdout or completed.stderr or ""

    def _build_command(
        self, *, output_file: Path, answer_image_path: str, use_image_input: bool
    ) -> list[str]:
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
        if use_image_input:
            image_flag = self._supported_image_flag()
            if image_flag is None:
                raise CodexCliProviderError(
                    "Codex CLI image input is not supported by this installed version."
                )
            command.extend([image_flag, answer_image_path])
        return command

    def _supported_image_flag(self) -> str | None:
        help_text = self._help_text or ""
        for flag in _IMAGE_FLAGS:
            if flag in help_text:
                return flag
        return None

    def _read_json_output(self, output_file: Path) -> dict[str, Any]:
        if not output_file.is_file():
            raise CodexCliProviderError("Codex CLI did not write --output-last-message file")
        text = output_file.read_text(encoding="utf-8")
        if not text.strip():
            raise CodexCliProviderError("Codex CLI --output-last-message file was empty")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CodexCliProviderError(
                "Codex CLI output-last-message did not contain exact valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise CodexCliProviderError("Codex CLI JSON output must be an object")
        return payload

    def _build_prompt(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        messages: list[dict[str, Any]],
        image_input_enabled: bool,
        student_answer_text: str | None = None,
        marking_policy: str = "general",
    ) -> str:
        model_answer = (
            rubric_json.get("model_answer") or rubric_json.get("answer_key") or "Not provided."
        )
        if image_input_enabled:
            image_statement = (
                "Image input is enabled only if a supported Codex CLI image flag is used. "
                "Do not invent visible handwriting/image content."
            )
        else:
            image_statement = (
                "Image input is disabled. No answer image content is available to the provider. "
                "Do not invent visible handwriting/image content. "
                "Include image_input_disabled in review_flags."
            )
        policy_instruction = self._policy_instruction(marking_policy)
        math_stat_guidance = build_handwritten_math_stat_guidance()
        normalized_policy = self._normalize_marking_policy(marking_policy)
        rendered_messages = "\n\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in messages
        )
        manual_answer_text = (student_answer_text or "").strip()
        answer_text_block = (
            manual_answer_text or "Not supplied. Do not infer answer content from the image path."
        )
        return f"""You are producing a grade suggestion for TA Agent.
Return ONLY valid JSON matching the GradeSuggestionOutput schema.
Do not write markdown.
Do not write prose outside JSON.
Do not modify files.
Do not run commands.
Do not ask for approval.
This is a suggestion only.
Teacher final review is required.
Set needs_review=true.
Include teacher_review_required in review_flags.
Include codex_cli_provider in review_flags.
If image input is disabled, include image_input_disabled in review_flags.
Use marking policy: {normalized_policy}.
{policy_instruction}

Math/stat grading guidance:
{math_stat_guidance}
Include marking_policy:{normalized_policy} in review_flags.
Do not change max_score or criterion max_marks because of marking policy.
If you cannot evaluate the answer, set confidence=0 and needs_review=true.
Do not invent visible handwriting/image content.

Task input:
Question text:
{question_text}

Model answer:
{model_answer}

Rubric JSON:
{json.dumps(rubric_json, ensure_ascii=False, default=str)}

Question total marks:
{question_total_marks}

Image input enabled:
{str(image_input_enabled).lower()}
{image_statement}

Marking policy: {normalized_policy}

Existing prompt context:
{rendered_messages}

Teacher-confirmed student answer text:
{answer_text_block}

Output JSON schema fields:
score, max_score, confidence, needs_review, rubric_breakdown, detected_answer_summary,
major_errors, feedback_to_student, review_flags.
Every rubric_breakdown item must include criterion_id, criterion, max_marks, awarded_marks,
reason, evidence, confidence. Awarded marks must sum to score.
"""

    @staticmethod
    def _normalize_marking_policy(marking_policy: str) -> str:
        policy = marking_policy.strip().lower()
        return policy if policy in {"tough", "general", "easy"} else "general"

    @classmethod
    def _policy_instruction(cls, marking_policy: str) -> str:
        normalized = cls._normalize_marking_policy(marking_policy)
        return build_marking_policy_instruction(normalized)

    @staticmethod
    def _append_flag(flags: list[str], flag: str) -> None:
        if flag not in flags:
            flags.append(flag)

    @staticmethod
    def _sanitize(message: str) -> str:
        without_keys = _API_KEY_PATTERN.sub("[REDACTED]", message)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", without_keys)

    def _format_process_failure(
        self, completed: CompletedProcessLike, *, command: list[str]
    ) -> str:
        stdout = self._sanitize((completed.stdout or "").strip())
        stderr = self._sanitize((completed.stderr or "").strip())
        combined = "\n".join(part for part in [stderr, stdout] if part)
        classification = self._classify_failure(combined)
        command_display = self._redacted_command(command)
        detail_parts = [
            f"Codex CLI exited with status {completed.returncode}",
            f"classification={classification}",
            f"model={self.model_name}",
            f"command={command_display}",
        ]
        if stderr:
            detail_parts.append(f"stderr={stderr[:_MAX_CAPTURE_CHARS]}")
        if stdout:
            detail_parts.append(f"stdout={stdout[:_MAX_CAPTURE_CHARS]}")
        if not stderr and not stdout:
            detail_parts.append("no stdout/stderr captured")
        return "; ".join(detail_parts)

    @staticmethod
    def _classify_failure(message: str) -> str:
        lower = message.lower()
        if any(
            token in lower for token in ["not logged in", "login", "auth", "unauthorized", "401"]
        ):
            return "auth"
        if any(token in lower for token in ["model", "not found", "unsupported"]):
            return "model"
        if any(token in lower for token in ["rate limit", "quota", "usage limit", "429"]):
            return "usage_limit"
        if any(token in lower for token in ["502", "bad gateway", "temporar", "transient"]):
            return "transient_502"
        return "process_exit"

    @classmethod
    def _redacted_command(cls, command: list[str]) -> str:
        return " ".join(cls._sanitize(part) for part in command)
