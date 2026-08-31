"""Gemini provider behind the Brain Adapter boundary.

Grading uses the shared prompt registry and returns the validated
GradeSuggestionOutput schema like every other provider. Document
extraction (question paper / rubric) sends rasterized page images.
"""

import base64
import json
import time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
)
from packages.brain.cost_tracker import estimate_gemini_cost
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.universal_vision import (
    UniversalVisionCompletion,
    UniversalVisionProviderMixin,
)

QUESTION_EXTRACTION_PROMPT = """
You are an expert exam paper analyser.
Extract all questions from this exam paper image(s).

Return ONLY valid JSON - no markdown fences, no explanation, no preamble:
{
  "questions": [
    {
      "question_number": "1",
      "question_text": "full question text here",
      "marks": 10,
      "sub_questions": [
        {
          "question_number": "1(a)",
          "question_text": "sub question text",
          "marks": 5,
          "sub_questions": []
        }
      ]
    }
  ],
  "warnings": []
}

Rules:
- question_number must match exactly what is printed on the paper
- marks must be an integer, never null
- If marks are unclear, add a note to warnings and use 0
- sub_questions is an empty list if there are no sub-questions
- warnings is an empty list if there are no issues
"""

RUBRIC_EXTRACTION_PROMPT = """
You are an expert marking scheme analyser.
Extract all marking criteria from this rubric/marking scheme image(s).

Return ONLY valid JSON - no markdown fences, no explanation, no preamble:
{
  "criteria": [
    {
      "question_number": "1",
      "criterion_text": "description of what earns marks",
      "max_marks": 10,
      "sub_criteria": [
        {
          "question_number": "1(a)",
          "criterion_text": "sub criterion description",
          "max_marks": 5,
          "sub_criteria": []
        }
      ]
    }
  ],
  "warnings": []
}

Rules:
- question_number must match the question paper numbering exactly
- max_marks must be an integer
- sub_criteria is an empty list if there are no sub-criteria
- warnings is an empty list if there are no issues
"""


def _parse_strict_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response was not a JSON object")
    return parsed


def _pdf_to_image_parts(pdf_path: str) -> list[dict[str, Any]]:
    import fitz

    doc = fitz.open(pdf_path)
    parts: list[dict[str, Any]] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(pix.tobytes("jpeg")).decode("utf-8"),
                    }
                }
            )
    finally:
        doc.close()
    return parts


def _data_url_to_inline_part(image_data_url: str) -> dict[str, Any]:
    header, _, payload = image_data_url.partition(",")
    mime_type = header.removeprefix("data:").removesuffix(";base64")
    return {"inline_data": {"mime_type": mime_type, "data": payload}}


class GeminiBrainProvider(UniversalVisionProviderMixin, BrainProvider):
    provider_name = "gemini"
    execution_location = BrainExecutionLocation.CLOUD
    image_input_mode = BrainImageInputMode.DATA_URL
    _VISION_CAPABILITIES = frozenset(
        {
            BrainCapability.QUESTION_PDF_EXTRACTION,
            BrainCapability.RUBRIC_PDF_EXTRACTION,
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
            BrainCapability.VISUAL_MAPPING,
            BrainCapability.VISUAL_TRANSCRIPTION,
            BrainCapability.TRANSCRIPTION_REPAIR,
        }
    )

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
        timeout_seconds: float = 120.0,
        image_input_enabled: bool = False,
        structured_output_mode: str = "json_schema",
        verify_model_on_start: bool = False,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini provider requires an API key")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
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
            capabilities.update(self._VISION_CAPABILITIES)
        self.capabilities = frozenset(capabilities)
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                api_key=self.api_key,
                http_options={"timeout": int(self.timeout_seconds * 1000)},
            )
        return self._client

    def _generate(
        self,
        contents: list[Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> Any:
        return self._get_client().models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

    def _structured_config(
        self,
        *,
        response_model: type[BaseModel] | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": 0}
        if self.structured_output_mode != "prompt_only":
            config["response_mime_type"] = "application/json"
        if self.structured_output_mode == "json_schema" and response_model is not None:
            config["response_json_schema"] = response_model.model_json_schema()
        if max_tokens is not None:
            config["max_output_tokens"] = max_tokens
        return config

    def _usage_cost(self, response: Any) -> Decimal:
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        return estimate_gemini_cost(input_tokens=input_tokens, output_tokens=output_tokens)

    def _complete_structured_vision(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
        schema_name: str,
        max_tokens: int | None = None,
    ) -> UniversalVisionCompletion:
        del schema_name
        if not self.vision_enabled:
            raise RuntimeError("Image input is disabled for the Gemini provider")
        contents: list[Any] = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            }
            for image_bytes, mime_type in images
        ]
        contents.append(prompt)
        started = time.perf_counter()
        response = self._generate(
            contents,
            config=self._structured_config(
                response_model=response_model,
                max_tokens=max_tokens,
            ),
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage_metadata", None)
        return UniversalVisionCompletion(
            payload=_parse_strict_json(response.text),
            latency_ms=latency_ms,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            completion_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        )

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
        del question_text, question_total_marks, answer_image_path
        del task_name, model_policy, marking_policy, rubric_json, student_answer_text
        prompt_text = "\n\n".join(
            str(message.get("content", "")) for message in (messages or [])
        )
        contents: list[Any] = [prompt_text]
        if image_data_url:
            contents.insert(0, _data_url_to_inline_part(image_data_url))
        response = self._generate(
            contents,
            config=self._structured_config(response_model=None, max_tokens=None),
        )
        raw_output = _parse_strict_json(response.text)
        raw_output["model_provider"] = self.provider_name
        raw_output["model_name"] = self.model_name
        raw_output["prompt_version"] = prompt_version
        raw_output["needs_review"] = True
        review_flags = list(raw_output.get("review_flags") or [])
        for flag in (
            "teacher_review_required",
            "image_input_used" if image_data_url else "image_input_disabled",
        ):
            if flag not in review_flags:
                review_flags.append(flag)
        raw_output["review_flags"] = review_flags
        raw_output["cost_estimate"] = self._usage_cost(response)
        return GradeSuggestionOutput.model_validate(raw_output)

    def extract_questions_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        if not self.vision_enabled:
            raise RuntimeError("Image input is disabled for the Gemini provider")
        parts = _pdf_to_image_parts(pdf_path)
        parts.append(QUESTION_EXTRACTION_PROMPT)
        response = self._generate(
            parts,
            config=self._structured_config(response_model=None, max_tokens=None),
        )
        result = _parse_strict_json(response.text)
        if "questions" not in result:
            raise ValueError(
                "Gemini response missing 'questions' key. "
                f"Raw response: {response.text[:300]}"
            )
        return result

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        if not self.vision_enabled:
            raise RuntimeError("Image input is disabled for the Gemini provider")
        parts = _pdf_to_image_parts(pdf_path)
        parts.append(RUBRIC_EXTRACTION_PROMPT)
        response = self._generate(
            parts,
            config=self._structured_config(response_model=None, max_tokens=None),
        )
        result = _parse_strict_json(response.text)
        if "criteria" not in result:
            raise ValueError(
                "Gemini response missing 'criteria' key. "
                f"Raw response: {response.text[:300]}"
            )
        return result

    def verify_available_model(self) -> None:
        if self.verify_model_on_start:
            self._get_client().models.get(model=self.model_name)
