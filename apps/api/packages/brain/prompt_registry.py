from typing import Any

from packages.brain.schemas import ModelPolicy

PROMPT_VERSIONS: dict[ModelPolicy, str] = {
    ModelPolicy.MOCK_GRADING: "mock-grading-v1",
    ModelPolicy.REAL_GRADING: "real-grading-v1",
}

MARKING_POLICY_INSTRUCTIONS: dict[str, str] = {
    "tough": (
        "Tough marking: Strictly follow the rubric. Penalize missing reasoning even if "
        "the final answer is correct. Penalize unsupported final answers. Penalize "
        "ambiguous or unreadable work. Do not give benefit of doubt unless evidence is "
        "visible. Lower confidence when required steps are missing or handwriting is "
        "unclear."
    ),
    "general": (
        "General marking: Follow the rubric normally. Award marks for equivalent valid "
        "methods. Penalize clear errors according to the rubric. Use balanced judgement."
    ),
    "easy": (
        "Easy marking: Follow the rubric but be lenient on minor notation/presentation "
        "issues. Accept equivalent reasoning where mathematically/semantically valid. "
        "Give partial credit for correct ideas even if presentation is imperfect. Do not "
        "ignore major conceptual errors. Do not award marks for unsupported work that "
        "contradicts the answer."
    ),
}


REAL_GRADING_SYSTEM_PROMPT = """You are a grading assistant. Produce a grade suggestion only.
Teacher final review is always required. Do not create a final grade.
Do not invent answer content. If supplied evidence is unclear or incomplete,
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
    marking_policy: str = "general",
) -> list[dict[str, str]]:
    model_answer = (
        rubric_json.get("model_answer") or rubric_json.get("answer_key") or "Not provided."
    )
    if image_input_enabled:
        image_note = (
            "Image input is enabled. The attached image is a cropped handwritten "
            "answer region. Grade using only visible answer content, the question, "
            "the model answer, and the rubric. Do not invent unreadable content. "
            "If handwriting is unclear, lower confidence."
        )
    else:
        image_note = (
            "Image input is disabled for this provider path. "
            "Do not claim handwriting/image understanding."
        )
    normalized_policy = marking_policy.strip().lower()
    policy_instruction = MARKING_POLICY_INSTRUCTIONS.get(
        normalized_policy, MARKING_POLICY_INSTRUCTIONS["general"]
    )
    user_prompt = f"""
Task: answer_region_grading
Question text:
{question_text}

Model answer:
{model_answer}

Rubric JSON:
{rubric_json}

Image evidence path label:
{answer_image_path}

Image instructions:
{image_note}

Marking policy: {normalized_policy}
Policy instructions:
{policy_instruction}
Do not change max_score, rubric criterion max_marks, or teacher-review requirements
because of policy. Include marking_policy:{normalized_policy} in review_flags.

Return strict JSON with these fields:
score, max_score, confidence, needs_review, rubric_breakdown, detected_answer_summary,
major_errors, feedback_to_student, review_flags.
Every rubric_breakdown item must include criterion_id, criterion, max_marks, awarded_marks,
reason, evidence, confidence. Awarded marks must sum to score. Set needs_review=true and include
teacher_review_required in review_flags. This is a suggestion only; teacher final review
is required.
"""
    return [
        {"role": "system", "content": REAL_GRADING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
