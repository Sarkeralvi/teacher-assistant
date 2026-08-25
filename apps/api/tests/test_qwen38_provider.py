from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter
from packages.brain.llama_cpp_qwen38_vision_provider import (
    LlamaCppQwen38VisionProvider,
    _Qwen38TranscriptionPayload,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

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


class AuthFailClient(FakeClient):
    def get(self, *_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse({}, status_code=401)


def provider_with(completion: dict[str, Any]) -> tuple[LlamaCppQwen38VisionProvider, FakeClient]:
    # Unit tests exercise provider parsing in isolation.  Production
    # construction is always lease-enforced by default.
    provider = LlamaCppQwen38VisionProvider(api_key="test-key", require_model_lease=False)
    client = FakeClient(completion)
    provider.client = client
    return provider, client


def test_qwen38_refuses_an_unleased_inference_call_before_http() -> None:
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
        "usage": {},
    }
    provider = LlamaCppQwen38VisionProvider(
        api_key="test-key",
    )
    client = FakeClient(completion)
    provider.client = client

    with pytest.raises(RuntimeError, match="lease is required"):
        provider.transcribe_image(
            image_bytes=b"\x89PNG\r\n\x1a\nimage",
            mime_type="image/png",
            label="1(a)",
        )

    assert client.requests == []


def test_qwen38_rejects_a_nontext_system_prompt_before_http() -> None:
    provider, client = provider_with(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"draft_text":"","uncertain_glyphs":[],"is_blank":true,'
                            '"is_irrelevant":false,"confidence":1.0,"needs_review":true}'
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="system prompt content must be plain text"):
        provider._structured_completion(
            messages=[{"role": "system", "content": []}],
            response_model=_Qwen38TranscriptionPayload,
            schema_name="invalid",
        )

    assert client.requests == []


def test_configured_qwen38_adapter_enforces_the_provider_lease_guard() -> None:
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN38_ENABLED=True,
        LOCAL_QWEN38_API_KEY="key-local-test",
        LOCAL_QWEN38_MODEL="qwen3.8-27b-q4km",
    )

    adapter = BrainAdapter.for_provider(settings, "llama_cpp_qwen38")

    assert isinstance(adapter.provider, LlamaCppQwen38VisionProvider)
    assert adapter.provider.require_model_lease is True


def test_qwen38_model_check_refuses_an_invalid_api_key() -> None:
    provider = LlamaCppQwen38VisionProvider(api_key="test-key", require_model_lease=False)
    provider.client = AuthFailClient({})

    with pytest.raises(RuntimeError, match="API-key authentication failed"):
        provider.verify_available_model()


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
    assert "response_format" not in client.requests[0]
    assert client.requests[0]["messages"][0]["role"] == "system"
    assert "exactly one JSON object" in client.requests[0]["messages"][0]["content"]
    with pytest.raises(ValueError, match="magic"):
        provider.transcribe_image(image_bytes=b"not-an-image", mime_type="image/png")


def test_visual_transcription_keeps_blank_evidence_empty() -> None:
    completion = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"draft_text":"","uncertain_glyphs":[],"is_blank":true,'
                        '"is_irrelevant":false,"confidence":0.95,"needs_review":false}'
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    provider, client = provider_with(completion)

    result = provider.transcribe_image(
        image_bytes=b"\x89PNG\r\n\x1a\nblank", mime_type="image/png", label="1(a)"
    )

    assert result.is_blank is True
    assert result.draft_text == ""
    # The model cannot weaken the mandatory teacher-review gate.
    assert result.needs_review is True
    prompt = client.requests[0]["messages"][1]["content"][0]["text"]
    assert "empty string" in prompt
    assert '"draft_text"' in prompt


def test_reference_bundle_uses_a_bounded_nonthinking_response() -> None:
    completion = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "questions": [
                                {
                                    "question_number": "1",
                                    "parent_question_number": None,
                                    "node_type": "question",
                                    "question_text": "Find x.",
                                    "model_answer": "x = 4",
                                    "marks": 2,
                                    "source_question_pages": [1],
                                    "source_solution_pages": [1],
                                    "source_text_excerpt": "Find x.",
                                    "confidence": 0.9,
                                    "criteria": [
                                        {
                                            "criterion_label": "Answer",
                                            "description": "States x = 4.",
                                            "max_marks": 2,
                                            "confidence": 0.9,
                                            "source_rubric_pages": [1],
                                            "blocker": None,
                                        }
                                    ],
                                    "blockers": [],
                                    "needs_review": True,
                                }
                            ],
                            "warnings": [],
                        }
                    )
                }
            }
        ],
        "usage": {},
    }
    provider, client = provider_with(completion)
    image = b"\x89PNG\r\n\x1a\nimage"

    provider.extract_reference_bundle_from_images(
        documents={
            "QUESTION": [(image, "image/png", 1)],
            "SOLUTION": [(image, "image/png", 1)],
            "RUBRIC": [(image, "image/png", 1)],
        }
    )

    request = client.requests[0]
    # 3 total pages (1 QUESTION + 1 SOLUTION + 1 RUBRIC): base 1500 + 1000/page.
    assert request["max_tokens"] == 4500
    assert request["chat_template_kwargs"] == {
        "enable_thinking": False,
        "preserve_thinking": False,
    }


def test_reference_bundle_token_budget_scales_with_page_count() -> None:
    provider = LlamaCppQwen38VisionProvider(api_key="test-key")
    # Small bundle: content-need-bound, well under the context ceiling.
    assert provider._reference_bundle_token_budget(1) == 2500
    assert provider._reference_bundle_token_budget(3) == 4500
    # Large bundle: context-room-bound, clamped below the raw content-need formula.
    budget_at_7_pages = provider._reference_bundle_token_budget(7)
    assert budget_at_7_pages < 1500 + 1000 * 7
    assert budget_at_7_pages >= 1500


def test_reference_bundle_refuses_when_context_cannot_hold_a_useful_reply() -> None:
    provider = LlamaCppQwen38VisionProvider(api_key="test-key")
    with pytest.raises(ValueError, match="too little room"):
        provider._reference_bundle_token_budget(9)


def test_reference_bundle_truncation_reports_a_clear_actionable_error() -> None:
    completion = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": '{"questions": [{"question_number": "1"'},
            }
        ],
        "usage": {"prompt_tokens": 4000, "completion_tokens": 1500},
    }
    provider, _client = provider_with(completion)
    image = b"\x89PNG\r\n\x1a\nimage"

    with pytest.raises(ValueError, match="cut off before finishing") as caught:
        provider.extract_reference_bundle_from_images(
            documents={
                "QUESTION": [(image, "image/png", 1)],
                "SOLUTION": [(image, "image/png", 1)],
                "RUBRIC": [(image, "image/png", 1)],
            }
        )
    # Names both causes and quotes the output, because "needs a larger budget"
    # alone pointed the wrong way on a looping response once already.
    message = str(caught.value)
    assert "budget is too small" in message
    assert "repeated until it ran out" in message
    assert "question_number" in message


def test_page_mapping_token_budget_scales_with_label_count() -> None:
    provider = LlamaCppQwen38VisionProvider(api_key="test-key")
    # Few labels: held at the floor rather than dropping below what already worked.
    assert provider._page_mapping_token_budget(1) == 900
    assert provider._page_mapping_token_budget(2) == 900
    # The 7-label paper that was truncated at a flat 900 now gets real headroom.
    assert provider._page_mapping_token_budget(7) == 1040
    assert provider._page_mapping_token_budget(20) == 2600
    # Ceiling-bound, never unbounded.
    assert provider._page_mapping_token_budget(200) == 4000


def test_page_mapping_request_carries_the_scaled_budget() -> None:
    completion = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"regions": [], "needs_review": true}'},
            }
        ],
        "usage": {"prompt_tokens": 1577, "completion_tokens": 12},
    }
    provider, client = provider_with(completion)

    provider.map_page_answer_regions(
        image_bytes=b"\x89PNG\r\n\x1a\nimage",
        mime_type="image/png",
        question_labels=[
            "1(a)(i)",
            "1(a)(ii)",
            "1(b)(i)",
            "1(b)(ii)",
            "1(c)(i)",
            "1(c)(ii)",
            "1(c)(iii)",
        ],
    )

    # The real failure on assessment 61: 7 labels against a flat 900.
    assert client.requests[0]["max_tokens"] == 1040
    assert client.requests[0]["chat_template_kwargs"]["enable_thinking"] is False


def test_page_mapping_uses_question_identity_without_grading_student_work() -> None:
    completion = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"regions": [], "needs_review": true}'},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 12},
    }
    provider, client = provider_with(completion)

    provider.map_page_answer_regions(
        image_bytes=b"\x89PNG\r\n\x1a\nimage",
        mime_type="image/png",
        question_labels=["1(a)(i)"],
        question_references=[
            {
                "question_no": "1(a)(i)",
                "question_text": "Find the conditional probability.",
                "model_answer": "0.38",
                "rubric": {"secret": "must not enter mapping"},
            }
        ],
    )

    prompt = client.requests[0]["messages"][1]["content"][0]["text"]
    assert "Find the conditional probability." in prompt
    assert "judge correctness" in prompt
    assert "Wrong, partial, irrelevant" in prompt
    assert "0.38" not in prompt
    assert "rubric" not in prompt.casefold()


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
    provider, client = provider_with(completion)
    with pytest.raises(ValueError, match="maximum score"):
        provider.grade(
            question_text="Solve x.",
            question_total_marks=Decimal("2"),
            rubric_json={"criteria": [{"id": "c1", "max_marks": "3"}]},
            answer_image_path="[image input disabled]",
            student_answer_text="x = 4",
            prompt_version="test",
            messages=[
                {"role": "system", "content": "grade safely"},
                {"role": "user", "content": "fresh"},
            ],
        )

    assert [message["role"] for message in client.requests[0]["messages"]] == [
        "system",
        "user",
    ]
    assert "Return exactly one JSON object" in client.requests[0]["messages"][0]["content"]


def test_every_call_sends_a_repetition_penalty() -> None:
    """Regression: greedy decoding looped until the token cap on a real page.

    A handwritten rubric produced "10/10\\n10/10\\n10/10..." until it exhausted
    2048 tokens -- 325 seconds, unparseable JSON. The same page with this
    penalty returned correct complete output in 44 seconds using 296 tokens.

    The failure presented as "needs a larger token budget", which it did not.
    Without this the pipeline fails on exactly the hard pages it exists to read.
    """
    completion = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "draft_text": "P(X) = 7/12",
                            "uncertain_glyphs": [],
                            "is_blank": False,
                            "is_irrelevant": False,
                            "confidence": 0.9,
                            "needs_review": True,
                        }
                    )
                }
            }
        ],
        "usage": {},
    }
    provider, client = provider_with(completion)

    provider.transcribe_image(
        image_bytes=b"\x89PNG\r\n\x1a\nimage", mime_type="image/png"
    )

    request = client.requests[0]
    assert request["repeat_penalty"] > 1.0


def test_a_markdown_fenced_json_response_is_still_parsed() -> None:
    """Regression: three backticks discarded a correct transcription.

    The system prompt asks for a bare JSON object with "no Markdown fence" and
    the model wraps it in ```json regardless. Reference extraction failed with
    "not valid JSON at char 0" while the transcription inside was complete and
    correct. An instruction is a request, not a constraint.
    """
    payload = {
        "draft_text": "P(X) = 7/12",
        "uncertain_glyphs": [],
        "is_blank": False,
        "is_irrelevant": False,
        "confidence": 0.9,
        "needs_review": True,
    }
    completion = {
        "choices": [{"message": {"content": "```json\n" + json.dumps(payload) + "\n```"}}],
        "usage": {},
    }
    provider, _client = provider_with(completion)

    result = provider.transcribe_image(
        image_bytes=b"\x89PNG\r\n\x1a\nimage", mime_type="image/png"
    )

    assert result.draft_text == "P(X) = 7/12"


def test_an_unfenced_json_response_is_unaffected() -> None:
    payload = {
        "draft_text": "x = 4",
        "uncertain_glyphs": [],
        "is_blank": False,
        "is_irrelevant": False,
        "confidence": 0.9,
        "needs_review": True,
    }
    completion = {"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {}}
    provider, _client = provider_with(completion)

    result = provider.transcribe_image(
        image_bytes=b"\x89PNG\r\n\x1a\nimage", mime_type="image/png"
    )

    assert result.draft_text == "x = 4"
