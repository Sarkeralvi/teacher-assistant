#!/usr/bin/env python3
"""Seed a teacher-graded evaluation case into the grading eval fixture set.

Given an answer_region_id and the score the teacher actually awarded, this
resolves the question, active rubric, and max_score from the database,
validates the case against the harness schema, and appends it to
apps/api/packages/evaluation/fixtures/grading/teacher_eval_cases.json.

Usage (inside the backend container):
    docker compose exec backend python scripts/seed_eval_case.py \
        --answer-region-id 42 --expected-score 3.5 --answer-type partial \
        --notes "Student dropped a negative in step 2."
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models import AnswerRegion, Question, Rubric  # noqa: E402
from app.services.grading_service import GradingService  # noqa: E402
from packages.evaluation.grading_evaluation import EvaluationCase  # noqa: E402

DEFAULT_FIXTURE_PATH = (
    API_ROOT / "packages" / "evaluation" / "fixtures" / "grading" / "teacher_eval_cases.json"
)
ANSWER_TYPES = ("correct", "partial", "wrong", "blank", "irrelevant", "unknown")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--answer-region-id", type=int, required=True)
    parser.add_argument(
        "--expected-score",
        required=True,
        help="Score the teacher actually awarded, e.g. 3.5",
    )
    parser.add_argument("--notes", default="", help="Why this score: where the student went wrong")
    parser.add_argument("--answer-type", choices=ANSWER_TYPES, default="unknown")
    parser.add_argument("--case-id", default=None, help="Defaults to teacher_ar<answer_region_id>")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument(
        "--replace", action="store_true", help="Overwrite an existing case with the same case_id"
    )
    return parser.parse_args()


def build_case(args: argparse.Namespace) -> EvaluationCase:
    try:
        expected_score = Decimal(args.expected_score)
    except InvalidOperation:
        sys.exit(f"--expected-score is not a valid decimal: {args.expected_score!r}")
    with SessionLocal() as db:
        region = db.get(AnswerRegion, args.answer_region_id)
        if region is None:
            sys.exit(f"AnswerRegion not found: {args.answer_region_id}")
        question = db.get(Question, region.question_id)
        if question is None:
            sys.exit(f"Question not found for answer region: {region.question_id}")
        rubric = (
            db.query(Rubric)
            .filter(Rubric.question_id == question.id, Rubric.is_active.is_(True))
            .order_by(Rubric.version.desc())
            .first()
        )
        if rubric is None:
            sys.exit(
                f"No active rubric for question {question.id}. "
                "Create/activate a rubric in the rubric editor first."
            )
        max_score = Decimal(str(rubric.rubric_json.get("total_marks")))
        if expected_score > max_score:
            sys.exit(f"expected_score {expected_score} exceeds rubric total_marks {max_score}")
        packet = GradingService(db).get_grading_evidence_packet(region.id)
        readiness = packet.get("readiness_result")
        if isinstance(readiness, dict) and not readiness.get("ready_for_grading"):
            print(
                "Warning: evidence packet not ready for grading yet; the harness will "
                f"fail on this case until resolved: {', '.join(readiness.get('blockers', []))}",
                file=sys.stderr,
            )
        return EvaluationCase(
            case_id=args.case_id or f"teacher_ar{region.id}",
            answer_region_id=region.id,
            question_id=question.id,
            rubric_id=rubric.id,
            expected_score=expected_score,
            max_score=max_score,
            teacher_notes=args.notes,
            answer_type=args.answer_type,
            question_text=question.question_text,
            model_answer=question.model_answer or "",
            rubric=rubric.rubric_json,
        )


def main() -> None:
    args = parse_args()
    case = build_case(args)

    fixture_path: Path = args.fixture
    if fixture_path.exists():
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        cases = document["cases"] if isinstance(document, dict) else document
    else:
        cases = []
    existing_index = next(
        (i for i, item in enumerate(cases) if item.get("case_id") == case.case_id), None
    )
    if existing_index is not None and not args.replace:
        sys.exit(f"Case {case.case_id!r} already exists in {fixture_path}. Use --replace.")
    duplicate_region = any(
        item.get("answer_region_id") == case.answer_region_id
        and item.get("case_id") != case.case_id
        for item in cases
    )
    if duplicate_region:
        print(
            f"Warning: answer_region_id {case.answer_region_id} already appears "
            "under a different case_id.",
            file=sys.stderr,
        )

    payload = case.model_dump(mode="json")
    if existing_index is not None:
        cases[existing_index] = payload
    else:
        cases.append(payload)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps({"cases": cases}, indent=2), encoding="utf-8")

    print(f"Wrote case {case.case_id!r} ({len(cases)} total) to {fixture_path}")
    print(
        "Run the harness (mock provider by default):\n"
        "  docker compose exec backend python -m packages.evaluation.grading_evaluation "
        f"{fixture_path}"
    )


if __name__ == "__main__":
    main()
