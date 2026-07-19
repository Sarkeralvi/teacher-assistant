"""Gemini provider behind the Brain Adapter boundary.

Grading uses the shared prompt registry and returns the validated
GradeSuggestionOutput schema like every other provider. Document
extraction (question paper / rubric) sends rasterized page images.
"""

import base64
import json
from decimal import Decimal
from typing import Any

from packages.brain.cost_tracker import estimate_gemini_cost
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy

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


class GeminiBrainProvider(BrainProvider):
    provider_name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
    ) -> None:
        if not api_key:
            raise ValueError("Gemini provider requires an API key")
        self.api_key = api_key
        self.model_name = model_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _generate(self, contents: list[Any]) -> Any:
        return self._get_client().models.generate_content(
            model=self.model_name, contents=contents
        )

    def _usage_cost(self, response: Any) -> Decimal:
        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        return estimate_gemini_cost(input_tokens=input_tokens, output_tokens=output_tokens)

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
        response = self._generate(contents)
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
        parts = _pdf_to_image_parts(pdf_path)
        parts.append(QUESTION_EXTRACTION_PROMPT)
        response = self._generate(parts)
        result = _parse_strict_json(response.text)
        if "questions" not in result:
            raise ValueError(
                "Gemini response missing 'questions' key. "
                f"Raw response: {response.text[:300]}"
            )
        return result

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        parts = _pdf_to_image_parts(pdf_path)
        parts.append(RUBRIC_EXTRACTION_PROMPT)
        response = self._generate(parts)
        result = _parse_strict_json(response.text)
        if "criteria" not in result:
            raise ValueError(
                "Gemini response missing 'criteria' key. "
                f"Raw response: {response.text[:300]}"
            )
        return result
