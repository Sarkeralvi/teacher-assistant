import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from packages.brain.adapter import BrainAdapter
from packages.brain.codex_cli_provider import CodexCliProvider, CodexCliProviderError
from packages.brain.prompt_registry import build_grading_prompt
from packages.brain.schemas import ModelPolicy
from tests.test_openai_provider import rubric_payload


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def valid_codex_output() -> dict[str, object]:
    return {
        "score": 3,
        "max_score": 10,
        "confidence": 0.42,
        "needs_review": False,
        "rubric_breakdown": [
            {
                "criterion_id": "concept",
                "criterion": "Core concept",
                "max_marks": 4,
                "awarded_marks": 2,
                "reason": "Partial conceptual match in provided text.",
                "evidence": None,
                "confidence": 0.4,
            },
            {
                "criterion_id": "working",
                "criterion": "Working",
                "max_marks": 6,
                "awarded_marks": 1,
                "reason": "Limited working shown in provided text.",
                "evidence": None,
                "confidence": 0.4,
            },
        ],
        "detected_answer_summary": "Text-only provider suggestion.",
        "major_errors": ["Incomplete working"],
        "feedback_to_student": "Add complete reasoning.",
        "review_flags": [],
    }


def messages(image_input_enabled: bool = False) -> list[dict[str, str]]:
    return build_grading_prompt(
        question_text="Explain the concept.",
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        image_input_enabled=image_input_enabled,
    )


def make_provider(
    *,
    which_result: str | None = "/usr/local/bin/codex",
    help_text: str = (
        "--cd <DIR>\n--sandbox <SANDBOX_MODE>\n"
        "--output-last-message <FILE>\n--json\n--image <FILE>"
    ),
    runner=None,
    image_input_enabled: bool = False,
) -> CodexCliProvider:
    def fake_which(command: str) -> str | None:
        assert command == "codex"
        return which_result

    def default_runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout=help_text)
        output_file = Path(cmd[cmd.index("--output-last-message") + 1])
        output_file.write_text(json.dumps(valid_codex_output()), encoding="utf-8")
        return FakeCompletedProcess(stdout="event log", stderr="")

    return CodexCliProvider(
        command="codex",
        model_name="gpt-5.5",
        timeout_seconds=300,
        sandbox="read-only",
        use_json=True,
        output_last_message=True,
        image_input_enabled=image_input_enabled,
        workdir="/home/newton/teacher-assistant",
        which=fake_which,
        runner=runner or default_runner,
    )


def test_codex_cli_provider_builds_safe_exec_command_with_output_last_message() -> None:
    calls: list[list[str]] = []
    inputs: list[str | None] = []

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        input_value = kwargs.get("input")
        inputs.append(input_value if isinstance(input_value, str) else None)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(
                stdout="--cd <DIR>\n--sandbox <SANDBOX_MODE>\n--output-last-message <FILE>\n--json"
            )
        output_file = Path(cmd[cmd.index("--output-last-message") + 1])
        output_file.write_text(json.dumps(valid_codex_output()), encoding="utf-8")
        return FakeCompletedProcess()

    result = make_provider(runner=runner).grade(
        question_text="Explain the concept.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version="ignored",
        task_name="answer_region_grading",
        model_policy=ModelPolicy.REAL_GRADING,
        messages=messages(),
    )

    exec_cmd = calls[-1]
    assert exec_cmd[:2] == ["codex", "exec"]
    assert "--cd" in exec_cmd
    assert exec_cmd[exec_cmd.index("--cd") + 1] == "/home/newton/teacher-assistant"
    assert "--sandbox" in exec_cmd
    assert exec_cmd[exec_cmd.index("--sandbox") + 1] == "read-only"
    assert "--output-last-message" in exec_cmd
    assert "--json" in exec_cmd
    assert exec_cmd[exec_cmd.index("--model") + 1] == "gpt-5.5"
    assert "--image" not in exec_cmd
    assert "--skip-git-repo-check" not in exec_cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in exec_cmd
    assert inputs[-1] is not None
    assert "You are producing a grade suggestion for TA Agent." in inputs[-1]
    assert "Marking policy: general" in inputs[-1]
    assert "General marking" in inputs[-1]
    assert "Apply the rubric criterion-by-criterion" in inputs[-1]
    assert "Return strict JSON" in inputs[-1]
    assert "exact canonical grading unit and max marks" in inputs[-1]
    assert "formula choice, substitution, and valid final answer" in inputs[-1]
    assert "Do not over-penalize messy handwriting" in inputs[-1]
    assert "Bayes/probability score-band guidance for 6-mark subparts" in inputs[-1]
    assert "5-6 marks" in inputs[-1]
    assert "3-4 marks" in inputs[-1]
    assert "0-2 marks" in inputs[-1]
    assert "conceptual error" in inputs[-1]
    assert "arithmetic slip" in inputs[-1]
    assert "notation/presentation issue" in inputs[-1]
    assert "Bayes" in inputs[-1]
    assert "do not automatically slash the score" in inputs[-1]
    assert "Dependent rubric grading guidance" in inputs[-1]
    assert "Evaluate rubric criteria in context, not as isolated keyword checks" in inputs[-1]
    assert (
        "Do not award marks for a dependent criterion when its prerequisite claim is incorrect"
        in inputs[-1]
    )
    assert result.model_provider == "codex_cli"
    assert result.model_name == "gpt-5.5"
    assert result.prompt_version == "codex_cli_grading_v1"
    assert result.needs_review is True
    assert "teacher_review_required" in result.review_flags
    assert "codex_cli_provider" in result.review_flags
    assert "image_input_disabled" in result.review_flags


def test_codex_cli_provider_instructs_wrong_entity_phrase_gets_no_dependent_credit() -> None:
    provider = make_provider()
    prompt = provider._build_prompt(  # noqa: SLF001
        question_text="What is the capital of Bangladesh? Give one identifying phrase.",
        question_total_marks=Decimal("10.00"),
        rubric_json={
            "model_answer": (
                "Dhaka is the capital of Bangladesh. It is the country's main "
                "administrative and political centre."
            ),
            "criteria": [
                {"id": "capital", "name": "Capital identified correctly", "max_marks": "6"},
                {"id": "phrase", "name": "Valid identifying phrase", "max_marks": "4"},
            ],
        },
        messages=[],
        image_input_enabled=False,
        student_answer_text="Chittagong is the capital of Bangladesh. It is a major port city.",
    )

    assert "Chittagong is the capital of Bangladesh. It is a major port city." in prompt
    assert "the phrase must identify or describe Dhaka" in prompt
    assert (
        "Do not award marks for a dependent criterion when its prerequisite claim is incorrect"
        in prompt
    )
    assert "If a detail supports a wrong entity or wrong primary answer" in prompt
    assert "do not award that detail" in prompt
    assert "unless the rubric explicitly allows unrelated partial credit" in prompt


def test_codex_cli_provider_can_skip_git_repo_check_for_host_dev_mode() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(
                stdout="--cd <DIR>\n--sandbox <SANDBOX_MODE>\n--output-last-message <FILE>\n--json"
            )
        output_file = Path(cmd[cmd.index("--output-last-message") + 1])
        output_file.write_text(json.dumps(valid_codex_output()), encoding="utf-8")
        return FakeCompletedProcess()

    make_provider(runner=runner).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version="ignored",
        messages=messages(),
    )
    assert "--skip-git-repo-check" not in calls[-1]

    calls.clear()
    provider = CodexCliProvider(
        command="codex",
        model_name="gpt-5.5",
        timeout_seconds=300,
        sandbox="read-only",
        use_json=True,
        output_last_message=True,
        image_input_enabled=False,
        workdir="/home/newton/teacher-assistant",
        skip_git_repo_check=True,
        which=lambda command: "/usr/local/bin/codex",
        runner=runner,
    )
    provider.grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version="ignored",
        messages=messages(),
    )

    assert "--skip-git-repo-check" in calls[-1]


def test_codex_cli_missing_command_fails_clearly() -> None:
    provider = make_provider(which_result=None)

    with pytest.raises(CodexCliProviderError, match="codex command not found"):
        provider.grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )


def test_codex_cli_missing_output_last_message_support_fails_clearly() -> None:
    provider = make_provider(help_text="--cd <DIR>\n--sandbox <SANDBOX_MODE>")

    with pytest.raises(CodexCliProviderError, match="--output-last-message"):
        provider.grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )


def test_codex_cli_image_disabled_does_not_attempt_image_input() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout="--cd\n--sandbox\n--output-last-message\n--image")
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            json.dumps(valid_codex_output()), encoding="utf-8"
        )
        return FakeCompletedProcess()

    result = make_provider(runner=runner, image_input_enabled=False).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="/tmp/region.png",
        prompt_version="ignored",
        messages=messages(image_input_enabled=False),
    )

    assert "--image" not in calls[-1]
    assert "image_input_disabled" in result.review_flags


def test_codex_cli_image_enabled_includes_supported_image_flag() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(
                stdout="--cd\n--sandbox\n--output-last-message\n--json\n-i, --image <FILE>"
            )
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            json.dumps(valid_codex_output()), encoding="utf-8"
        )
        return FakeCompletedProcess()

    result = make_provider(runner=runner, image_input_enabled=True).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="/tmp/region.png",
        prompt_version="ignored",
        messages=messages(image_input_enabled=True),
    )

    assert "--image" in calls[-1]
    assert calls[-1][calls[-1].index("--image") + 1] == "/tmp/region.png"
    assert "image_input_used" in result.review_flags
    assert "image_input_disabled" not in result.review_flags


def test_codex_cli_image_enabled_without_image_path_omits_image_flag() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        calls.append(cmd)
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(
                stdout="--cd\n--sandbox\n--output-last-message\n--json\n--image <FILE>"
            )
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            json.dumps(valid_codex_output()), encoding="utf-8"
        )
        return FakeCompletedProcess()

    result = make_provider(runner=runner, image_input_enabled=True).grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="",
        prompt_version="ignored",
        messages=messages(image_input_enabled=True),
    )

    assert "--image" not in calls[-1]
    assert "image_input_disabled" in result.review_flags
    assert "image_input_used" not in result.review_flags


def test_codex_cli_image_enabled_but_no_image_flag_support_fails_clearly() -> None:
    provider = make_provider(
        help_text="--cd <DIR>\n--sandbox <SANDBOX_MODE>\n--output-last-message <FILE>",
        image_input_enabled=True,
    )

    with pytest.raises(CodexCliProviderError, match="image input is not supported"):
        provider.grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="/tmp/region.png",
            prompt_version="ignored",
            messages=messages(image_input_enabled=True),
        )


def test_codex_cli_parses_valid_json_from_output_last_message_file() -> None:
    result = make_provider().grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version="ignored",
        messages=messages(),
    )

    assert result.score == Decimal("3")
    assert result.confidence == Decimal("0.42")


def test_codex_cli_non_json_output_file_fails_safely() -> None:
    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout="--cd\n--sandbox\n--output-last-message")
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text("not json", encoding="utf-8")
        return FakeCompletedProcess()

    with pytest.raises(CodexCliProviderError, match="valid JSON"):
        make_provider(runner=runner).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )


def test_codex_cli_subprocess_timeout_fails_safely() -> None:
    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout="--cd\n--sandbox\n--output-last-message")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

    with pytest.raises(CodexCliProviderError, match="timed out"):
        make_provider(runner=runner).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )


def test_codex_cli_subprocess_non_zero_exit_fails_safely() -> None:
    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout="--cd\n--sandbox\n--output-last-message")
        return FakeCompletedProcess(returncode=2, stderr="failed with sk-secret-value")

    with pytest.raises(CodexCliProviderError) as exc_info:
        make_provider(runner=runner).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )
    error = str(exc_info.value)
    assert "exited with status 2" in error
    assert "classification=process_exit" in error
    assert "model=gpt-5.5" in error
    assert "command=codex exec" in error
    assert "stderr=failed with [REDACTED]" in error
    assert "sk-secret-value" not in error


def test_codex_cli_subprocess_failure_classifies_auth_model_usage_and_502() -> None:
    assert CodexCliProvider._classify_failure("401 unauthorized login required") == "auth"
    assert CodexCliProvider._classify_failure("unsupported model gpt-x") == "model"
    assert CodexCliProvider._classify_failure("rate limit exceeded") == "usage_limit"
    assert CodexCliProvider._classify_failure("502 bad gateway transient") == "transient_502"


def test_codex_cli_validation_failure_is_not_silently_accepted() -> None:
    def runner(cmd: list[str], **kwargs: object) -> FakeCompletedProcess:
        if cmd == ["codex", "--version"]:
            return FakeCompletedProcess(stdout="codex-cli 0.128.0")
        if cmd == ["codex", "exec", "--help"]:
            return FakeCompletedProcess(stdout="--cd\n--sandbox\n--output-last-message")
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            json.dumps({"score": 999, "max_score": 10}), encoding="utf-8"
        )
        return FakeCompletedProcess()

    with pytest.raises(ValidationError):
        make_provider(runner=runner).grade(
            question_text="Explain.",
            question_total_marks=Decimal("10.00"),
            rubric_json=rubric_payload(),
            answer_image_path="artifacts/region.png",
            prompt_version="ignored",
            messages=messages(),
        )


def test_codex_cli_adapter_does_not_require_openai_api_key() -> None:
    settings = Settings(BRAIN_PROVIDER="codex_cli", OPENAI_API_KEY="")

    adapter = BrainAdapter.from_settings(settings)

    assert isinstance(adapter.provider, CodexCliProvider)
    assert adapter.provider.provider_name == "codex_cli"
    assert adapter.provider.model_name == "gpt-5.5"


def test_codex_cli_raw_output_never_contains_image_base64() -> None:
    result = make_provider().grade(
        question_text="Explain.",
        question_total_marks=Decimal("10.00"),
        rubric_json=rubric_payload(),
        answer_image_path="artifacts/region.png",
        prompt_version="ignored",
        messages=messages(),
        image_data_url="data:image/png;base64,ZmFrZQ==",
    )

    assert "data:image" not in result.model_dump_json()
