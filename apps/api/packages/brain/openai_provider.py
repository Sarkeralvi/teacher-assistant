import base64
import json
import re
import time
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.universal_vision import (
    UniversalVisionCompletion,
    UniversalVisionProviderMixin,
)


class OpenAICompatibleProvider(UniversalVisionProviderMixin, BrainProvider):
    provider_name = "openai"
    image_input_mode = BrainImageInputMode.DATA_URL

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
        provider_name: str = "openai",
        execution_location: BrainExecutionLocation = BrainExecutionLocation.CLOUD,
        image_input_enabled: bool = False,
        structured_output_mode: str = "json_schema",
        verify_model_on_start: bool = False,
        managed_local_phase: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.provider_name = provider_name
        self.execution_location = execution_location
        self.managed_local_phase = managed_local_phase
        self.vision_enabled = image_input_enabled
        self.verify_model_on_start = verify_model_on_start
        normalized_mode = structured_output_mode.strip().lower()
        if normalized_mode not in {"json_schema", "json_object", "prompt_only"}:
            raise ValueError(
                "Structured output mode must be json_schema, json_object, or prompt_only"
            )
        self.structured_output_mode = normalized_mode
        capabilities = {BrainCapability.GRADING}
        if image_input_enabled:
            capabilities.update(
                {
                    BrainCapability.QUESTION_PDF_EXTRACTION,
                    BrainCapability.RUBRIC_PDF_EXTRACTION,
                    BrainCapability.VISUAL_REFERENCE_EXTRACTION,
                    BrainCapability.VISUAL_MAPPING,
                    BrainCapability.VISUAL_TRANSCRIPTION,
                    BrainCapability.TRANSCRIPTION_REPAIR,
                }
            )
        self.capabilities = frozenset(capabilities)
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
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del (
            question_text,
            question_total_marks,
            answer_image_path,
            task_name,
            model_policy,
            marking_policy,
        )
        request_json: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._with_optional_image(messages or [], image_data_url),
            "temperature": 0,
        }
        if self.structured_output_mode != "prompt_only":
            request_json["response_format"] = {"type": "json_object"}
        try:
            response = self.client.post(
                "/chat/completions",
                headers=self._headers(),
                json=request_json,
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
        self._append_flag(review_flags, "teacher_review_required")
        self._append_flag(
            review_flags,
            "image_input_used" if image_data_url else "image_input_disabled",
        )
        raw_output["review_flags"] = review_flags
        raw_output["cost_estimate"] = self._estimate_cost(payload)
        try:
            return GradeSuggestionOutput.model_validate(raw_output)
        except ValidationError:
            raise

    def _complete_structured_vision(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
        schema_name: str,
        max_tokens: int | None = None,
    ) -> UniversalVisionCompletion:
        if not self.vision_enabled:
            raise RuntimeError("Image input is disabled for this OpenAI-compatible provider")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_bytes, mime_type in images:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                }
            )
        request_json: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
        }
        if self.structured_output_mode == "json_schema" and response_model is not None:
            request_json["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            }
        elif self.structured_output_mode in {"json_schema", "json_object"}:
            request_json["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            request_json["max_tokens"] = max_tokens
        started = time.perf_counter()
        try:
            response = self.client.post(
                "/chat/completions",
                headers=self._headers(),
                json=request_json,
            )
            response.raise_for_status()
            body = response.json()
            payload = json.loads(self._extract_content(body))
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc
        if not isinstance(payload, dict):
            raise ValueError("OpenAI-compatible structured response must be a JSON object")
        usage = body.get("usage") if isinstance(body, dict) else None
        return UniversalVisionCompletion(
            payload=payload,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=_optional_usage(usage, "prompt_tokens"),
            completion_tokens=_optional_usage(usage, "completion_tokens"),
        )

    def verify_available_model(self) -> None:
        if not self.verify_model_on_start:
            return
        try:
            response = self.client.get("/models", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc
        models = payload.get("data") if isinstance(payload, dict) else None
        model_ids = {
            item.get("id")
            for item in (models or [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if self.model_name not in model_ids:
            raise RuntimeError("Configured provider model alias was not advertised")

    def _with_optional_image(
        self, messages: list[dict[str, Any]], image_data_url: str | None
    ) -> list[dict[str, Any]]:
        if not image_data_url:
            return messages
        if not messages:
            return [self._vision_user_message("", image_data_url)]
        prepared = [dict(message) for message in messages]
        last_user_index = next(
            (
                index
                for index in range(len(prepared) - 1, -1, -1)
                if prepared[index].get("role") == "user"
            ),
            None,
        )
        if last_user_index is None:
            prepared.append(self._vision_user_message("", image_data_url))
            return prepared
        user_message = prepared[last_user_index]
        content = user_message.get("content", "")
        text = content if isinstance(content, str) else json.dumps(content)
        user_message["content"] = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
        prepared[last_user_index] = user_message
        return prepared

    def _vision_user_message(self, text: str, image_data_url: str) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }

    def _append_flag(self, review_flags: list[str], flag: str) -> None:
        if flag not in review_flags:
            review_flags.append(flag)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _sanitize_error(self, message: str) -> str:
        sanitized = message.replace(self.api_key, "[REDACTED]") if self.api_key else message
        sanitized = re.sub(r"sk-[A-Za-z0-9_\-]+", "[REDACTED]", sanitized)
        return re.sub(
            r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+",
            "[IMAGE_DATA_REDACTED]",
            sanitized,
        )

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


def _optional_usage(usage: object, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    return value if isinstance(value, int) and value >= 0 else None
