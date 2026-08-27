import hashlib
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.qwen38_visual_transcription_service import (
    Qwen38VisualTranscriptionService,
    VisualTranscriptionError,
    _repair_decision_hash,
    _repair_source_text,
    _source_run_has_repairable_output,
    _thinking_repair_input_hash,
)
from packages.brain.schemas_qwen38 import (
    FINAL_INTENT_PROMPT_VERSION,
    THINKING_REPAIR_PROMPT_VERSION,
)


def test_legacy_include_crossed_out_transcript_cannot_be_confirmed() -> None:
    service = Qwen38VisualTranscriptionService(None)  # type: ignore[arg-type]
    region = SimpleNamespace(id=42)
    run = SimpleNamespace(
        answer_region_id=42,
        profile="qwen38_verbatim_visual",
        prompt_version="qwen38-forensic-verbatim-v1",
    )
    teacher = SimpleNamespace(id=7)

    with pytest.raises(VisualTranscriptionError, match="older combined"):
        service.confirm(
            region,  # type: ignore[arg-type]
            run,  # type: ignore[arg-type]
            teacher=teacher,  # type: ignore[arg-type]
            draft_hash="0" * 64,
        )


def test_visible_edit_inventory_requires_thinking_before_confirmation() -> None:
    service = Qwen38VisualTranscriptionService(None)  # type: ignore[arg-type]
    draft_text = "[visibly crossed] x=3\nx=4"
    run = SimpleNamespace(
        answer_region_id=42,
        profile="qwen38_verbatim_visual",
        prompt_version=FINAL_INTENT_PROMPT_VERSION,
        status="succeeded",
        draft_text=draft_text,
        normalized_result={"is_blank": False, "requires_thinking_repair": True},
    )

    with pytest.raises(VisualTranscriptionError, match="explicit Thinking review"):
        service.confirm(
            SimpleNamespace(id=42),  # type: ignore[arg-type]
            run,  # type: ignore[arg-type]
            teacher=SimpleNamespace(id=7),  # type: ignore[arg-type]
            draft_hash=hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        )


def test_transcription_cannot_replace_evidence_after_grading_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Qwen38VisualTranscriptionService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_assert_enabled", lambda _expected_model: None)
    monkeypatch.setattr(
        service,
        "_mapping_for_region",
        lambda _region_id: SimpleNamespace(teacher_confirmed=True),
    )
    region = SimpleNamespace(id=42, grading_jobs=[SimpleNamespace(id=9)], grade_suggestions=[])
    teacher = SimpleNamespace(id=7)

    with pytest.raises(VisualTranscriptionError, match="after grading has started"):
        service.create(
            region,  # type: ignore[arg-type]
            teacher=teacher,  # type: ignore[arg-type]
            expected_model="qwen3.8-27b-q4km",
        )


def test_thinking_repair_has_an_independent_disabled_by_default_kill_switch() -> None:
    service = Qwen38VisualTranscriptionService(
        None,  # type: ignore[arg-type]
        settings=Settings(
            BRAIN_ALLOW_REAL_PROVIDERS=True,
            LOCAL_QWEN38_ENABLED=True,
            LOCAL_QWEN38_TRANSCRIPTION_ENABLED=True,
            LOCAL_QWEN38_THINKING_REPAIR_ENABLED=False,
        ),
    )

    with pytest.raises(VisualTranscriptionError, match="thinking repair is disabled"):
        service._assert_thinking_repair_enabled("qwen3.8-27b-q4km")


def test_thinking_repair_can_rescue_an_unsafe_model_blank() -> None:
    source = SimpleNamespace(
        draft_text="",
        normalized_result={
            "is_blank": True,
            "editing_analysis": {
                "editing_marks": [
                    {
                        "page_index": 1,
                        "bbox": [10, 10, 990, 990],
                        "status": "cancelled",
                        "position_hint": "whole page claim",
                    }
                ]
            },
        },
    )

    assert _source_run_has_repairable_output(source) is True  # type: ignore[arg-type]
    assert "returned blank" in _repair_source_text(source)  # type: ignore[arg-type]


def test_thinking_repair_duplicate_hash_is_scoped_to_prompt_contract() -> None:
    common = {
        "source_hash": "a" * 64,
        "source_run_id": 52,
        "source_draft_hash": "b" * 64,
    }

    old_hash = _thinking_repair_input_hash(
        **common,
        prompt_version="qwen38-final-intent-thinking-repair-v5",
    )
    current_hash = _thinking_repair_input_hash(**common)

    assert old_hash != current_hash


def test_thinking_repair_requires_teacher_review_of_every_editing_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = [
        {
            "page_index": 1,
            "bbox": [100, 200, 700, 350],
            "status": "cancelled",
            "position_hint": "middle line crossed by two diagonal strokes",
        },
        {
            "page_index": 1,
            "bbox": [120, 700, 850, 900],
            "status": "replacement",
            "position_hint": "uncancelled bottom line",
        },
    ]
    decision_hash = _repair_decision_hash(decisions)
    draft_text = "A^c = {P, PF, PPF, PPPF, PPPP}"
    draft_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
    run = SimpleNamespace(
        id=11,
        answer_region_id=42,
        profile="qwen38_thinking_repair",
        prompt_version=THINKING_REPAIR_PROMPT_VERSION,
        status="succeeded",
        draft_text=draft_text,
        normalized_result={
            "decision_set_sha256": decision_hash,
            "editing_analysis": {"editing_marks": decisions},
        },
        source_image_sha256="a" * 64,
        confirmed_text=None,
        confirmed_by_teacher_id=None,
        confirmed_at=None,
    )
    region = SimpleNamespace(
        id=42,
        grading_jobs=[],
        grade_suggestions=[],
        manual_answer_text=None,
        evidence_status="unconfirmed",
    )
    mapping = SimpleNamespace(
        teacher_confirmed=True,
        mapping_status="blocked",
        blocker_reason="old rejection",
    )
    db = SimpleNamespace(add=lambda _item: None, commit=lambda: None)
    service = Qwen38VisualTranscriptionService(db)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_source_hash", lambda _region: "a" * 64)
    monkeypatch.setattr(service, "_mapping_for_region", lambda _region_id: mapping)
    monkeypatch.setattr(service, "_audit", lambda *_args, **_kwargs: None)
    teacher = SimpleNamespace(id=7)

    with pytest.raises(VisualTranscriptionError, match="editing decisions changed"):
        service.confirm_thinking_repair(
            region,  # type: ignore[arg-type]
            run,  # type: ignore[arg-type]
            teacher=teacher,  # type: ignore[arg-type]
            draft_hash=draft_hash,
            decision_set_hash="0" * 64,
            reviewed_decision_indexes=[0, 1],
        )

    with pytest.raises(VisualTranscriptionError, match="every visual editing decision"):
        service.confirm_thinking_repair(
            region,  # type: ignore[arg-type]
            run,  # type: ignore[arg-type]
            teacher=teacher,  # type: ignore[arg-type]
            draft_hash=draft_hash,
            decision_set_hash=decision_hash,
            reviewed_decision_indexes=[0],
        )

    service.confirm_thinking_repair(
        region,  # type: ignore[arg-type]
        run,  # type: ignore[arg-type]
        teacher=teacher,  # type: ignore[arg-type]
        draft_hash=draft_hash,
        decision_set_hash=decision_hash,
        reviewed_decision_indexes=[0, 1],
    )

    assert run.status == "confirmed"
    assert region.manual_answer_text == draft_text
    assert region.evidence_status == "partial"
    assert mapping.mapping_status == "teacher_confirmed"
    assert mapping.blocker_reason is None
