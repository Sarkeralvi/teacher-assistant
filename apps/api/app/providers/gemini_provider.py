"""
Gemini API provider for TAAgent.
Handles question extraction, rubric extraction, and answer grading.
All AI calls for the product go through this module.
"""

import base64
import json
import os
from collections.abc import Sequence
from functools import lru_cache

import fitz  # pymupdf
from google import genai

_MODEL = "gemini-2.0-flash"


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Gemini provider is not configured.")
    return genai.Client(api_key=api_key)


def _generate_content(contents: Sequence[object]):
    return _client().models.generate_content(model=_MODEL, contents=contents)

_QUESTION_EXTRACTION_PROMPT = """
You are an expert exam paper analyser.
Extract all questions from this exam paper image(s).

Return ONLY valid JSON — no markdown fences, no explanation, no preamble:
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

_RUBRIC_EXTRACTION_PROMPT = """
You are an expert marking scheme analyser.
Extract all marking criteria from this rubric/marking scheme image(s).

Return ONLY valid JSON — no markdown fences, no explanation, no preamble:
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

_GRADING_PROMPT = """
You are an expert exam marker. Grade the following student answer.

QUESTION:
{question}

MARKING SCHEME / RUBRIC:
{rubric}

STUDENT ANSWER:
{answer}

MARKING POLICY: {policy}

Policy meanings:
- tough: strict application of rubric, penalise omissions and vagueness
- general: standard marking, reasonable benefit of the doubt for partial understanding
- easy: generous marking, reward any evidence of understanding

Return ONLY valid JSON — no markdown fences, no explanation, no preamble:
{{
  "score": <integer, marks awarded>,
  "max_score": <integer, maximum possible marks>,
  "feedback": "<specific feedback explaining the score, referencing rubric criteria>",
  "confidence": "<high|medium|low>",
  "warnings": []
}}

Rules:
- score must not exceed max_score
- score must not be negative
- feedback must explain specifically why marks were awarded or deducted
- confidence is low if the handwriting was unclear or the answer was ambiguous
- warnings lists any issues (illegible text, missing answer, etc.)
"""


def _pdf_to_image_parts(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    parts: list[dict] = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("jpeg")
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(img_bytes).decode("utf-8"),
                }
            }
        )
    doc.close()
    return parts


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def extract_questions_from_pdf(pdf_path: str) -> dict:
    parts = _pdf_to_image_parts(pdf_path)
    parts.append(_QUESTION_EXTRACTION_PROMPT)
    response = _generate_content(parts)
    result = _parse_json(response.text)
    if "questions" not in result:
        raise ValueError(
            "Gemini response missing 'questions' key. "
            f"Raw response: {response.text[:300]}"
        )
    return result


def extract_rubric_from_pdf(pdf_path: str) -> dict:
    parts = _pdf_to_image_parts(pdf_path)
    parts.append(_RUBRIC_EXTRACTION_PROMPT)
    response = _generate_content(parts)
    result = _parse_json(response.text)
    if "criteria" not in result:
        raise ValueError(
            "Gemini response missing 'criteria' key. "
            f"Raw response: {response.text[:300]}"
        )
    return result


def grade_answer(
    question_text: str,
    rubric_text: str,
    student_answer: str,
    policy: str = "general",
) -> dict:
    prompt = _GRADING_PROMPT.format(
        question=question_text,
        rubric=rubric_text,
        answer=student_answer,
        policy=policy,
    )
    response = _generate_content([prompt])
    result = _parse_json(response.text)
    required = {"score", "max_score", "feedback"}
    missing = required - set(result.keys())
    if missing:
        raise ValueError(
            "Gemini grading response missing keys "
            f"{missing}. Raw: {response.text[:300]}"
        )
    return result
