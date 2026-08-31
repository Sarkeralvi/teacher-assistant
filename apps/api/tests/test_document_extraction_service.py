import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.document_extraction import (
    BridgeUnavailableError,
    DocumentExtractionError,
    HostBridgeCodexDocumentExtractor,
    _normalize_provider_document_result,
    build_document_extractor,
    validate_normalized_output,
)


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


QUESTION_PAYLOAD = {
    "question_nodes": [
        {
            "question_number": "Q1",
            "parent_question_number": None,
            "label": "Q1",
            "text": "Answer the following.",
            "marks": 10,
            "node_type": "question",
            "source_page": 1,
            "source_reference": {"source_text_excerpt": "Q1. Answer the following. [10 marks]"},
            "confidence": 0.9,
            "teacher_confirmed": False,
        },
        {
            "question_number": "Q1(a)",
            "parent_question_number": "Q1",
            "label": "Q1(a)",
            "text": "What is 2 + 2?",
            "marks": 4,
            "node_type": "subquestion",
            "source_page": 1,
            "source_reference": {"source_text_excerpt": "Q1(a). What is 2 + 2? [4 marks]"},
            "confidence": 0.95,
            "teacher_confirmed": False,
        },
    ],
    "blockers": [],
}

RUBRIC_PAYLOAD = {
    "criteria": [
        {
            "question_number": "Q1(a)",
            "criterion_label": "Correct answer",
            "description": "Correct answer",
            "max_marks": 4,
            "confidence": 0.91,
            "blocker": None,
            "teacher_confirmed": False,
        }
    ],
    "blockers": [],
}


def test_disabled_provider_blocks_real_extraction() -> None:
    settings = Settings(
        CODEX_EXTRACTION_ENABLED=False, CODEX_EXTRACTION_PROVIDER="host_bridge_codex"
    )

    extractor = build_document_extractor(settings=settings)

    with pytest.raises(BridgeUnavailableError, match="disabled"):
        extractor.extract(Path("/tmp/missing.pdf"), "question_paper", "application/pdf")


def test_mock_provider_is_not_selected_as_real_provider() -> None:
    settings = Settings(CODEX_EXTRACTION_ENABLED=True, CODEX_EXTRACTION_PROVIDER="mock")

    extractor = build_document_extractor(settings=settings)

    assert extractor.provider == "mock"


def test_host_bridge_command_is_built_safely(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        output_file = Path(cmd[cmd.index("--output-file") + 1])
        output_file.write_text(json.dumps(QUESTION_PAYLOAD), encoding="utf-8")
        return FakeCompletedProcess(stdout="ok")

    extractor = HostBridgeCodexDocumentExtractor(
        bridge_command="python scripts/codex_extract_document.py",
        timeout_seconds=30,
        runner=runner,
    )
    file_path = tmp_path / "fixture.txt"
    file_path.write_text("Q1. Answer the following. [10 marks]", encoding="utf-8")

    result = extractor.extract(file_path, "question_paper", "text/plain")

    assert result.normalized_output["question_nodes"][0]["question_number"] == "Q1"
    command = calls[-1]
    assert command[0].endswith("python")
    assert "scripts/codex_extract_document.py" in command
    assert "--input-file" in command
    assert str(file_path) == command[command.index("--input-file") + 1]
    assert "--output-file" in command
    assert "--extraction-type" in command
    assert command[command.index("--extraction-type") + 1] == "question_paper"


def test_host_bridge_uses_image_flag_for_image_inputs(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        output_file = Path(cmd[cmd.index("--output-file") + 1])
        output_file.write_text(json.dumps(RUBRIC_PAYLOAD), encoding="utf-8")
        return FakeCompletedProcess(stdout="ok")

    extractor = HostBridgeCodexDocumentExtractor(
        bridge_command="python scripts/codex_extract_document.py",
        timeout_seconds=30,
        runner=runner,
    )
    file_path = tmp_path / "fixture.png"
    file_path.write_bytes(b"not-a-real-image-but-sufficient-for-command-assembly")

    result = extractor.extract(file_path, "rubric", "image/png")

    assert result.normalized_output["criteria"][0]["question_number"] == "Q1(a)"
    command = calls[-1]
    assert "--input-file" in command
    assert str(file_path) == command[command.index("--input-file") + 1]
    assert command[command.index("--extraction-type") + 1] == "rubric"


def test_host_bridge_malformed_json_fails_cleanly(tmp_path: Path) -> None:
    def runner(cmd: list[str], **_kwargs: object) -> FakeCompletedProcess:
        output_file = Path(cmd[cmd.index("--output-file") + 1])
        output_file.write_text("not-json", encoding="utf-8")
        return FakeCompletedProcess(stdout="ok")

    extractor = HostBridgeCodexDocumentExtractor(
        bridge_command="python scripts/codex_extract_document.py",
        timeout_seconds=30,
        runner=runner,
    )
    file_path = tmp_path / "fixture.txt"
    file_path.write_text("Q1. Answer the following. [10 marks]", encoding="utf-8")

    with pytest.raises(DocumentExtractionError, match="malformed JSON"):
        extractor.extract(file_path, "question_paper", "text/plain")


def test_validate_normalized_output_accepts_question_tree_sample() -> None:
    payload = validate_normalized_output("question_paper", QUESTION_PAYLOAD)

    assert payload["question_nodes"][1]["question_number"] == "Q1(a)"
    assert payload["question_nodes"][1]["parent_question_number"] == "Q1"


def test_validate_normalized_output_accepts_rubric_sample() -> None:
    payload = validate_normalized_output("rubric", RUBRIC_PAYLOAD)

    assert payload["criteria"][0]["question_number"] == "Q1(a)"
    assert payload["criteria"][0]["criterion_label"] == "Correct answer"


def test_provider_question_tree_is_flattened_into_canonical_nodes() -> None:
    payload = _normalize_provider_document_result(
        "question_paper",
        {
            "questions": [
                {
                    "question_number": "1",
                    "question_text": "Answer both parts.",
                    "marks": 10,
                    "sub_questions": [
                        {
                            "question_number": "1(a)",
                            "question_text": "State the result.",
                            "marks": 4,
                            "sub_questions": [],
                        }
                    ],
                }
            ],
            "warnings": ["Page number was faint"],
        },
    )

    assert [item["question_number"] for item in payload["question_nodes"]] == [
        "1",
        "1(a)",
    ]
    assert payload["question_nodes"][1]["parent_question_number"] == "1"
    assert payload["question_nodes"][1]["node_type"] == "subquestion"
    assert payload["blockers"] == ["Page number was faint"]


def test_provider_rubric_tree_is_flattened_into_canonical_criteria() -> None:
    payload = _normalize_provider_document_result(
        "rubric",
        {
            "criteria": [
                {
                    "question_number": "1",
                    "criterion_text": "Uses the correct method.",
                    "max_marks": 3,
                    "sub_criteria": [
                        {
                            "question_number": "1(a)",
                            "criterion_text": "Shows the substitution.",
                            "max_marks": 1,
                            "sub_criteria": [],
                        }
                    ],
                }
            ],
            "warnings": [],
        },
    )

    assert [item["question_number"] for item in payload["criteria"]] == ["1", "1(a)"]
    assert payload["criteria"][1]["description"] == "Shows the substitution."
