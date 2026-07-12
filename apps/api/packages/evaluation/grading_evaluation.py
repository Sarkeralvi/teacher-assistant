from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AnswerRegion,
    Assessment,
    Course,
    GradeSuggestion,
    Question,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.services.grading_service import GradingService
from app.services.storage import LocalStorage
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem

_FALSE_CONFIDENT_THRESHOLD = Decimal("0.8")
_FALSE_CONFIDENT_ERROR_MARKS = Decimal("1")
_DEFAULT_MAX_REAL_CASES = 5
_REAL_PROVIDER_MODES = {"codex_cli", "openai"}


class GradingEvaluationError(RuntimeError):
    """Raised when an evaluation run would violate safety constraints."""


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    answer_region_id: int = Field(gt=0)
    question_id: int = Field(gt=0)
    rubric_id: int = Field(gt=0)
    expected_score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    teacher_notes: str = ""
    answer_type: str = Field(
        default="unknown", pattern="^(correct|partial|wrong|blank|irrelevant|unknown)$"
    )
    generated_fixture_reference: str | None = None
    question_text: str = ""
    model_answer: str = ""
    rubric: dict[str, Any] | None = None

    @field_validator("expected_score")
    @classmethod
    def expected_score_cannot_exceed_large_bound(cls, value: Decimal) -> Decimal:
        return value


@dataclass(frozen=True)
class EvaluationArtifactPaths:
    json_path: Path
    markdown_path: Path


class GradingEvaluationRunner:
    def __init__(
        self,
        *,
        provider_mode: str = "mock",
        allow_real_provider: bool = False,
        max_real_cases: int = _DEFAULT_MAX_REAL_CASES,
        output_dir: Path | None = None,
        marking_policy: str = "general",
    ) -> None:
        self.provider_mode = provider_mode.strip().lower() or "mock"
        self.allow_real_provider = allow_real_provider
        self.max_real_cases = max_real_cases
        self.marking_policy = self._normalize_marking_policy(marking_policy)
        self.output_dir = output_dir or (
            Path(get_settings().local_storage_root) / "exports" / "grading_evals"
        )

    def validate_provider_mode(self, cases: list[EvaluationCase]) -> None:
        if self.provider_mode in _REAL_PROVIDER_MODES and not self.allow_real_provider:
            raise GradingEvaluationError(
                "Real provider evaluation must be explicitly enabled with "
                "TA_EVAL_ALLOW_REAL_PROVIDER=true."
            )
        if self.provider_mode in _REAL_PROVIDER_MODES and len(cases) > self.max_real_cases:
            raise GradingEvaluationError(
                f"Real provider evaluation is limited to at most {self.max_real_cases} real cases."
            )

    def run(self, db: Session, cases: list[EvaluationCase]) -> dict[str, Any]:
        self.validate_provider_mode(cases)
        previous_provider = os.environ.get("BRAIN_PROVIDER")
        os.environ["BRAIN_PROVIDER"] = self.provider_mode
        get_settings.cache_clear()
        try:
            rows: list[dict[str, Any]] = []
            service = GradingService(db)
            for eval_case in cases:
                self._validate_case_records(db, eval_case)
                job, suggestion = service.grade_answer_region(
                    eval_case.answer_region_id, marking_policy=self.marking_policy
                )
                output = _suggestion_output_from_record(suggestion)
                absolute_error = abs(Decimal(suggestion.score or 0) - eval_case.expected_score)
                rows.append(
                    {
                        "case": eval_case,
                        "suggestion": output,
                        "grading_job_id": job.id,
                        "grade_suggestion_id": suggestion.id,
                        "absolute_error": absolute_error,
                        "model_provider": suggestion.model_provider,
                        "model_name": suggestion.model_name,
                        "prompt_version": suggestion.prompt_version,
                        "marking_policy": suggestion.marking_policy,
                    }
                )
            result = {
                "run_id": datetime.now(UTC).strftime("grading-eval-%Y%m%dT%H%M%SZ"),
                "created_at": datetime.now(UTC).isoformat(),
                "provider_mode": self.provider_mode,
                "marking_policy": self.marking_policy,
                "case_count": len(cases),
                "metrics": calculate_metrics(rows),
                "cases": [_serialize_case_result(row) for row in rows],
            }
            paths = write_evaluation_artifacts(result, self.output_dir)
            result["artifact_json_path"] = str(paths.json_path)
            result["artifact_markdown_path"] = str(paths.markdown_path)
            return result
        finally:
            if previous_provider is None:
                os.environ.pop("BRAIN_PROVIDER", None)
            else:
                os.environ["BRAIN_PROVIDER"] = previous_provider
            get_settings.cache_clear()

    @staticmethod
    def _normalize_marking_policy(marking_policy: str) -> str:
        policy = marking_policy.strip().lower()
        return policy if policy in {"tough", "general", "easy"} else "general"

    @staticmethod
    def _validate_case_records(db: Session, eval_case: EvaluationCase) -> None:
        region = db.get(AnswerRegion, eval_case.answer_region_id)
        if region is None:
            raise GradingEvaluationError(f"AnswerRegion not found: {eval_case.answer_region_id}")
        if region.question_id != eval_case.question_id:
            raise GradingEvaluationError(
                f"Case {eval_case.case_id} question_id does not match AnswerRegion.question_id"
            )
        rubric = db.get(Rubric, eval_case.rubric_id)
        if rubric is None:
            raise GradingEvaluationError(f"Rubric not found: {eval_case.rubric_id}")
        if rubric.question_id != eval_case.question_id or not rubric.is_active:
            raise GradingEvaluationError(
                f"Case {eval_case.case_id} rubric is not active for the case question"
            )
        if Decimal(str(rubric.rubric_json.get("total_marks"))) != eval_case.max_score:
            raise GradingEvaluationError(
                f"Case {eval_case.case_id} max_score does not match active rubric total_marks"
            )


def _suggestion_output_from_record(suggestion: GradeSuggestion) -> GradeSuggestionOutput:
    """Normalize a stored grade suggestion into the strict provider output schema.

    Providers currently persist a loose grade_result dict in raw_response_json, so
    fall back to the structured GradeSuggestion columns when strict validation fails.
    """
    raw = suggestion.raw_response_json or {}
    try:
        return GradeSuggestionOutput.model_validate(raw)
    except ValidationError:
        pass
    score = Decimal(str(suggestion.score or 0))
    max_score = Decimal(str(suggestion.max_score or 0))
    confidence = Decimal(str(suggestion.confidence or 0))
    review_flags = list(dict.fromkeys(str(flag) for flag in raw.get("review_flags") or []))
    feedback = (suggestion.feedback or "").strip() or "(no feedback recorded)"
    return GradeSuggestionOutput(
        score=score,
        max_score=max_score,
        confidence=confidence,
        needs_review=bool(suggestion.needs_review),
        rubric_breakdown=[
            RubricBreakdownItem(
                criterion_id="total",
                criterion="Total (reconstructed from stored suggestion)",
                max_marks=max_score,
                awarded_marks=score,
                reason="Raw provider output is not schema-compliant; using stored totals.",
                confidence=confidence,
            )
        ],
        detected_answer_summary=feedback,
        major_errors=[str(item) for item in raw.get("major_errors") or []],
        feedback_to_student=feedback,
        review_flags=review_flags or ["raw_output_not_schema_compliant"],
        model_provider=suggestion.model_provider or "unknown",
        model_name=suggestion.model_name or "unknown",
        prompt_version=suggestion.prompt_version or "unknown",
    )


def load_evaluation_cases(path: Path) -> list[EvaluationCase]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
        payloads = loaded["cases"] if isinstance(loaded, dict) and "cases" in loaded else loaded
    if not isinstance(payloads, list):
        raise GradingEvaluationError("Evaluation dataset must be a JSON array or JSONL objects")
    return [EvaluationCase.model_validate(item) for item in payloads]


_SYNTHETIC_RUBRIC = {
    "total_marks": "5.00",
    "criteria": [
        {
            "id": "method",
            "name": "Method",
            "description": "Uses the expected method or reasoning.",
            "max_marks": "3.00",
        },
        {
            "id": "answer",
            "name": "Final answer",
            "description": "Provides the correct final answer and units where needed.",
            "max_marks": "2.00",
        },
    ],
}

_SYNTHETIC_CASE_SPECS = [
    ("correct", "5.00", "The area is 24 cm^2 because 6 x 4 = 24."),
    ("partial", "3.00", "I multiply length and width but write 20 cm^2."),
    ("wrong", "1.00", "The area is 10 cm^2 because I added 6 and 4."),
    ("blank", "0.00", ""),
    ("irrelevant", "0.00", "I like football and did not answer the maths question."),
]


def create_synthetic_grading_quality_dataset(db: Session) -> list[EvaluationCase]:
    """Create five tiny non-student grading-quality cases and generated PNG fixtures."""
    storage = LocalStorage()
    teacher = User(
        name="Synthetic Grading Teacher",
        email=f"synthetic-grading-{datetime.now(UTC).timestamp()}@example.com",
        password_hash="synthetic-fixture-only",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(
        teacher_id=teacher.id,
        code="SYN-GRD",
        title="Synthetic grading quality evaluation",
        department="Evaluation",
        semester="synthetic",
    )
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Synthetic area quiz",
        assessment_type="quiz",
        total_marks=Decimal("5.00"),
        status="ready",
    )
    db.add(assessment)
    db.flush()
    question = Question(
        assessment_id=assessment.id,
        question_no="1",
        question_text="A rectangle is 6 cm long and 4 cm wide. Find its area.",
        model_answer="Area = length x width = 6 x 4 = 24 cm^2.",
        total_marks=Decimal("5.00"),
    )
    db.add(question)
    db.flush()
    rubric = Rubric(
        question_id=question.id,
        version=1,
        rubric_json=_SYNTHETIC_RUBRIC,
        is_active=True,
    )
    db.add(rubric)
    db.flush()

    cases: list[EvaluationCase] = []
    for index, (answer_type, expected_score, answer_text) in enumerate(
        _SYNTHETIC_CASE_SPECS, start=1
    ):
        submission = Submission(
            assessment_id=assessment.id,
            student_identifier=f"SYN-{answer_type.upper()}",
            student_name=f"Synthetic {answer_type.title()} Answer",
            status="ready",
        )
        db.add(submission)
        db.flush()
        page_file = storage.page_image_path(submission.id, 1)
        region_file = storage.answer_region_image_path(submission.id)
        _write_synthetic_answer_image(
            page_file.absolute_path,
            answer_type=answer_type,
            answer_text=answer_text or "[blank answer]",
        )
        _write_synthetic_answer_image(
            region_file.absolute_path,
            answer_type=answer_type,
            answer_text=answer_text or "[blank answer]",
        )
        page = SubmissionPage(
            submission_id=submission.id,
            page_no=1,
            image_path=page_file.relative_path,
            quality_score=Decimal("1.0000"),
        )
        db.add(page)
        db.flush()
        region = AnswerRegion(
            submission_id=submission.id,
            question_id=question.id,
            page_id=page.id,
            x=Decimal("0"),
            y=Decimal("0"),
            width=Decimal("640"),
            height=Decimal("220"),
            image_path=region_file.relative_path,
        )
        db.add(region)
        db.flush()
        cases.append(
            EvaluationCase(
                case_id=f"synthetic_grading_{index:02d}_{answer_type}",
                answer_region_id=region.id,
                question_id=question.id,
                rubric_id=rubric.id,
                expected_score=Decimal(expected_score),
                max_score=Decimal("5.00"),
                teacher_notes=f"Synthetic {answer_type} answer fixture; not student data.",
                answer_type=answer_type,
                generated_fixture_reference=region_file.relative_path,
                question_text=question.question_text,
                model_answer=question.model_answer or "",
                rubric=_SYNTHETIC_RUBRIC,
            )
        )
    db.commit()
    return cases


def _write_synthetic_answer_image(path: Path, *, answer_type: str, answer_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 220), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 632, 212), outline="black", width=2)
    draw.text((24, 24), f"Synthetic {answer_type} answer", fill="black")
    y = 70
    for line in _wrap_text(answer_text, width=72):
        draw.text((24, y), line, fill="black")
        y += 26
    image.save(path, format="PNG")


def _wrap_text(text: str, *, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if sum(len(item) for item in current) + len(current) + len(word) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Decimal | int]:
    if not rows:
        return {
            "case_count": 0,
            "exact_match_rate": Decimal("0"),
            "within_1_mark_rate": Decimal("0"),
            "mean_absolute_error": Decimal("0"),
            "false_confident_error_count": 0,
            "average_confidence": Decimal("0"),
            "needs_review_rate": Decimal("0"),
            "severe_error_count": 0,
            "over_score_count": 0,
            "under_score_count": 0,
            "by_answer_type": {},
        }
    errors = [_row_error(row) for row in rows]
    confidences = [_row_confidence(row) for row in rows]
    needs_review_count = sum(1 for row in rows if _row_suggestion(row).needs_review)
    false_confident_error_count = sum(
        1
        for row, error in zip(rows, errors, strict=True)
        if _row_confidence(row) >= _FALSE_CONFIDENT_THRESHOLD
        and error > _FALSE_CONFIDENT_ERROR_MARKS
    )
    total = Decimal(len(rows))
    by_answer_type: dict[str, dict[str, Decimal | int]] = {}
    answer_types = sorted({_row_case(row).answer_type for row in rows})
    for answer_type in answer_types:
        typed_rows = [row for row in rows if _row_case(row).answer_type == answer_type]
        typed_errors = [_row_error(row) for row in typed_rows]
        typed_confidences = [_row_confidence(row) for row in typed_rows]
        typed_total = Decimal(len(typed_rows))
        by_answer_type[answer_type] = {
            "case_count": len(typed_rows),
            "exact_match_rate": Decimal(sum(1 for error in typed_errors if error == 0))
            / typed_total,
            "within_1_mark_rate": Decimal(
                sum(1 for error in typed_errors if error <= _FALSE_CONFIDENT_ERROR_MARKS)
            )
            / typed_total,
            "mean_absolute_error": sum(typed_errors, Decimal("0")) / typed_total,
            "average_confidence": sum(typed_confidences, Decimal("0")) / typed_total,
        }
    return {
        "case_count": len(rows),
        "exact_match_rate": Decimal(sum(1 for error in errors if error == 0)) / total,
        "within_1_mark_rate": Decimal(
            sum(1 for error in errors if error <= _FALSE_CONFIDENT_ERROR_MARKS)
        )
        / total,
        "mean_absolute_error": sum(errors, Decimal("0")) / total,
        "false_confident_error_count": false_confident_error_count,
        "average_confidence": sum(confidences, Decimal("0")) / total,
        "needs_review_rate": Decimal(needs_review_count) / total,
        "severe_error_count": sum(1 for error in errors if error >= Decimal("2")),
        "over_score_count": sum(
            1 for row in rows if _row_suggestion(row).score > _row_case(row).expected_score
        ),
        "under_score_count": sum(
            1 for row in rows if _row_suggestion(row).score < _row_case(row).expected_score
        ),
        "by_answer_type": by_answer_type,
    }


def write_evaluation_artifacts(result: dict[str, Any], output_dir: Path) -> EvaluationArtifactPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(result.get("run_id") or datetime.now(UTC).strftime("grading-eval-%Y%m%dT%H%M%SZ"))
    json_path = output_dir / f"{run_id}.json"
    markdown_path = output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    return EvaluationArtifactPaths(json_path=json_path, markdown_path=markdown_path)


def _serialize_case_result(row: dict[str, Any]) -> dict[str, Any]:
    eval_case = row["case"]
    suggestion = _row_suggestion(row)
    absolute_error = _row_error(row)
    return {
        "case_id": eval_case.case_id,
        "answer_region_id": eval_case.answer_region_id,
        "question_id": eval_case.question_id,
        "rubric_id": eval_case.rubric_id,
        "expected_score": eval_case.expected_score,
        "max_score": eval_case.max_score,
        "teacher_notes": eval_case.teacher_notes,
        "answer_type": eval_case.answer_type,
        "generated_fixture_reference": eval_case.generated_fixture_reference,
        "question_text": eval_case.question_text,
        "model_answer": eval_case.model_answer,
        "grade_suggestion_id": row.get("grade_suggestion_id"),
        "grading_job_id": row.get("grading_job_id"),
        "ai_score": suggestion.score,
        "ai_max_score": suggestion.max_score,
        "confidence": suggestion.confidence,
        "needs_review": suggestion.needs_review,
        "absolute_error": absolute_error,
        "false_confident_error": suggestion.confidence >= _FALSE_CONFIDENT_THRESHOLD
        and absolute_error > _FALSE_CONFIDENT_ERROR_MARKS,
        "model_provider": row.get("model_provider") or suggestion.model_provider,
        "model_name": row.get("model_name") or suggestion.model_name,
        "prompt_version": row.get("prompt_version") or suggestion.prompt_version,
        "marking_policy": row.get("marking_policy") or "general",
        "review_flags": suggestion.review_flags,
    }


def _row_case(row: dict[str, Any]) -> EvaluationCase:
    eval_case = row["case"]
    if not isinstance(eval_case, EvaluationCase):
        raise TypeError("row case must be EvaluationCase")
    return eval_case


def _row_suggestion(row: dict[str, Any]) -> GradeSuggestionOutput:
    suggestion = row["suggestion"]
    if not isinstance(suggestion, GradeSuggestionOutput):
        raise TypeError("row suggestion must be GradeSuggestionOutput")
    return suggestion


def _row_error(row: dict[str, Any]) -> Decimal:
    if "absolute_error" in row:
        return Decimal(row["absolute_error"])
    suggestion = _row_suggestion(row)
    eval_case = row["case"]
    return abs(Decimal(suggestion.score) - Decimal(eval_case.expected_score))


def _row_confidence(row: dict[str, Any]) -> Decimal:
    return Decimal(_row_suggestion(row).confidence)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _render_markdown(result: dict[str, Any]) -> str:
    metrics = result.get("metrics", {})
    lines = [
        f"# Grading Evaluation: {result.get('run_id', 'unknown')}",
        "",
        f"Provider mode: `{result.get('provider_mode', 'unknown')}`",
        f"Marking policy: `{result.get('marking_policy', 'general')}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Cases", ""])
    for item in result.get("cases", []):
        lines.append(
            (
                "- `{case_id}`: expected {expected_score}, AI {ai_score}, "
                "abs error {absolute_error}, confidence {confidence}, "
                "needs_review {needs_review}, policy {marking_policy}"
            ).format(
                case_id=item.get("case_id", "unknown"),
                expected_score=item.get("expected_score", "unknown"),
                ai_score=item.get("ai_score", "unknown"),
                absolute_error=item.get("absolute_error", "unknown"),
                confidence=item.get("confidence", "unknown"),
                needs_review=item.get("needs_review", "unknown"),
                marking_policy=item.get("marking_policy", result.get("marking_policy", "general")),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TA grading evaluation harness")
    parser.add_argument("dataset", type=Path, help="Path to JSON or JSONL evaluation dataset")
    parser.add_argument("--provider", default=os.environ.get("TA_EVAL_PROVIDER", "mock"))
    parser.add_argument(
        "--allow-real-provider",
        action="store_true",
        default=os.environ.get("TA_EVAL_ALLOW_REAL_PROVIDER", "").lower() == "true",
    )
    parser.add_argument("--max-real-cases", type=int, default=_DEFAULT_MAX_REAL_CASES)
    parser.add_argument(
        "--marking-policy",
        default=os.environ.get("TA_EVAL_MARKING_POLICY", "general"),
        choices=("tough", "general", "easy"),
        help="Marking policy to pass into grading prompts.",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    from app.db.session import SessionLocal

    args = _parse_args()
    cases = load_evaluation_cases(args.dataset)
    runner = GradingEvaluationRunner(
        provider_mode=args.provider,
        allow_real_provider=args.allow_real_provider,
        max_real_cases=args.max_real_cases,
        output_dir=args.output_dir,
        marking_policy=args.marking_policy,
    )
    with SessionLocal() as db:
        result = runner.run(db, cases)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
