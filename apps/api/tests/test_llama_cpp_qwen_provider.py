import json
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.llama_cpp_qwen_provider import (
    LlamaCppQwenProvider,
    _reference_question_number_hints,
)


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
        auth_status_code: int = 200,
    ) -> None:
        self.completion = completion
        self.models = models or ["qwen3.6-35b-a3b-q4km"]
        self.auth_status_code = auth_status_code
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((path, kwargs))
        if path == "../props":
            return FakeResponse({"model_path": "redacted"}, status_code=self.auth_status_code)
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
                "criterion_status": "partially_met",
                "max_marks": "6.00",
                "awarded_marks": "5.00",
                "reason": "Mostly correct",
                "evidence": "Confirmed",
                "confidence": "0.70",
            },
            {
                "criterion_id": "working",
                "criterion": "Working",
                "criterion_status": "partially_met",
                "max_marks": "4.00",
                "awarded_marks": "2.00",
                "reason": "Some working",
                "evidence": "Confirmed",
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


def valid_reference_completion() -> dict[str, Any]:
    content = {
        "questions": [
            {
                "question_number": "1(a)",
                "parent_question_number": "1",
                "node_type": "subquestion",
                "question_text": "Calculate the probability.",
                "model_answer": "Use total probability to obtain 31/120.",
                "marks": "5.00",
                "source_question_pages": [1],
                "source_solution_pages": [1],
                "source_text_excerpt": "Calculate the probability.",
                "confidence": "0.90",
                "criteria": [
                    {
                        "criterion_label": "Method",
                        "description": "Uses total probability.",
                        "max_marks": "3.00",
                        "confidence": "0.90",
                        "source_rubric_pages": [1],
                        "blocker": None,
                    },
                    {
                        "criterion_label": "Answer",
                        "description": "Obtains 31/120.",
                        "max_marks": "2.00",
                        "confidence": "0.90",
                        "source_rubric_pages": [1],
                        "blocker": None,
                    },
                ],
                "blockers": [],
                "needs_review": True,
            }
        ],
        "warnings": [],
    }
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 300, "completion_tokens": 200, "total_tokens": 500},
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
        prompt_version="real-grading-v2",
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
    assert [call[0] for call in client.get_calls] == ["../props", "models"]
    request = client.post_calls[0][1]["json"]
    assert request["model"] == "qwen3.6-35b-a3b-q4km"
    assert request["max_tokens"] == 1600
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


def test_qwen_links_three_ocr_documents_in_one_strict_draft_call() -> None:
    client = FakeClient(valid_reference_completion())
    provider = make_provider(client)

    result = provider.extract_reference_bundle_from_ocr_documents(
        {
            "question_paper": [
                {
                    "page": 1,
                    "text": "QUESTION OCR",
                    "markdown": "DUPLICATED QUESTION MARKDOWN",
                }
            ],
            "solution": [{"page": 1, "text": "SOLUTION OCR"}],
            "rubric": [{"page": 1, "text": "RUBRIC OCR"}],
        }
    )

    assert result["questions"][0]["needs_review"] is True
    assert result["usage"]["total_tokens"] == 500
    assert len(client.post_calls) == 1
    request = client.post_calls[0][1]["json"]
    prompt = json.dumps(request["messages"])
    assert "QUESTION OCR" in prompt
    assert "DUPLICATED QUESTION MARKDOWN" not in prompt
    assert "SOLUTION OCR" in prompt
    assert "RUBRIC OCR" in prompt
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["max_tokens"] == 3500
    schema = request["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["questions"]["maxItems"] == 20
    question_schema = schema["$defs"]["QwenReferenceQuestionDraft"]
    assert "criteria" in question_schema["required"]
    assert question_schema["properties"]["criteria"]["minItems"] == 1
    assert question_schema["properties"]["criteria"]["maxItems"] == 8
    model_answer_options = question_schema["properties"]["model_answer"]["anyOf"]
    assert any(option.get("maxLength") == 1800 for option in model_answer_options)
    assert "exactly one object per gradable leaf" in prompt
    assert "successive worked-answer blocks" in prompt
    assert "[RUBRIC HANDWRITING FOCUS]" in prompt


def test_qwen_reference_bundle_rejects_a_leaf_without_rubric_criteria() -> None:
    completion = valid_reference_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["questions"][0]["criteria"] = []
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    with pytest.raises(ValueError, match="invalid structured output"):
        make_provider(FakeClient(completion)).extract_reference_bundle_from_ocr_documents(
            {
                "question_paper": [{"page": 1, "text": "QUESTION OCR"}],
                "solution": [{"page": 1, "text": "SOLUTION OCR"}],
                "rubric": [{"page": 1, "text": "RUBRIC OCR"}],
            }
        )


def test_qwen_reference_bundle_derives_missing_marks_from_complete_criteria() -> None:
    completion = valid_reference_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["questions"][0]["marks"] = None
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    result = make_provider(FakeClient(completion)).extract_reference_bundle_from_ocr_documents(
        {
            "question_paper": [{"page": 1, "text": "QUESTION OCR"}],
            "solution": [{"page": 1, "text": "SOLUTION OCR"}],
            "rubric": [{"page": 1, "text": "RUBRIC OCR"}],
        }
    )

    assert result["questions"][0]["marks"] == "5.00"


def test_qwen_reference_bundle_rejects_marks_that_disagree_with_criteria() -> None:
    completion = valid_reference_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["questions"][0]["marks"] = "6.00"
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    with pytest.raises(ValueError, match="invalid structured output"):
        make_provider(FakeClient(completion)).extract_reference_bundle_from_ocr_documents(
            {
                "question_paper": [{"page": 1, "text": "QUESTION OCR"}],
                "solution": [{"page": 1, "text": "SOLUTION OCR"}],
                "rubric": [{"page": 1, "text": "RUBRIC OCR"}],
            }
        )


def test_reference_structure_scanner_finds_nested_leaf_questions() -> None:
    hints = _reference_question_number_hints(
        {
            "question_paper": [
                {
                    "text": """1. (a) Probability stem
(i) First part
(ii) Second part
(b) Bayes stem
(i) Bus
(ii) Car
(c) Inspection stem
(i) Sample space
(ii) First inspection
(iii) Four inspections"""
                }
            ]
        }
    )

    assert hints == [
        "1(a)(i)",
        "1(a)(ii)",
        "1(b)(i)",
        "1(b)(ii)",
        "1(c)(i)",
        "1(c)(ii)",
        "1(c)(iii)",
    ]


def test_qwen_provider_refuses_model_alias_mismatch_before_completion() -> None:
    client = FakeClient(valid_completion(), models=["different-model"])

    with pytest.raises(RuntimeError, match="model alias mismatch"):
        make_provider(client).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric(),
            answer_image_path="unused.png",
            student_answer_text="Confirmed.",
            prompt_version="real-grading-v2",
            messages=[],
        )

    assert client.post_calls == []


def test_qwen_provider_requires_authenticated_protected_endpoint() -> None:
    client = FakeClient(valid_completion(), auth_status_code=401)

    with pytest.raises(RuntimeError, match="API-key authentication failed"):
        make_provider(client).verify_available_model()

    assert [call[0] for call in client.get_calls] == ["../props"]
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
            prompt_version="real-grading-v2",
            messages=[],
        )


def test_qwen_provider_reconciles_score_from_auditable_breakdown() -> None:
    completion = valid_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["score"] = "8.00"
    body["confidence"] = "0.95"
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    result = make_provider(FakeClient(completion)).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric(),
        answer_image_path="unused.png",
        student_answer_text="Confirmed.",
        prompt_version="real-grading-v2",
        messages=[],
    )

    assert result.score == Decimal("7.00")
    assert result.confidence == Decimal("0.75")
    assert "score_reconciled_from_breakdown" in result.review_flags


def test_qwen_provider_removes_credit_for_a_not_met_criterion() -> None:
    completion = valid_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["rubric_breakdown"][0]["criterion_status"] = "not_met"
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    result = make_provider(FakeClient(completion)).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric(),
        answer_image_path="unused.png",
        student_answer_text="Confirmed.",
        prompt_version="real-grading-v2",
        messages=[],
    )

    assert result.score == Decimal("2.00")
    assert result.rubric_breakdown[0].awarded_marks == Decimal("0")
    assert result.confidence == Decimal("0.70")
    assert "criterion_status_reconciled" in result.review_flags


def test_qwen_provider_removes_credit_without_verbatim_student_evidence() -> None:
    completion = valid_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["rubric_breakdown"][0]["evidence"] = "x = 4"
    completion["choices"][0]["message"]["content"] = json.dumps(body)

    result = make_provider(FakeClient(completion)).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric(),
        answer_image_path="unused.png",
        student_answer_text="Confirmed.",
        prompt_version="real-grading-v2",
        messages=[],
    )

    assert result.score == Decimal("2.00")
    assert result.rubric_breakdown[0].awarded_marks == Decimal("0")
    assert result.confidence == Decimal("0.70")
    assert "unsupported_criterion_evidence_removed" in result.review_flags


def test_qwen_provider_removes_credit_when_rubric_prerequisite_failed() -> None:
    completion = valid_completion()
    body = json.loads(completion["choices"][0]["message"]["content"])
    body["rubric_breakdown"][0]["criterion_status"] = "not_met"
    completion["choices"][0]["message"]["content"] = json.dumps(body)
    dependent_rubric = rubric()
    dependent_rubric["criteria"][1]["depends_on"] = ["concept"]

    result = make_provider(FakeClient(completion)).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=dependent_rubric,
        answer_image_path="unused.png",
        student_answer_text="Confirmed.",
        prompt_version="real-grading-v2",
        messages=[],
    )

    assert result.score == Decimal("0")
    assert all(item.awarded_marks == 0 for item in result.rubric_breakdown)
    assert "dependent_criterion_credit_removed" in result.review_flags

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
            prompt_version="real-grading-v2",
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
