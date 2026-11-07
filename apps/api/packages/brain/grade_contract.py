"""Provider-neutral checks every real grade suggestion passes before it is stored.

Until v2 these guards lived inside individual local providers, so a grade from a
cloud transport skipped them. They now run in the adapter for every real
provider:

* the question maximum and the pinned rubric's criterion ids and maxima cannot
  be changed by the model;
* credit for a criterion needs a short verbatim quote of the student's answer
  (when the grade was drafted from answer text);
* a criterion that depends on others earns nothing unless its prerequisites
  earned full marks, unless the rubric allows follow-through.

A changed maximum or rubric shape is flagged and the confidence capped, so the
draft can never pass as clean; the bulk service then quarantines that one item
(raising here would instead pause a whole cohort run). Unsupported or dependent
credit is removed, the score is recomputed from the breakdown, the confidence is
capped and a review flag explains the change. Nothing here can raise a mark.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem

ADJUSTED_CONFIDENCE_CAP = Decimal("0.75")
CONTRACT_VIOLATION_CONFIDENCE_CAP = Decimal("0.50")
UNSUPPORTED_EVIDENCE_FLAG = "unsupported_criterion_evidence_removed"
DEPENDENT_CREDIT_FLAG = "dependent_criterion_credit_removed"
MAXIMUM_CHANGED_FLAG = "question_maximum_changed_by_model"
RUBRIC_SHAPE_FLAG = "rubric_criteria_changed_by_model"
MIN_EVIDENCE_CHARS = 3
MODEL_SCORE_FLAG_PREFIX = "model_score_before_checks:"


class GradeContractError(ValueError):
    """A grade suggestion changed something the pinned rubric fixes."""


def enforce_grade_contract(
    output: GradeSuggestionOutput,
    *,
    question_total_marks: Decimal,
    rubric_json: dict[str, Any],
    student_answer_text: str | None,
    evidence_text_required: bool = True,
) -> GradeSuggestionOutput:
    """``evidence_text_required`` is true whenever the grader saw text only (no image).

    Then every credited criterion must quote that text, and an empty or missing
    answer text can support no credit at all.
    """
    flags = list(output.review_flags)
    violated = False
    if Decimal(output.max_score) != Decimal(question_total_marks):
        violated = True
        flags.append(MAXIMUM_CHANGED_FLAG)

    items = [item.model_copy() for item in output.rubric_breakdown]
    aligned = True
    expected = _expected_criteria(rubric_json)
    if expected:
        try:
            items = _align_to_rubric(items, expected)
        except GradeContractError:
            aligned = False
            violated = True
            flags.append(RUBRIC_SHAPE_FLAG)

    if violated:
        # A draft on the wrong scale or rubric is stored exactly as the model wrote
        # it, flagged and never clean, so the bulk quarantine and the teacher see
        # what actually came back. Credit is adjusted only on a consistent draft.
        return GradeSuggestionOutput.model_validate(
            {
                **output.model_dump(),
                "confidence": min(output.confidence, CONTRACT_VIOLATION_CONFIDENCE_CAP),
                "review_flags": list(dict.fromkeys(flags)),
            }
        )

    changed = False
    answer_text = student_answer_text or ""
    if evidence_text_required or answer_text.strip():
        if _remove_unsupported_credit(items, answer_text):
            changed = True
            flags.append(UNSUPPORTED_EVIDENCE_FLAG)
    # Dependencies are keyed by criterion id, so they need the rubric's own ids.
    if aligned and _remove_dependent_credit(items, rubric_json):
        changed = True
        flags.append(DEPENDENT_CREDIT_FLAG)
    if not changed and items == list(output.rubric_breakdown):
        return output
    if changed:
        # Keep the model's own total visible, so a reviewer (and the eval) can tell
        # marks the model withheld from marks these checks removed.
        flags.append(f"{MODEL_SCORE_FLAG_PREFIX}{output.score}")
    confidence = min(output.confidence, ADJUSTED_CONFIDENCE_CAP) if changed else output.confidence
    return GradeSuggestionOutput.model_validate(
        {
            **output.model_dump(),
            "score": sum((item.awarded_marks for item in items), Decimal("0")),
            "confidence": confidence,
            "rubric_breakdown": [item.model_dump() for item in items],
            "review_flags": list(dict.fromkeys(flags)),
        }
    )


def _expected_criteria(rubric_json: dict[str, Any]) -> dict[str, Decimal | None]:
    criteria = rubric_json.get("criteria")
    if not isinstance(criteria, list):
        return {}
    expected: dict[str, Decimal | None] = {}
    for item in criteria:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        criterion_id = str(item.get("id")).strip()
        if not criterion_id:
            continue
        expected[criterion_id] = _decimal_or_none(item.get("max_marks"))
    return expected


def _align_to_rubric(
    items: list[RubricBreakdownItem],
    expected: dict[str, Decimal | None],
) -> list[RubricBreakdownItem]:
    canonical = {_id_key(criterion_id): criterion_id for criterion_id in expected}
    if len(canonical) != len(expected):
        raise GradeContractError("The pinned rubric has ambiguous criterion ids")
    seen: set[str] = set()
    aligned: list[RubricBreakdownItem] = []
    for item in items:
        key = _id_key(item.criterion_id)
        criterion_id = canonical.get(key)
        if criterion_id is None:
            raise GradeContractError("The grade names a criterion that is not in the pinned rubric")
        if key in seen:
            raise GradeContractError("The grade lists a rubric criterion more than once")
        seen.add(key)
        maximum = expected[criterion_id]
        if maximum is not None and item.max_marks != maximum:
            raise GradeContractError("The model changed a pinned rubric criterion maximum")
        aligned.append(
            item if item.criterion_id == criterion_id
            else item.model_copy(update={"criterion_id": criterion_id})
        )
    if seen != set(canonical):
        raise GradeContractError("The grade does not cover every pinned rubric criterion")
    return aligned


def _remove_unsupported_credit(
    items: list[RubricBreakdownItem], student_answer_text: str
) -> bool:
    changed = False
    for index, item in enumerate(items):
        if item.awarded_marks <= 0:
            continue
        if evidence_is_verbatim_student_text(item.evidence, student_answer_text):
            continue
        items[index] = item.model_copy(
            update={
                "awarded_marks": Decimal("0"),
                "confidence": min(item.confidence, ADJUSTED_CONFIDENCE_CAP),
            }
        )
        changed = True
    return changed


def _remove_dependent_credit(
    items: list[RubricBreakdownItem], rubric_json: dict[str, Any]
) -> bool:
    criteria = rubric_json.get("criteria")
    if not isinstance(criteria, list):
        return False
    requirements: dict[str, tuple[str, ...]] = {}
    for criterion in criteria:
        if not isinstance(criterion, dict) or criterion.get("id") is None:
            continue
        if bool(criterion.get("allow_follow_through", False)):
            continue
        dependencies = criterion.get("depends_on") or []
        if not isinstance(dependencies, list):
            continue
        requirements[str(criterion.get("id")).strip()] = tuple(
            str(dependency).strip() for dependency in dependencies
        )
    if not any(requirements.values()):
        return False
    position = {item.criterion_id: index for index, item in enumerate(items)}
    changed = False
    pending = True
    while pending:
        pending = False
        for criterion_id, dependency_ids in requirements.items():
            index = position.get(criterion_id)
            if index is None or not dependency_ids or items[index].awarded_marks <= 0:
                continue
            prerequisites_met = all(
                dependency_id in position
                and items[position[dependency_id]].awarded_marks
                == items[position[dependency_id]].max_marks
                for dependency_id in dependency_ids
            )
            if prerequisites_met:
                continue
            items[index] = items[index].model_copy(
                update={
                    "awarded_marks": Decimal("0"),
                    "confidence": min(items[index].confidence, ADJUSTED_CONFIDENCE_CAP),
                }
            )
            changed = True
            pending = True
    return changed


def evidence_is_verbatim_student_text(evidence: str | None, student_answer_text: str) -> bool:
    if not (evidence or "").strip():
        return False
    candidate = str(evidence).strip()
    candidate = re.sub(
        r"(?i)^\s*(?:student(?:'s)?\s+(?:answer|work)|answer|evidence)\s*:\s*",
        "",
        candidate,
    ).strip()
    candidate = candidate.strip("'\"`“”‘’ ")
    normalized_candidate = _normalize_evidence_text(candidate)
    normalized_answer = _normalize_evidence_text(student_answer_text)
    if not normalized_candidate or normalized_candidate not in normalized_answer:
        return False
    # A one- or two-character quote ("2", "x", "=") appears in almost any answer
    # and proves nothing, unless it is the student's entire answer.
    return (
        len(normalized_candidate) >= MIN_EVIDENCE_CHARS
        or normalized_candidate == normalized_answer
    )


def _normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = normalized.replace("×", "x").replace("−", "-")
    return " ".join(normalized.split()).strip(" .;,'\"`“”‘’")


def _id_key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
