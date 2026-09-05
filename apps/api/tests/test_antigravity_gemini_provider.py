"""Contract and isolation tests for the Antigravity Gemini provider."""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.brain.adapter import BrainAdapter
from packages.brain.antigravity_gemini_vision_provider import (
    PROVIDER_NAME,
    AntigravityGeminiVisionProvider,
)
from packages.brain.capabilities import BrainCapability


def _agy_success(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            {
                "status": "SUCCESS",
                "response": json.dumps(payload),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        ),
        stderr="",
    )


def _transcription_payload() -> dict[str, object]:
    return {
        "draft_text": "The answer is 42",
        "uncertain_glyphs": [],
        "editing_marks": [],
        "cancellation_detected": False,
        "replacement_detected": False,
        "uncertain_correction_detected": False,
        "requires_thinking_repair": False,
        "is_blank": False,
        "is_irrelevant": False,
        "confidence": 0.95,
        "needs_review": True,
    }


def _grade_payload() -> dict[str, object]:
    return {
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


def test_provider_exposes_canonical_visual_contract(tmp_path: Path) -> None:
    provider = AntigravityGeminiVisionProvider(repository_root=tmp_path)
    adapter = BrainAdapter(provider)

    assert provider.provider_name == PROVIDER_NAME
    assert BrainCapability.VISUAL_MAPPING in adapter.runtime.capabilities
    assert BrainCapability.VISUAL_PAGE_READ in adapter.runtime.capabilities
    assert BrainCapability.VISUAL_TRANSCRIPTION in adapter.runtime.capabilities
    assert BrainCapability.GRADING in adapter.runtime.capabilities


def test_transcription_runs_through_adapter_and_cleans_workspace(tmp_path: Path) -> None:
    workspaces: list[Path] = []

    def runner(command: list[str], **kwargs: object) -> SimpleNamespace:
        workspace = Path(str(kwargs["cwd"]))
        assert [path.name for path in workspace.iterdir()] == ["input-1.png"]
        assert "view_file" in command[2]
        workspaces.append(workspace)
        return _agy_success(_transcription_payload())

    adapter = BrainAdapter(
        AntigravityGeminiVisionProvider(repository_root=tmp_path, runner=runner)
    )
    result = adapter.transcribe_images(
        images=[(b"fake-image", "image/png")],
        label="Q1",
    )

    assert result.draft_text == "The answer is 42"
    assert result.model_provider == PROVIDER_NAME
    assert result.prompt_tokens == 100
    assert all(not workspace.exists() for workspace in workspaces)


def test_page_read_and_mapping_use_canonical_signatures(tmp_path: Path) -> None:
    payloads = iter(
        [
            {
                "blocks": [
                    {
                        "question_label": "Q1",
                        "bbox": [100, 100, 900, 300],
                        "text": "x = 42",
                        "continues_from_previous": False,
                        "label_source": "heading",
                        "confidence": 0.9,
                    }
                ],
                "is_blank_page": False,
                "needs_review": True,
            },
            {
                "regions": [
                    {
                        "question_label": "Q1",
                        "bbox": [100, 100, 900, 300],
                        "continues_from_previous": False,
                        "continues_to_next": False,
                        "confidence": 0.9,
                        "warnings": [],
                    }
                ],
                "needs_review": True,
            },
        ]
    )

    def runner(_command: list[str], **_kwargs: object) -> SimpleNamespace:
        return _agy_success(next(payloads))

    adapter = BrainAdapter(
        AntigravityGeminiVisionProvider(repository_root=tmp_path, runner=runner)
    )
    page = adapter.read_page(
        image_bytes=b"page",
        mime_type="image/png",
        question_labels=["Q1"],
    )
    mapping = adapter.map_page_answer_regions(
        image_bytes=b"page",
        mime_type="image/png",
        question_labels=["Q1"],
    )

    assert page.blocks[0].text == "x = 42"
    assert mapping.regions[0].question_label == "Q1"


def test_grading_output_is_forced_to_teacher_review(tmp_path: Path) -> None:
    image = tmp_path / "answer.png"
    image.write_bytes(b"image")
    provider = AntigravityGeminiVisionProvider(
        repository_root=tmp_path,
        runner=lambda *_args, **_kwargs: _agy_success(_grade_payload()),
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
    assert "antigravity_cli_provider" in result.review_flags


def test_workspace_is_removed_after_timeout(tmp_path: Path) -> None:
    workspaces: list[Path] = []

    def runner(_command: list[str], **kwargs: object) -> SimpleNamespace:
        workspaces.append(Path(str(kwargs["cwd"])))
        raise subprocess.TimeoutExpired("agy", 120)

    adapter = BrainAdapter(
        AntigravityGeminiVisionProvider(repository_root=tmp_path, runner=runner)
    )
    with pytest.raises(RuntimeError, match="timed out after 120s"):
        adapter.transcribe_images(images=[(b"page", "image/png")], label="Q1")

    assert workspaces and all(not workspace.exists() for workspace in workspaces)


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(returncode=1, stdout="", stderr="bad"), "exited with code 1"),
        (
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "ERROR", "error": "Invalid prompt"}),
                stderr="",
            ),
            "Invalid prompt",
        ),
        (SimpleNamespace(returncode=0, stdout="not json", stderr=""), "parse agy"),
        (
            SimpleNamespace(returncode=0, stdout="x" * 1_000_001, stderr=""),
            "output size limit",
        ),
    ],
)
def test_transport_failures_surface(
    tmp_path: Path, result: SimpleNamespace, message: str
) -> None:
    provider = AntigravityGeminiVisionProvider(
        repository_root=tmp_path,
        runner=lambda *_args, **_kwargs: result,
    )
    with pytest.raises(RuntimeError, match=message):
        provider.transcribe_images(images=[(b"page", "image/png")], label="Q1")


def test_malformed_model_payload_fails_strict_validation(tmp_path: Path) -> None:
    provider = AntigravityGeminiVisionProvider(
        repository_root=tmp_path,
        runner=lambda *_args, **_kwargs: _agy_success({"draft_text": "partial"}),
    )
    with pytest.raises(RuntimeError, match="was not usable"):
        provider.transcribe_images(images=[(b"page", "image/png")], label="Q1")


def test_trailing_agy_artifact_does_not_weaken_payload_validation(tmp_path: Path) -> None:
    wrapper = _agy_success(_transcription_payload())
    outer = json.loads(wrapper.stdout)
    outer["response"] += '\n{"toolAction":"done"}'
    provider = AntigravityGeminiVisionProvider(
        repository_root=tmp_path,
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(outer), stderr=""
        ),
    )

    result = provider.transcribe_images(images=[(b"page", "image/png")], label="Q1")
    assert result.draft_text == "The answer is 42"


def test_current_agy_envelope_metadata_does_not_replace_strict_payload_validation(
    tmp_path: Path,
) -> None:
    model_payload = _transcription_payload()
    model_payload.update(
        {
            "toolAction": "Submitting visual transcription draft",
            "toolSummary": "Visual transcription draft",
        }
    )
    wrapper = _agy_success(model_payload)
    outer = json.loads(wrapper.stdout)
    outer.update(
        {
            "conversation_id": "conversation-1",
            "duration_seconds": 1.25,
            "num_turns": 2,
            "structured_output": {},
            "json_schema": {"type": "object"},
        }
    )
    outer["usage"].update(
        {"thinking_tokens": 3, "cache_read_tokens": 4, "total_tokens": 157}
    )
    provider = AntigravityGeminiVisionProvider(
        repository_root=tmp_path,
        runner=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(outer), stderr=""
        ),
    )

    result = provider.transcribe_images(images=[(b"page", "image/png")], label="Q1")

    assert result.draft_text == "The answer is 42"
    assert result.prompt_tokens == 100
