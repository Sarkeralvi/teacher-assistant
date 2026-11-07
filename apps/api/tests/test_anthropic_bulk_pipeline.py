"""The Claude provider drives the REAL Bulk Supervised pipeline end to end.

Only the wire call (``AnthropicApiProvider._send``) is scripted, so everything
between the bulk service and the SDK request is production code: profile
construction from settings, the capability and feature gates, page reading,
whole-transcript assignment, the transcript-review gate, grading through the
adapter (including the shared grade contract), call observation and cost
accounting. No network and no paid call.
"""

from __future__ import annotations

import json
import re
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BulkEvaluationItem, GradeSuggestion
from app.services.bulk_evaluation_service import BulkEvaluationService
from packages.brain.anthropic_provider import (
    REFUSAL_FALLBACK_BETA,
    AnthropicApiProvider,
    register_call_observer,
)
from tests.bulk150_harness import (
    assert_no_final_grades,
    bulk150_db_session,  # noqa: F401  (fixture)
    bulk_environment,
    drain,
    harness_storage,
    resume_all_items,
    review_all_transcripts,
    seed_assessment,
)

MODEL = "claude-opus-5-5"
LABELS = ("Q1", "Q2")


def _message(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        model=MODEL,
        stop_reason="end_turn",
        stop_details=None,
        usage=SimpleNamespace(
            input_tokens=1500,
            output_tokens=400,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )


class ScriptedClaude:
    """Answers each request from what the request itself contains."""

    def __init__(self) -> None:
        self.page_reads = 0
        self.requests: list[dict[str, Any]] = []

    def __call__(
        self, provider: AnthropicApiProvider, params: dict[str, Any], *, use_fallback: bool
    ) -> tuple[SimpleNamespace, str]:
        del provider
        self.requests.append({"use_fallback": use_fallback, **params})
        content = params["messages"][0]["content"]
        text = content if isinstance(content, str) else content[-1]["text"]
        if "FINALIZED LABELS" in text and "complete handwritten mathematics" in text:
            return self._page_read(text), f"req_read_{self.page_reads}"
        if "SAVED COMPLETE-SCRIPT TRANSCRIPT" in text:
            return self._assignment(text), "req_assign"
        if "Task: answer_region_grading" in text:
            return self._grade(text), "req_grade"
        raise AssertionError(f"unexpected Claude request: {text[:120]}")

    def _page_read(self, prompt: str) -> SimpleNamespace:
        labels = json.loads(prompt.split("FINALIZED LABELS: ", 1)[1].split("\n", 1)[0])
        label = labels[self.page_reads % len(labels)]
        self.page_reads += 1
        return _message(
            {
                "blocks": [
                    {
                        "question_label": label,
                        "bbox": [50, 50, 950, 600],
                        "text": f"answer for {label} read {self.page_reads}",
                        "continues_from_previous": False,
                        "label_source": "heading",
                        "confidence": 0.97,
                    }
                ],
                "is_blank_page": False,
                "needs_review": True,
            }
        )

    @staticmethod
    def _assignment(prompt: str) -> SimpleNamespace:
        questions = json.loads(
            prompt.split("FINALIZED QUESTIONS\n", 1)[1].split("\n\n", 1)[0]
        )
        blocks = re.findall(r"\[page=(\d+) block=(\d+)\] answer for (\S+)", prompt)
        mappings = []
        for question in questions:
            owned = [(int(page), int(block)) for page, block, label in blocks
                     if label == question["question_no"]]
            mappings.append(
                {
                    "question_id": question["question_id"],
                    "question_no": question["question_no"],
                    "status": "mapped" if owned else "not_found",
                    "block_references": [
                        {"page_no": page, "block_orders": [block]} for page, block in owned
                    ],
                    "confidence": 0.95,
                    "warnings": [],
                    "needs_review": True,
                }
            )
        return _message(
            {
                "contract_version": "full-transcript-assignment-v4",
                "mappings": mappings,
                "unassigned_block_references": [],
                "non_answer_block_references": [],
                "warnings": [],
            }
        )

    @staticmethod
    def _grade(prompt: str) -> SimpleNamespace:
        quoted = re.search(r"answer for (Q\d) read \d+", prompt)
        assert quoted is not None, "grading prompt must carry the saved transcript text"
        return _message(
            {
                "score": 4,
                "max_score": 5,
                "confidence": 0.9,
                "needs_review": True,
                "rubric_breakdown": [
                    {
                        "criterion_id": "accuracy",
                        "criterion": "Accuracy",
                        "criterion_status": "partially_met",
                        "max_marks": 5,
                        "awarded_marks": 4,
                        "reason": "Mostly correct",
                        "evidence": quoted.group(0),
                        "confidence": 0.9,
                    }
                ],
                "detected_answer_summary": "Answer present",
                "major_errors": [],
                "feedback_to_student": "Good work; check the last step.",
                "review_flags": [],
            }
        )


def _scripts_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for student in ("S001", "S002"):
            document = pymupdf.open()
            for page_no in (1, 2):
                page = document.new_page(width=595, height=842)
                page.insert_text((72, 120), f"{student} handwritten page {page_no}", fontsize=18)
            archive.writestr(f"{student}.pdf", document.tobytes())
            document.close()
    return path


def test_claude_profile_runs_the_real_bulk_pipeline(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "BRAIN_PROVIDER": "anthropic",
        "BRAIN_ALLOW_REAL_PROVIDERS": "true",
        "ANTHROPIC_ENABLED": "true",
        "ANTHROPIC_API_KEY": "test-key-not-real",
    }.items():
        monkeypatch.setenv(name, value)
    scripted = ScriptedClaude()
    monkeypatch.setattr(
        AnthropicApiProvider,
        "_send",
        lambda self, params, *, use_fallback: scripted(self, params, use_fallback=use_fallback),
    )
    # The pre-run key check is a real (unbilled) request; keep this test offline.
    verified: list[str] = []
    monkeypatch.setattr(
        AnthropicApiProvider,
        "verify_available_model",
        lambda self: verified.append(self.model_name),
    )
    calls: list[dict[str, Any]] = []
    unregister = register_call_observer(calls.append)
    try:
        with bulk_environment(tmp_path / "storage") as settings:
            seeded = seed_assessment(db_session, questions=LABELS, marks="5.00")
            service = BulkEvaluationService(
                db_session, settings=settings, storage=harness_storage(settings)
            )
            archive = _scripts_zip(tmp_path / "scripts.zip")
            run = service.create_from_zip(
                assessment_id=seeded.assessment.id,
                grading_run=seeded.grading_run,
                teacher=seeded.teacher,
                upload=UploadFile(filename=archive.name, file=archive.open("rb")),
                expected_model=MODEL,
                marking_policy="general",
                maximum_provider_calls=60,
                provider="anthropic",
            )
            assert run.provider == "anthropic"
            assert run.model_name == MODEL
            drain(run.id, settings=settings)
            review = review_all_transcripts(db_session, run.id, seeded.teacher)
            assert len(review.confirmed) == 2, review.refused
            resume_all_items(run.id, seeded.teacher, settings=settings)
            result = drain(run.id, settings=settings)
            assert result.error is None
    finally:
        unregister()

    db_session.expire_all()
    items = db_session.scalars(
        select(BulkEvaluationItem).where(BulkEvaluationItem.run_id == run.id)
    ).all()
    assert len(items) == 4
    assert {item.status for item in items} == {"graded"}
    suggestions = [db_session.get(GradeSuggestion, item.grade_suggestion_id) for item in items]
    for suggestion in suggestions:
        assert suggestion is not None
        assert suggestion.model_provider == "anthropic"
        assert suggestion.model_name == MODEL
        assert suggestion.score == Decimal("4.00")
        assert suggestion.needs_review is True
        assert suggestion.cost_estimate and suggestion.cost_estimate > 0
        flags = suggestion.raw_response_json["review_flags"]
        assert {"teacher_review_required", "anthropic_api_provider"} <= set(flags)
    assert_no_final_grades(db_session, run.id)

    assert verified, "every execution hold checks the key and model first"
    tasks = [call["task"] for call in calls]
    assert tasks.count("visual_page_read") == 4
    assert tasks.count("grading") == 4
    assert all(call["model_served"] == MODEL for call in calls)
    # Grading may use the refusal fallback; evidence tasks never do.
    for request in scripted.requests:
        content = request["messages"][0]["content"]
        text = content if isinstance(content, str) else content[-1]["text"]
        assert request["use_fallback"] is ("Task: answer_region_grading" in text)
        assert not {"temperature", "top_p", "top_k"} & set(request)
    # The page reads were blind: no model answer or rubric text reached them.
    for request in scripted.requests:
        content = request["messages"][0]["content"]
        if isinstance(content, list):
            assert "Synthetic model answer" not in content[-1]["text"]
    assert REFUSAL_FALLBACK_BETA  # imported constant stays defined
