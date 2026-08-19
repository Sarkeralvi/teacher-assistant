from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from packages.brain.llama_cpp_qwen38_vision_provider import LlamaCppQwen38VisionProvider


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, completion: dict[str, Any]) -> None:
        self.completion = completion
        self.requests: list[dict[str, Any]] = []

    def get(self, *_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse({"data": [{"id": "qwen3.8-27b-q4km"}]})

    def post(self, _path: str, *, json: dict[str, Any], **_kwargs: object) -> FakeResponse:
        self.requests.append(json)
        return FakeResponse(self.completion)


def provider_with(completion: dict[str, Any]) -> tuple[LlamaCppQwen38VisionProvider, FakeClient]:
    provider = LlamaCppQwen38VisionProvider(api_key="test-key")
    client = FakeClient(completion)
    provider.client = client
    return provider, client


def test_visual_transcription_disables_thinking_and_requires_png_magic() -> None:
    completion = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"draft_text":"x = 4","uncertain_glyphs":[],"is_blank":false,'
                        '"is_irrelevant":false,"confidence":0.9,"needs_review":true}'
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    provider, client = provider_with(completion)
    result = provider.transcribe_image(
        image_bytes=b"\x89PNG\r\n\x1a\nimage", mime_type="image/png", label="1(a)"
    )
    assert result.needs_review is True
    assert client.requests[0]["chat_template_kwargs"] == {
        "enable_thinking": False,
        "preserve_thinking": False,
    }
    with pytest.raises(ValueError, match="magic"):
        provider.transcribe_image(image_bytes=b"not-an-image", mime_type="image/png")


def test_qwen38_grading_rejects_changed_rubric_contract() -> None:
    completion = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "score": 1,
                            "max_score": 3,
                            "confidence": 0.7,
                            "needs_review": True,
                            "rubric_breakdown": [
                                {
                                    "criterion_id": "c1",
                                    "criterion": "step",
                                    "criterion_status": "met",
                                    "max_marks": 3,
                                    "awarded_marks": 1,
                                    "reason": "shown",
                                    "evidence": "x = 4",
                                    "confidence": 0.7,
                                }
                            ],
                            "detected_answer_summary": "x = 4",
                            "major_errors": [],
                            "feedback_to_student": "Review working.",
                            "review_flags": ["teacher_review_required"],
                        }
                    )
                }
            }
        ],
        "usage": {},
    }
    provider, _client = provider_with(completion)
    with pytest.raises(ValueError, match="maximum score"):
        provider.grade(
            question_text="Solve x.",
            question_total_marks=Decimal("2"),
            rubric_json={"criteria": [{"id": "c1", "max_marks": "3"}]},
            answer_image_path="[image input disabled]",
            student_answer_text="x = 4",
            prompt_version="test",
            messages=[{"role": "user", "content": "fresh"}],
        )
