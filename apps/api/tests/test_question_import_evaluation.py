import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas import DraftQuestion
from packages.evaluation.question_import_evaluation import (
    ExpectedQuestion,
    QuestionImportEvalCase,
    QuestionImportEvaluationError,
    QuestionImportEvaluationRunner,
    calculate_question_import_metrics,
    load_question_import_eval_cases,
    write_question_import_eval_artifacts,
)


def expected(
    question_no: str,
    text: str,
    total_marks: str | None = None,
) -> ExpectedQuestion:
    return ExpectedQuestion(
        question_no=question_no,
        question_text=text,
        total_marks=Decimal(total_marks) if total_marks is not None else None,
    )


def draft(
    question_no: str,
    text: str,
    total_marks: str | None = None,
    confidence: str = "0.80",
) -> DraftQuestion:
    return DraftQuestion(
        draft_id=f"draft-{question_no}",
        question_no=question_no,
        question_text=text,
        model_answer=None,
        total_marks=Decimal(total_marks) if total_marks is not None else None,
        confidence=Decimal(confidence),
        source_page=1,
        source_text_excerpt=text,
        needs_review=True,
    )


def eval_case(
    case_id: str = "qimport_case_001",
    expected_questions: list[ExpectedQuestion] | None = None,
) -> QuestionImportEvalCase:
    return QuestionImportEvalCase(
        case_id=case_id,
        assessment_id=123,
        input_file_path="/tmp/synthetic_question_paper.png",
        expected_questions=expected_questions
        or [expected("1", "Differentiate y = x^2.", "5.00")],
        teacher_notes="Synthetic typed question paper.",
    )


def test_question_import_eval_loader_supports_json_and_jsonl(tmp_path: Path) -> None:
    payload = {
        "cases": [
            {
                "case_id": "qimport_case_001",
                "assessment_id": 123,
                "input_file_path": "/tmp/paper.png",
                "expected_questions": [
                    {
                        "question_no": "1",
                        "question_text": "Differentiate y = x^2.",
                        "total_marks": "5.00",
                    }
                ],
                "teacher_notes": "Synthetic typed question paper.",
            }
        ]
    }
    json_path = tmp_path / "cases.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    jsonl_path = tmp_path / "cases.jsonl"
    jsonl_path.write_text(json.dumps(payload["cases"][0]) + "\n", encoding="utf-8")

    assert load_question_import_eval_cases(json_path)[0].case_id == "qimport_case_001"
    jsonl_cases = load_question_import_eval_cases(jsonl_path)
    assert jsonl_cases[0].expected_questions[0].total_marks == Decimal("5.00")


def test_question_import_eval_metrics_count_and_question_number_matches() -> None:
    metrics = calculate_question_import_metrics(
        [
            {
                "case": eval_case(
                    expected_questions=[
                        expected("1", "Differentiate y = x^2.", "5.00"),
                        expected("2", "Solve 2x + 3 = 7.", "4.00"),
                    ]
                ),
                "draft_questions": [
                    draft("1", "Differentiate y = x^2.", "5.00"),
                    draft("2", "Solve 2x + 3 = 7.", "4.00"),
                ],
                "provider_warnings": [],
                "parse_failed": False,
            }
        ]
    )

    assert metrics["case_count"] == 1
    assert metrics["expected_question_count"] == 2
    assert metrics["extracted_question_count"] == 2
    assert metrics["question_count_match_rate"] == Decimal("1")
    assert metrics["question_number_match_rate"] == Decimal("1")


def test_question_import_eval_metrics_marks_and_text_similarity() -> None:
    metrics = calculate_question_import_metrics(
        [
            {
                "case": eval_case(
                    expected_questions=[expected("1", "Differentiate y = x^2.", "5.00")]
                ),
                "draft_questions": [draft("1", "Differentiate y = x^2.", "5.00")],
                "provider_warnings": [],
                "parse_failed": False,
            },
            {
                "case": eval_case(
                    "qimport_case_002",
                    expected_questions=[expected("2", "Solve 2x + 3 = 7.", "4.00")],
                ),
                "draft_questions": [draft("2", "Solve 2x + 3 = 8.", "5.00")],
                "provider_warnings": [],
                "parse_failed": False,
            },
        ]
    )

    assert metrics["exact_text_match_rate"] == Decimal("0.5")
    assert metrics["marks_match_rate"] == Decimal("0.5")
    assert Decimal("0.8") <= metrics["normalized_text_similarity_average"] < Decimal("1")


def test_question_import_eval_runner_uses_injected_mock_extractor(tmp_path: Path) -> None:
    paper = tmp_path / "paper.png"
    paper.write_bytes(b"fake image")
    cases = [eval_case("qimport_case_001")]
    cases[0].input_file_path = str(paper)
    calls: list[tuple[Path, str]] = []

    class FakeExtractor:
        provider = "mock"

        def extract(self, file_path: Path, content_type: str):
            calls.append((file_path, content_type))
            return type(
                "Result",
                (),
                {
                    "draft_questions": [draft("1", "Differentiate y = x^2.", "5.00")],
                    "warnings": [],
                },
            )()

    runner = QuestionImportEvaluationRunner(
        provider="mock",
        output_dir=tmp_path / "artifacts",
        extractor_factory=lambda _provider: FakeExtractor(),
    )

    result = runner.run(cases)

    assert calls == [(paper, "image/png")]
    assert result["metrics"]["question_count_match_rate"] == Decimal("1")
    assert Path(result["artifact_json_path"]).is_file()
    assert Path(result["artifact_markdown_path"]).is_file()


def test_real_codex_eval_rejected_unless_env_and_cli_flag_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER", raising=False)
    runner = QuestionImportEvaluationRunner(
        provider="codex_cli_question_extractor",
        allow_real_provider=True,
    )

    with pytest.raises(
        QuestionImportEvaluationError,
        match="QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER",
    ):
        runner.validate_provider_mode([eval_case()])

    monkeypatch.setenv("QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER", "true")
    runner = QuestionImportEvaluationRunner(
        provider="codex_cli_question_extractor",
        allow_real_provider=False,
    )

    with pytest.raises(QuestionImportEvaluationError, match="--allow-real-provider"):
        runner.validate_provider_mode([eval_case()])


def test_real_codex_eval_enforces_max_real_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER", "true")
    runner = QuestionImportEvaluationRunner(
        provider="codex_cli_question_extractor",
        allow_real_provider=True,
        max_real_cases=1,
    )

    with pytest.raises(QuestionImportEvaluationError, match="at most 1 real"):
        runner.validate_provider_mode([eval_case("case_1"), eval_case("case_2")])


def test_question_import_eval_artifact_writer(tmp_path: Path) -> None:
    result = {
        "run_id": "question-import-eval-test",
        "provider": "mock",
        "metrics": {"case_count": 1, "question_count_match_rate": Decimal("1")},
        "cases": [
            {
                "case_id": "qimport_case_001",
                "expected_question_count": 1,
                "extracted_question_count": 1,
                "provider_warnings": [],
            }
        ],
    }

    paths = write_question_import_eval_artifacts(result, tmp_path)

    assert paths.json_path.is_file()
    assert paths.markdown_path.is_file()
    assert paths.json_path.parent == tmp_path
    assert "question_count_match_rate" in paths.json_path.read_text(encoding="utf-8")
    assert "qimport_case_001" in paths.markdown_path.read_text(encoding="utf-8")
