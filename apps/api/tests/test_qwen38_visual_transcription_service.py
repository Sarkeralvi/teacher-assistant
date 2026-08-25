from types import SimpleNamespace

import pytest

from app.services.qwen38_visual_transcription_service import (
    Qwen38VisualTranscriptionService,
    VisualTranscriptionError,
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

    with pytest.raises(VisualTranscriptionError, match="retired include-crossed-out rules"):
        service.confirm(
            region,  # type: ignore[arg-type]
            run,  # type: ignore[arg-type]
            teacher=teacher,  # type: ignore[arg-type]
            draft_hash="0" * 64,
        )
