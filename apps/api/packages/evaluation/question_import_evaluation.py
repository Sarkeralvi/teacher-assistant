from __future__ import annotations

import argparse
import json
import mimetypes
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.question_import_extractor import (
    CODEX_QUESTION_PROVIDER,
    QuestionExtractor,
    build_question_extractor,
)

_DEFAULT_MAX_REAL_CASES = 3
_REAL_PROVIDERS = {CODEX_QUESTION_PROVIDER}
_REAL_ENV_FLAG = "QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER"


class QuestionImportEvaluationError(RuntimeError):
    """Raised when question import evaluation setup or execution is unsafe."""


class ExpectedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_no: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    total_marks: Decimal | None = Field(default=None, gt=Decimal("0"))


class QuestionImportEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    assessment_id: int = Field(gt=0)
    input_file_path: str = Field(min_length=1)
    expected_questions: list[ExpectedQuestion] = Field(min_length=1)
    teacher_notes: str = ""
    content_type: str | None = None


@dataclass(frozen=True)
class QuestionImportEvalArtifactPaths:
    json_path: Path
    markdown_path: Path


ExtractorFactory = Callable[[str], QuestionExtractor]


class QuestionImportEvaluationRunner:
    def __init__(
        self,
        *,
        provider: str = "mock",
        allow_real_provider: bool = False,
        max_real_cases: int = _DEFAULT_MAX_REAL_CASES,
        output_dir: Path | None = None,
        extractor_factory: ExtractorFactory | None = None,
    ) -> None:
        self.provider = provider.strip() or "mock"
        self.allow_real_provider = allow_real_provider
        self.max_real_cases = max_real_cases
        self.output_dir = output_dir or (
            Path(get_settings().local_storage_root) / "exports" / "question_import_evals"
        )
        self.extractor_factory = extractor_factory or self._default_extractor_factory

    def validate_provider_mode(self, cases: list[QuestionImportEvalCase]) -> None:
        if self.provider not in _REAL_PROVIDERS:
            return
        if os.environ.get(_REAL_ENV_FLAG, "").lower() != "true":
            raise QuestionImportEvaluationError(
                f"Real Codex question extraction eval requires {_REAL_ENV_FLAG}=true."
            )
        if not self.allow_real_provider:
            raise QuestionImportEvaluationError(
                "Real Codex question extraction eval requires --allow-real-provider."
            )
        if len(cases) > self.max_real_cases:
            raise QuestionImportEvaluationError(
                "Real Codex question extraction eval is limited to at most "
                f"{self.max_real_cases} real cases."
            )

    def run(self, cases: list[QuestionImportEvalCase]) -> dict[str, Any]:
        self.validate_provider_mode(cases)
        extractor = self.extractor_factory(self.provider)
        rows: list[dict[str, Any]] = []
        for eval_case in cases:
            input_path = Path(eval_case.input_file_path)
            if not input_path.is_file():
                raise QuestionImportEvaluationError(
                    f"Evaluation input file not found for {eval_case.case_id}: {input_path}"
                )
            content_type = eval_case.content_type or _guess_content_type(input_path)
            try:
                result = extractor.extract(input_path, content_type)
                rows.append(
                    {
                        "case": eval_case,
                        "draft_questions": result.draft_questions,
                        "provider_warnings": result.warnings,
                        "parse_failed": False,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - evaluation reports provider failure per case
                rows.append(
                    {
                        "case": eval_case,
                        "draft_questions": [],
                        "provider_warnings": [str(exc)],
                        "parse_failed": True,
                    }
                )
        result_payload = {
            "run_id": datetime.now(UTC).strftime("question-import-eval-%Y%m%dT%H%M%SZ"),
            "created_at": datetime.now(UTC).isoformat(),
            "provider": self.provider,
            "case_count": len(cases),
            "metrics": calculate_question_import_metrics(rows),
            "cases": [_serialize_case_result(row) for row in rows],
        }
        paths = write_question_import_eval_artifacts(result_payload, self.output_dir)
        result_payload["artifact_json_path"] = str(paths.json_path)
        result_payload["artifact_markdown_path"] = str(paths.markdown_path)
        return result_payload

    @staticmethod
    def _default_extractor_factory(provider: str) -> QuestionExtractor:
        return build_question_extractor(requested_provider=provider)


def load_question_import_eval_cases(path: Path) -> list[QuestionImportEvalCase]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
        payloads = loaded["cases"] if isinstance(loaded, dict) and "cases" in loaded else loaded
    if not isinstance(payloads, list):
        raise QuestionImportEvaluationError(
            "Question import eval dataset must be JSON array or JSONL"
        )
    return [QuestionImportEvalCase.model_validate(item) for item in payloads]


def calculate_question_import_metrics(rows: list[dict[str, Any]]) -> dict[str, Decimal | int]:
    if not rows:
        return {
            "case_count": 0,
            "expected_question_count": 0,
            "extracted_question_count": 0,
            "question_count_match_rate": Decimal("0"),
            "question_number_match_rate": Decimal("0"),
            "exact_text_match_rate": Decimal("0"),
            "normalized_text_similarity_average": Decimal("0"),
            "marks_match_rate": Decimal("0"),
            "needs_review_rate": Decimal("0"),
            "provider_warning_count": 0,
            "parse_failure_count": 0,
        }
    case_count = len(rows)
    expected_count = 0
    extracted_count = 0
    count_matches = 0
    number_matches = 0
    text_exact_matches = 0
    text_similarity_total = Decimal("0")
    marks_matches = 0
    comparable_marks = 0
    comparable_text = 0
    extracted_draft_count = 0
    needs_review_count = 0
    warning_count = 0
    parse_failure_count = 0

    for row in rows:
        eval_case = _row_case(row)
        drafts = _row_drafts(row)
        expected_questions = eval_case.expected_questions
        expected_count += len(expected_questions)
        extracted_count += len(drafts)
        extracted_draft_count += len(drafts)
        needs_review_count += sum(1 for item in drafts if item.needs_review)
        warning_count += len(row.get("provider_warnings") or [])
        parse_failure_count += 1 if row.get("parse_failed") else 0
        if len(expected_questions) == len(drafts):
            count_matches += 1
        expected_numbers = {item.question_no for item in expected_questions}
        draft_numbers = {item.question_no for item in drafts}
        if expected_numbers == draft_numbers:
            number_matches += 1
        drafts_by_no = {item.question_no: item for item in drafts}
        for expected_question in expected_questions:
            draft = drafts_by_no.get(expected_question.question_no)
            if draft is None:
                continue
            comparable_text += 1
            if _normalize_text(draft.question_text) == _normalize_text(
                expected_question.question_text
            ):
                text_exact_matches += 1
            text_similarity_total += _text_similarity(
                expected_question.question_text, draft.question_text
            )
            if expected_question.total_marks is not None:
                comparable_marks += 1
                if draft.total_marks == expected_question.total_marks:
                    marks_matches += 1

    total_cases = Decimal(case_count)
    return {
        "case_count": case_count,
        "expected_question_count": expected_count,
        "extracted_question_count": extracted_count,
        "question_count_match_rate": Decimal(count_matches) / total_cases,
        "question_number_match_rate": Decimal(number_matches) / total_cases,
        "exact_text_match_rate": _safe_rate(text_exact_matches, comparable_text),
        "normalized_text_similarity_average": (
            text_similarity_total / Decimal(comparable_text) if comparable_text else Decimal("0")
        ),
        "marks_match_rate": _safe_rate(marks_matches, comparable_marks),
        "needs_review_rate": _safe_rate(needs_review_count, extracted_draft_count),
        "provider_warning_count": warning_count,
        "parse_failure_count": parse_failure_count,
    }


def write_question_import_eval_artifacts(
    result: dict[str, Any], output_dir: Path
) -> QuestionImportEvalArtifactPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(
        result.get("run_id")
        or datetime.now(UTC).strftime("question-import-eval-%Y%m%dT%H%M%SZ")
    )
    json_path = output_dir / f"{run_id}.json"
    markdown_path = output_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    return QuestionImportEvalArtifactPaths(json_path=json_path, markdown_path=markdown_path)


def _serialize_case_result(row: dict[str, Any]) -> dict[str, Any]:
    eval_case = _row_case(row)
    drafts = _row_drafts(row)
    return {
        "case_id": eval_case.case_id,
        "assessment_id": eval_case.assessment_id,
        "input_file_path": eval_case.input_file_path,
        "teacher_notes": eval_case.teacher_notes,
        "expected_question_count": len(eval_case.expected_questions),
        "extracted_question_count": len(drafts),
        "expected_questions": eval_case.expected_questions,
        "draft_questions": drafts,
        "provider_warnings": row.get("provider_warnings") or [],
        "parse_failed": bool(row.get("parse_failed")),
    }


def _row_case(row: dict[str, Any]) -> QuestionImportEvalCase:
    eval_case = row["case"]
    if not isinstance(eval_case, QuestionImportEvalCase):
        raise TypeError("row case must be QuestionImportEvalCase")
    return eval_case


def _row_drafts(row: dict[str, Any]) -> list[Any]:
    return list(row.get("draft_questions") or [])


def _safe_rate(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return Decimal(numerator) / Decimal(denominator)


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def _text_similarity(expected_text: str, draft_text: str) -> Decimal:
    ratio = SequenceMatcher(
        None, _normalize_text(expected_text), _normalize_text(draft_text)
    ).ratio()
    return Decimal(str(ratio))


def _guess_content_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


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
    lines = [
        f"# Question Import Evaluation: {result.get('run_id', 'unknown')}",
        "",
        f"Provider: `{result.get('provider', 'unknown')}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in (result.get("metrics") or {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Cases", ""])
    for item in result.get("cases", []):
        lines.append(
            (
                "- `{case_id}`: expected {expected_question_count}, extracted "
                "{extracted_question_count}, warnings {provider_warnings}, "
                "parse_failed {parse_failed}"
            ).format(
                case_id=item.get("case_id", "unknown"),
                expected_question_count=item.get("expected_question_count", "unknown"),
                extracted_question_count=item.get("extracted_question_count", "unknown"),
                provider_warnings=len(item.get("provider_warnings") or []),
                parse_failed=item.get("parse_failed", False),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TA question import extraction evaluation")
    parser.add_argument("dataset", type=Path, help="Path to JSON or JSONL evaluation dataset")
    parser.add_argument(
        "--provider", default=os.environ.get("QUESTION_IMPORT_EVAL_PROVIDER", "mock")
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-real-cases", type=int, default=_DEFAULT_MAX_REAL_CASES)
    parser.add_argument("--allow-real-provider", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cases = load_question_import_eval_cases(args.dataset)
    runner = QuestionImportEvaluationRunner(
        provider=args.provider,
        allow_real_provider=args.allow_real_provider,
        max_real_cases=args.max_real_cases,
        output_dir=args.output_dir,
    )
    result = runner.run(cases)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
