"""Smoke tests for the synthetic bulk harness (tests.bulk150_harness).

They drive the REAL Bulk Supervised pipeline with a fake brain provider and prove the
harness is trustworthy: it reaches graded drafts, its leakage detector can actually fail,
injected faults change outcomes, and byte-identical pages shared by two students stay
separate. No network, no model server, no real data.

Tests marked ``xfail(strict=True, reason="GAP: ...")`` assert the CORRECT behaviour and fail
today because of a production defect the harness proved. They are the evidence for the
findings; when the product is fixed they flip to XPASS(strict) and must be un-marked.

A GAP test is ``xfail(raises=AssertionError)``, and a failed ``assert`` in its SETUP is an
``AssertionError`` too, so a Fault that never fired would still XFAIL and "prove" a defect the
test never reached. Therefore a GAP test contains exactly ONE kind of plain ``assert``: the
desired-behaviour assertion. Every setup check (the Fault fired, the run paused, the teacher
gate accepted, the budget was what the scenario needs) goes through
:func:`tests.bulk150_harness.precondition`, whose ``pytest.fail`` is not an ``AssertionError``
and so shows up as a real FAILURE. ``test_precondition_...`` below pins that behaviour against
the real xfail machinery, and the same holds for the shared helpers (``_run``,
``_gate_and_grade``, ``_kill_mid_grading``) that GAP tests call.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    AuditLog,
    BulkEvaluationItem,
    BulkEvaluationRun,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
)
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.storage import LocalStorage
from tests.bulk150_harness import (  # noqa: F401
    BULK_ENV_FLAGS,
    CLEANUP_MODELS,
    CallRecord,
    Corpus,
    DrainResult,
    FakeBulkBrainProvider,
    Fault,
    HarnessError,
    HarnessStorage,
    ProcessKilled,
    RecoverMidCall,
    Seeded,
    age_grading_jobs,
    age_page_reservations,
    age_run_heartbeat,
    assert_continuations_isolated,
    assert_disposable_database,
    assert_every_answered_question_graded,
    assert_no_cross_student_evidence,
    assert_no_final_grades,
    assert_settings_agree,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    bulk_environment,
    common_students,
    drain,
    drain_unit_budget,
    drop_block,
    empty_non_blank_page,
    expire_lease,
    hallucinate_label,
    hard_kill_skips_lease_release,
    harness_storage,
    import_zip,
    install_fake_brain,
    item_views,
    leave_lease_held,
    make_settings,
    other_session,
    parse_tokens,
    precondition,
    precondition_faults_fired,
    read_lease,
    reconcile_unknown_pages,
    register_stored_pages,
    require_active_storage,
    resume_all_items,
    reverse_blocks,
    review_all_transcripts,
    seed_assessment,
    try_resume_run,
)


@dataclass
class Ctx:
    db: Session
    settings: Settings
    seeded: Seeded
    corpus: Corpus
    provider: FakeBulkBrainProvider
    run_id: int


def _start(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    students: int = 3,
    pages: int = 2,
    questions: int = 2,
    budget_slack: int = 2,
    register: bool = True,
    managed_local_phase: str | None = None,
    before_import: Callable[[FakeBulkBrainProvider], None] | None = None,
    **corpus_kwargs: Any,
) -> Ctx:
    """Seed, build the archive, import it. ``before_import`` sees the provider first, so a
    Fault can target the ``create_from_zip`` preflight (verify call #1)."""

    seeded = seed_assessment(db, questions=questions)
    corpus = build_zip(
        tmp_path / "bulk.zip", students=students, pages=pages, questions=questions, **corpus_kwargs
    )
    provider = FakeBulkBrainProvider(corpus, managed_local_phase=managed_local_phase)
    install_fake_brain(monkeypatch, provider, settings)
    if before_import is not None:
        before_import(provider)
    run = import_zip(
        db,
        seeded=seeded,
        corpus=corpus,
        provider=provider,
        settings=settings,
        budget_slack=budget_slack,
        register=register,
    )
    return Ctx(db, settings, seeded, corpus, provider, run.id)


def _read_stage(ctx: Ctx) -> DrainResult:
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _gate_and_grade(ctx: Ctx) -> DrainResult:
    """Teacher gate through the real routes, resume the held items, grade them.

    A refused gate is a broken PRECONDITION (see the module docstring), not a finding.
    """

    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _run(ctx: Ctx) -> BulkEvaluationRun:
    ctx.db.expire_all()
    run = ctx.db.get(BulkEvaluationRun, ctx.run_id)
    if run is None:  # not an assert: see the module docstring
        pytest.fail(f"PRECONDITION BROKEN: run {ctx.run_id} does not exist")
    return run


def _assert_calls_match(ctx: Ctx) -> None:
    """The run's own call ledger equals what the fake provider actually served."""

    assert _run(ctx).calls_used == ctx.provider.total_calls


def test_three_students_run_the_whole_pipeline_to_graded_drafts(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seeded = seed_assessment(db_session, questions=2)
    corpus = build_zip(tmp_path / "three.zip", students=3, pages=2, questions=2, layout="images")
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)

    run = import_zip(db_session, seeded=seeded, corpus=corpus, provider=provider, settings=bulk_env)
    assert (run.total_submissions, run.total_pages, run.total_items) == (3, 6, 6)
    assert run.import_manifest["visual_evidence_path"] == "page_read"
    assert corpus.call_budget() == 12
    assert run.authorized_call_limit == 14  # exact need + the harness's default slack of 2

    # Stage 1: every page is read exactly once and nothing is graded before the teacher gate.
    first = drain(run.id, settings=bulk_env, provider=provider)
    assert first.status == "completed_with_exceptions"
    assert provider.counts == {"read_page": 6, "map": 0, "grade": 0}
    views = item_views(db_session, run.id)
    assert {(v.status, v.stage, v.codes) for v in views.values()} == {
        ("exception", "read", ("evidence_review_required",))
    }
    assert_no_final_grades(db_session, run.id)

    # Stage 2: the real teacher gate, through the real route functions.
    reviewed = review_all_transcripts(db_session, run.id, seeded.teacher)
    assert not reviewed.refused
    assert len(reviewed.confirmed) == 3
    resumed = resume_all_items(run.id, seeded.teacher, settings=bulk_env)
    assert len(resumed.resumed) == 6 and not resumed.refused

    # Stage 3: draft grading.
    second = drain(run.id, settings=bulk_env, provider=provider)
    assert second.status == "review_ready", second
    assert provider.counts == {"read_page": 6, "map": 0, "grade": 6}

    db_session.expire_all()
    final_run = db_session.get(BulkEvaluationRun, run.id)
    assert final_run is not None
    assert final_run.calls_used == provider.total_calls == 12
    assert (final_run.clean_item_count, final_run.exception_count) == (6, 0)

    views = item_views(db_session, run.id)
    assert len(views) == 6
    for (student, question), view in views.items():
        assert (view.status, view.stage) == ("graded", "review"), (student, question)
        assert view.confidence is not None and view.confidence >= 0.80
        assert view.provider_calls == 1
    # Each grading call received exactly its own student's, its own question's text.
    for call in provider.calls_of("grade"):
        assert call.verdict == "ok", call
    for student, question in views:
        seen = [
            call.tokens
            for call in provider.calls_of("grade")
            if call.question == question and set(call.students) == {student}
        ]
        assert seen == [tuple(corpus.expected_tokens(student, question))], (student, question)

    inspected = assert_no_cross_student_evidence(
        db_session, run.id, corpus=corpus, provider=provider
    )
    assert inspected >= 6 * 3
    assert_no_final_grades(db_session, run.id)


@pytest.mark.parametrize("mode", ["unlabeled", "inferred"])
def test_continuation_blocks_exercise_the_whole_transcript_assignment_call(
    mode: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        continuation=mode,
        spill=True,
    )
    assert all(ctx.corpus.needs_assignment_call(s) for s in ctx.corpus.students)

    first = _read_stage(ctx)
    # One read per page, then exactly one whole-transcript assignment call per script.
    assert ctx.provider.counts == {"read_page": 4, "map": 2, "grade": 0}
    assert first.status == "completed_with_exceptions"
    # Inferred ownership is never auto-trusted: every item waits for the teacher.
    assert {v.codes for v in item_views(ctx.db, ctx.run_id).values()} == {
        ("inferred_question_label",)
    }
    for call in ctx.provider.calls_of("map"):
        assert set(call.question_labels) == set(ctx.seeded.labels)

    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    assert len(reviewed.ownership_confirmed) == 2 and not reviewed.refused
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)

    assert final.status == "review_ready", final
    assert ctx.provider.counts == {"read_page": 4, "map": 2, "grade": 4}
    assert ctx.provider.total_calls == ctx.corpus.call_budget()
    _assert_calls_match(ctx)
    for call in ctx.provider.calls_of("grade"):
        assert call.verdict == "ok", call
    # Q1 spilled over the page break into the page that opens Q2: both pieces reach Q1.
    for student in ctx.corpus.students:
        assert len(ctx.corpus.expected_tokens(student, "Q1")) == 2
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)
    assert_no_final_grades(ctx.db, ctx.run_id)


@pytest.mark.parametrize(
    "options",
    [
        {"layout": "folders"},
        {"layout": "pdf", "manifest": True},
        {"layout": "images", "manifest": True, "image_format": "jpg"},
        {"layout": "images", "identifiers": ["alice.01", "Bob-02"]},
        {"layout": "images", "wrapper": None, "page_size": (300, 400)},
    ],
    ids=["folders", "pdf+manifest", "jpg+manifest", "custom-identifiers", "page-size"],
)
def test_every_corpus_option_reaches_graded_drafts(
    options: dict[str, Any],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, **options)
    assert ctx.corpus.layout == options["layout"]
    if options.get("manifest"):
        assert all(source.startswith("scan_") for source in ctx.corpus.sources.values())
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final
    views = item_views(ctx.db, ctx.run_id)
    assert {student for student, _q in views} == set(ctx.corpus.students)
    assert {v.status for v in views.values()} == {"graded"}
    _assert_calls_match(ctx)
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)


def test_pdf_layout_out_of_order_answers_and_a_blank_page(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=3,
        pages=3,
        questions=3,
        layout="pdf",
        out_of_order=("S002",),
        blank_pages=(("S003", 2),),
    )
    # S002 answers Q3 before Q1.
    assert ctx.corpus.expected_tokens("S002", "Q3")[0].endswith("|p1|b1")
    assert ctx.corpus.expected_tokens("S002", "Q1")[0].endswith("|p3|b1")

    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final
    views = item_views(ctx.db, ctx.run_id)
    # S003's Q2 sat on the blank page: the whole script was read and nothing answers it.
    blank = views[("S003", "Q2")]
    assert (blank.status, blank.codes, blank.suggestion_id) == (
        "exception",
        ("missing_answer",),
        None,
    )
    graded = [key for key, view in views.items() if view.status == "graded"]
    assert len(graded) == 8
    assert ctx.provider.counts == {"read_page": 9, "map": 0, "grade": 8}
    _assert_calls_match(ctx)
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)
    assert_no_final_grades(ctx.db, ctx.run_id)


def test_leaking_provider_is_caught_by_the_leak_detector(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL: the detector must fail when another student's text arrives."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    ctx.provider.leak[("S001", 1)] = "S002"  # S001's page 1 comes back with S002's writing
    _read_stage(ctx)
    final = _gate_and_grade(ctx)

    # The pipeline itself sees nothing wrong, and the fake grader (which has no student
    # context) even rates the leaked evidence clean. Only the detector stands in the way.
    assert final.status == "review_ready", final
    leaked = item_views(ctx.db, ctx.run_id)[("S001", "Q1")]
    assert leaked.status == "graded" and leaked.confidence is not None
    assert float(leaked.confidence) == 0.95
    with pytest.raises(AssertionError, match=r"foreign student token SYN150\|S002\|Q1\|p1\|b1"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)
    # The unleaked student is fine on its own: the detector names the guilty submission only.
    with pytest.raises(AssertionError) as caught:
        assert_no_cross_student_evidence(ctx.db, ctx.run_id)
    assert "expected S002" not in str(caught.value)


def test_a_mixed_student_leak_is_visible_to_the_fake_grader_as_low_confidence(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL 3: evidence that MIXES two students is flagged by the grader as well.

    S001's page 2 comes back with S002's writing. S001/Q1 now holds its own page-1 text plus
    S002's continuation, so the fake grader sees two students and rates it 0.40; the leak
    detector fails too. S001/Q2 is a complete substitution by ONE other student: the grader
    cannot tell (production sends no student identity in the grading prompt) and rates it
    clean, so only ``assert_no_cross_student_evidence`` can catch that half.
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        continuation=True,
        spill=True,
    )
    ctx.provider.leak[("S001", 2)] = "S002"
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final

    views = item_views(ctx.db, ctx.run_id)
    mixed = views[("S001", "Q1")]
    assert (mixed.status, mixed.codes) == ("exception", ("verification_disagreement",))
    assert mixed.confidence is not None and float(mixed.confidence) == 0.40
    substituted = views[("S001", "Q2")]  # wholly another student's text: grader is blind to it
    assert substituted.status == "graded" and float(substituted.confidence or 0) == 0.95
    assert {views[("S002", q)].status for q in ctx.seeded.labels} == {"graded"}
    verdicts = {(c.question, c.verdict) for c in ctx.provider.calls_of("grade") if c.question}
    assert ("Q1", "mixed_students") in verdicts

    with pytest.raises(AssertionError, match="foreign student token SYN150\\|S002\\|Q1\\|p2\\|b1"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)
    with pytest.raises(AssertionError, match="saw several students"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, provider=ctx.provider)


def test_leak_detector_also_fails_on_mixing_inside_the_database(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL 2: no provider involved, the stored evidence rows are swapped."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    _read_stage(ctx)
    _gate_and_grade(ctx)
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)

    ids = {row.student_identifier: row.id for row in ctx.db.scalars(select(Submission)).all()}
    spans = {
        student: ctx.db.scalars(
            select(AnswerEvidenceSpan)
            .join(AnswerEvidenceAssignment)
            .where(
                AnswerEvidenceAssignment.submission_id == submission_id,
                AnswerEvidenceAssignment.is_current.is_(True),
            )
            .order_by(AnswerEvidenceSpan.id)
        ).first()
        for student, submission_id in ids.items()
    }
    first, second = spans["S001"], spans["S002"]
    assert first is not None and second is not None
    first_block, second_block = first.script_transcript_block_id, second.script_transcript_block_id
    ctx.db.execute(
        update(AnswerEvidenceSpan)
        .where(AnswerEvidenceSpan.id == first.id)
        .values(script_transcript_block_id=second_block)
    )
    ctx.db.commit()
    assert first_block != second_block
    with pytest.raises(AssertionError, match="foreign student token"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)


def test_unregistered_page_fails_loudly_instead_of_inventing_text(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, register=False)
    result = _read_stage(ctx)
    assert result.status == "paused"
    assert "no expected page registered" in (result.error or "")
    assert ctx.provider.calls[0].outcome == "unregistered"


def test_failed_page_read_pauses_the_run_and_resume_reads_that_page_again(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure injection changes the outcome, and production's recovery path works."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("read_page", RuntimeError("synthetic 500"), student="S002"))

    paused = _read_stage(ctx)
    assert paused.status == "paused"
    assert "synthetic 500" in (paused.error or "")
    views = item_views(ctx.db, ctx.run_id)
    # S001 had already been read and handed to the teacher gate; only S002 is in doubt.
    assert {v.codes for k, v in views.items() if k[0] == "S001"} == {("evidence_review_required",)}
    assert {(v.status, v.codes) for k, v in views.items() if k[0] == "S002"} == {
        ("uncertain", ("provider_contract_failure",))
    }
    # The failed attempt is a call used, and the page is recorded as a known failure.
    assert ctx.provider.counts["read_page"] == 3 and _run(paused and ctx).calls_used == 3
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert sorted(states) == ["failed", "succeeded", "succeeded"]

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    settled = _read_stage(ctx)
    assert settled.status == "completed_with_exceptions"
    assert ctx.provider.counts["read_page"] == 5  # S002 page 1 again (fault spent), then page 2
    _assert_calls_match(ctx)
    views = item_views(ctx.db, ctx.run_id)
    assert {v.codes for v in views.values()} == {("evidence_review_required",)}


def test_a_timeout_is_an_unknown_outcome_that_only_a_teacher_can_reconcile(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("read_page", TimeoutError("timed out"), on_call=3))
    paused = _read_stage(ctx)
    assert paused.status == "paused"
    assert "outcome is unknown" in (paused.error or "")
    assert "unknown_outcome" in ctx.db.scalars(select(ScriptPageTranscript.state)).all()

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert not resumed and "must be reconciled" in (refusal or "")
    # Never re-dispatched behind the teacher's back.
    assert ctx.provider.counts["read_page"] == 3

    assert len(reconcile_unknown_pages(ctx.db, ctx.run_id, ctx.seeded.teacher)) == 1
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    assert _read_stage(ctx).status == "completed_with_exceptions"
    assert ctx.provider.counts["read_page"] == 5
    _assert_calls_match(ctx)


def test_a_failed_grading_call_quarantines_exactly_that_item(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=2))
    _read_stage(ctx)
    paused = _gate_and_grade(ctx)
    assert paused.status == "paused"
    assert "synthetic grader 500" in (paused.error or "")

    views = item_views(ctx.db, ctx.run_id)
    # Grading is question-major: call 2 is the second student's Q1.
    assert views[("S002", "Q1")].status == "uncertain"
    assert views[("S001", "Q1")].status == "graded"

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    assert _read_stage(ctx).status == "review_ready"
    views = item_views(ctx.db, ctx.run_id)
    # The uncertain item is NOT retried automatically: a teacher must ask for it.
    assert views[("S002", "Q1")].status == "uncertain"
    assert sum(v.status == "graded" for v in views.values()) == 3

    retried = resume_all_items(
        ctx.run_id,
        ctx.seeded.teacher,
        settings=ctx.settings,
        codes={"provider_contract_failure"},
        only_stage=None,
    )
    assert len(retried.resumed) == 1 and not retried.refused
    assert _read_stage(ctx).status == "review_ready"
    assert item_views(ctx.db, ctx.run_id)[("S002", "Q1")].status == "graded"
    assert ctx.provider.counts["grade"] == 5


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP: a grading call that raises is never charged to the run's call budget: "
        "_consume_calls (bulk_evaluation_service.py:2258) runs only after run_queued_job returns, "
        "and _sync_failed_page_read_calls (L1544) only covers the reading stage. calls_used "
        "therefore under-counts dispatched grading calls, so the 'hard' authorized_call_limit "
        "can be exceeded by the number of failed grading calls."
    ),
)
def test_a_failed_grading_call_is_charged_to_the_call_budget(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=2))
    _read_stage(ctx)
    paused = _gate_and_grade(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed grading call must pause the run: {paused}")
    # call 1 succeeded, call 2 raised, then the pause
    precondition(ctx.provider.counts["grade"] == 2, f"grade calls: {ctx.provider.counts}")
    assert _run(ctx).calls_used == ctx.provider.total_calls


def test_a_killed_worker_leaves_the_page_dispatched_and_the_items_running(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("read_page", ProcessKilled("simulated kill -9"), on_call=3))
    with pytest.raises(ProcessKilled):
        _read_stage(ctx)  # BaseException: no production handler may swallow it

    run = _run(ctx)
    assert run.status == "reading"  # nobody got to pause it
    views = item_views(ctx.db, ctx.run_id)
    assert {v.status for k, v in views.items() if k[0] == "S002"} == {"running"}
    assert {v.codes for k, v in views.items() if k[0] == "S001"} == {("evidence_review_required",)}
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert sorted(states) == ["dispatched", "succeeded", "succeeded"]
    assert ctx.provider.calls[-1].outcome == "raised:ProcessKilled"


def test_a_killed_worker_can_be_recovered_by_a_teacher(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("read_page", ProcessKilled("simulated kill -9"), on_call=3))
    with pytest.raises(ProcessKilled):
        _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    age_run_heartbeat(ctx.db, ctx.run_id)
    # the dead worker's claim is hours old
    precondition(age_page_reservations(ctx.db, ctx.run_id) == 1, "exactly one dispatched page")

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    refusals: dict[int, str] = {}
    if not resumed:
        reconcile_unknown_pages(
            ctx.db,
            ctx.run_id,
            ctx.seeded.teacher,
            states=("dispatched", "unknown_outcome"),
            refusals=refusals,
        )
        resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, f"no way back from a killed worker: {refusal}; reconcile refused: {refusals}"
    assert _read_stage(ctx).status == "completed_with_exceptions"


def test_a_run_authorised_for_exactly_the_calls_it_needs_still_finishes(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, budget_slack=0)
    precondition(
        _run(ctx).authorized_call_limit == ctx.corpus.call_budget() == 8,
        "the authorization must be exactly the calls the run needs",
    )
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    # all the work was done...
    precondition(ctx.provider.counts["grade"] == 4, f"grade calls: {ctx.provider.counts}")
    assert final.status == "review_ready", final  # ...so the run must say so, not 'paused'


def test_a_failed_whole_transcript_assignment_call_can_be_retried(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        continuation=True,
        spill=True,
    )
    ctx.provider.inject(Fault("map", RuntimeError("synthetic map 500"), on_call=1))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed assignment must pause the run: {paused}")
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"run-level resume was refused: {refusal}")
    # RC-38 (fixed 2026-10-13): Resume revives the script's read-stage items; its pages are
    # reused and only the failed assignment call runs again.
    _read_stage(ctx)
    views = item_views(ctx.db, ctx.run_id)
    assert not any("provider_contract_failure" in view.codes for view in views.values()), views
    # Both scripts need an assignment call: S001's failed one, its retry, and S002's.
    assert ctx.provider.counts["map"] == 3
    assert ctx.provider.counts["read_page"] == 4  # every page read exactly once


def test_retrying_one_scripts_reading_never_reopens_a_stopped_run(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only the run-level Resume reopens a stopped run; an item click on it is refused."""

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        continuation=True,
        spill=True,
    )
    ctx.provider.inject(Fault("map", RuntimeError("synthetic map 500"), on_call=1))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed assignment must pause the run: {paused}")
    db = ctx.db
    db.expire_all()
    run = db.get(BulkEvaluationRun, ctx.run_id)
    assert run is not None
    run.status = "stopped"
    run.stop_requested = True
    db.commit()
    uncertain = [
        view for view in item_views(db, ctx.run_id).values() if view.status == "uncertain"
    ]
    precondition(uncertain, "the failed assignment must leave an uncertain read item")
    retried = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage="read"
    )
    assert not retried.resumed and retried.refused, retried
    assert all("stopped" in reason for reason in retried.refused.values()), retried.refused
    db.expire_all()
    assert db.get(BulkEvaluationRun, ctx.run_id).status == "stopped"


def test_blocks_returned_out_of_reading_order_still_reach_the_right_question(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seeded = seed_assessment(db_session, questions=2)
    corpus = build_zip(
        tmp_path / "order.zip", students=2, pages=2, questions=2, continuation=True, spill=True
    )
    provider = FakeBulkBrainProvider(corpus)
    provider.emit_order = "reversed"
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(db_session, seeded=seeded, corpus=corpus, provider=provider, settings=bulk_env)
    ctx = Ctx(db_session, bulk_env, seeded, corpus, provider, run.id)
    _read_stage(ctx)
    final = _gate_and_grade(ctx)

    # The scenario only means something if the fake really answered bottom-to-top...
    def bbox_order(call: CallRecord) -> tuple[str, ...]:
        if call.page_no is None:  # a setup check, so not an assert (see the module docstring)
            pytest.fail(f"PRECONDITION BROKEN: read #{call.index} names no registered page")
        return tuple(b.token for b in corpus.page_spec(call.students[0], call.page_no).blocks)

    out_of_order = [
        call
        for call in provider.calls_of("read_page")
        if len(call.tokens) > 1 and call.tokens != bbox_order(call)
    ]
    precondition(out_of_order, "no page read came back out of bbox order: emit_order had no effect")
    # ...and the pipeline went all the way to grading, so the evidence exists to inspect. (The
    # status itself is not part of the claim: mis-attributed evidence may well be flagged.)
    precondition(
        final.stage == "review" and provider.counts["grade"] > 0 and not final.harness_errors,
        f"the run did not reach grading and review: {final}",
    )
    assert_no_cross_student_evidence(db_session, run.id, corpus=corpus, provider=provider)


def test_every_whole_transcript_call_numbers_blocks_in_saved_order_even_on_re_analysis(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The model must be shown the numbering that ``block_index`` resolves, on BOTH paths.

    Fresh read: the pages come straight from a provider that answers bottom-to-top. Re-analysis
    (``resume_item``'s transcript-assignment branch): the pages are reloaded from the saved
    transcript. Either way ``block.order`` in the prompt is ``block_index + 1``, i.e. bbox order.
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        continuation="unlabeled",
        spill=True,
        budget_slack=8,  # the repeated analysis costs one more call per script
        before_import=lambda provider: setattr(provider, "emit_order", "reversed"),
    )
    _read_stage(ctx)
    precondition(ctx.provider.counts["map"] == 2, f"one analysis per script: {ctx.provider.counts}")

    # Make each saved analysis look unfinished, which is what resume_item re-runs from the saved
    # pages (the provider is never asked to read a page again).
    ctx.db.expire_all()
    transcripts = ctx.db.scalars(select(ScriptTranscript)).all()
    precondition(len(transcripts) == 2, f"expected one transcript per script: {transcripts}")
    for transcript in transcripts:
        transcript.assignment_status = "failed"
        transcript.assignment_error = "synthetic: analysis to be repeated"
    ctx.db.commit()
    resumed = resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed.resumed and not resumed.refused, f"re-analysis refused: {resumed}")
    audited = ctx.db.scalars(
        select(AuditLog).where(
            AuditLog.event_type == "bulk_evaluation_transcript_assignment_resumed"
        )
    ).all()
    precondition(len(audited) == 2, f"the transcript-assignment branch did not run: {audited}")
    _read_stage(ctx)
    precondition(ctx.provider.counts["map"] == 4, f"analysis not repeated: {ctx.provider.counts}")
    precondition(
        ctx.provider.counts["read_page"] == 4, f"a page was re-read: {ctx.provider.counts}"
    )

    final = _gate_and_grade(ctx)
    precondition(
        final.stage == "review" and ctx.provider.counts["grade"] > 0 and not final.harness_errors,
        f"the run did not reach grading and review: {final}",
    )
    out_of_order = [
        call
        for call in ctx.provider.calls_of("read_page")
        if len(call.tokens) > 1
        and call.tokens
        != tuple(b.token for b in ctx.corpus.page_spec(call.students[0], call.page_no or 0).blocks)
    ]
    precondition(out_of_order, "no page read came back out of bbox order: emit_order had no effect")

    def saved_order(call: CallRecord) -> tuple[str, ...]:
        return tuple(
            block.token
            for page_no in (1, 2)
            for block in ctx.corpus.page_spec(call.students[0], page_no).blocks
        )

    map_calls = ctx.provider.calls_of("map")
    fresh, re_analysis = map_calls[:2], map_calls[2:]
    # Reloaded from the saved transcript, so this path was already consistent...
    assert [call.tokens for call in re_analysis] == [saved_order(call) for call in re_analysis]
    # ...while the fresh path used to hand the model the provider's own (reversed) order.
    assert [call.tokens for call in fresh] == [saved_order(call) for call in fresh]
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)
    assert_no_final_grades(ctx.db, ctx.run_id)


def test_byte_identical_pages_shared_by_two_students_stay_separate(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        shared_pages=((("S001", "S002"), 1),),
    )
    # The two students really do hand in the same bytes for page 1.
    entry = next(e for e in ctx.provider.registry.values() if len(e.students) == 2)
    assert entry.students == {"S001", "S002"}
    assert len(ctx.provider.registry) == 3  # shared p1 + two distinct p2

    _read_stage(ctx)
    # No cross-student reuse: each copy cost its own read, and each has its own transcript.
    assert ctx.provider.counts["read_page"] == 4
    transcripts = ctx.db.scalars(select(ScriptTranscript)).all()
    assert len(transcripts) == 2 and len({t.submission_id for t in transcripts}) == 2
    pages = ctx.db.scalars(select(ScriptPageTranscript)).all()
    shared_hash = {p.source_image_sha256 for p in pages if p.page_no == 1}
    assert len(shared_hash) == 1 and len({p.script_transcript_id for p in pages}) == 2
    assert len({p.submission_page_id for p in pages}) == 4

    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final
    views = item_views(ctx.db, ctx.run_id)
    assert len({v.suggestion_id for v in views.values()}) == 4  # four distinct drafts
    for (student, question), view in views.items():
        assert view.status == "graded", (student, question)
        suggestion = ctx.db.get(GradeSuggestion, view.suggestion_id)
        assert suggestion is not None
        assignment = ctx.db.get(AnswerEvidenceAssignment, suggestion.answer_evidence_assignment_id)
        assert assignment is not None
        submission = ctx.db.get(Submission, assignment.submission_id)
        assert submission is not None and submission.student_identifier == student
    # Q1 lives on the shared page: its evidence carries the shared owner token for BOTH.
    for student in ("S001", "S002"):
        assert ctx.corpus.expected_tokens(student, "Q1") == ["SYN150|S001+S002|Q1|p1|b1"]
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)
    assert_no_final_grades(ctx.db, ctx.run_id)
    _assert_calls_match(ctx)


def test_final_grades_exist_only_after_the_teacher_approves_and_the_helper_notices(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    assert_no_final_grades(ctx.db, ctx.run_id)

    db = SessionLocal()
    try:
        service = BulkEvaluationService(db, settings=ctx.settings, storage=harness_storage())
        run = service.get_run(ctx.run_id)
        snapshot = service.review_snapshot_hash(run)
        suggestion_ids = [i.grade_suggestion_id for i in run.items if i.status == "graded"]
        approved, already, _ = service.approve_clean(
            run,
            suggestion_ids=[i for i in suggestion_ids if i is not None],
            review_snapshot_sha256=snapshot,
            teacher_id=ctx.seeded.teacher.id,
        )
        assert (approved, already) == (4, 0)
        workbook = load_workbook(__import__("io").BytesIO(service.build_results_workbook(run)))
    finally:
        db.close()
    assert workbook.sheetnames == ["Approved Scores", "Student Totals", "Exceptions", "Run Summary"]
    assert ctx.db.scalar(select(func.count(FinalGrade.id))) == 4
    with pytest.raises(AssertionError, match="FinalGrade row exists"):
        assert_no_final_grades(ctx.db, ctx.run_id)
    assert _run(ctx).status == "completed"


# =========================================================================== page identity


def _swap_stored_pages(
    db: Session, assessment_id: int, first: tuple[str, int], second: tuple[str, int]
) -> None:
    """Simulate an intake defect: two submission pages exchange their stored images."""

    pages: dict[tuple[str, int], SubmissionPage] = {}
    for submission in db.scalars(
        select(Submission).where(Submission.assessment_id == assessment_id)
    ):
        for page in db.scalars(
            select(SubmissionPage).where(SubmissionPage.submission_id == submission.id)
        ):
            pages[(submission.student_identifier, page.page_no)] = page
    left, right = pages[first], pages[second]
    left.image_path, right.image_path = right.image_path, left.image_path
    db.commit()


SWAPS = (
    pytest.param((("S001", 1), ("S002", 1)), id="cross-student"),
    pytest.param((("S001", 1), ("S001", 2)), id="page-order"),
)


def _intake_only(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Ctx:
    return _start(db, settings, monkeypatch, tmp_path, students=2, register=False)


def test_pixel_owners_are_shared_by_identical_and_blank_pages(tmp_path: Path) -> None:
    corpus = build_zip(
        tmp_path / "owners.zip",
        students=3,
        pages=2,
        questions=2,
        shared_pages=((("S001", "S002"), 1),),
        blank_pages=(("S001", 2), ("S003", 2)),
    )
    groups = sorted(sorted(owners) for owners in corpus.pixel_owners().values() if len(owners) > 1)
    assert groups == [[("S001", 1), ("S002", 1)], [("S001", 2), ("S003", 2)]]
    # Every corpus page has exactly one digest.
    assert sum(len(owners) for owners in corpus.pixel_owners().values()) == corpus.total_pages


@pytest.mark.parametrize("swap", SWAPS)
def test_a_swapped_stored_page_fails_loudly_at_registration(
    swap: tuple[tuple[str, int], tuple[str, int]],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL: the registry follows the PIXELS, so a mis-assigned image is refused.

    Before this check the registry took the expected page from the database's claim, so a
    swapped ``image_path`` produced a fully green run (all drafts graded at 0.95).
    """

    ctx = _intake_only(db_session, bulk_env, monkeypatch, tmp_path)
    _swap_stored_pages(ctx.db, ctx.seeded.assessment.id, *swap)
    with pytest.raises(HarnessError, match=r"intake mis-assigned a page.*pixels say"):
        register_stored_pages(ctx.db, ctx.provider, ctx.corpus, ctx.seeded.assessment.id)


@pytest.mark.parametrize("swap", SWAPS)
def test_a_swapped_page_is_still_caught_downstream_by_a_lenient_registry(
    swap: tuple[tuple[str, int], tuple[str, int]],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Second line of defence: with ``strict_identity=False`` the fake answers from the
    pixels, the pipeline runs, and the evidence detector fails on the mis-assigned text."""

    ctx = _intake_only(db_session, bulk_env, monkeypatch, tmp_path)
    _swap_stored_pages(ctx.db, ctx.seeded.assessment.id, *swap)
    registered = register_stored_pages(
        ctx.db, ctx.provider, ctx.corpus, ctx.seeded.assessment.id, strict_identity=False
    )
    assert registered == ctx.corpus.total_pages
    assert len(ctx.provider.identity_mismatches) == 2
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final  # the pipeline itself notices nothing
    with pytest.raises(AssertionError, match="cross-student/question evidence leakage"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)


# =========================================================================== ownership / links

PAIR: dict[str, Any] = {
    "students": 2,
    "pages": 2,
    "questions": 2,
    "shared_pages": ((("S001", "S002"), 1),),
}


def _full_run(ctx: Ctx) -> None:
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)


def _current_assignment(db: Session, student: str, label: str) -> AnswerEvidenceAssignment:
    row = db.scalar(
        select(AnswerEvidenceAssignment)
        .join(Submission, Submission.id == AnswerEvidenceAssignment.submission_id)
        .join(Question, Question.id == AnswerEvidenceAssignment.question_id)
        .where(
            Submission.student_identifier == student,
            Question.question_no == label,
            AnswerEvidenceAssignment.is_current.is_(True),
        )
    )
    assert row is not None
    return row


def _other_students_copy_of(db: Session, block_id: int, other: str) -> int:
    """The block of ``other``'s transcript at the same page and index (byte-identical text)."""

    original = db.get(ScriptTranscriptBlock, block_id)
    assert original is not None
    page = db.get(ScriptPageTranscript, original.script_page_transcript_id)
    assert page is not None
    twin = db.scalar(
        select(ScriptTranscriptBlock)
        .join(
            ScriptPageTranscript,
            ScriptPageTranscript.id == ScriptTranscriptBlock.script_page_transcript_id,
        )
        .join(ScriptTranscript, ScriptTranscript.id == ScriptPageTranscript.script_transcript_id)
        .join(Submission, Submission.id == ScriptTranscript.submission_id)
        .where(
            Submission.student_identifier == other,
            ScriptPageTranscript.page_no == page.page_no,
            ScriptTranscriptBlock.block_index == original.block_index,
        )
    )
    assert twin is not None and twin.id != original.id
    assert twin.effective_text == original.effective_text  # indistinguishable by text
    return twin.id


def test_a_span_repointed_at_the_other_students_identical_block_is_flagged(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL: tokens cannot tell two byte-identical pages apart; ownership can."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, **PAIR)
    _full_run(ctx)  # the control: a clean shared-page run raises nothing
    span = _current_assignment(ctx.db, "S001", "Q1").spans[0]
    twin = _other_students_copy_of(ctx.db, span.script_transcript_block_id, "S002")
    ctx.db.execute(
        update(AnswerEvidenceSpan)
        .where(AnswerEvidenceSpan.id == span.id)
        .values(script_transcript_block_id=twin)
    )
    ctx.db.commit()
    with pytest.raises(AssertionError) as caught:
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)
    message = str(caught.value)
    assert re.search(r"belongs to transcript \d+ \(submission \d+\), but assignment", message)
    assert "foreign student token" not in message  # only the structural check can see it
    # The suggestion that was graded on that assignment trips the same check.
    assert "suggestion" in message and "bound span" in message


def test_a_page_transcript_reading_another_submissions_page_is_flagged(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, **PAIR)
    _full_run(ctx)
    span = _current_assignment(ctx.db, "S001", "Q1").spans[0]
    block = ctx.db.get(ScriptTranscriptBlock, span.script_transcript_block_id)
    assert block is not None
    other_page = ctx.db.scalar(
        select(SubmissionPage)
        .join(Submission, Submission.id == SubmissionPage.submission_id)
        .where(Submission.student_identifier == "S002", SubmissionPage.page_no == 1)
    )
    assert other_page is not None
    ctx.db.execute(
        update(ScriptPageTranscript)
        .where(ScriptPageTranscript.id == block.script_page_transcript_id)
        .values(submission_page_id=other_page.id)
    )
    ctx.db.commit()
    with pytest.raises(AssertionError, match=r"reads a submission page of submission"):
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)


def test_items_pointing_at_each_others_drafts_are_flagged(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL: the workbook and approve_clean key on item.grade_suggestion_id."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, **PAIR)
    _full_run(ctx)
    views = item_views(ctx.db, ctx.run_id)
    first, second = views[("S001", "Q1")], views[("S002", "Q1")]
    assert first.suggestion_id != second.suggestion_id
    ctx.db.execute(
        update(BulkEvaluationItem)
        .where(BulkEvaluationItem.id == first.item_id)
        .values(grade_suggestion_id=second.suggestion_id)
    )
    ctx.db.execute(
        update(BulkEvaluationItem)
        .where(BulkEvaluationItem.id == second.item_id)
        .values(grade_suggestion_id=first.suggestion_id)
    )
    ctx.db.commit()
    with pytest.raises(AssertionError) as caught:
        assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus)
    assert str(caught.value).count("belongs to region") == 2


# =========================================================================== shared pages


def test_common_students_intersects_instead_of_comparing_raw_owner_fields() -> None:
    tokens = parse_tokens("SYN150|S001+S002|Q1|p1|b1 SYN150|S001|Q1|p2|b1")
    assert common_students(tokens) == {"S001"}
    assert common_students(parse_tokens("SYN150|S001+S002|Q1|p1|b1")) == {"S001", "S002"}
    assert common_students(parse_tokens("SYN150|S001|Q1|p1|b1 SYN150|S002|Q1|p2|b1")) == set()
    assert common_students([]) == set()


def test_a_shared_page_inside_a_multi_page_answer_grades_clean(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One question over two pages, page 1 byte-identical for S001 and S002.

    Each draft's evidence is ``S001+S002`` (page 1) plus the student's own page 2; that is ONE
    student's answer. Splitting on the raw owner field called it two students ('mixed_students',
    0.40) and made the leak detector raise on legitimate evidence.
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=1,
        shared_pages=((("S001", "S002"), 1),),
    )
    assert ctx.corpus.expected_tokens("S001", "Q1") == [
        "SYN150|S001+S002|Q1|p1|b1",
        "SYN150|S001|Q1|p2|b1",
    ]
    _full_run(ctx)
    views = item_views(ctx.db, ctx.run_id)
    assert {(v.status, float(v.confidence or 0)) for v in views.values()} == {("graded", 0.95)}
    grading = ctx.provider.calls_of("grade")
    assert sorted(call.students for call in grading) == [("S001",), ("S002",)]
    assert {call.verdict for call in grading} == {"ok"}
    _assert_calls_match(ctx)


# =========================================================================== environment / hygiene


def test_get_settings_and_make_settings_agree_inside_bulk_env(bulk_env: Settings) -> None:
    """One Settings truth: GradingService / the worker path read get_settings(), the harness
    hands make_settings() to the services, and both say the same."""

    live = get_settings()
    for name in (
        "bulk_supervised_enabled",
        "local_script_preparation_enabled",
        "local_single_answer_grading_enabled",
    ):
        assert getattr(live, name) is True and getattr(bulk_env, name) is True, name
    assert live.cohort_model_grading_enabled is False
    assert bulk_env.cohort_model_grading_enabled is False
    assert live.local_ai_phase_switch_enabled is False  # would drive real model servers
    assert_settings_agree(bulk_env, live)  # raises HarnessError on any disagreement
    assert harness_storage().root == Path(bulk_env.local_storage_root).resolve()


def test_assert_settings_agree_rejects_a_diverging_or_dangerous_settings(tmp_path: Path) -> None:
    root = tmp_path / "s"
    good = make_settings(root)
    assert_settings_agree(good, make_settings(root))
    with pytest.raises(HarnessError, match="bulk_supervised_enabled"):
        assert_settings_agree(good, make_settings(root, BULK_SUPERVISED_ENABLED=False))
    with pytest.raises(HarnessError, match="storage roots"):
        assert_settings_agree(good, make_settings(tmp_path / "elsewhere"))
    dangerous = make_settings(root, COHORT_MODEL_GRADING_ENABLED=True)
    with pytest.raises(HarnessError, match="COHORT_MODEL_GRADING_ENABLED must stay false"):
        assert_settings_agree(dangerous, dangerous)
    switching = make_settings(root, LOCAL_AI_PHASE_SWITCH_ENABLED=True)
    with pytest.raises(HarnessError, match="LOCAL_AI_PHASE_SWITCH_ENABLED must stay false"):
        assert_settings_agree(switching, switching)


def test_bulk_environment_restores_the_environment_and_the_settings_cache(
    tmp_path: Path,
) -> None:
    """The env goes back BEFORE the cache is cleared: no cached bulk Settings leaks out."""

    names = ["LOCAL_STORAGE_ROOT", "UPLOADS_DIR", "ARTIFACTS_DIR", *BULK_ENV_FLAGS]
    before = {name: os.environ.get(name) for name in names}
    get_settings.cache_clear()
    flag_before = get_settings().bulk_supervised_enabled
    root_before = get_settings().local_storage_root
    with bulk_environment(tmp_path / "scoped") as settings:
        assert get_settings().bulk_supervised_enabled is True
        assert Path(get_settings().local_storage_root) == tmp_path / "scoped"
        assert harness_storage(settings).root == (tmp_path / "scoped").resolve()
    assert {name: os.environ.get(name) for name in names} == before
    assert get_settings().bulk_supervised_enabled is flag_before
    assert get_settings().local_storage_root == root_before
    with pytest.raises(HarnessError, match="bulk_env fixture is not active"):
        harness_storage()


def test_storage_helpers_refuse_settings_that_are_not_the_active_environment(
    bulk_env: Settings, tmp_path: Path
) -> None:
    """Never fall back to a root the process environment (possibly the real data dir) names."""

    other = make_settings(tmp_path / "other-root")
    with pytest.raises(HarnessError, match="differ from the active bulk_env"):
        harness_storage(other)
    with pytest.raises(HarnessError, match="differ from the active bulk_env"):
        drain(1, settings=other)
    with pytest.raises(HarnessError, match="differ from the active bulk_env"):
        try_resume_run(1, object(), settings=other)  # type: ignore[arg-type]
    with pytest.raises(HarnessError, match="differ from the active bulk_env"):
        resume_all_items(1, object(), settings=other)  # type: ignore[arg-type]
    assert not (tmp_path / "other-root").exists()  # nothing was created there either


def _refused_everywhere(storage: LocalStorage, settings: Settings, match: str) -> None:
    """Every helper that takes an explicit ``storage=`` refuses it, before touching anything.

    The guard is each helper's first statement, so ``object()`` placeholders prove the
    arguments were never used: nothing was read, queried or created.
    """

    with pytest.raises(HarnessError, match=match):
        require_active_storage(storage, settings)
    with pytest.raises(HarnessError, match=match):
        import_zip(
            object(),  # type: ignore[arg-type]
            seeded=object(),  # type: ignore[arg-type]
            corpus=object(),  # type: ignore[arg-type]
            provider=object(),  # type: ignore[arg-type]
            settings=settings,
            storage=storage,
        )
    with pytest.raises(HarnessError, match=match):
        register_stored_pages(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            1,
            storage,
            settings=settings,
        )


def test_an_explicit_storage_is_refused_when_no_bulk_env_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit ``storage=`` used to skip the active-env check altogether."""

    settings = make_settings(tmp_path / "stray")
    harness_made = HarnessStorage(settings)
    try:
        with monkeypatch.context() as env:
            # A literal ``LocalStorage()`` reads get_settings(): point that at tmp_path, so the
            # test itself can never touch (or even mkdir) the process environment's real root.
            env.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "bare"))
            env.setenv("UPLOADS_DIR", str(tmp_path / "bare" / "uploads"))
            env.setenv("ARTIFACTS_DIR", str(tmp_path / "bare" / "artifacts"))
            get_settings.cache_clear()
            bare = LocalStorage()
    finally:
        get_settings.cache_clear()
    for storage in (bare, harness_made):
        _refused_everywhere(storage, settings, "bulk_env fixture is not active")


def test_an_explicit_storage_must_match_the_active_environment_and_the_passed_settings(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    accepted = HarnessStorage(bulk_env)
    assert require_active_storage(accepted) is accepted
    assert require_active_storage(accepted, bulk_env) is accepted
    bare = LocalStorage()  # reads get_settings(), which bulk_env made agree: same roots
    assert require_active_storage(bare, bulk_env) is bare

    # An explicit, matching storage works end to end through the real import.
    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "explicit.zip", students=1, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(
        db_session,
        seeded=seeded,
        corpus=corpus,
        provider=provider,
        settings=bulk_env,
        storage=accepted,
    )
    assert run.total_submissions == 1 and len(provider.registry) == 1

    # Roots elsewhere (all three, or only ONE of them) are refused: the active env wins.
    elsewhere = make_settings(tmp_path / "elsewhere")
    stray = HarnessStorage(elsewhere)
    one_root = HarnessStorage(bulk_env)
    one_root.uploads_dir = (tmp_path / "uploads-elsewhere").resolve()
    for bad in (stray, one_root):
        _refused_everywhere(bad, bulk_env, "differ from the active bulk_env roots")
    # Storage that matches the environment but not the settings the caller PASSED is refused too.
    _refused_everywhere(accepted, elsewhere, "differ from the passed settings")
    assert not (tmp_path / "uploads-elsewhere").exists()


def test_precondition_is_a_real_failure_that_xfail_raises_assertion_error_cannot_absorb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the REAL xfail machinery: a bare ``assert`` in a GAP test's setup is silently
    XFAILed (the wrong-reason pass), ``precondition`` is reported as FAILED."""

    assert not issubclass(pytest.fail.Exception, AssertionError)
    precondition(True, "holds")
    with pytest.raises(pytest.fail.Exception, match="the setup never happened"):
        precondition(False, "the setup never happened")

    module = tmp_path / "test_inner_gap.py"
    module.write_text(
        "import pytest\n"
        "from tests.bulk150_harness import precondition\n"
        "GAP = pytest.mark.xfail(strict=True, raises=AssertionError, reason='GAP')\n"
        "@GAP\n"
        "def test_setup_written_as_a_bare_assert():\n"
        "    assert False, 'broken setup'\n"
        "@GAP\n"
        "def test_setup_written_as_a_precondition():\n"
        "    precondition(False, 'broken setup')\n"
        "@GAP\n"
        "def test_only_the_desired_behaviour_fails():\n"
        "    precondition(True, 'setup is fine')\n"
        "    assert False, 'the desired behaviour does not hold'\n",
        encoding="utf-8",
    )
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    seen: dict[str, tuple[str, bool]] = {}

    class Recorder:
        def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
            if report.when == "call":
                seen[report.nodeid.split("::")[-1]] = (
                    report.outcome,
                    hasattr(report, "wasxfail"),
                )

    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    pytest.main(
        [
            str(module),
            "-q",
            "-c",
            str(ini),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            "--capture=sys",
        ],
        plugins=[Recorder()],
    )
    assert seen == {
        # (outcome, was-xfail): the first is the hole this helper closes
        "test_setup_written_as_a_bare_assert": ("skipped", True),  # XFAIL, the wrong reason
        "test_setup_written_as_a_precondition": ("failed", False),  # FAILED, loudly
        "test_only_the_desired_behaviour_fails": ("skipped", True),  # XFAIL, the right reason
    }


def test_precondition_faults_fired_flags_a_fault_that_never_fired(tmp_path: Path) -> None:
    corpus = build_zip(tmp_path / "faults.zip", students=1, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    precondition_faults_fired(provider)  # no Fault, nothing to flag
    fault = provider.inject(Fault("grade", RuntimeError("never"), student="S999"))
    with pytest.raises(pytest.fail.Exception, match="never fired"):
        precondition_faults_fired(provider)
    fault.fired = 1
    precondition_faults_fired(provider)


def test_disposable_database_guard_mirrors_conftest() -> None:
    assert_disposable_database("teacher_assistant_test", {})
    assert_disposable_database("bulk150_hfix_test", {"CI": ""})
    for name in ("teacher_assistant", "teacher_assistant_prod", "test_teacher", "", None):
        with pytest.raises(HarnessError, match="does not end in '_test'"):
            assert_disposable_database(name, {})
    # CI=true IS an override, exactly as in tests/conftest.py: GitHub Actions runs the suite
    # against a throwaway service database named ``teacher_assistant``. Anything else is refused.
    assert_disposable_database("teacher_assistant", {"CI": "true"})
    with pytest.raises(HarnessError):
        assert_disposable_database("teacher_assistant", {"CI": "false"})
    assert_disposable_database("teacher_assistant", {"TA_ALLOW_DESTRUCTIVE_TEST_DATABASE": "true"})
    # The database this session actually runs against satisfies the guard.
    assert_disposable_database(engine.url.database)


def test_cleanup_models_cover_every_table_children_first() -> None:
    names = [model.__tablename__ for model in CLEANUP_MODELS]
    assert len(names) == len(set(names))
    tables = {table.name: table for table in Base.metadata.sorted_tables}
    assert set(names) == set(tables) - {"alembic_version"}, "a table is missing from CLEANUP_MODELS"
    position = {name: index for index, name in enumerate(names)}
    for name in names:
        for foreign_key in tables[name].foreign_keys:
            parent = foreign_key.column.table.name
            if parent != name:
                assert position[name] < position[parent], f"{name} must be deleted before {parent}"


def test_drain_unit_budget_scales_with_the_run_and_stays_bounded() -> None:
    assert drain_unit_budget(BulkEvaluationRun(total_items=2250, total_submissions=150)) == 4660
    assert drain_unit_budget(BulkEvaluationRun(total_items=6, total_submissions=3)) == 25
    # A fixed 2000 would have refused a 150-student, 15-question run mid-way.
    assert drain_unit_budget(BulkEvaluationRun(total_items=2250, total_submissions=150)) > 2000


def test_drain_refuses_to_loop_forever(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    with pytest.raises(HarnessError, match="did not settle within 1 units"):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider, max_units=1)
    assert _read_stage(ctx).settled  # the derived default budget is ample


def test_an_explicit_zero_call_authorization_is_not_replaced_by_the_default(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``maximum_provider_calls or default`` silently turned 0 into the exact budget."""

    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "zero.zip", students=1, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    with pytest.raises(Exception, match=r"(?i)authoriz|provider.call|limit") as caught:
        import_zip(
            db_session,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=bulk_env,
            maximum_provider_calls=0,
        )
    assert not isinstance(caught.value, HarnessError)  # production refused it, not the harness
    db_session.rollback()
    assert db_session.scalar(select(func.count(BulkEvaluationRun.id))) == 0


def test_strict_harness_separates_a_harness_mistake_from_a_product_failure(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``run_next`` swallows every Exception into 'paused'; ``strict_harness`` un-swallows ours."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, register=False)
    with pytest.raises(HarnessError, match="harness errors.*no expected page registered"):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider, strict_harness=True)
    ctx2 = _start(db_session, bulk_env, monkeypatch, tmp_path / "again", students=1, register=False)
    paused = drain(ctx2.run_id, settings=ctx2.settings, provider=ctx2.provider)
    assert paused.status == "paused" and len(paused.harness_errors) == 1


# =========================================================================== failure injection


def test_fault_arguments_are_validated_and_legacy_predicates_still_work() -> None:
    with pytest.raises(HarnessError, match="needs an exc, a transform or a callback"):
        Fault("read_page")
    with pytest.raises(HarnessError, match="either an exception or a transform"):
        Fault("read_page", RuntimeError("x"), transform=drop_block())
    with pytest.raises(HarnessError, match=r"Fault\.when must be"):
        Fault("read_page", RuntimeError("x"), when="during")  # type: ignore[arg-type]
    with pytest.raises(HarnessError, match="verify Fault has no output"):
        Fault("verify", RuntimeError("x"), when="after")
    with pytest.raises(HarnessError, match="verify Fault has no output"):
        Fault("verify", transform=drop_block())
    legacy = Fault("read_page", RuntimeError("x"), when=lambda record: record.index == 2)
    assert legacy.timing == "before" and legacy.predicate is not None
    explicit = Fault("grade", RuntimeError("x"), when="after", predicate=lambda record: True)
    assert explicit.timing == "after" and explicit.predicate is not None
    assert Fault("read_page", RuntimeError("x")).timing == "before"


def test_a_fault_that_matches_no_call_is_reported_instead_of_staying_silent(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A mis-targeted Fault (a student that does not exist) used to let the run finish green."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    fault = ctx.provider.inject(Fault("grade", RuntimeError("never"), student="S999"))
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    assert fault.fired == 0
    with pytest.raises(HarnessError, match="never fired"):
        ctx.provider.assert_faults_fired()
    with pytest.raises(HarnessError, match="never fired"):
        fault.assert_fired()


def test_a_failing_preflight_verify_refuses_the_import_and_bills_nothing(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``verify`` call #1 is the ``create_from_zip`` preflight."""

    faults: list[Fault] = []
    providers: list[FakeBulkBrainProvider] = []

    def arm(provider: FakeBulkBrainProvider) -> None:
        providers.append(provider)
        faults.append(
            provider.inject(Fault("verify", RuntimeError("model server down"), on_call=1))
        )

    with pytest.raises(BulkEvaluationError, match="unavailable or mismatched"):
        _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, before_import=arm)
    provider = providers[0]
    assert faults[0].fired == 1 and len(provider.verify_calls) == 1
    # A probe is not a billed call: the ledgers did not move.
    assert provider.total_calls == 0 and provider.counts == {"read_page": 0, "map": 0, "grade": 0}
    db_session.rollback()
    assert db_session.scalar(select(func.count(BulkEvaluationRun.id))) == 0


def test_a_failing_verify_before_a_script_read_pauses_before_any_page_row_exists(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``verify`` fires inside ``hold_brain_execution``, BEFORE ``reserve_page`` commits a row.

    A read ``Fault`` can only fire after the page is reserved, so it can never express "the model
    server was down when this script started". Verify call #1 is the preflight, #2 is S001's
    read and #3 is S002's.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    assert len(ctx.provider.verify_calls) == 1  # the preflight
    fault = ctx.provider.inject(Fault("verify", RuntimeError("model server down"), on_call=3))
    paused = _read_stage(ctx)
    assert (paused.status, fault.fired) == ("paused", 1)
    assert "model server down" in (paused.error or "")
    # S001 was read completely; S002 never reached reserve_page: no row, nothing billed.
    assert ctx.provider.counts == {"read_page": 2, "map": 0, "grade": 0}
    assert _run(ctx).calls_used == ctx.provider.total_calls == 2
    ctx.db.expire_all()
    owners = {
        row.student_identifier
        for row in ctx.db.scalars(
            select(Submission)
            .join(ScriptTranscript, ScriptTranscript.submission_id == Submission.id)
            .join(
                ScriptPageTranscript,
                ScriptPageTranscript.script_transcript_id == ScriptTranscript.id,
            )
        )
    }
    assert owners == {"S001"}
    assert {
        (v.status, v.codes) for k, v in item_views(ctx.db, ctx.run_id).items() if k[0] == "S002"
    } == {("uncertain", ("provider_contract_failure",))}


def test_a_model_unavailable_before_a_script_read_can_be_retried(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("verify", RuntimeError("model server down"), on_call=3))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the probe failure must pause the run: {paused}")
    # S001's two pages were read before the probe failed; S002's never were.
    precondition(ctx.provider.counts["read_page"] == 2, f"reads so far: {ctx.provider.counts}")
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"run-level resume was refused: {refusal}")
    _read_stage(ctx)
    # The model is back: S002's two pages must be read now (S001's two were read already).
    assert ctx.provider.counts["read_page"] == 4, ctx.provider.counts


def test_output_computed_and_then_lost_is_a_billed_unknown_outcome(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``when='after'``: the provider answered (and billed) but nobody ever saw the answer."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    fault = ctx.provider.inject(
        Fault("read_page", RuntimeError("connection reset by peer"), when="after", on_call=3)
    )
    paused = _read_stage(ctx)
    record = ctx.provider.calls[2]
    assert fault.fired == 1
    assert record.outcome == "raised_after:RuntimeError"
    assert record.tokens == ("SYN150|S002|Q1|p1|b1",)  # the output WAS produced
    assert paused.status == "paused" and "outcome is unknown" in (paused.error or "")
    assert "unknown_outcome" in ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert _run(ctx).calls_used == ctx.provider.total_calls == 3  # billed, never seen
    # Never silently re-dispatched: only a teacher's reconciliation reopens the page.
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert not resumed and "must be reconciled" in (refusal or "")
    assert ctx.provider.counts["read_page"] == 3
    assert len(reconcile_unknown_pages(ctx.db, ctx.run_id, ctx.seeded.teacher)) == 1
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    assert _read_stage(ctx).status == "completed_with_exceptions"
    assert ctx.provider.counts["read_page"] == 5  # S002 page 1 is paid for a second time
    _assert_calls_match(ctx)


@pytest.mark.parametrize("kind", ["read_page", "map"])
@pytest.mark.parametrize(
    "timeout",
    [
        pytest.param(TimeoutError("timed out"), id="timeout-with-message"),
        pytest.param(httpx.ReadTimeout("timed out"), id="httpx-with-message"),
        pytest.param(
            TimeoutError(),
            id="bare-timeout",
            marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason="GAP: see below"),
        ),
        pytest.param(
            httpx.ReadTimeout(""),
            id="httpx-empty-message",
            marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason="GAP: see below"),
        ),
    ],
)
def test_every_kind_of_timeout_is_an_unknown_outcome(
    kind: str,
    timeout: BaseException,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A timeout may have been billed and produced output nobody saw: never auto-retry it.

    GAP (the two xfail variants): ``BrainAdapter`` re-raises every provider ``Exception`` as
    ``RuntimeError(str(exc))`` (adapter.py:605), so ``classify_dispatch_failure``'s
    ``isinstance(exc, TimeoutError)`` branch can never be true on the adapter path and only a
    marker in the MESSAGE saves it. A timeout with an empty message (a bare ``TimeoutError()``,
    ``httpx.ReadTimeout('')``) is recorded as a KNOWN, retryable failure and may be paid twice.
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        continuation=True,
        spill=True,
    )
    ctx.provider.inject(Fault(kind, timeout, on_call=1 if kind == "map" else 3))  # type: ignore[arg-type]
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"a timeout must pause the run: {paused}")
    ctx.db.expire_all()
    if kind == "map":
        statuses = [t.assignment_status for t in ctx.db.scalars(select(ScriptTranscript)).all()]
        assert "unknown_outcome" in statuses, statuses
    else:
        states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
        assert "unknown_outcome" in states, sorted(states)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP (found with Fault.transform): one hallucinated question label ('Q99') makes the "
        "page-read abort the whole script with 'The brain provider returned an unknown finalized "
        "question' AFTER the page was stored as 'succeeded'. The run pauses, resume revives "
        "nothing (no known page failure), the script's remaining pages are never read and its "
        "items stay 'uncertain' for good; resume_item refuses 'Page-read provider work cannot "
        "be retried'. A bad label should become an unresolved block for the teacher instead."
    ),
)
def test_a_hallucinated_question_label_does_not_strand_the_script(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    fault = ctx.provider.inject(Fault("read_page", transform=hallucinate_label("Q99"), on_call=1))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(fault.fired == 1, f"the transform fired {fault.fired} times")
    precondition(paused.status == "paused", f"the bad label must pause the run: {paused}")
    precondition(ctx.provider.calls[0].verdict == "transformed", "the first read was not altered")
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"run-level resume was refused: {refusal}")
    _read_stage(ctx)
    # However a fix gets there (re-read the page, or keep the bad block as unresolved), every
    # page of both scripts ends read, nothing is stranded as an unretryable provider failure,
    # and S001's items wait at the teacher gate instead.
    ctx.db.expire_all()
    pages = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert pages == ["succeeded"] * 4, pages
    views = item_views(ctx.db, ctx.run_id)
    summary = {key: (v.status, v.codes) for key, v in views.items()}
    assert not any(
        v.status == "uncertain" or "provider_contract_failure" in v.codes for v in views.values()
    ), summary
    assert {v.status for k, v in views.items() if k[0] == "S001"} == {"exception"}, summary
    assert _run(ctx).status == "completed_with_exceptions", summary


def test_dropping_a_block_turns_an_answer_into_missing_answer_and_the_helper_sees_it(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL for ``assert_every_answered_question_graded``.

    The model silently omits S001's only page-1 block. Production demotes S001/Q1 to
    ``missing_answer`` and the leak detector stays green (there is no wrong evidence, only
    absent evidence); the completeness helper is what notices.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    fault = ctx.provider.inject(Fault("read_page", transform=drop_block(0), on_call=1))
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    assert fault.fired == 1
    assert ctx.provider.calls[0].tokens == () and "transformed" in ctx.provider.calls[0].verdict
    views = item_views(ctx.db, ctx.run_id)
    assert (views[("S001", "Q1")].status, views[("S001", "Q1")].codes) == (
        "exception",
        ("missing_answer",),
    )
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, provider=ctx.provider)  # blind to it
    with pytest.raises(AssertionError, match=r"S001/Q1: answered but exception/read"):
        assert_every_answered_question_graded(ctx.corpus, views)
    unexpected = assert_every_answered_question_graded(ctx.corpus, views, strict=False)
    assert list(unexpected) == [("S001", "Q1")]
    # A test that EXPECTS the exception lists it and passes; everything else is still checked.
    assert not assert_every_answered_question_graded(
        ctx.corpus, views, allowed_exceptions=[("S001", "Q1")]
    )


def test_the_completeness_helper_passes_a_clean_run_and_flags_a_draft_for_a_blank_answer(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=3,
        pages=3,
        questions=3,
        blank_pages=(("S003", 2),),
    )
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    views = item_views(ctx.db, ctx.run_id)
    # S003/Q2 sat on the blank page: unanswered, so its missing_answer exception is EXPECTED.
    assert assert_every_answered_question_graded(ctx.corpus, views) == {}
    blank = views[("S003", "Q2")]
    forged = {
        **views,
        ("S003", "Q2"): replace(blank, status="graded", suggestion_id=1, confidence=Decimal("0.9")),
    }
    with pytest.raises(AssertionError, match=r"S003/Q2: never answered but graded"):
        assert_every_answered_question_graded(ctx.corpus, forged)
    missing = {key: view for key, view in views.items() if key != ("S001", "Q1")}
    assert assert_every_answered_question_graded(ctx.corpus, missing, strict=False) == {
        ("S001", "Q1"): "no bulk item exists for it"
    }


def test_the_empty_non_blank_page_transform_is_wired(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``empty_non_blank_page``: the page comes back declared non-blank but without a block.

    Wiring only. OBSERVATION, deliberately not asserted because "correct" is debatable: the
    store keeps such a page as 'succeeded' (``record_page_success`` never checks that a
    non-blank page has blocks) and the script's Q1 then becomes a plain ``missing_answer``
    without a teacher prompt, so only a teacher looking at the empty page transcript notices.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    fault = ctx.provider.inject(Fault("read_page", transform=empty_non_blank_page(), on_call=1))
    _read_stage(ctx)
    assert fault.fired == 1 and ctx.provider.calls[0].tokens == ()
    assert "transformed" in ctx.provider.calls[0].verdict
    ctx.db.expire_all()
    pages = ctx.db.scalars(select(ScriptPageTranscript)).all()
    assert {page.state for page in pages} == {"succeeded"}
    assert not any(page.is_blank_page for page in pages)  # declared non-blank, yet blockless


def test_blocks_returned_in_reverse_order_are_recorded_as_such(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``reverse_blocks`` is the per-call spelling of ``provider.emit_order = 'reversed'``."""

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=2,
        questions=2,
        continuation=True,
        spill=True,
    )
    fault = ctx.provider.inject(Fault("read_page", transform=reverse_blocks(), times=None))
    _read_stage(ctx)
    assert fault.fired == ctx.provider.counts["read_page"] == 4
    for call in ctx.provider.calls_of("read_page"):
        student, page_no = call.students[0], call.page_no
        assert page_no is not None
        in_order = tuple(block.token for block in ctx.corpus.page_spec(student, page_no).blocks)
        assert call.tokens == tuple(reversed(in_order)), call
    assert any(len(call.tokens) == 2 for call in ctx.provider.calls_of("read_page"))


def test_recover_pressed_mid_call_does_not_dispatch_the_in_flight_page_again(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``Fault.callback`` + :class:`RecoverMidCall`: a second session presses Recover.

    The heartbeat is aged, so the real ``resume`` treats the run as abandoned. It is refused
    because the in-flight page is 'dispatched' and its outcome is unknown, and the call that
    was in flight still lands: nothing is read twice and the ledgers agree.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    recover = RecoverMidCall(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    fault = ctx.provider.inject(Fault("read_page", callback=recover, on_call=3))
    _read_stage(ctx)
    assert fault.fired == recover.invocations == 1
    assert recover.error is None, recover.error  # the in-flight unit held no row lock
    assert recover.resumed is False and "must be reconciled" in (recover.refusal or "")
    assert ctx.provider.counts["read_page"] == 4  # no page was dispatched a second time
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert states == ["succeeded"] * 4  # the in-flight result was kept
    _assert_calls_match(ctx)


def test_other_session_cannot_hang_the_test_on_a_row_the_unit_holds(
    db_session: Session,
    bulk_env: Settings,
) -> None:
    seeded = seed_assessment(db_session, questions=1)
    locked = select(Course).where(Course.id == seeded.course.id).with_for_update()
    db_session.execute(locked)  # this session now holds the row lock, like an in-flight unit
    started = time.perf_counter()
    with other_session(lock_timeout_ms=300) as other, pytest.raises(OperationalError, match="lock"):
        other.execute(locked).all()
    assert time.perf_counter() - started < 10  # it failed fast instead of waiting forever
    db_session.rollback()
    plain = SessionLocal()  # the setting must not leak onto the pooled connection
    try:
        assert plain.execute(text("SHOW lock_timeout")).scalar() in {"0", "0ms"}
    finally:
        plain.close()


_NO_LOCK_TIMEOUT = {"0", "0ms"}


def _warm_pool(connections: int = 4) -> None:
    """Leave several IDLE connections in the application engine's pool.

    A leak of ``lock_timeout`` onto a pooled connection needs at least two of them: the old
    ``other_session`` SET it on one and RESET it on whichever the pool handed out next.
    """

    held = [engine.connect() for _ in range(connections)]
    for connection in held:
        connection.close()


def _pooled_lock_timeouts() -> list[str]:
    """``SHOW lock_timeout`` on EVERY idle connection of the application engine's pool.

    The connections are all checked out at the same time. Checking them out one after the
    other could keep returning the same connection and prove nothing.
    """

    idle = engine.pool.checkedin()  # type: ignore[attr-defined]
    precondition(idle >= 2, f"the pool holds {idle} idle connection(s): nothing to inspect")
    held = [engine.connect() for _ in range(idle)]
    try:
        return [str(connection.execute(text("SHOW lock_timeout")).scalar()) for connection in held]
    finally:
        for connection in held:
            connection.close()


def test_other_session_keeps_its_timeout_across_commits_and_never_touches_the_pool(
    db_session: Session,
) -> None:
    """The property the old SET/RESET implementation lacked.

    A ``Session`` gives its connection back at ``commit()`` and takes another for the next
    statement, so a ``SET`` made on it does not survive the commit. The timeout now rides on
    the connection's startup options of a private ``NullPool`` engine: it is still in force
    after any number of commits, and the application engine's pool is never involved.
    """

    _warm_pool()
    pool_before = (engine.pool.checkedin(), engine.pool.checkedout())  # type: ignore[attr-defined]
    with other_session(lock_timeout_ms=1234) as other:
        assert other.execute(text("SHOW lock_timeout")).scalar() == "1234ms"
        other.commit()  # releases the connection; the next statement opens a different one
        assert other.execute(text("SHOW lock_timeout")).scalar() == "1234ms"
        other.execute(text("SELECT 1"))
        other.commit()
        assert other.execute(text("SHOW lock_timeout")).scalar() == "1234ms"
    assert (engine.pool.checkedin(), engine.pool.checkedout()) == pool_before  # type: ignore[attr-defined]
    assert set(_pooled_lock_timeouts()) <= _NO_LOCK_TIMEOUT
    assert db_session.execute(text("SHOW lock_timeout")).scalar() in _NO_LOCK_TIMEOUT


def test_recover_mid_call_leaves_lock_timeout_unset_on_every_pooled_connection(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REGRESSION: ``RecoverMidCall`` commits after aging the heartbeat.

    With the old ``other_session`` that commit moved the session to another pooled connection,
    the ``RESET`` hit the wrong one, and ``lock_timeout = 2s`` stayed on a pooled connection
    for whichever test drew it next (``test_other_session_cannot_hang...`` then failed in a
    full-suite run with ``2s in {0, 0ms}``). After the scenario EVERY idle pooled connection,
    and the test's own session, must report no timeout.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _warm_pool()
    recover = RecoverMidCall(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    ctx.provider.inject(Fault("read_page", callback=recover, on_call=3))
    _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(recover.invocations == 1, f"Recover ran {recover.invocations} times")
    # The aged heartbeat was committed (the step that used to strand the setting) and the
    # service call really ran in the other session: it must not have died on a lock timeout.
    precondition(recover.error is None, f"Recover failed in the other session: {recover.error!r}")
    precondition(recover.resumed is not None, "Recover neither resumed nor refused")
    assert set(_pooled_lock_timeouts()) <= _NO_LOCK_TIMEOUT
    assert db_session.execute(text("SHOW lock_timeout")).scalar() in _NO_LOCK_TIMEOUT


# =========================================================================== managed-local lease


def _watch_lease(
    db: Session,
    provider: FakeBulkBrainProvider,
    seen: list[tuple[str, str | None, str | None]],
) -> None:
    """Record which lease row is held at the moment of every verify / read / grade call."""

    def snapshot(record: CallRecord) -> None:
        row = read_lease(db)
        seen.append(
            (record.kind, row.holder_kind if row else None, row.model_phase if row else None)
        )

    for kind in ("verify", "read_page", "grade"):
        provider.inject(Fault(kind, callback=snapshot, times=None))  # type: ignore[arg-type]


def test_the_managed_local_variant_runs_the_real_lease_around_every_operation(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, str | None, str | None]] = []
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        managed_local_phase="Qwen38",
        before_import=lambda provider: _watch_lease(db_session, provider, seen),
    )
    assert ctx.provider.managed_local_phase == "Qwen38"
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    assert seen[0] == ("verify", "bulk_evaluation_preflight", "Qwen38")
    assert {(kind, holder) for kind, holder, _phase in seen} == {
        ("verify", "bulk_evaluation_preflight"),
        ("verify", "script_page_read"),
        ("read_page", "script_page_read"),
        ("verify", "grading"),
        ("grade", "grading"),
    }
    assert {phase for _kind, _holder, phase in seen} == {"Qwen38"}
    row = read_lease(ctx.db)
    assert row is not None and row.holder_id is None  # released after the last operation
    # Probes are not billed: 1 preflight + 2 script reads + 4 grades.
    assert len(ctx.provider.verify_calls) == 7
    assert ctx.provider.counts == {"read_page": 4, "map": 0, "grade": 4}
    _assert_calls_match(ctx)
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)


def test_the_default_fake_never_takes_a_lease(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, pages=1, questions=1)
    _read_stage(ctx)
    assert _gate_and_grade(ctx).status == "review_ready"
    assert read_lease(ctx.db) is None  # no row: the lease service was never entered
    assert len(ctx.provider.verify_calls) == 3  # ...but the probe still ran: preflight, read, grade


def test_process_killed_is_graceful_unwinding_so_the_lease_is_released(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """THE LIMIT of ``ProcessKilled``: ``LocalModelLeaseService.hold``'s ``finally`` still runs."""

    ctx = _start(
        db_session, bulk_env, monkeypatch, tmp_path, students=2, managed_local_phase="Qwen38"
    )
    ctx.provider.inject(Fault("read_page", ProcessKilled("simulated kill"), on_call=3))
    with pytest.raises(ProcessKilled):
        _read_stage(ctx)
    lease = read_lease(ctx.db)
    assert lease is not None and lease.holder_id is None  # released: NOT what kill -9 would leave
    assert "dispatched" in ctx.db.scalars(select(ScriptPageTranscript.state)).all()


def test_a_hard_kill_leaves_the_managed_lease_held_by_the_dead_worker(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session, bulk_env, monkeypatch, tmp_path, students=2, managed_local_phase="Qwen38"
    )
    skipped = hard_kill_skips_lease_release(monkeypatch)
    ctx.provider.inject(Fault("read_page", ProcessKilled("simulated kill -9"), on_call=3))
    with pytest.raises(ProcessKilled):
        _read_stage(ctx)
    lease = read_lease(ctx.db)
    assert lease is not None and lease.holder_kind == "script_page_read"
    assert skipped == [lease.holder_id]
    assert lease.expires_at is not None and lease.model_phase == "Qwen38"


def test_a_dead_holders_lease_blocks_grading_until_it_expires(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``leave_lease_held`` writes what a hard kill leaves; the slot stays closed until expiry."""

    ctx = _start(
        db_session, bulk_env, monkeypatch, tmp_path, students=2, managed_local_phase="Qwen38"
    )
    _read_stage(ctx)
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    assert not reviewed.refused, reviewed.refused
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    holder = leave_lease_held(
        ctx.db, holder_kind="grading", holder_id="grading_job:999999:dead-worker"
    )
    blocked = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert blocked.status == "paused" and "Local model is busy" in (blocked.error or "")
    assert ctx.provider.counts["grade"] == 0  # fail-closed: nothing was dispatched
    lease = read_lease(ctx.db)
    assert lease is not None and lease.holder_id == holder  # still the dead worker's

    expire_lease(ctx.db)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    resume_all_items(
        ctx.run_id,
        ctx.seeded.teacher,
        settings=ctx.settings,
        codes={"provider_contract_failure"},
        only_stage=None,
    )
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final
    assert ctx.provider.counts["grade"] == 4
    row = read_lease(ctx.db)
    assert row is not None and row.holder_id is None  # reclaimed, used, released


# =========================================================================== killed mid-grading


def _kill_mid_grading(ctx: Ctx) -> None:
    _read_stage(ctx)
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=2))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)


def test_a_worker_killed_mid_grading_leaves_the_item_and_its_job_running(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _kill_mid_grading(ctx)
    run = _run(ctx)
    assert (run.status, run.stage) == ("grading", "grading")  # nobody got to pause it
    views = item_views(ctx.db, ctx.run_id)
    assert views[("S001", "Q1")].status == "graded"
    assert views[("S002", "Q1")].status == "running"  # grading is question-major: call 2
    jobs = sorted(job.status for job in ctx.db.scalars(select(GradingJob)).all())
    assert jobs == ["running", "succeeded"]
    assert read_lease(ctx.db) is None


def test_a_worker_killed_mid_grading_can_be_regraded(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _kill_mid_grading(ctx)
    age_run_heartbeat(ctx.db, ctx.run_id)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"stale-run recovery was refused: {refusal}")
    retried = resume_all_items(
        ctx.run_id,
        ctx.seeded.teacher,
        settings=ctx.settings,
        codes={"provider_contract_failure"},
        only_stage=None,
    )
    precondition(retried.resumed, f"the teacher's retry found nothing to retry: {retried.refused}")
    age_grading_jobs(ctx.db)  # unmanaged fake: age the killed job past the RQ timeout
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final.error


def test_continuations_never_carry_over_between_scripts(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=3,
        pages=2,
        questions=2,
        continuation=True,
        spill=True,
    )
    _read_stage(ctx)
    assert assert_continuations_isolated(ctx.provider) == 3  # one first page per script
    # Page 2 DOES legitimately start with the open continuation of its own script's page 1.
    assert any(call.open_continuations for call in ctx.provider.calls_of("read_page"))

    # NEGATIVE CONTROL: a page-1 read that arrives with another script's open continuation.
    sha = next(
        key for key, entry in ctx.provider.registry.items() if {p for _s, p in entry.pages} == {1}
    )
    ctx.provider.calls.append(
        CallRecord(
            kind="read_page",
            index=99,
            seq=99,
            students=("S002",),
            page_no=1,
            image_sha256=sha,
            open_continuations=("Q1",),
        )
    )
    with pytest.raises(AssertionError, match=r"(?s)continuation carried across scripts.*\['Q1'\]"):
        assert_continuations_isolated(ctx.provider)
