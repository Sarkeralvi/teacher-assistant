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


def _transcript_assignment_payload() -> dict[str, object]:
    return {
        "mappings": [
            {
                "question_id": 41,
                "question_no": "1(a)(i)",
                "status": "mapped",
                "block_references": [{"page_no": 1, "block_orders": [1]}],
                "confidence": 0.9,
                "warnings": [],
                "needs_review": True,
            }
        ],
        "unassigned_block_references": [],
        "non_answer_block_references": [],
        "warnings": [],
    }


def test_claude_assigns_saved_transcript_in_text_only_restricted_mode(
    tmp_path: Path,
) -> None:
    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        workspace = Path(str(kwargs["cwd"]))
        assert list(workspace.iterdir()) == []
        assert command[command.index("--tools") + 1] == ""
        assert "Use no tools" in str(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": _transcript_assignment_payload()}),
            stderr="",
        )

    provider = ClaudeCliProvider(
        workdir=str(tmp_path), which=lambda _command: "claude.cmd", runner=runner
    )
    result = provider.map_submission_answers_from_ocr_pages(
        pages=[{"page_no": 1, "blocks": [{"order": 1, "text": "(i) work"}]}],
        questions=[
            {
                "question_id": 41,
                "question_no": "1(a)(i)",
                "question_text": "Find the value.",
            }
        ],
    )

    assert BrainCapability.OCR_ANSWER_MAPPING in provider.capabilities
    assert result["mappings"][0]["block_references"][0]["block_orders"] == [1]


def test_claude_mapping_runs_through_adapter_in_restricted_workspace(
    tmp_path: Path,
) -> None:
    workspaces: list[Path] = []

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        workspace = Path(str(kwargs["cwd"]))
        assert command[0] == "claude.cmd"
        assert [path.name for path in workspace.iterdir()] == ["input-1.png"]
        assert "--restricted" in command
        assert "--safe-mode" in command
        assert "--dangerously-skip-permissions" not in command
        assert json.loads(command[command.index("--mcp-config") + 1]) == {
            "mcpServers": {}
        }
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


def test_claude_runner_decodes_cli_output_as_utf8(tmp_path: Path) -> None:
    # Text mode without an explicit codec decodes with the locale codepage, which
    # on Windows turned a live extraction's "P(X^c ∩ Y^c) ≈ 0.2583" into
    # "P(X^c âˆ© Y^c) â‰ˆ 0.2583".
    captured: dict[str, object] = {}

    def runner(_command: list[str], **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "result": json.dumps(
                        {
                            "regions": [],
                            "notes": "P(X^c ∩ Y^c) ≈ 0.2583",
                        }
                    ),
                }
            ),
            stderr="",
        )

    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=runner,
    )
    try:
        provider.map_page_answer_regions(
            image_bytes=b"page",
            mime_type="image/png",
            question_labels=["Q1"],
        )
    except ClaudeCliProviderError:
        # The payload shape is irrelevant here; only the decoding contract is.
        pass

    assert captured.get("encoding") == "utf-8"
    assert captured.get("errors") == "strict"


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
                "criterion_status": "partially_met",
                "max_marks": 2,
                "awarded_marks": 1,
                "reason": "Partial working is visible.",
                "evidence": "x = 42",
                "confidence": 0.7,
            }
        ],
        "detected_answer_summary": "Partial answer",
        "review_flags": [],
    }
    def runner(command: list[str], **_kwargs: object) -> SimpleNamespace:
        schema = json.loads(command[command.index("--json-schema") + 1])
        assert "score" in schema["properties"]
        assert "model_provider" not in schema["properties"]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": payload}),
            stderr="",
        )

    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=runner,
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
    assert result.major_errors == []
    assert result.feedback_to_student == "Teacher review is required before feedback is released."
    assert "teacher_review_required" in result.review_flags
    assert "claude_cli_provider" in result.review_flags


def test_claude_transcript_grading_uses_no_image_or_read_tool(tmp_path: Path) -> None:
    payload = {
        "score": 1,
        "max_score": 2,
        "confidence": 0.7,
        "rubric_breakdown": [
            {
                "criterion_id": "work",
                "criterion": "Shows working",
                "criterion_status": "partially_met",
                "max_marks": 2,
                "awarded_marks": 1,
                "reason": "Partial working is present.",
                "evidence": "x = 42",
                "confidence": 0.7,
            }
        ],
        "detected_answer_summary": "Partial answer",
        "review_flags": [],
    }

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        workspace = Path(str(kwargs["cwd"]))
        assert list(workspace.iterdir()) == []
        assert command[command.index("--tools") + 1] == ""
        assert command[command.index("--allowedTools") + 1] == ""
        assert "Read" in command[command.index("--disallowedTools") + 1]
        assert "Use no tools" in str(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"structured_output": payload}),
            stderr="",
        )

    provider = ClaudeCliProvider(
        workdir=str(tmp_path),
        which=lambda _command: "claude.cmd",
        runner=runner,
    )
    result = provider.grade(
        question_text="Solve x.",
        question_total_marks=Decimal("2"),
        rubric_json={},
        answer_image_path="[stored transcript evidence; image input disabled]",
        prompt_version="test-v1",
        student_answer_text="x = 42",
        messages=[{"role": "user", "content": "Grade the transcript."}],
    )

    assert result.score == Decimal("1")


def test_claude_transcription_reconciles_redundant_editing_flags(tmp_path: Path) -> None:
    payload = {
        "draft_text": "visible answer",
        "uncertain_glyphs": [],
        "editing_marks": [
            {
                "page_index": 1,
                "bbox": [10, 10, 900, 100],
                "status": "replacement",
                "position_hint": "final line",
            }
        ],
        "cancellation_detected": False,
        "replacement_detected": False,
        "uncertain_correction_detected": False,
        "requires_thinking_repair": False,
        "is_blank": False,
        "is_irrelevant": False,
        "confidence": 0.8,
        "needs_review": True,
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

    result = BrainAdapter(provider).transcribe_image(
        image_bytes=b"page",
        mime_type="image/png",
        label="Q1",
    )

    assert result.replacement_detected is True
    assert result.cancellation_detected is False


def test_claude_page_read_preserves_text_when_only_bbox_is_invalid(
    tmp_path: Path,
) -> None:
    payload = {
        "blocks": [
            {
                "question_label": "Q1",
                "bbox": [900, 100, 100, 300],
                "text": "x = 42",
                "continues_from_previous": False,
                "label_source": "heading",
                "confidence": 0.9,
            }
        ],
        "is_blank_page": False,
        "needs_review": True,
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

    result = provider.read_page(
        image_bytes=b"page", mime_type="image/png", question_labels=["Q1"]
    )

    assert result.blocks[0].text == "x = 42"
    assert result.blocks[0].bbox == [0, 0, 1000, 1000]
    assert result.blocks[0].label_source == "inferred"
    assert result.blocks[0].confidence == Decimal("0.49")
