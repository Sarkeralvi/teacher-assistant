"""Offline checks for the Claude smoke-eval runner (no network, no database)."""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_against_teacher_marks.py"
_spec = importlib.util.spec_from_file_location("eval_against_teacher_marks", _SCRIPT)
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
# Dataclasses resolve their module through sys.modules while the class is created.
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)


def _blueprint(path: Path, *, criterion_marks: tuple[str, ...] = ("2", "3"), marks="5") -> Path:
    path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question_number": "1(a)",
                        "question_text": "Find x.",
                        "model_answer": "x = 2",
                        "marks": marks,
                        "criteria": [
                            {"criterion_label": f"step {index}", "max_marks": value}
                            for index, value in enumerate(criterion_marks, start=1)
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("label", ["1(a)", "Q1 (a)", "1.a", "1a", " question 1(A) "])
def test_part_labels_compare_loosely(label: str) -> None:
    assert runner.normalize_label(label) == "1a"


def test_blueprint_criteria_must_add_up_to_question_marks(tmp_path: Path) -> None:
    assert runner.load_blueprint(_blueprint(tmp_path / "ok.json"))[0]["marks"] == Decimal("5")
    with pytest.raises(runner.EvalError, match="sum to 4"):
        runner.load_blueprint(_blueprint(tmp_path / "bad.json", criterion_marks=("2", "2")))


def test_marks_map_teacher_labels_onto_blueprint_labels(tmp_path: Path) -> None:
    marks_file = tmp_path / "marks.csv"
    marks_file.write_text(
        "script_file,student_id,part_label,mark\n2105001.pdf,2105001,Ans 1a,3.5\n",
        encoding="utf-8",
    )
    with pytest.raises(runner.EvalError, match="label-map"):
        runner.load_marks(marks_file, {}, ["1(a)"])
    marks = runner.load_marks(marks_file, {"Ans 1a": "1(a)"}, ["1(a)"])
    assert marks[("2105001", "1a")] == Decimal("3.5")


def test_outputs_must_stay_outside_the_repository() -> None:
    with pytest.raises(runner.EvalError, match="outside the repository"):
        runner._require_outside_repo(runner.REPO_ROOT / "tmp" / "eval-out")


def test_env_file_loads_only_named_keys_and_requires_the_eval_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # setenv (not delenv) so that monkeypatch restores every name the runner writes.
    for name in (
        "ANTHROPIC_EVAL_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "BRAIN_PROVIDER",
        "ANTHROPIC_ENABLED",
        "BRAIN_ALLOW_REAL_PROVIDERS",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "DATABASE_URL=postgresql://real-pilot-db\nANTHROPIC_API_KEY=app-key-not-for-evals\n",
        encoding="utf-8",
    )
    assert runner._load_env_file(env_file) == []
    with pytest.raises(runner.EvalError, match="ANTHROPIC_EVAL_API_KEY"):
        runner._configure_claude_environment()
    env_file.write_text("ANTHROPIC_EVAL_API_KEY='eval-key'\n", encoding="utf-8")
    assert runner._load_env_file(env_file) == ["ANTHROPIC_EVAL_API_KEY"]
    runner._configure_claude_environment()
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "eval-key"
    assert "DATABASE_URL" not in os.environ


def test_paid_steps_need_explicit_approval_and_get_a_hard_cap() -> None:
    with pytest.raises(runner.EvalError, match="--yes"):
        runner._confirm_spend(Decimal("1.23"), Decimal("3.00"), approved=False)
    assert runner._confirm_spend(Decimal("1"), Decimal("3"), approved=True) == Decimal("7")
    assert runner._confirm_spend(
        Decimal("1"), Decimal("3"), approved=True, cap_usd=Decimal("2.5")
    ) == Decimal("2.5")


def test_spend_tracker_refuses_the_next_call_once_the_cap_is_reached() -> None:
    from packages.brain.anthropic_provider import SpendLimitReached

    tracker = runner.SpendTracker(Decimal("1.00"))
    tracker.guard("visual_page_read")
    tracker.observe({"cost_usd": "0.60"})
    tracker.guard("visual_page_read")
    tracker.observe({"cost_usd": "0.45"})
    with pytest.raises(SpendLimitReached, match="grading call was not sent"):
        tracker.guard("grading")


def test_only_disposable_databases_are_accepted() -> None:
    url = "postgresql+psycopg://u@127.0.0.1:5432/teacher_assistant_test"
    assert runner._require_disposable_url(url) == url
    with pytest.raises(runner.EvalError, match="disposable"):
        runner._require_disposable_url("postgresql+psycopg://u@127.0.0.1:5432/teacher_assistant")


def test_report_flag_names_match_the_grade_checks() -> None:
    from packages.brain import grade_contract as contract

    assert runner.MODEL_SCORE_PREFIX == contract.MODEL_SCORE_FLAG_PREFIX
    assert {
        contract.UNSUPPORTED_EVIDENCE_FLAG,
        contract.DEPENDENT_CREDIT_FLAG,
        contract.MAXIMUM_CHANGED_FLAG,
        contract.RUBRIC_SHAPE_FLAG,
        "not_met_criterion_credit_removed",
    } == runner.CHANGE_FLAGS


def test_input_paths_are_made_absolute_before_the_working_directory_changes() -> None:
    resolved = runner._absolute("marks.csv")
    assert resolved is not None and resolved.is_absolute()
    assert runner._absolute(None) is None


def test_comparison_counts_over_scores_and_flag_recall() -> None:
    def row(
        student: str, part: str, ai: str | None, *, confidence="0.9", flags=(), status="graded"
    ):
        submission = SimpleNamespace(student_identifier=student)
        question = SimpleNamespace(question_no=part, total_marks=Decimal("5"))
        item = SimpleNamespace(status=status, exception_codes=[])
        suggestion = (
            None
            if ai is None
            else SimpleNamespace(
                score=Decimal(ai),
                confidence=Decimal(confidence),
                raw_response_json={"review_flags": list(flags)},
            )
        )
        return submission, question, item, suggestion

    teacher = {
        ("s1", "1a"): Decimal("3"),
        ("s1", "1b"): Decimal("2"),
        ("s2", "1a"): Decimal("4"),
        ("s2", "1b"): Decimal("5"),
    }
    report = runner._compare(
        [
            row("S1", "1(a)", "3"),
            row("S1", "1(b)", "4.5", confidence="0.95"),
            row("S2", "1(a)", "2.5", confidence="0.6"),
            row("S2", "1(b)", None, status="exception"),
        ],
        teacher,
        settings_threshold=Decimal("0.80"),
    )
    aggregate = report["aggregate"]
    assert aggregate["parts_compared"] == 3
    assert aggregate["parts_unscored_by_ai"] == 1
    assert aggregate["exact_matches"] == 1
    assert aggregate["over_scored_parts"] == 1
    assert aggregate["largest_over_score"] == "2.5"
    assert aggregate["under_scored_parts"] == 1
    assert aggregate["misses_of_one_mark_or_more"] == 2
    # The confident +2.5 over-score was NOT flagged; the low-confidence miss was.
    assert aggregate["those_misses_flagged_for_review"] == 1
