from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.question_import_extractor import (
    CodexQuestionExtractionError,
    CodexQuestionExtractor,
)

HELP_TEXT = "codex exec --output-last-message --cd --sandbox --json --skip-git-repo-check"


def make_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=420, height=220)
    page.insert_text((20, 40), "Q1. What is 2 + 2? [4 marks]")
    doc.save(path)
    doc.close()


def extractor_with_output(raw_output: str) -> CodexQuestionExtractor:
    def runner(command, **kwargs):
        if command[:2] == ["codex", "--version"]:
            return SimpleNamespace(returncode=0, stdout="codex 1.0", stderr="")
        if command[:3] == ["codex", "exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout=HELP_TEXT, stderr="")
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(raw_output, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return CodexQuestionExtractor(
        command="codex",
        model_name="gpt-5.5",
        which=lambda command: "/usr/bin/codex" if command == "codex" else None,
        runner=runner,
        workdir="/tmp",
    )


def test_valid_codex_json_payload_passes_schema(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper)
    extractor = extractor_with_output(
        json.dumps(
            {
                "questions": [
                    {
                        "question_no": "1",
                        "question_text": "What is 2 + 2?",
                        "model_answer": None,
                        "total_marks": 4,
                        "confidence": 0.9,
                        "source_page": 1,
                        "source_text_excerpt": "Q1. What is 2 + 2? [4 marks]",
                        "needs_review": True,
                    }
                ],
                "warnings": [],
            }
        )
    )

    result = extractor.extract(paper, "application/pdf")

    assert len(result.draft_questions) == 1
    assert result.draft_questions[0].question_no == "1"
    assert result.draft_questions[0].total_marks == 4


def test_markdown_fenced_codex_json_payload_is_parsed(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper)
    extractor = extractor_with_output(
        "```json\n"
        + json.dumps(
            {
                "questions": [
                    {
                        "question_no": "1",
                        "question_text": "What is 2 + 2?",
                        "model_answer": None,
                        "total_marks": "4",
                        "confidence": 0.8,
                        "source_page": 1,
                        "source_text_excerpt": "Q1. What is 2 + 2? [4 marks]",
                        "needs_review": True,
                    }
                ],
                "warnings": ["fenced"],
            }
        )
        + "\n```"
    )

    result = extractor.extract(paper, "application/pdf")

    assert result.warnings == ["fenced"]
    assert result.draft_questions[0].question_text == "What is 2 + 2?"


def test_malformed_codex_json_fails_cleanly(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper)
    extractor = extractor_with_output("not json")

    with pytest.raises(CodexQuestionExtractionError) as exc:
        extractor.extract(paper, "application/pdf")

    assert "valid JSON" in str(exc.value)
    assert "preview=" in str(exc.value)


def test_wrong_codex_schema_reports_actionable_validation_errors(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper)
    extractor = extractor_with_output(
        json.dumps({"questions": [], "warnings": ["could not read file"]})
    )

    with pytest.raises(CodexQuestionExtractionError) as exc:
        extractor.extract(paper, "application/pdf")

    message = str(exc.value)
    assert "schema validation failed" in message
    assert "questions" in message
    assert "too_short" in message
    assert "top-level keys: questions, warnings" in message


def test_pdf_text_is_included_in_prompt_for_codex_handoff(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper)
    prompts: list[str] = []

    def runner(command, **kwargs):
        if command[:2] == ["codex", "--version"]:
            return SimpleNamespace(returncode=0, stdout="codex 1.0", stderr="")
        if command[:3] == ["codex", "exec", "--help"]:
            return SimpleNamespace(returncode=0, stdout=HELP_TEXT, stderr="")
        prompts.append(kwargs["input"])
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "questions": [
                        {
                            "question_no": "1",
                            "question_text": "What is 2 + 2?",
                            "model_answer": None,
                            "total_marks": 4,
                            "confidence": 0.9,
                            "source_page": 1,
                            "source_text_excerpt": "Q1. What is 2 + 2? [4 marks]",
                            "needs_review": True,
                        }
                    ],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    extractor = CodexQuestionExtractor(
        command="codex",
        which=lambda command: "/usr/bin/codex" if command == "codex" else None,
        runner=runner,
        workdir="/tmp",
    )

    extractor.extract(paper, "application/pdf")

    assert "Extracted text preview from uploaded file" in prompts[0]
    assert "Q1. What is 2 + 2? [4 marks]" in prompts[0]
