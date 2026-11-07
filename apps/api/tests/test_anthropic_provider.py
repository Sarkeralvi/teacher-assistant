"""Contract tests for the Claude (Anthropic API) provider.

No network: every test drives the provider through a fake SDK client that
records the exact request parameters and returns a scripted message.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.anthropic_provider import (
    MAX_IMAGE_LONG_EDGE_PX,
    MAX_IMAGE_PIXELS,
    REFUSAL_FALLBACK_BETA,
    AnthropicApiProvider,
    AnthropicPricing,
    AnthropicProviderError,
    claude_json_schema,
    prepare_image_for_claude,
    register_call_observer,
)
from packages.brain.capabilities import BrainCapability, BrainExecutionLocation
from packages.brain.policy import brain_policy_from_settings
from packages.brain.prompt_registry import build_grading_prompt
from packages.brain.schemas_qwen38 import VisualPageTranscriptOutput
from packages.brain.transcript_assignment import FullTranscriptAssignmentOutput

MODEL = "claude-opus-5-5"


# ---------------------------------------------------------------------------
# Fake SDK
# ---------------------------------------------------------------------------


def _message(
    payload: dict[str, Any] | str,
    *,
    model: str = MODEL,
    stop_reason: str = "end_turn",
    input_tokens: int = 1200,
    output_tokens: int = 300,
    category: str | None = None,
) -> SimpleNamespace:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        model=model,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        _request_id="req_test_123",
    )


class _Stream:
    def __init__(self, message: SimpleNamespace, events: int = 2) -> None:
        self._message = message
        self._events = events
        self.closed = False

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.closed = True
        return None

    def __iter__(self):
        for index in range(self._events):
            yield SimpleNamespace(type="ping", index=index)

    def get_final_message(self) -> SimpleNamespace:
        return self._message


class _Messages:
    def __init__(self, owner: FakeClient, *, beta: bool) -> None:
        self._owner = owner
        self._beta = beta

    def stream(self, **params: Any) -> _Stream:
        self._owner.calls.append({"beta": self._beta, **params})
        return _Stream(self._owner.replies.pop(0))


class FakeClient:
    def __init__(self, *replies: SimpleNamespace) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.messages = _Messages(self, beta=False)
        self.beta = SimpleNamespace(messages=_Messages(self, beta=True))
        self.models = SimpleNamespace(retrieve=lambda model_id: SimpleNamespace(id=model_id))


def _provider(*replies: SimpleNamespace, **kwargs: Any) -> tuple[AnthropicApiProvider, FakeClient]:
    client = FakeClient(*replies)
    return AnthropicApiProvider(model_name=MODEL, client=client, **kwargs), client


def _png(width: int = 40, height: int = 60) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", (width, height), color=255).save(buffer, format="PNG")
    return buffer.getvalue()


def _page_read_payload() -> dict[str, Any]:
    return {
        "blocks": [
            {
                "question_label": "1(a)",
                "bbox": [10, 10, 990, 400],
                "text": "x = 2",
                "continues_from_previous": False,
                "label_source": "heading",
                "confidence": 0.93,
            }
        ],
        "is_blank_page": False,
        "needs_review": True,
    }


def _grade_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "score": 3,
        "max_score": 4,
        "confidence": 0.9,
        "needs_review": True,
        "rubric_breakdown": [
            {
                "criterion_id": "c1",
                "criterion": "Correct setup",
                "criterion_status": "met",
                "max_marks": 2,
                "awarded_marks": 2,
                "reason": "Setup shown",
                "evidence": "x = 2",
                "confidence": 0.9,
            },
            {
                "criterion_id": "c2",
                "criterion": "Correct final answer",
                "criterion_status": "partially_met",
                "max_marks": 2,
                "awarded_marks": 1,
                "reason": "Arithmetic slip",
                "evidence": "y = 5",
                "confidence": 0.8,
            },
        ],
        "detected_answer_summary": "Solved for x, slipped on y.",
        "major_errors": ["arithmetic slip"],
        "feedback_to_student": "Check the final arithmetic.",
        "review_flags": [],
    }
    payload.update(overrides)
    return payload


def _grading_messages() -> list[dict[str, str]]:
    return build_grading_prompt(
        question_text="Solve the system.",
        rubric_json={
            "criteria": [
                {"id": "c1", "name": "Correct setup", "max_marks": 2},
                {"id": "c2", "name": "Correct final answer", "max_marks": 2},
            ],
            "model_answer": "x = 2, y = 4",
        },
        answer_image_path="[stored transcript evidence; image input disabled]",
        image_input_enabled=False,
        student_answer_text="x = 2\ny = 5",
    )


def _grade(provider: AnthropicApiProvider) -> Any:
    return provider.grade(
        question_text="Solve the system.",
        question_total_marks=Decimal("4"),
        rubric_json={},
        answer_image_path="[stored transcript evidence; image input disabled]",
        prompt_version="real-grading-v3",
        student_answer_text="x = 2\ny = 5",
        messages=_grading_messages(),
    )


# ---------------------------------------------------------------------------
# Schema and image preparation
# ---------------------------------------------------------------------------


_UNSUPPORTED = {
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "default",
    "title",
}


def _schema_nodes(node: Any):
    """Yield every subschema, skipping the name->schema mappings themselves."""

    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for subschema in value.values():
                    yield from _schema_nodes(subschema)
            else:
                yield from _schema_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_nodes(item)


def test_schema_is_closed_and_free_of_unsupported_constraints() -> None:
    from packages.brain.anthropic_provider import _AnthropicGradeSuggestionDraft
    from packages.brain.llama_cpp_qwen_provider import QwenReferenceBundlePayload
    from packages.brain.schemas_qwen38 import VisualPageMappingOutput
    from packages.brain.universal_vision import _VisualTranscriptionDraft

    for model in (
        VisualPageTranscriptOutput,
        VisualPageMappingOutput,
        _VisualTranscriptionDraft,
        FullTranscriptAssignmentOutput,
        QwenReferenceBundlePayload,
        _AnthropicGradeSuggestionDraft,
    ):
        schema = claude_json_schema(model)
        nodes = list(_schema_nodes(schema))
        assert len(nodes) > 3
        for node in nodes:
            assert not (_UNSUPPORTED & set(node)), (model.__name__, sorted(node))
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False


def test_schema_keeps_property_names_that_look_like_keywords() -> None:
    class Odd(BaseModel):
        model_config = ConfigDict(extra="forbid")
        title: str
        default: int

    schema = claude_json_schema(Odd)
    assert set(schema["properties"]) == {"title", "default"}
    assert schema["required"] == ["title", "default"]


def test_schema_refuses_free_form_objects() -> None:
    class FreeForm(BaseModel):
        data: dict[str, Any]

    with pytest.raises(ValueError, match="closed objects"):
        claude_json_schema(FreeForm)


def test_large_image_is_downscaled_inside_claude_limits() -> None:
    prepared, media_type = prepare_image_for_claude(_png(4000, 3000), "image/png")
    with Image.open(io.BytesIO(prepared)) as image:
        width, height = image.size
    assert max(width, height) <= MAX_IMAGE_LONG_EDGE_PX
    assert width * height <= MAX_IMAGE_PIXELS
    assert media_type in {"image/png", "image/jpeg"}


def test_small_supported_image_passes_through_unchanged() -> None:
    original = _png()
    prepared, media_type = prepare_image_for_claude(original, "image/png")
    assert prepared == original
    assert media_type == "image/png"


def test_undecodable_image_fails_closed() -> None:
    with pytest.raises(ValueError, match="could not be decoded"):
        prepare_image_for_claude(b"not an image", "image/png")


# ---------------------------------------------------------------------------
# Page read: the blind evidence pass
# ---------------------------------------------------------------------------


def test_page_read_request_is_blind_structured_and_sampling_free() -> None:
    provider, client = _provider(_message(_page_read_payload()))
    output = provider.read_page(
        image_bytes=_png(),
        mime_type="image/png",
        question_labels=["1(a)"],
        question_references=[
            {
                "question_no": "1(a)",
                "question_text": "Find x.",
                "model_answer": "SECRET-SOLUTION-TEXT",
                "rubric": "SECRET-RUBRIC-TEXT",
                "marks": "SECRET-MARKS-7",
            }
        ],
    )
    assert output.blocks[0].text == "x = 2"
    assert output.needs_review is True
    (call,) = client.calls
    assert call["beta"] is False
    assert call["model"] == MODEL
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(call)
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[-1]["type"] == "text"
    sent_text = json.dumps(call, default=str)
    for secret in ("SECRET-SOLUTION-TEXT", "SECRET-RUBRIC-TEXT", "SECRET-MARKS-7"):
        assert secret not in sent_text


@pytest.mark.parametrize(
    ("stop_reason", "match"),
    [("refusal", "declined"), ("max_tokens", "max_tokens"), ("pause_turn", "unexpected")],
)
def test_incomplete_or_declined_responses_fail_closed(stop_reason: str, match: str) -> None:
    provider, _client = _provider(
        _message(_page_read_payload(), stop_reason=stop_reason, category="other")
    )
    with pytest.raises(AnthropicProviderError, match=match):
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])


def test_substituted_model_fails_closed_for_evidence_tasks() -> None:
    provider, _client = _provider(_message(_page_read_payload(), model="claude-sonnet-5-5"))
    with pytest.raises(AnthropicProviderError, match="served by claude-sonnet-5-5"):
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])


def test_dated_snapshot_of_configured_model_is_accepted() -> None:
    provider, _client = _provider(_message(_page_read_payload(), model=f"{MODEL}-20261101"))
    output = provider.read_page(
        image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"]
    )
    assert output.blocks


@pytest.mark.parametrize("served", [f"{MODEL}-unexpected", f"{MODEL}-mini", f"{MODEL}2"])
def test_other_suffixes_count_as_substitution(served: str) -> None:
    provider, _client = _provider(_message(_page_read_payload(), model=served))
    with pytest.raises(AnthropicProviderError, match="served by"):
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])


def test_a_stream_past_its_wall_clock_deadline_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import packages.brain.anthropic_provider as provider_module

    ticks = iter([0.0, 10.0, 999.0, 1999.0, 2999.0])
    monkeypatch.setattr(provider_module.time, "monotonic", lambda: next(ticks))
    client = FakeClient(_message(_page_read_payload()))
    stream = _Stream(client.replies[0], events=5)
    client.messages.stream = lambda **params: stream
    provider = AnthropicApiProvider(model_name=MODEL, client=client, call_deadline_seconds=900)
    with pytest.raises(AnthropicProviderError, match="deadline"):
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])
    assert stream.closed


def test_call_settings_must_fit_inside_a_worker_job() -> None:
    with pytest.raises(ValueError, match="worker job"):
        AnthropicApiProvider(
            model_name=MODEL,
            client=FakeClient(),
            timeout_seconds=1200,
            call_deadline_seconds=1500,
            max_retries=2,
        )
    provider = AnthropicApiProvider(model_name=MODEL, client=FakeClient())
    assert provider.timeout_seconds <= 3540


def test_contract_failures_do_not_chain_student_text() -> None:
    payload = _page_read_payload()
    payload["blocks"][0]["confidence"] = "STUDENT-WROTE-THIS-SECRET"
    provider, _client = _provider(_message(payload))
    with pytest.raises(AnthropicProviderError) as raised:
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])
    assert "STUDENT-WROTE-THIS-SECRET" not in str(raised.value)
    # Nothing that echoes the response is attached for a traceback to print.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None or raised.value.__suppress_context__


def test_spend_guard_refuses_before_anything_is_sent() -> None:
    from packages.brain.anthropic_provider import SpendLimitReached, register_spend_guard

    def refuse(task: str) -> None:
        raise SpendLimitReached(f"cap reached before {task}")

    provider, client = _provider(_message(_page_read_payload()))
    unregister = register_spend_guard(refuse)
    try:
        with pytest.raises(SpendLimitReached, match="visual_page_read"):
            provider.read_page(
                image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"]
            )
    finally:
        unregister()
    assert client.calls == []


def test_invalid_page_geometry_keeps_text_in_review() -> None:
    payload = _page_read_payload()
    payload["blocks"][0]["bbox"] = [900, 10, 100, 400]
    provider, _client = _provider(_message(payload))
    output = provider.read_page(
        image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"]
    )
    assert output.blocks[0].bbox == [0, 0, 1000, 1000]
    assert output.blocks[0].confidence <= Decimal("0.49")


# ---------------------------------------------------------------------------
# Transcript assignment (text only)
# ---------------------------------------------------------------------------


def test_assignment_is_text_only_and_validated() -> None:
    pages = [{"page": 1, "blocks": [{"order": 1, "text": "x = 2"}]}]
    questions = [{"question_id": 7, "question_no": "1(a)", "question_text": "Find x."}]
    reply = {
        "contract_version": "full-transcript-assignment-v4",
        "mappings": [
            {
                "question_id": 7,
                "question_no": "1(a)",
                "status": "mapped",
                "block_references": [{"page_no": 1, "block_orders": [1]}],
                "confidence": 0.95,
                "warnings": [],
                "needs_review": True,
            }
        ],
        "unassigned_block_references": [],
        "non_answer_block_references": [],
        "warnings": [],
    }
    provider, client = _provider(_message(reply))
    result = provider.map_submission_answers_from_ocr_pages(pages=pages, questions=questions)
    assert result["mappings"][0]["status"] == "mapped"
    (call,) = client.calls
    assert isinstance(call["messages"][0]["content"], str)
    assert call["output_config"]["effort"] == "medium"


# ---------------------------------------------------------------------------
# Grading (text only, fallback allowed but flagged)
# ---------------------------------------------------------------------------


def test_grading_is_text_only_uses_refusal_fallback_and_records_cost() -> None:
    provider, client = _provider(_message(_grade_payload(), input_tokens=2000, output_tokens=500))
    output = _grade(provider)
    (call,) = client.calls
    assert call["beta"] is True
    assert call["betas"] == [REFUSAL_FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert call["output_config"]["effort"] == "high"
    assert isinstance(call["messages"][0]["content"], str)
    assert "teacher_confirmed_student_answer" in call["messages"][0]["content"]
    assert call["system"].startswith("You are a grading assistant")
    assert output.score == Decimal("3")
    assert output.needs_review is True
    assert {"teacher_review_required", "anthropic_api_provider"} <= set(output.review_flags)
    assert output.cost_estimate == AnthropicPricing().cost(input_tokens=2000, output_tokens=500)
    assert output.prompt_tokens == 2000
    assert output.completion_tokens == 500
    assert output.model_provider == "anthropic"


def test_grading_served_by_fallback_model_is_flagged_and_capped() -> None:
    records: list[dict[str, Any]] = []
    unregister = register_call_observer(records.append)
    try:
        provider, _client = _provider(_message(_grade_payload(), model="claude-opus-5"))
        output = _grade(provider)
    finally:
        unregister()
    assert "served_by_fallback_model:claude-opus-5" in output.review_flags
    assert output.confidence <= Decimal("0.5")
    assert output.model_name == "claude-opus-5"
    assert records[-1]["fallback_served"] is True


def test_mid_stream_fallback_continuation_is_read_as_one_answer() -> None:
    text = json.dumps(_grade_payload())
    cut = len(text) // 2
    message = _message(text, model="claude-opus-5")
    message.content = [
        SimpleNamespace(type="text", text=text[:cut]),
        SimpleNamespace(type="fallback", **{"from": {"model": MODEL}}),
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text[cut:]),
    ]
    provider, _client = _provider(message)
    output = _grade(provider)
    assert output.score == Decimal("3")
    assert "served_by_fallback_model:claude-opus-5" in output.review_flags


def test_grading_without_fallback_rejects_substituted_model() -> None:
    provider, client = _provider(
        _message(_grade_payload(), model="claude-opus-5"), refusal_fallback_enabled=False
    )
    with pytest.raises(AnthropicProviderError, match="served by claude-opus-5"):
        _grade(provider)
    assert client.calls[0]["beta"] is False


def test_grading_zeroes_credit_on_a_criterion_marked_not_met() -> None:
    payload = _grade_payload()
    payload["rubric_breakdown"][1]["criterion_status"] = "not_met"
    provider, _client = _provider(_message(payload))
    output = _grade(provider)
    assert output.rubric_breakdown[1].awarded_marks == Decimal("0")
    assert output.score == Decimal("2")
    assert "not_met_criterion_credit_removed" in output.review_flags


def test_grading_refuses_image_input() -> None:
    provider, _client = _provider()
    with pytest.raises(ValueError, match="text-only"):
        provider.grade(
            question_text="q",
            question_total_marks=Decimal("1"),
            rubric_json={},
            answer_image_path="answer.png",
            prompt_version="v",
            messages=_grading_messages(),
            image_data_url="data:image/png;base64,AAAA",
        )


# ---------------------------------------------------------------------------
# Key and model check
# ---------------------------------------------------------------------------


def test_model_check_is_cached_per_key_and_failures_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import packages.brain.anthropic_provider as provider_module

    monkeypatch.setattr(provider_module, "_VERIFIED_MODELS", {})
    lookups: list[str] = []

    def retrieve(model_id: str) -> SimpleNamespace:
        lookups.append(model_id)
        if len(lookups) == 1:
            raise RuntimeError("temporary outage")
        return SimpleNamespace(id=model_id)

    client = FakeClient()
    client.models = SimpleNamespace(retrieve=retrieve)
    provider = AnthropicApiProvider(api_key="key-one", model_name=MODEL, client=client)
    with pytest.raises(AnthropicProviderError, match="temporary outage"):
        provider.verify_available_model()
    provider.verify_available_model()
    provider.verify_available_model()
    assert len(lookups) == 2  # the failure was retried, the success was cached
    other = AnthropicApiProvider(api_key="key-two", model_name=MODEL, client=client)
    other.verify_available_model()
    assert len(lookups) == 3


def test_model_check_rejects_a_different_model() -> None:
    client = FakeClient()
    client.models = SimpleNamespace(retrieve=lambda model_id: SimpleNamespace(id="claude-x"))
    provider = AnthropicApiProvider(api_key="key-three", model_name=MODEL, client=client)
    with pytest.raises(AnthropicProviderError, match="resolved to claude-x"):
        provider.verify_available_model()


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def test_call_observer_gets_metadata_but_never_text() -> None:
    records: list[dict[str, Any]] = []
    unregister = register_call_observer(records.append)
    try:
        provider, _client = _provider(_message(_page_read_payload()))
        provider.read_page(image_bytes=_png(), mime_type="image/png", question_labels=["1(a)"])
    finally:
        unregister()
    (record,) = records
    assert record["task"] == "visual_page_read"
    assert record["model_served"] == MODEL
    assert record["request_id"] == "req_test_123"
    assert record["image_count"] == 1
    assert "x = 2" not in json.dumps(record)


# ---------------------------------------------------------------------------
# Profile wiring
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "BRAIN_PROVIDER": "anthropic",
        "BRAIN_ALLOW_REAL_PROVIDERS": True,
        "ANTHROPIC_ENABLED": True,
        "ANTHROPIC_API_KEY": "test-key-not-real",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_profile_builds_on_both_profile_and_legacy_provider_paths() -> None:
    settings = _settings()
    for adapter in (
        BrainAdapter.for_profile(settings, "anthropic"),
        BrainAdapter.for_provider(settings, "anthropic"),
    ):
        assert isinstance(adapter.provider, AnthropicApiProvider)
        assert adapter.runtime.location is BrainExecutionLocation.CLOUD
        assert adapter.runtime.model == MODEL
        assert adapter.image_input_enabled is False
        for capability in (
            BrainCapability.GRADING,
            BrainCapability.VISUAL_PAGE_READ,
            BrainCapability.OCR_ANSWER_MAPPING,
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
        ):
            assert adapter.supports(capability)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ANTHROPIC_API_KEY": ""},
        {"ANTHROPIC_ENABLED": False},
        {"BRAIN_ALLOW_REAL_PROVIDERS": False},
    ],
)
def test_profile_refuses_to_build_without_every_switch(overrides: dict[str, Any]) -> None:
    with pytest.raises(BrainProviderConfigurationError):
        BrainAdapter.for_profile(_settings(**overrides), "anthropic")


def test_policy_enables_claude_features_and_covers_retries_in_job_timeout() -> None:
    policy = brain_policy_from_settings(_settings())
    assert policy.provider == "anthropic"
    assert policy.page_read_enabled
    assert policy.reference_extraction_enabled
    assert policy.grading_enabled
    assert policy.job_timeout_seconds >= policy.adapter.provider.timeout_seconds


def test_visual_work_never_silently_swaps_the_configured_provider() -> None:
    from packages.brain.policy import configured_visual_provider

    settings = Settings(_env_file=None, BRAIN_PROVIDER="mock", LOCAL_QWEN38_ENABLED=True)
    assert configured_visual_provider(settings) == "mock"
    assert configured_visual_provider(_settings()) == "anthropic"


def test_api_key_is_redacted_from_adapter_errors() -> None:
    settings = _settings(ANTHROPIC_API_KEY="sk-ant-should-never-appear")
    adapter = BrainAdapter.for_profile(settings, "anthropic")
    assert "sk-ant-should-never-appear" not in adapter._sanitize_error(
        "boom sk-ant-should-never-appear"
    )
