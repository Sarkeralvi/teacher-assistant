from typing import Any

from packages.brain.schemas import ModelPolicy

PROMPT_VERSIONS: dict[ModelPolicy, str] = {
    ModelPolicy.MOCK_GRADING: "mock-grading-v1",
    ModelPolicy.REAL_GRADING: "real-grading-v3",
}

MARKING_POLICY_INSTRUCTIONS: dict[str, tuple[str, ...]] = {
    "tough": (
        "Tough marking",
        "- Apply the rubric criterion-by-criterion rather than using a vague overall impression.",
        "- Award full marks only for complete, correct, and well-justified answers.",
        "- Penalize missing reasoning, missing steps, vague reasoning, unsupported claims,",
        "  and final answers that are not justified by visible work.",
        "- A correct final answer with little or no working should receive limited credit,",
        "  not automatic full marks.",
        "- Penalize notation or presentation problems when they reduce clarity or hide",
        "  missing reasoning.",
        "- When a score is borderline, bias toward the lower end of the rubric range.",
        "- Confidence should fall when key steps are missing or evidence is hard to read.",
    ),
    "general": (
        "General marking",
        "- Apply the rubric criterion-by-criterion and keep the rubric as the source of truth.",
        "- Award marks fairly for correct methods and correct reasoning.",
        "- Give partial credit when the method is mostly correct but a step is missing or",
        "  slightly wrong.",
        "- Minor wording, notation, or presentation issues should not be heavily penalized",
        "  when the meaning is clear.",
        "- Balance the final answer and the working instead of over-weighting either one.",
        "- When a score is borderline, choose the middle of the plausible rubric range.",
    ),
    "easy": (
        "Easy marking",
        "- Apply the rubric criterion-by-criterion and keep the rubric as the source of truth.",
        "- Award partial credit generously when the answer shows real understanding or visible",
        "  method.",
        "- Give the benefit of the doubt when reasoning is partially visible and the answer is",
        "  plausibly on track.",
        "- Penalize only clear conceptual mistakes, unsupported claims, or missing required",
        "  components.",
        "- A correct final answer with weak working can receive more credit than under tough or",
        "  general, but not automatic full marks.",
        "- Do not ignore major conceptual errors or contradictions.",
        "- When a score is borderline, bias toward the higher end of the rubric range if the",
        "  rubric allows it.",
    ),
}

HANDWRITTEN_MATH_STAT_GRADING_GUIDANCE: tuple[str, ...] = (
    "Handwritten mathematics/statistics grading guidance",
    "- Grade against the exact canonical grading unit and max marks shown in the question",
    "  context.",
    "- Use the active rubric and model answer as primary evidence; do not replace them",
    "  with a vague overall impression.",
    (
        "- Award credit for correct mathematical/statistical setup, formula choice, "
        "substitution, and valid final answer."
    ),
    "- Do not over-penalize messy handwriting, imperfect notation, or missing polish if",
    "  the mathematical intent is clear.",
    "- Distinguish conceptual error, arithmetic slip, notation/presentation issue,",
    "  incomplete working, and correct setup but missing final simplification.",
    "- For probability, Bayes, and statistics questions, give substantial credit for",
    "  correct formula and correct identification of numerator/denominator events.",
    "Bayes/probability score-band guidance for 6-mark subparts",
    (
        "- 5-6 marks: Award near-full/full credit when the answer shows Bayes theorem "
        "or equivalent conditional-probability formula, correct identification of "
        "target event and evidence event, correct denominator/total probability "
        "expansion, and plausible numerator/substitution or final posterior "
        "value/expression"
    ),
    "  with no conceptual",
    "  reversal of conditional probability.",
    "- Messy handwriting, compressed arithmetic, or imperfect notation alone should not",
    "  reduce a conceptually correct answer to mid-credit.",
    "- 3-4 marks: Use for answers with correct formula but one important missing/unclear",
    "  component, such as denominator missing one branch, numerator not tied to the target",
    "  event, final arithmetic absent and substitution unclear, or recoverable event",
    "  confusion.",
    "- 0-2 marks: Use for wrong conditional direction, no Bayes/conditional probability",
    "  setup, unsupported numeric answer, or major conceptual mismatch.",
    "- Do not mark harshly when final arithmetic is compressed but the result, setup, or",
    "  equivalent expression is present.",
    "- Penalize real conceptual mismatch, unsupported answers, or contradictions; do not",
    "  treat presentation mess as a conceptual error by default.",
    "- If handwriting is uncertain, set needs_review=true, lower confidence, and explain",
    "  the uncertainty, but do not automatically slash the score.",
    "- Never create a FinalGrade. Always preserve teacher review requirement.",
    "Three-decimal numerical precision policy",
    (
        "- Do not deduct marks when a student's numerical answer is correct to three decimal "
        "places, or when an exact fraction/algebraic form is numerically equivalent."
    ),
    (
        "- Treat an absolute numerical difference of at most 0.0005 as consistent with correct "
        "rounding to three decimal places; do not cite precision as an error in that case."
    ),
    (
        "- Override this rule only when the teacher-confirmed question or active rubric explicitly "
        "requires more than three decimal places or a specified exact form."
    ),
    (
        "- This precision tolerance does not excuse a conceptual, formula, substitution, or method "
        "error merely because an unrelated number is close."
    ),
)

SEMANTIC_EQUIVALENCE_GRADING_GUIDANCE: tuple[str, ...] = (
    "Semantic equivalence and student-defined notation guidance",
    (
        "- Treat the model answer as a semantic reference, not an exact-string, symbol-name, "
        "set-name, or presentation template."
    ),
    (
        "- Before deducting marks for different symbols, read any explicit definitions in the "
        "teacher-confirmed student answer and substitute those meanings consistently."
    ),
    (
        "- If a consistent renaming of student-defined symbols produces the same mathematical "
        "objects, events, outcomes, relations, or method as the model answer, treat the notation "
        "as mathematically equivalent and do not deduct marks merely for that renaming."
    ),
    (
        "- A different set name or a different listing order is not an error unless the question "
        "or rubric explicitly requires that name or an ordered sequence."
    ),
    (
        "- Example: if the student explicitly defines F as fail and P as does not fail, then "
        "{F, PF, PPF, PPPF, PPPP} is notation-equivalent to "
        "{N, NF, NNF, NNNF, NNNN} when N means does not fail."
    ),
    (
        "- Apply that substitution element-by-element. Under the same definitions, "
        "{P, PF, PPF, PPPF, PPPP} is not fully equivalent to the reference because its first "
        "outcome maps to N rather than F; the other four outcomes still match. Use the rubric "
        "to award proportionate partial credit instead of treating the entire construction as "
        "wrong merely because it uses P rather than N."
    ),
    (
        "- Do penalize a real semantic defect: an undefined or inconsistently used symbol, a "
        "missing or duplicate outcome, an impossible outcome, a changed event meaning, or an "
        "incorrect relation. Do not invent a symbol definition that the student did not supply."
    ),
    (
        "- In every rubric reason, state the semantic comparison you performed. Never claim that "
        "canonical notation is required unless that requirement is explicit in the question or "
        "rubric."
    ),
)

DEPENDENT_RUBRIC_GRADING_GUIDANCE: tuple[str, ...] = (
    "Dependent rubric grading guidance",
    "- Evaluate rubric criteria in context, not as isolated keyword checks.",
    "- Do not award marks for a dependent criterion when its prerequisite claim is incorrect,",
    "  unless the rubric explicitly allows unrelated partial credit.",
    "- A substitution criterion requires substitution into the correct formula or relation;",
    "  do not award it for inserting values into an incorrect formula unless the rubric",
    "  explicitly grants follow-through credit.",
    "- Phrase, detail, justification, or identifying-description marks must refer to the",
    "  correct entity or answer required by the question and model answer.",
    "- If a detail supports a wrong entity or wrong primary answer, do not award that detail",
    "  as credit for the correct-answer detail criterion.",
    "- Example: if the question asks for the capital of Bangladesh plus an identifying phrase,",
    "  and the student says Chittagong is the capital and it is a major port city, award no",
    "  identifying-phrase marks for describing Chittagong because the prerequisite capital",
    "  answer is wrong; the phrase must identify or describe Dhaka.",
)


REAL_GRADING_SYSTEM_PROMPT = """You are a grading assistant. Produce a grade suggestion only.
Teacher final review is always required. Do not create a final grade.
Do not invent answer content. If supplied evidence is unclear or incomplete,
lower confidence and explain the uncertainty. Output only strict JSON matching the requested schema.
"""


def get_prompt_version(policy: ModelPolicy) -> str:
    return PROMPT_VERSIONS[policy]


def build_marking_policy_instruction(marking_policy: str) -> str:
    normalized_policy = marking_policy.strip().lower()
    return "\n".join(
        MARKING_POLICY_INSTRUCTIONS.get(normalized_policy, MARKING_POLICY_INSTRUCTIONS["general"])
    )


def build_handwritten_math_stat_guidance() -> str:
    return "\n".join(HANDWRITTEN_MATH_STAT_GRADING_GUIDANCE)


def build_dependent_rubric_guidance() -> str:
    return "\n".join(DEPENDENT_RUBRIC_GRADING_GUIDANCE)


def build_semantic_equivalence_guidance() -> str:
    return "\n".join(SEMANTIC_EQUIVALENCE_GRADING_GUIDANCE)


def build_grading_prompt(
    *,
    question_text: str,
    rubric_json: dict[str, Any],
    answer_image_path: str,
    image_input_enabled: bool,
    student_answer_text: str | None = None,
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
            "Do not claim handwriting/image understanding. Use the teacher-confirmed "
            "student answer text below as the assessable answer evidence."
        )
    manual_answer_text = (student_answer_text or "").strip()
    answer_text_block = (
        manual_answer_text or "Not supplied. Do not infer answer content from the image path."
    )
    normalized_policy = marking_policy.strip().lower()
    policy_instruction = build_marking_policy_instruction(normalized_policy)
    math_stat_guidance = build_handwritten_math_stat_guidance()
    dependent_rubric_guidance = build_dependent_rubric_guidance()
    semantic_equivalence_guidance = build_semantic_equivalence_guidance()
    user_prompt = f"""
Task: answer_region_grading
<question>
{question_text}
</question>

<model_answer_reference_only>
{model_answer}
</model_answer_reference_only>

<rubric>
{rubric_json}
</rubric>

Image evidence path label:
{answer_image_path}

Teacher-confirmed student answer text:
<teacher_confirmed_student_answer>
{answer_text_block}
</teacher_confirmed_student_answer>

Image instructions:
{image_note}

Marking policy: {normalized_policy}
Policy instructions:
{policy_instruction}

Math/stat grading guidance:
{math_stat_guidance}

Dependent rubric grading guidance:
{dependent_rubric_guidance}

Semantic equivalence grading guidance:
{semantic_equivalence_guidance}

Do not change max_score, rubric criterion max_marks, or teacher-review requirements
because of policy. Include marking_policy:{normalized_policy} in review_flags.

Return strict JSON with these fields:
score, max_score, confidence, needs_review, rubric_breakdown, detected_answer_summary,
major_errors, feedback_to_student, review_flags.
Every rubric_breakdown item must include criterion_id, criterion, criterion_status, max_marks,
awarded_marks, reason, evidence, confidence. criterion_status must be met, partially_met, or
not_met. A not_met criterion must receive zero. Never award a criterion that is absent from or
contradicted by the teacher-confirmed student answer. For every positive award, evidence must be
a short verbatim substring copied only from <teacher_confirmed_student_answer>; do not add a
label, explanation, or text from the model answer. Use null evidence for zero awards. Before
returning, verify that every credited claim is actually present in the student answer and that
the awarded marks sum to score. Set needs_review=true and include
teacher_review_required in review_flags. This is a suggestion only; teacher final review
is required.
"""
    return [
        {"role": "system", "content": REAL_GRADING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
