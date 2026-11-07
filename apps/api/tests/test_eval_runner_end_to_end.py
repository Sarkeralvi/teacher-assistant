"""The smoke-eval runner end to end, offline.

``extract`` and ``run`` execute exactly as the founder will run them, against the
disposable test database, with only the Claude wire call scripted. A crash anywhere
between intake and the written report would otherwise first show up in a paid run.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
import os
import re
import sys
import zipfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from packages.brain.anthropic_provider import AnthropicApiProvider
from tests.bulk150_harness import bulk150_db_session  # noqa: F401  (fixture)
from tests.test_anthropic_bulk_pipeline import ScriptedClaude, _message

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_against_teacher_marks.py"
_spec = importlib.util.spec_from_file_location("eval_runner_e2e", _SCRIPT)
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)


class RubricAwareClaude(ScriptedClaude):
    """Credits the first rubric criterion in full, quoting the student's own text."""

    def __call__(self, provider: Any, params: dict[str, Any], *, use_fallback: bool) -> Any:
        content = params["messages"][0]["content"]
        text = content if isinstance(content, str) else content[-1]["text"]
        if "teacher-reviewable reference bundle" in text:
            self.requests.append({"use_fallback": use_fallback, **params})
            return _message(_reference_bundle()), "req_bundle"
        return super().__call__(provider, params, use_fallback=use_fallback)

    @staticmethod
    def _grade(prompt: str) -> SimpleNamespace:
        quoted = re.search(r"answer for \S+ read \d+", prompt)
        assert quoted is not None
        rubric = ast.literal_eval(prompt.split("<rubric>\n", 1)[1].split("\n</rubric>", 1)[0])
        breakdown = []
        for index, criterion in enumerate(rubric["criteria"]):
            maximum = Decimal(criterion["max_marks"])
            breakdown.append(
                {
                    "criterion_id": criterion["id"],
                    "criterion": criterion["name"],
                    "criterion_status": "met" if index == 0 else "not_met",
                    "max_marks": str(maximum),
                    "awarded_marks": str(maximum if index == 0 else 0),
                    "reason": "scripted",
                    "evidence": quoted.group(0) if index == 0 else None,
                    "confidence": "0.9",
                }
            )
        score = sum(Decimal(item["awarded_marks"]) for item in breakdown)
        maximum = sum(Decimal(item["max_marks"]) for item in breakdown)
        return _message(
            {
                "score": str(score),
                "max_score": str(maximum),
                "confidence": "0.9",
                "needs_review": True,
                "rubric_breakdown": breakdown,
                "detected_answer_summary": "scripted",
                "major_errors": [],
                "feedback_to_student": "scripted",
                "review_flags": [],
            }
        )


def _reference_bundle() -> dict[str, Any]:
    def question(number: str, marks: int, criteria: list[int]) -> dict[str, Any]:
        return {
            "question_number": number,
            "parent_question_number": "1",
            "node_type": "subquestion",
            "question_text": f"Question {number}",
            "model_answer": f"Model answer {number}",
            "marks": marks,
            "source_question_pages": [1],
            "source_solution_pages": [1],
            "source_text_excerpt": f"Question {number}",
            "confidence": 0.9,
            "criteria": [
                {
                    "criterion_label": f"{number} step {index}",
                    "description": f"{number} step {index}",
                    "max_marks": value,
                    "confidence": 0.9,
                    "source_rubric_pages": [1],
                }
                for index, value in enumerate(criteria, start=1)
            ],
            "blockers": [],
            "needs_review": True,
        }

    return {"questions": [question("1(a)", 5, [2, 3]), question("1(b)", 4, [4])], "warnings": []}


def _pdf(pages: int, label: str) -> bytes:
    document = pymupdf.open()
    for page_no in range(1, pages + 1):
        document.new_page(width=595, height=842).insert_text(
            (72, 120), f"{label} page {page_no}", fontsize=18
        )
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def exam_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "exam"
    folder.mkdir()
    (folder / "Question.pdf").write_bytes(_pdf(1, "question"))
    (folder / "Solution.pdf").write_bytes(_pdf(1, "solution"))
    (folder / "rubric.pdf").write_bytes(_pdf(1, "rubric"))
    with zipfile.ZipFile(folder / "Scripts-flat.zip", "w") as archive:
        for student in ("S001", "S002"):
            archive.writestr(f"{student}.pdf", _pdf(2, student))
    return folder


@pytest.fixture
def offline_claude(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[RubricAwareClaude]:
    """Scripted wire, isolated environment, restored working directory and settings cache."""

    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_ENABLED",
        "BRAIN_ALLOW_REAL_PROVIDERS",
        "BRAIN_PROVIDER",
        "SCRIPT_PAGE_RENDER_DPI",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("ANTHROPIC_EVAL_API_KEY", "eval-key-not-real")
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    monkeypatch.chdir(tmp_path)
    # The test base directory sits inside the repository; the real guard is tested elsewhere.
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path / "not-the-repository")
    scripted = RubricAwareClaude()
    monkeypatch.setattr(
        AnthropicApiProvider,
        "_send",
        lambda self, params, *, use_fallback: scripted(self, params, use_fallback=use_fallback),
    )
    monkeypatch.setattr(AnthropicApiProvider, "verify_available_model", lambda self: None)
    get_settings.cache_clear()
    yield scripted
    get_settings.cache_clear()


def test_extract_writes_a_blueprint_draft(
    exam_dir: Path, tmp_path: Path, offline_claude: RubricAwareClaude
) -> None:
    out = tmp_path / "out-extract"
    args = SimpleNamespace(
        exam_dir=str(exam_dir), out=str(out), env_file=None, yes=True, max_cost_usd=None
    )
    assert runner.cmd_extract(args) == 0
    draft = json.loads((out / "blueprint.draft.json").read_text(encoding="utf-8"))
    assert [item["question_number"] for item in draft["questions"]] == ["1(a)", "1(b)"]
    assert [call["task"] for call in draft["_eval"]["calls"]] == ["visual_reference_bundle"]
    (request,) = offline_claude.requests
    images = [block for block in request["messages"][0]["content"] if block["type"] == "image"]
    assert len(images) == 3  # question, solution and rubric pages


def test_run_compares_claude_with_teacher_marks_and_writes_reports(
    db_session: Session, exam_dir: Path, tmp_path: Path, offline_claude: RubricAwareClaude
) -> None:
    confirmed = tmp_path / "blueprint.confirmed.json"
    confirmed.write_text(json.dumps(_reference_bundle()), encoding="utf-8")
    marks = tmp_path / "marks.csv"
    marks.write_text(
        "script_file,student_id,part_label,mark\n"
        "S001.pdf,S001,1a,2\nS001.pdf,S001,1b,4\n"
        "S002.pdf,S002,1(a),3\nS002.pdf,S002,1(b),3\n",
        encoding="utf-8",
    )
    out = tmp_path / "out-run"
    args = SimpleNamespace(
        exam_dir=str(exam_dir),
        out=str(out),
        blueprint=str(confirmed),
        blueprint_draft=None,
        marks=str(marks),
        label_map=None,
        env_file=None,
        yes=True,
        max_cost_usd=None,
        render_dpi=144,
        database_url=os.environ["DATABASE_URL"],
        keep_db=False,
    )
    assert runner.cmd_run(args) == 0

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    agreement = summary["agreement"]
    # Claude gives 2/5 on 1(a) and 4/4 on 1(b) for both students.
    assert agreement["parts_compared"] == 4
    assert agreement["exact_matches"] == 2
    assert agreement["over_scored_parts"] == 1
    assert agreement["under_scored_parts"] == 1
    assert agreement["grade_contract"]["parts_with_credit_removed"] == 0
    assert summary["eval_only_transcript_confirmation"] is True
    assert summary["spending"]["cap_reached"] is False
    tasks = summary["calls"]["by_task"]
    assert tasks["visual_page_read"]["calls"] == 4
    assert tasks["grading"]["calls"] == 4
    with (out / "per_part.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["item_status"] for row in rows} == {"graded"}
    assert sum(1 for _ in (out / "calls.jsonl").open(encoding="utf-8")) == len(
        offline_claude.requests
    )
    # No student answer text in the aggregate report.
    assert "answer for" not in (out / "summary.json").read_text(encoding="utf-8")
