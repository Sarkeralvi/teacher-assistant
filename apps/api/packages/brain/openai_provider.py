import json
import re
from decimal import Decimal
from typing import Any

import httpx
from pydantic import ValidationError

from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy


class OpenAICompatibleProvider(BrainProvider):
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.client = client or httpx.Client(base_url=self.base_url, timeout=timeout_seconds)

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, str]] | None = None,
    ) -> GradeSuggestionOutput:
        del question_text, question_total_marks, answer_image_path, task_name, model_policy
        try:
            response = self.client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_name,
                    "messages": messages or [],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc
        payload = response.json()
        content = self._extract_content(payload)
        raw_output = json.loads(content)
        raw_output["model_provider"] = self.provider_name
        raw_output["model_name"] = self.model_name
        raw_output["prompt_version"] = prompt_version
        raw_output["needs_review"] = True
        review_flags = list(raw_output.get("review_flags") or [])
        if "teacher_review_required" not in review_flags:
            review_flags.append("teacher_review_required")
        raw_output["review_flags"] = review_flags
        raw_output["cost_estimate"] = self._estimate_cost(payload)
        try:
            return GradeSuggestionOutput.model_validate(raw_output)
        except ValidationError:
            raise

    def _sanitize_error(self, message: str) -> str:
        sanitized = message.replace(self.api_key, "[REDACTED]") if self.api_key else message
        return re.sub(r"sk-[A-Za-z0-9_\-]+", "[REDACTED]", sanitized)

    def _extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI response missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ValueError("OpenAI response missing message content")
        return message["content"]

    def _estimate_cost(self, payload: dict[str, Any]) -> Decimal:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return Decimal("0")
        total_tokens = usage.get("total_tokens") or 0
        return Decimal(str(total_tokens)) * Decimal("0")
