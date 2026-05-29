import json
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.question_import_extractor import (
    CodexQuestionExtractionError,
    CodexQuestionExtractor,
    build_question_extractor,
)


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def valid_codex_output() -> dict[str, object]:
    return {
        "questions": [
            {
                "question_no": "1",
                "question_text": "Differentiate y = x^2.",
                "model_answer": None,
                "total_marks": 5,
                "confidence": 0.8,
                "source_page": 1,
                "source_text_excerpt": "Q1. Differentiate y = x^2. [5 marks]",
                "needs_review": True,
            }
        ],
        "warnings": ["synthetic smoke warning"],
    }


HELP_TEXT = "Usage: codex exec --cd --sandbox --output-last-message --image"


def make_provider(tmp_path: Path, payload: dict[str, object] | str | None = None):
    calls: list[dict[str, object]] = []

    def which(command: str) -> str | None:
        assert command == "codex"
        return "/usr/local/bin/codex"

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append({"cmd": cmd, **kwargs})
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout=HELP_TEXT)
        output_file = Path(cmd[cmd.index("--output-last-message") + 1])
        if payload is None:
            output_file.write_text(json.dumps(valid_codex_output()), encoding="utf-8")
        elif isinstance(payload, str):
            output_file.write_text(payload, encoding="utf-8")
        else:
            output_file.write_text(json.dumps(payload), encoding="utf-8")
        return FakeCompletedProcess(stdout="ok")

    provider = CodexQuestionExtractor(
        command="codex",
        timeout_seconds=30,
        sandbox="read-only",
        workdir=str(tmp_path),
        image_input_enabled=True,
        which=which,
        runner=runner,
    )
    return provider, calls


def test_question_import_provider_defaults_to_mock_without_real_flag() -> None:
    settings = Settings()

    extractor = build_question_extractor(settings=settings)

    assert extractor.provider == "mock"


def test_codex_question_extractor_rejected_unless_explicitly_enabled() -> None:
    settings = Settings(
        QUESTION_IMPORT_PROVIDER="codex_cli_question_extractor",
        CODEX_QUESTION_EXTRACTION_ENABLED=False,
    )

    with pytest.raises(CodexQuestionExtractionError, match="explicitly enabled"):
        build_question_extractor(settings=settings)


def test_codex_question_extractor_validates_fake_runner_output(tmp_path: Path) -> None:
    paper_path = tmp_path / "paper.png"
    paper_path.write_bytes(b"fake image")
    provider, calls = make_provider(tmp_path)

    result = provider.extract(paper_path, "image/png")

    assert provider.provider == "codex_cli_question_extractor"
    assert result.warnings == ["synthetic smoke warning"]
    assert len(result.draft_questions) == 1
    draft = result.draft_questions[0]
    assert draft.draft_id == "draft-1"
    assert draft.question_no == "1"
    assert draft.needs_review is True
    assert draft.total_marks == 5
    exec_call = calls[-1]
    assert exec_call["input"]
    assert "Return ONLY valid JSON" in str(exec_call["input"])
    assert "--image" in exec_call["cmd"]
    assert str(paper_path) in exec_call["cmd"]


def test_codex_question_extractor_invalid_json_fails_cleanly(tmp_path: Path) -> None:
    paper_path = tmp_path / "paper.png"
    paper_path.write_bytes(b"fake image")
    provider, _calls = make_provider(tmp_path, payload="not json")

    with pytest.raises(CodexQuestionExtractionError, match="valid JSON"):
        provider.extract(paper_path, "image/png")


def test_codex_question_extractor_invalid_schema_fails_cleanly(tmp_path: Path) -> None:
    paper_path = tmp_path / "paper.png"
    paper_path.write_bytes(b"fake image")
    provider, _calls = make_provider(tmp_path, payload={"questions": [{"question_no": "1"}]})

    with pytest.raises(CodexQuestionExtractionError, match="schema"):
        provider.extract(paper_path, "image/png")


def test_codex_question_extractor_subprocess_failure_is_sanitized(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def which(_command: str) -> str | None:
        return "/usr/local/bin/codex"

    def runner(cmd: list[str], **_kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout=HELP_TEXT)
        return FakeCompletedProcess(
            stderr="failed sk-secret data:image/png;base64,AAAA", returncode=1
        )

    provider = CodexQuestionExtractor(
        workdir=str(tmp_path), image_input_enabled=True, which=which, runner=runner
    )
    paper_path = tmp_path / "paper.png"
    paper_path.write_bytes(b"fake image")

    with pytest.raises(CodexQuestionExtractionError) as exc_info:
        provider.extract(paper_path, "image/png")

    message = str(exc_info.value)
    assert "[REDACTED]" in message
    assert "[IMAGE_DATA_REDACTED]" in message
    assert "sk-secret" not in message
    assert "data:image" not in message


def test_codex_question_extractor_timeout_fails_cleanly(tmp_path: Path) -> None:
    def which(_command: str) -> str | None:
        return "/usr/local/bin/codex"

    def runner(cmd: list[str], **_kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout=HELP_TEXT)
        raise subprocess.TimeoutExpired(cmd, 1)

    provider = CodexQuestionExtractor(
        workdir=str(tmp_path), image_input_enabled=True, which=which, runner=runner
    )
    paper_path = tmp_path / "paper.png"
    paper_path.write_bytes(b"fake image")

    with pytest.raises(CodexQuestionExtractionError, match="timed out"):
        provider.extract(paper_path, "image/png")
