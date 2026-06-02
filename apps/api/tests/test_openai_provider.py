from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.mock_provider import MockBrainProvider
from packages.brain.openai_provider import OpenAICompatibleProvider
from packages.brain.prompt_registry import build_grading_prompt, get_prompt_version
from packages.brain.schemas import ModelPolicy


def rubric_payload() -> dict[str, object]:
    return {
        "total_marks": "10.00",
        "model_answer": "A complete answer explains the core concept and shows valid working.",
        "criteria": [
            {
                "id": "concept",
                "name": "Core concept",
                "description": "Identifies the correct principle or idea.",
                "max_marks": "4.00",
            },
            {
                "id": "working",
                "name": "Working",
                "description": "Shows valid working.",
                "max_marks": "6.00",
            },
        ],
    }


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeOpenAIClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


def valid_openai_payload() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": """
                    {
                      "score": 3,
                      "max_score": 10,
                      "confidence": 0.42,
                      "needs_review": true,
                      "rubric_breakdown": [
                        {
                          "criterion_id": "concept",
                          "criterion": "Core concept",
                          "max_marks": 4,
                          "awarded_marks": 2,
                          "reason": "Partial conceptual match in provided text.",
                          "evidence": null,
                          "confidence": 0.4
                        },
                        {
                          "criterion_id": "working",
                          "criterion": "Working",
                          "max_marks": 6,
                          "awarded_marks": 1,
                          "reason": "Limited working shown in provided text.",
                          "evidence": null,
                          "confidence": 0.4
                        }
                      ],
                      "detected_answer_summary": "Text-only provider suggestion.",
                      "major_errors": ["Incomplete working"],
                      "feedback_to_student": "Add complete reasoning.",
                      "review_flags": ["teacher_review_required"]
                    }
                    """
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def test_adapter_uses_mock_provider_by_default_without_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(BRAIN_PROVIDER="mock", OPENAI_API_KEY="")

    adapter = BrainAdapter.from_settings(settings)

    assert isinstance(adapter.provider, MockBrainProvider)
    result = adapter.grade_answer_region(
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
    )
    assert result.model_provider == "mock"


def test_openai_provider_requires_api_key() -> None:
    settings = Settings(BRAIN_PROVIDER="openai", OPENAI_API_KEY="", OPENAI_MODEL="gpt-test")

    with pytest.raises(BrainProviderConfigurationError, match="OPENAI_API_KEY is required"):
        BrainAdapter.from_settings(settings)


def test_openai_provider_mocked_response_validates_to_grade_suggestion() -> None:
    client = FakeOpenAIClient(valid_openai_payload())
    provider = OpenAICompatibleProvider(
        api_key="sk-test-secret",
        model_name="gpt-test",
        base_url="https://example.test/v1",
        client=client,
    )

    grading_prompt = build_grading_prompt(
        question_text="Explain the concept.",
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        image_input_enabled=False,
    )
    assert "Marking policy: general" in grading_prompt[1]["content"]
    assert "General marking" in grading_prompt[1]["content"]
    assert "Apply the rubric criterion-by-criterion" in grading_prompt[1]["content"]
    assert "Return strict JSON" in grading_prompt[1]["content"]
    assert "teacher_review_required" in grading_prompt[1]["content"]
    assert "active rubric and model answer as primary evidence" in grading_prompt[1]["content"]
    assert "formula choice, substitution, and valid final answer" in grading_prompt[1]["content"]
    assert "Do not over-penalize messy handwriting" in grading_prompt[1]["content"]

    result = provider.grade(
        task_name="answer_region_grading",
        model_policy=ModelPolicy.REAL_GRADING,
        messages=grading_prompt,
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version=get_prompt_version(ModelPolicy.REAL_GRADING),
    )

    assert result.model_provider == "openai"
    assert result.model_name == "gpt-test"
    assert result.prompt_version == "real-grading-v1"
    assert result.needs_review is True
    assert "teacher_review_required" in result.review_flags
    assert result.score == Decimal("3")
    assert result.cost_estimate >= Decimal("0")
    request = client.requests[0]
    assert request["url"] == "/chat/completions"
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer sk-test-secret"


def test_openai_provider_without_image_input_does_not_include_image_payload() -> None:
    client = FakeOpenAIClient(valid_openai_payload())
    provider = OpenAICompatibleProvider(
        api_key="sk-test-secret",
        model_name="gpt-test",
        base_url="https://example.test/v1",
        client=client,
    )

    result = provider.grade(
        task_name="answer_region_grading",
        model_policy=ModelPolicy.REAL_GRADING,
        messages=build_grading_prompt(
            question_text="Explain the concept.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            image_input_enabled=False,
        ),
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version=get_prompt_version(ModelPolicy.REAL_GRADING),
        image_data_url=None,
    )

    request_json = client.requests[0]["json"]
    assert "data:image" not in str(request_json)
    assert "image_input_disabled" in result.review_flags


def test_openai_provider_with_image_input_includes_data_url_payload() -> None:
    client = FakeOpenAIClient(valid_openai_payload())
    provider = OpenAICompatibleProvider(
        api_key="sk-test-secret",
        model_name="gpt-test",
        base_url="https://example.test/v1",
        client=client,
    )

    result = provider.grade(
        task_name="answer_region_grading",
        model_policy=ModelPolicy.REAL_GRADING,
        messages=build_grading_prompt(
            question_text="Explain the concept.",
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            image_input_enabled=True,
        ),
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version=get_prompt_version(ModelPolicy.REAL_GRADING),
        image_data_url="data:image/png;base64,ZmFrZS1wbmc=",
    )

    request_json = client.requests[0]["json"]
    assert "data:image/png;base64,ZmFrZS1wbmc=" in str(request_json)
    assert "image_input_used" in result.review_flags
    assert result.needs_review is True


def test_adapter_image_enabled_missing_path_fails_safely(tmp_path) -> None:
    adapter = BrainAdapter(
        OpenAICompatibleProvider(
            api_key="sk-test-secret",
            model_name="gpt-test",
            client=FakeOpenAIClient(valid_openai_payload()),
        ),
        image_input_enabled=True,
        storage_root=tmp_path,
    )

    with pytest.raises(
        RuntimeError, match="Image input enabled but cropped answer image is missing"
    ):
        adapter.grade_answer_region(
            question_text="Explain the concept.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/missing.png",
        )


def test_openai_provider_rejects_invalid_structured_output() -> None:
    client = FakeOpenAIClient(
        {"choices": [{"message": {"content": '{"score": 999, "max_score": 10}'}}]}
    )
    provider = OpenAICompatibleProvider(
        api_key="sk-test-secret",
        model_name="gpt-test",
        base_url="https://example.test/v1",
        client=client,
    )

    with pytest.raises(ValidationError):
        provider.grade(
            task_name="answer_region_grading",
            model_policy=ModelPolicy.REAL_GRADING,
            messages=[],
            question_text="Explain the concept.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version=get_prompt_version(ModelPolicy.REAL_GRADING),
        )


def test_sanitized_provider_error_does_not_expose_api_key() -> None:
    secret = "sk-live-should-not-appear"
    provider = OpenAICompatibleProvider(
        api_key=secret,
        model_name="gpt-test",
        base_url="https://example.test/v1",
        client=SimpleNamespace(
            post=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(secret))
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        provider.grade(
            task_name="answer_region_grading",
            model_policy=ModelPolicy.REAL_GRADING,
            messages=[],
            question_text="Explain the concept.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version=get_prompt_version(ModelPolicy.REAL_GRADING),
        )

    assert secret not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)
