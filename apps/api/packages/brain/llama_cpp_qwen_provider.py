from __future__ import annotations

import json
import re
from copy import deepcopy
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import (
    GradeSuggestionOutput,
    ModelPolicy,
    RubricBreakdownItem,
)


class QwenRubricBreakdownItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    max_marks: Decimal = Field(ge=Decimal("0"))
    awarded_marks: Decimal = Field(ge=Decimal("0"))
    reason: str = Field(min_length=1)
    evidence: str | None = None
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def awarded_marks_must_not_exceed_max(self) -> QwenRubricBreakdownItem:
        if self.awarded_marks > self.max_marks:
            raise ValueError("awarded_marks cannot exceed max_marks")
        return self


class QwenGradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]
    rubric_breakdown: list[QwenRubricBreakdownItem] = Field(min_length=1)
    detected_answer_summary: str = Field(min_length=1)
    major_errors: list[str]
    feedback_to_student: str = Field(min_length=1)
    review_flags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def score_must_match_breakdown(self) -> QwenGradePayload:
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        total = sum(
            (item.awarded_marks for item in self.rubric_breakdown), Decimal("0")
        )
        if total != self.score:
            raise ValueError("rubric breakdown awarded marks must sum to score")
        return self


class QwenQuestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str = Field(min_length=1, max_length=64)
    parent_question_number: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    question_text: str = Field(min_length=1)
    model_answer: str | None = None
    marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    node_type: Literal["question", "subquestion", "instruction"]
    source_page: int = Field(ge=1)
    source_text_excerpt: str = Field(min_length=1, max_length=500)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]


class QwenQuestionExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QwenQuestionDraft] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class QwenRubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_number: str | None = Field(default=None, max_length=64)
    criterion_label: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    max_marks: Decimal | None = Field(default=None, ge=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    blocker: str | None = None
    needs_review: Literal[True]


class QwenRubricExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[QwenRubricCriterion] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


_API_KEY_PATTERN = re.compile(r"(?:sk|key)-[A-Za-z0-9_\-]+", re.IGNORECASE)
_DATA_URL_PATTERN = re.compile(
    r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", re.IGNORECASE
)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LlamaCppQwenProvider(BrainProvider):
    """Text-only Qwen provider behind llama.cpp's OpenAI-compatible API."""

    provider_name = "llama_cpp_qwen"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout_seconds: float = 180.0,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("LOCAL_QWEN_API_KEY is required")
        if not model_name:
            raise ValueError("LOCAL_QWEN_MODEL is required")
        parsed_url = urlparse(base_url)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname not in _LOOPBACK_HOSTS
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("LOCAL_QWEN_BASE_URL must use HTTP on a loopback host")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/") + "/"
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            trust_env=False,
        )
        self._model_verified = False

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del answer_image_path, task_name, model_policy, image_data_url, marking_policy
        if not (student_answer_text or "").strip():
            raise ValueError("Teacher-confirmed student answer text is required")
        payload, usage = self._structured_completion(
            messages=messages or [],
            response_model=QwenGradePayload,
            schema_name="grade_suggestion",
        )
        assert isinstance(payload, QwenGradePayload)
        self._validate_grade_contract(payload, question_total_marks, rubric_json)
        flags = list(payload.review_flags)
        for flag in (
            "teacher_review_required",
            "image_input_disabled",
            "local_provider",
        ):
            if flag not in flags:
                flags.append(flag)
        return GradeSuggestionOutput(
            score=payload.score,
            max_score=payload.max_score,
            confidence=payload.confidence,
            needs_review=True,
            rubric_breakdown=[
                RubricBreakdownItem.model_validate(item.model_dump())
                for item in payload.rubric_breakdown
            ],
            detected_answer_summary=payload.detected_answer_summary,
            major_errors=payload.major_errors,
            feedback_to_student=payload.feedback_to_student,
            review_flags=flags,
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=Decimal("0"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

    def extract_questions_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        context = self._ocr_context(pages)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract question structure from local OCR text. Use only supplied text. "
                    "Every item is a draft and needs_review must be true. Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract questions, subquestions, marks, model answers when explicitly "
                    "present, source pages, short source excerpts, confidence, and warnings. "
                    "Do not invent missing answers or marks.\n\n" + context
                ),
            },
        ]
        payload, _usage = self._structured_completion(
            messages=messages,
            response_model=QwenQuestionExtractionPayload,
            schema_name="question_extraction",
        )
        assert isinstance(payload, QwenQuestionExtractionPayload)
        return payload.model_dump(mode="json")

    def extract_rubric_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        context = self._ocr_context(pages)
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract rubric criteria from local OCR text. Use only supplied text. "
                    "Every item is a draft and needs_review must be true. Return strict JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract criterion labels, descriptions, marks, question links, confidence, "
                    "blockers, and warnings. Do not invent missing marks.\n\n" + context
                ),
            },
        ]
        payload, _usage = self._structured_completion(
            messages=messages,
            response_model=QwenRubricExtractionPayload,
            schema_name="rubric_extraction",
        )
        assert isinstance(payload, QwenRubricExtractionPayload)
        return payload.model_dump(mode="json")

    def verify_model(self) -> None:
        if self._model_verified:
            return
        try:
            response = self.client.get("models", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Local Qwen model verification failed: {self._sanitize(str(exc))}"
            ) from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("Local Qwen model verification returned an invalid model list")
        model_ids = {
            item.get("id")
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if self.model_name not in model_ids:
            raise RuntimeError(
                "Local Qwen model alias mismatch; expected the configured model alias"
            )
        self._model_verified = True

    def verify_available_model(self) -> None:
        self.verify_model()

    def _structured_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        schema_name: str,
    ) -> tuple[BaseModel, dict[str, int]]:
        self.verify_model()
        try:
            response = self.client.post(
                "chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model_name,
                    "messages": messages,
                    "temperature": 0,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "strict": True,
                            "schema": _llama_cpp_json_schema(response_model),
                        },
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
            content = self._extract_content(body)
            raw = json.loads(content)
            validated = response_model.model_validate(raw)
        except (json.JSONDecodeError, ValidationError):
            raise ValueError("Local Qwen returned invalid structured output") from None
        except Exception as exc:
            raise RuntimeError(self._sanitize(str(exc))) from exc
        usage_payload = body.get("usage") if isinstance(body, dict) else None
        usage = {
            key: int(value)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage_payload, dict)
            and isinstance((value := usage_payload.get(key)), int)
            and value >= 0
        }
        return validated, usage

    def _validate_grade_contract(
        self,
        payload: QwenGradePayload,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
    ) -> None:
        expected_max = Decimal(str(rubric_json.get("total_marks", question_total_marks)))
        if payload.max_score != expected_max or payload.max_score != question_total_marks:
            raise ValueError("Local Qwen changed the canonical maximum score")
        criteria = rubric_json.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("Active rubric has no criteria")
        expected = {
            str(item.get("id")): Decimal(str(item.get("max_marks")))
            for item in criteria
            if isinstance(item, dict) and item.get("id") is not None
        }
        actual = {item.criterion_id: item.max_marks for item in payload.rubric_breakdown}
        if actual != expected:
            raise ValueError("Local Qwen changed rubric criterion IDs or maximum marks")

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Local Qwen response missing choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Local Qwen response missing message content")
        return content

    def _ocr_context(self, pages: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        for page in pages:
            page_no = page.get("page", page.get("page_no", "?"))
            text = str(page.get("text") or page.get("normalized_text") or "").strip()
            if text:
                chunks.append(f"--- Page {page_no} ---\n{text}")
        if not chunks:
            raise ValueError("Local OCR returned no text to extract")
        return "\n\n".join(chunks)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _sanitize(self, message: str) -> str:
        sanitized = message.replace(self.api_key, "[REDACTED]")
        sanitized = _API_KEY_PATTERN.sub("[REDACTED]", sanitized)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", sanitized)


def _llama_cpp_json_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Remove Pydantic's regex-backed Decimal string alternative.

    llama.cpp build 10249 cannot translate the ``\\d`` escape emitted in that
    alternative into a grammar. JSON numbers retain the same Decimal precision
    once Pydantic validates the response, while nullable Decimal fields keep
    their null alternative.
    """

    return _prefer_json_numbers(deepcopy(response_model.model_json_schema()))


def _prefer_json_numbers(value: Any) -> Any:
    if isinstance(value, list):
        return [_prefer_json_numbers(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _prefer_json_numbers(item) for key, item in value.items()}
    alternatives = normalized.get("anyOf")
    if not isinstance(alternatives, list):
        return normalized

    has_number = any(
        isinstance(option, dict) and option.get("type") == "number"
        for option in alternatives
    )
    if not has_number:
        return normalized
    filtered = [
        option
        for option in alternatives
        if not (
            isinstance(option, dict)
            and option.get("type") == "string"
            and "pattern" in option
        )
    ]
    if len(filtered) == len(alternatives):
        return normalized
    if len(filtered) == 1:
        metadata = {
            key: item
            for key, item in normalized.items()
            if key not in {"anyOf", "type", "minimum", "maximum"}
        }
        return {**filtered[0], **metadata}
    normalized["anyOf"] = filtered
    return normalized
