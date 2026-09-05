"""Contract tests for the isolated Claude Code CLI transport."""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter
from packages.brain.capabilities import BrainCapability
from packages.brain.claude_cli_provider import (
    ClaudeCliProvider,
    ClaudeCliProviderError,
)


def _mapping_payload() -> dict[str, object]:
    return {
        "regions": [
            {
                "question_label": "Q1",
                "bbox": [50, 100, 950, 400],
                "continues_from_previous": False,
                "continues_to_next": False,
                "confidence": 0.9,
                "warnings": [],
            }
        ],
        "needs_review": True,
    }


def test_claude_mapping_runs_through_adapter_in_restricted_workspace(
    tmp_path: Path,
) -> None:
    workspaces: list[Path] = []

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        workspace = Path(str(kwargs["cwd"]))
        assert [path.name for path in workspace.iterdir()] == ["input-1.png"]
        assert "--restricted" in command
        assert "--safe-mode" in command
        assert "--dangerously-skip-permissions" not in command
        assert command[command.index("--tools") + 1] == "Read"
        assert kwargs["input"] and "input-1.png" in str(kwargs["input"])
        workspaces.append(workspace)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": _mapping_payload()}),
            stderr="",
        )

    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=runner,
    )
    result = BrainAdapter(provider).map_page_answer_regions(
        image_bytes=b"page",
        mime_type="image/png",
        question_labels=["Q1"],
    )

    assert BrainCapability.VISUAL_MAPPING in provider.capabilities
    assert result.regions[0].question_label == "Q1"
    assert workspaces and all(not workspace.exists() for workspace in workspaces)


def test_claude_workspace_is_removed_after_timeout(tmp_path: Path) -> None:
    workspaces: list[Path] = []

    def runner(_command: list[str], **kwargs: object) -> SimpleNamespace:
        workspaces.append(Path(str(kwargs["cwd"])))
        raise subprocess.TimeoutExpired("claude", 30)

    provider = ClaudeCliProvider(
        timeout_seconds=30,
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=runner,
    )
    with pytest.raises(ClaudeCliProviderError, match="timed out after 30s"):
        provider.map_page_answer_regions(
            image_bytes=b"page",
            mime_type="image/png",
            question_labels=["Q1"],
        )

    assert workspaces and all(not workspace.exists() for workspace in workspaces)


def test_claude_rejects_missing_binary_without_calling_runner() -> None:
    provider = ClaudeCliProvider(
        which=lambda _command: None,
        runner=lambda *_args, **_kwargs: pytest.fail("runner must not be called"),
    )
    with pytest.raises(ClaudeCliProviderError, match="command not found"):
        provider.map_page_answer_regions(
            image_bytes=b"page",
            mime_type="image/png",
            question_labels=["Q1"],
        )


def test_claude_rejects_malformed_structured_output(tmp_path: Path) -> None:
    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"type": "result", "result": "not json"}),
            stderr="",
        ),
    )
    with pytest.raises(ClaudeCliProviderError, match="structured JSON"):
        provider.map_page_answer_regions(
            image_bytes=b"page",
            mime_type="image/png",
            question_labels=["Q1"],
        )


def test_claude_profile_constructs_without_running_the_cli() -> None:
    adapter = BrainAdapter.for_profile(
        Settings(BRAIN_ALLOW_REAL_PROVIDERS=True, CLAUDE_CLI_ENABLED=True),
        "claude_cli",
    )

    assert isinstance(adapter.provider, ClaudeCliProvider)
    assert adapter.runtime.is_cli is True
    assert adapter.runtime.location.value == "cloud"


def test_claude_grading_output_is_forced_to_teacher_review(tmp_path: Path) -> None:
    image = tmp_path / "answer.png"
    image.write_bytes(b"image")
    payload = {
        "score": 1,
        "max_score": 2,
        "confidence": 0.7,
        "rubric_breakdown": [
            {
                "criterion_id": "work",
                "criterion": "Shows working",
                "max_marks": 2,
                "awarded_marks": 1,
                "reason": "Partial working is visible.",
                "evidence": "x = 42",
                "confidence": 0.7,
            }
        ],
        "detected_answer_summary": "Partial answer",
        "major_errors": [],
        "feedback_to_student": "Show the remaining step.",
        "review_flags": [],
    }
    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": payload}),
            stderr="",
        ),
    )

    result = provider.grade(
        question_text="Solve x.",
        question_total_marks=Decimal("2"),
        rubric_json={},
        answer_image_path=str(image),
        prompt_version="test-v1",
        messages=[{"role": "user", "content": "Grade against the rubric."}],
    )

    assert result.score == Decimal("1")
    assert result.needs_review is True
    assert "teacher_review_required" in result.review_flags
    assert "claude_cli_provider" in result.review_flags
