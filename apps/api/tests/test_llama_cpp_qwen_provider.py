import json
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.llama_cpp_qwen_provider import LlamaCppQwenProvider


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(
        self,
        completion: dict[str, Any],
        *,
        models: list[str] | None = None,
    ) -> None:
        self.completion = completion
        self.models = models or ["qwen3.6-35b-a3b-q4km"]
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((path, kwargs))
        return FakeResponse({"data": [{"id": model} for model in self.models]})

    def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((path, kwargs))
        return FakeResponse(self.completion)


def rubric() -> dict[str, Any]:
    return {
        "total_marks": "10.00",
        "criteria": [
            {
                "id": "concept",
                "name": "Concept",
                "description": "Correct concept",
                "max_marks": "6.00",
            },
            {
                "id": "working",
                "name": "Working",
                "description": "Valid working",
                "max_marks": "4.00",
            },
        ],
    }


def valid_completion() -> dict[str, Any]:
    content = {
        "score": "7.00",
        "max_score": "10.00",
        "confidence": "0.70",
        "needs_review": True,
        "rubric_breakdown": [
            {
                "criterion_id": "concept",
                "criterion": "Concept",
                "max_marks": "6.00",
                "awarded_marks": "5.00",
                "reason": "Mostly correct",
                "evidence": "Teacher-confirmed text",
                "confidence": "0.70",
            },
            {
                "criterion_id": "working",
                "criterion": "Working",
                "max_marks": "4.00",
                "awarded_marks": "2.00",
                "reason": "Some working",
                "evidence": "Teacher-confirmed text",
                "confidence": "0.65",
            },
        ],
        "detected_answer_summary": "A mostly correct answer.",
        "major_errors": [],
        "feedback_to_student": "Show the final step.",
        "review_flags": ["teacher_review_required"],
    }
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
        },
    }


def make_provider(client: FakeClient) -> LlamaCppQwenProvider:
    return LlamaCppQwenProvider(
        api_key="key-local-secret",
        model_name="qwen3.6-35b-a3b-q4km",
        base_url="http://127.0.0.1:8080/v1",
        client=client,
    )


def test_qwen_provider_verifies_alias_and_returns_strict_text_only_draft() -> None:
    client = FakeClient(valid_completion())
    provider = make_provider(client)

    result = provider.grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric(),
        answer_image_path="private/path.png",
        student_answer_text="Teacher-confirmed answer.",
        prompt_version="real-grading-v1",
        messages=[{"role": "user", "content": "Grade the confirmed text."}],
    )

    assert result.score == Decimal("7.00")
    assert result.model_provider == "llama_cpp_qwen"
    assert result.model_name == "qwen3.6-35b-a3b-q4km"
    assert result.cost_estimate == Decimal("0")
    assert result.total_tokens == 200
    assert {"teacher_review_required", "image_input_disabled", "local_provider"} <= set(
        result.review_flags
    )
    assert client.get_calls[0][0] == "models"
    request = client.post_calls[0][1]["json"]
    assert request["model"] == "qwen3.6-35b-a3b-q4km"
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["response_format"]["type"] == "json_schema"
    wire_schema = json.dumps(request["response_format"]["json_schema"]["schema"])
    assert "\\\\d" not in wire_schema
    assert '"type": "number"' in wire_schema
    assert "private/path.png" not in json.dumps(request)


def test_qwen_adapter_does_not_send_the_answer_image_path() -> None:
    client = FakeClient(valid_completion())
    adapter = BrainAdapter(make_provider(client), image_input_enabled=False)

    adapter.grade_answer_region(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric(),
        answer_image_path="private/student/path.png",
        student_answer_text="Teacher-confirmed answer.",
    )

    request = client.post_calls[0][1]["json"]
    serialized = json.dumps(request)
    assert "private/student/path.png" not in serialized
    assert "Teacher-confirmed answer." in serialized


def test_qwen_provider_refuses_model_alias_mismatch_before_completion() -> None:
    client = FakeClient(valid_completion(), models=["different-model"])

    with pytest.raises(RuntimeError, match="model alias mismatch"):
        make_provider(client).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric(),
            answer_image_path="unused.png",
            student_answer_text="Confirmed.",
            prompt_version="real-grading-v1",
            messages=[],
        )

    assert client.post_calls == []


def test_qwen_provider_rejects_malformed_or_contract_changing_output() -> None:
    malformed = FakeClient({"choices": [{"message": {"content": "not-json"}}]})
    with pytest.raises(ValueError, match="invalid structured output"):
        make_provider(malformed).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric(),
            answer_image_path="unused.png",
            student_answer_text="Confirmed.",
            prompt_version="real-grading-v1",
            messages=[],
        )

    changed = valid_completion()
    body = json.loads(changed["choices"][0]["message"]["content"])
    body["max_score"] = "11.00"
    changed["choices"][0]["message"]["content"] = json.dumps(body)
    with pytest.raises(ValueError, match="canonical maximum score"):
        make_provider(FakeClient(changed)).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric(),
            answer_image_path="unused.png",
            student_answer_text="Confirmed.",
            prompt_version="real-grading-v1",
            messages=[],
        )


def test_qwen_adapter_requires_all_local_provider_switches() -> None:
    disabled = Settings(
        BRAIN_PROVIDER="llama_cpp_qwen",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN_ENABLED=False,
        LOCAL_QWEN_API_KEY="key-local-secret",
    )
    with pytest.raises(BrainProviderConfigurationError, match="LOCAL_QWEN_ENABLED"):
        BrainAdapter.from_settings(disabled)

    missing_key = Settings(
        BRAIN_PROVIDER="llama_cpp_qwen",
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN_ENABLED=True,
        LOCAL_QWEN_API_KEY="",
    )
    with pytest.raises(BrainProviderConfigurationError, match="LOCAL_QWEN_API_KEY"):
        BrainAdapter.from_settings(missing_key)
