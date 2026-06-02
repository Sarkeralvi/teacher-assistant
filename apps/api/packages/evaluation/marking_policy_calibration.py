from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

POLICIES: tuple[str, ...] = ("tough", "general", "easy")


@dataclass(frozen=True)
class CalibrationCase:
    case_id: str
    title: str
    description: str
    rubric_json: dict[str, Any]
    max_score: Decimal
    notes: str


@dataclass(frozen=True)
class CalibrationScore:
    score: Decimal
    confidence: Decimal
    needs_review: bool = True


_SYNTHETIC_RUBRIC = {
    "total_marks": "10.00",
    "model_answer": (
        "A complete answer explains the idea clearly and shows enough working to justify the "
        "result."
    ),
    "criteria": [
        {
            "id": "method",
            "name": "Method",
            "description": "Uses a valid method and applies it correctly.",
            "max_marks": "4.00",
        },
        {
            "id": "working",
            "name": "Working",
            "description": "Shows the key working or reasoning steps.",
            "max_marks": "3.00",
        },
        {
            "id": "answer",
            "name": "Final answer",
            "description": "Arrives at the correct final answer and uses clear notation.",
            "max_marks": "3.00",
        },
    ],
}

_CALIBRATION_CASES: tuple[CalibrationCase, ...] = (
    CalibrationCase(
        case_id="case_a_correct_final_answer_weak_working",
        title="Correct final answer, weak/no working",
        description=(
            "Synthetic non-student example: the final answer is correct, but the response shows "
            "very little working and only a short justification."
        ),
        rubric_json=_SYNTHETIC_RUBRIC,
        max_score=Decimal("10.00"),
        notes="Ambiguous enough that policy strictness should visibly change the score.",
    ),
    CalibrationCase(
        case_id="case_b_partial_method_one_wrong_step",
        title="Partially correct method with one wrong step",
        description=(
            "Synthetic non-student example: the method is mostly correct, but one algebraic or "
            "reasoning step is wrong or missing."
        ),
        rubric_json=_SYNTHETIC_RUBRIC,
        max_score=Decimal("10.00"),
        notes="The score should move upward as the policy becomes more generous.",
    ),
    CalibrationCase(
        case_id="case_c_minor_notation_issue",
        title="Mostly complete answer with minor notation issue",
        description=(
            "Synthetic non-student example: the answer is almost complete, with only a minor "
            "notation, wording, or presentation issue that should not dominate the grade."
        ),
        rubric_json=_SYNTHETIC_RUBRIC,
        max_score=Decimal("10.00"),
        notes="Optional check that easy remains slightly more generous than general.",
    ),
)

_FAKE_SCORE_TABLE: dict[str, dict[str, CalibrationScore]] = {
    "case_a_correct_final_answer_weak_working": {
        "tough": CalibrationScore(score=Decimal("3.0"), confidence=Decimal("0.72")),
        "general": CalibrationScore(score=Decimal("5.0"), confidence=Decimal("0.82")),
        "easy": CalibrationScore(score=Decimal("7.0"), confidence=Decimal("0.88")),
    },
    "case_b_partial_method_one_wrong_step": {
        "tough": CalibrationScore(score=Decimal("2.0"), confidence=Decimal("0.70")),
        "general": CalibrationScore(score=Decimal("4.0"), confidence=Decimal("0.80")),
        "easy": CalibrationScore(score=Decimal("6.0"), confidence=Decimal("0.86")),
    },
    "case_c_minor_notation_issue": {
        "tough": CalibrationScore(score=Decimal("7.0"), confidence=Decimal("0.84")),
        "general": CalibrationScore(score=Decimal("8.0"), confidence=Decimal("0.90")),
        "easy": CalibrationScore(score=Decimal("9.0"), confidence=Decimal("0.95")),
    },
}

_MATH_STAT_RUBRIC = {
    "total_marks": "6.00",
    "model_answer": (
        "Use the correct Bayes/probability formula, identify numerator and denominator "
        "events, substitute given probabilities correctly, and present the final probability "
        "or an equivalent expression."
    ),
    "criteria": [
        {
            "id": "formula_events",
            "name": "Formula and events",
            "description": "Chooses the correct formula and identifies the relevant events.",
            "max_marks": "2.00",
        },
        {
            "id": "substitution_working",
            "name": "Substitution and working",
            "description": (
                "Substitutes the correct numerator and denominator terms and shows "
                "enough working."
            ),
            "max_marks": "2.00",
        },
        {
            "id": "answer_interpretation",
            "name": "Answer and interpretation",
            "description": (
                "Gives the final probability or equivalent expression with reasonable notation."
            ),
            "max_marks": "2.00",
        },
    ],
}

_MATH_STAT_CASES: tuple[CalibrationCase, ...] = (
    CalibrationCase(
        case_id="math_stat_a_bayes_correct_setup_compact_working",
        title="Bayes setup correct with compact handwritten working",
        description=(
            "Synthetic non-student example: Bayes formula present, denominator correctly "
            "structured, numerator/substitution mostly correct, and final answer or equivalent "
            "expression present, but handwriting/presentation is imperfect."
        ),
        rubric_json=_MATH_STAT_RUBRIC,
        max_score=Decimal("6.00"),
        notes="Expected behavior: near full credit, not a severe 3/6-style under-score.",
    ),
    CalibrationCase(
        case_id="math_stat_b_correct_formula_arithmetic_slip",
        title="Correct formula with arithmetic slip",
        description=(
            "Synthetic non-student example: the correct probability/statistics formula and "
            "events are used, but one arithmetic simplification is wrong."
        ),
        rubric_json=_MATH_STAT_RUBRIC,
        max_score=Decimal("6.00"),
        notes=(
            "Expected behavior: meaningful partial credit because the concept and setup "
            "are right."
        ),
    ),
    CalibrationCase(
        case_id="math_stat_c_wrong_conceptual_setup",
        title="Wrong conceptual setup",
        description=(
            "Synthetic non-student example: uses an independence/product assumption or wrong "
            "conditional event where Bayes/total probability is required."
        ),
        rubric_json=_MATH_STAT_RUBRIC,
        max_score=Decimal("6.00"),
        notes="Expected behavior: low score because the conceptual setup is wrong.",
    ),
    CalibrationCase(
        case_id="math_stat_d_bayes_score_band_near_full_credit",
        title="Bayes score-band near-full credit target",
        description=(
            "Synthetic non-student example: Bayes formula, target/evidence events, and "
            "denominator expansion are visible; numerator or final posterior expression is "
            "compact or slightly unclear, but no conditional-probability reversal appears."
        ),
        rubric_json=_MATH_STAT_RUBRIC,
        max_score=Decimal("6.00"),
        notes=(
            "Expected behavior: score-band guidance should place this in the 5-6/6 range, "
            "not mid-credit, when the concept is correct."
        ),
    ),
)

_FAKE_MATH_STAT_SCORE_TABLE: dict[str, dict[str, Any]] = {
    "math_stat_a_bayes_correct_setup_compact_working": {
        "fake_score": Decimal("5.5"),
        "confidence": Decimal("0.78"),
        "expected_behavior": "near_full_credit",
        "severe_underscore": False,
    },
    "math_stat_b_correct_formula_arithmetic_slip": {
        "fake_score": Decimal("4.0"),
        "confidence": Decimal("0.74"),
        "expected_behavior": "meaningful_partial_credit",
        "severe_underscore": False,
    },
    "math_stat_c_wrong_conceptual_setup": {
        "fake_score": Decimal("1.5"),
        "confidence": Decimal("0.80"),
        "expected_behavior": "low_score",
        "severe_underscore": False,
    },
    "math_stat_d_bayes_score_band_near_full_credit": {
        "fake_score": Decimal("5.5"),
        "confidence": Decimal("0.76"),
        "expected_behavior": "bayes_score_band_5_to_6",
        "severe_underscore": False,
    },
}


def build_synthetic_math_stat_grading_cases() -> list[CalibrationCase]:
    return list(_MATH_STAT_CASES)


def _run_fake_math_stat_calibration() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for case in build_synthetic_math_stat_grading_cases():
        row = _FAKE_MATH_STAT_SCORE_TABLE[case.case_id]
        cases.append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "description": case.description,
                "notes": case.notes,
                "max_score": case.max_score,
                "fake_score": row["fake_score"],
                "confidence": row["confidence"],
                "needs_review": True,
                "expected_behavior": row["expected_behavior"],
                "severe_underscore": row["severe_underscore"],
            }
        )
    first_case = cases[0]
    return {
        "provider_mode": "fake",
        "real_provider_used": False,
        "call_count": 0,
        "final_grade_count": 0,
        "case_count": len(cases),
        "cases": cases,
        "summary": {
            "bayes_compact_working_not_severely_under_scored": (
                first_case["fake_score"] >= Decimal("5.0")
                and first_case["severe_underscore"] is False
            ),
            "correct_formula_arithmetic_slip_gets_partial_credit": cases[1]["fake_score"]
            >= Decimal("3.0"),
            "wrong_conceptual_setup_stays_low": cases[2]["fake_score"] <= Decimal("2.0"),
            "bayes_score_band_case_gets_5_to_6": Decimal("5.0")
            <= cases[3]["fake_score"]
            <= Decimal("6.0"),
        },
    }


def build_synthetic_marking_policy_cases() -> list[CalibrationCase]:
    return list(_CALIBRATION_CASES)


class MarkingPolicyCalibrationError(RuntimeError):
    pass


class MarkingPolicyCalibrationRunner:
    def __init__(
        self,
        *,
        provider_mode: str = "fake",
        allow_real_provider: bool = False,
        max_real_calls: int = 6,
    ) -> None:
        self.provider_mode = provider_mode
        self.allow_real_provider = allow_real_provider
        self.max_real_calls = max_real_calls

    def run(self) -> dict[str, Any]:
        if self.provider_mode != "fake":
            if not self.allow_real_provider:
                raise MarkingPolicyCalibrationError(
                    "Real provider calibration is disabled; set "
                    "TA_EVAL_ALLOW_REAL_PROVIDER=true to enable it."
                )
            raise MarkingPolicyCalibrationError(
                "Real provider calibration is not wired for this lightweight harness; "
                "use the existing grading evaluation runner instead."
            )

        cases = build_synthetic_marking_policy_cases()
        case_results: list[dict[str, Any]] = []
        call_count = 0
        monotonic_ordering = True
        meaningful_separation = True
        adjacent_gap_threshold = Decimal("1.00")
        score_summary: dict[str, list[Decimal]] = {policy: [] for policy in POLICIES}

        for case in cases:
            policy_rows: dict[str, CalibrationScore] = {}
            for policy in POLICIES:
                score = _FAKE_SCORE_TABLE[case.case_id][policy]
                policy_rows[policy] = score
                score_summary[policy].append(score.score)
            call_count += 0
            tough_score = policy_rows["tough"].score
            general_score = policy_rows["general"].score
            easy_score = policy_rows["easy"].score
            if not (tough_score <= general_score <= easy_score):
                monotonic_ordering = False
            if not (
                general_score - tough_score >= adjacent_gap_threshold
                and easy_score - general_score >= adjacent_gap_threshold
            ):
                meaningful_separation = False
            case_results.append(
                {
                    "case_id": case.case_id,
                    "title": case.title,
                    "description": case.description,
                    "notes": case.notes,
                    "max_score": case.max_score,
                    "policy_scores": {
                        policy: {
                            "score": row.score,
                            "confidence": row.confidence,
                            "needs_review": row.needs_review,
                        }
                        for policy, row in policy_rows.items()
                    },
                    "adjacent_gap_threshold": adjacent_gap_threshold,
                    "tough_general_gap": general_score - tough_score,
                    "general_easy_gap": easy_score - general_score,
                    "ordering_holds": tough_score <= general_score <= easy_score,
                    "meaningful_separation_holds": (
                        general_score - tough_score >= adjacent_gap_threshold
                        and easy_score - general_score >= adjacent_gap_threshold
                    ),
                }
            )

        policy_averages = {
            policy: _mean(scores) for policy, scores in score_summary.items()
        }
        return {
            "provider_mode": self.provider_mode,
            "allow_real_provider": self.allow_real_provider,
            "call_count": call_count,
            "max_real_calls": self.max_real_calls,
            "case_count": len(cases),
            "policies": list(POLICIES),
            "monotonic_ordering": monotonic_ordering,
            "meaningful_separation": meaningful_separation,
            "adjacent_gap_threshold": adjacent_gap_threshold,
            "policy_averages": policy_averages,
            "cases": case_results,
            "math_stat_calibration": _run_fake_math_stat_calibration(),
            "real_provider_used": False,
            "final_grade_count": 0,
        }


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TA marking policy calibration")
    parser.add_argument("--provider-mode", default="fake")
    parser.add_argument(
        "--allow-real-provider",
        action="store_true",
        default=False,
        help="Allow real-provider calibration; fake mode remains the default.",
    )
    parser.add_argument("--max-real-calls", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    runner = MarkingPolicyCalibrationRunner(
        provider_mode=args.provider_mode,
        allow_real_provider=args.allow_real_provider,
        max_real_calls=args.max_real_calls,
    )
    print(json.dumps(_jsonable(runner.run()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
