from typing import Any

from packages.brain.schemas import ModelPolicy

PROMPT_VERSIONS: dict[ModelPolicy, str] = {
    ModelPolicy.MOCK_GRADING: "mock-grading-v1",
    ModelPolicy.REAL_GRADING: "real-grading-v1",
}


REAL_GRADING_SYSTEM_PROMPT = """You are a grading assistant. Produce a grade suggestion only.
Teacher final review is always required. Do not create a final grade.
Do not invent answer content. If the supplied text or image evidence is unclear or incomplete,
lower confidence and explain the uncertainty. Output only strict JSON matching the requested schema.
"""


def get_prompt_version(policy: ModelPolicy) -> str:
    return PROMPT_VERSIONS[policy]


def build_grading_prompt(
    *,
    question_text: str,
    rubric_json: dict[str, Any],
    answer_image_path: str,
    image_input_enabled: bool,
) -> list[dict[str, str]]:
    model_answer = (
        rubric_json.get("model_answer")
        or rubric_json.get("answer_key")
        or "Not provided."
    )
    image_note = (
        f"Image input path available to provider: {answer_image_path}"
        if image_input_enabled
        else (
            "Image input is disabled for this provider path. "
            "Do not claim handwriting/image understanding."
        )
    )
    user_prompt = f"""
Task: answer_region_grading
Question text:
{question_text}

Model answer:
{model_answer}

Rubric JSON:
{rubric_json}

Image evidence:
{image_note}

Return strict JSON with these fields:
score, max_score, confidence, needs_review, rubric_breakdown, detected_answer_summary,
major_errors, feedback_to_student, review_flags.
Every rubric_breakdown item must include criterion_id, criterion, max_marks, awarded_marks,
reason, evidence, confidence. Awarded marks must sum to score. Set needs_review=true and include
teacher_review_required in review_flags. This is a suggestion only.
"""
    return [
        {"role": "system", "content": REAL_GRADING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
