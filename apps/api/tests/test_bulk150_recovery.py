"""PB probes: crash / restart / resume / retry / stop on the synthetic bulk harness.

Everything here drives the REAL ``BulkEvaluationService`` / ``GradingService`` /
``LocalScriptPageReadService`` with the fake brain provider of ``tests.bulk150_harness``. No
network, no model server, no real data.

Conventions (inherited from ``test_bulk150_harness_smoke``):

* ``xfail(strict=True, raises=AssertionError, reason="GAP <root_cause_key>: ...")`` marks a
  PROVEN product defect: the test asserts the CORRECT behaviour and fails today. When the product
  is fixed it flips to XPASS(strict) and the marker must be removed.
* A GAP test has exactly ONE kind of plain ``assert``: the desired-behaviour assertion. Every
  setup check (the Fault fired, the run reached the expected state, counts) goes through
  :func:`tests.bulk150_harness.precondition`, whose ``pytest.fail`` is not an ``AssertionError``
  and therefore shows up as a real FAILURE instead of silently xfailing for the wrong reason.
  A precondition only ever gates on facts that hold under ANY reasonable fix of the gap (the
  Fault fired, the late grade landed, the run settled); it never gates on the defective
  intermediate state itself, because an upstream fix would otherwise turn the XPASS into a hard
  FAIL for the wrong reason.
* Tests without a marker either refute a suspected gap (they protect behaviour that is already
  right) or pin the CURRENT behaviour of a product-policy question (see the ``POLICY`` names).

Probe index (ids as in the PB brief):

* PB-2   a grading_service rejection BEFORE its ``try`` block stranded the GradingJob 'queued'
         (fixed by F14: regression tests; a model answer edited mid-run is also held by the
         reference-bundle gate and never graded under)
* PB-4   idempotent re-upload enqueues again; ``run_next`` on a PAUSED run silently un-pauses it
* PB-5   Stop semantics (``resume_item`` cancels a Stop; Stop on an idle run)
* PB-6   a FALSE-STALE 'Recover' pressed while a healthy worker is inside one long provider call
* PB-7   budget exhaustion mid-run and the real call arithmetic of a 150-student cohort
* PB-8   ``_finish_processing`` over a still-'running' item
* PB-9   duplicate execution (two units on one run)
* PB-10  EXTRA (not in the brief): the resume routes lose the run when the queue is down
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes import bulk_evaluations as bulk_routes
from app.api.routes.script_transcripts import (
    confirm_script_transcript_review,
    correct_script_transcript_block,
)
from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerEvidenceAssignment,
    AuditLog,
    BulkEvaluationItem,
    BulkEvaluationRun,
    GradeSuggestion,
    GradingJob,
    Question,
    ScriptPageTranscript,
    ScriptTranscript,
    Submission,
)
from app.schemas import ScriptTranscriptBlockUpdate
from app.services import bulk_evaluation_service as bulk_module
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.grading_service import GradingService
from tests.bulk150_harness import (  # noqa: F401
    Corpus,
    DrainResult,
    FakeBulkBrainProvider,
    Fault,
    ProcessKilled,
    Seeded,
    age_grading_jobs,
    age_run_heartbeat,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    drain,
    expire_lease,
    hard_kill_skips_lease_release,
    harness_storage,
    import_zip,
    install_fake_brain,
    item_views,
    make_settings,
    other_session,
    precondition,
    precondition_faults_fired,
    read_lease,
    register_stored_pages,
    resume_all_items,
    review_all_transcripts,
    seed_assessment,
    set_authorised_limit,
    try_resume_run,
)

# --------------------------------------------------------------------------- shared plumbing


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
    students: int = 2,
    pages: int = 2,
    questions: int = 2,
    budget_slack: int = 2,
    maximum_provider_calls: int | None = None,
    managed_local_phase: str | None = None,
    **corpus_kwargs: Any,
) -> Ctx:
    """Seed, build the archive, import it through the real ``create_from_zip``."""

    seeded = seed_assessment(db, questions=questions)
    corpus = build_zip(
        tmp_path / "bulk.zip", students=students, pages=pages, questions=questions, **corpus_kwargs
    )
    provider = FakeBulkBrainProvider(corpus, managed_local_phase=managed_local_phase)
    install_fake_brain(monkeypatch, provider, settings)
    run = import_zip(
        db,
        seeded=seeded,
        corpus=corpus,
        provider=provider,
        settings=settings,
        budget_slack=budget_slack,
        maximum_provider_calls=maximum_provider_calls,
    )
    return Ctx(db, settings, seeded, corpus, provider, run.id)


def _read_stage(ctx: Ctx) -> DrainResult:
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _gate(ctx: Ctx) -> None:
    """Teacher transcript gate (real route functions) and the held items released."""

    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)


def _gate_and_grade(ctx: Ctx) -> DrainResult:
    _gate(ctx)
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _run(ctx: Ctx) -> BulkEvaluationRun:
    ctx.db.expire_all()
    run = ctx.db.get(BulkEvaluationRun, ctx.run_id)
    if run is None:  # not an assert: see the module docstring
        pytest.fail(f"PRECONDITION BROKEN: run {ctx.run_id} does not exist")
    return run


def _service(ctx: Ctx, db: Session) -> BulkEvaluationService:
    return BulkEvaluationService(db, settings=ctx.settings, storage=harness_storage(ctx.settings))


def _status_table(ctx: Ctx) -> dict[tuple[str, str], str]:
    """``(student, question) -> 'status/stage[codes]'`` for messages."""

    return {
        key: f"{view.status}/{view.stage}{list(view.codes) or ''}"
        for key, view in sorted(item_views(ctx.db, ctx.run_id).items())
    }


def _unit_elsewhere(ctx: Ctx) -> bool:
    """One ``run_next`` unit on an independent session (a second worker / a stray queued job)."""

    with other_session() as db:
        return _service(ctx, db).run_next(ctx.run_id)


def _stale_but_alive_seconds(settings: Settings) -> int:
    """How old the heartbeat looks 100 s after the stale threshold.

    A worker that is inside ONE long provider call is perfectly healthy, yet the bulk unit
    stamps ``heartbeat_at`` only when it starts and when it ends. The pilot's Qwen calls are
    allowed 1800 s (``local_qwen38_timeout_seconds``) and the RQ job 3600 s
    (``_enqueue``'s ``max(3600, ...)``), against a 600 s stale threshold.
    """

    return settings.cohort_dispatch_heartbeat_timeout_seconds + 100


class RecoverAfter:
    """``Fault.callback``: the teacher presses 'Recover interrupted run' mid-call.

    Differs from the harness' ``RecoverMidCall`` only in the heartbeat age: that one ages it by
    100000 s (a worker that is certainly dead, far beyond RQ's 3600 s job timeout); this one
    ages it by ``age_seconds`` (default: 100 s past the stale threshold), which is what a
    HEALTHY worker looks like in the middle of one long call. ``resumed``/``refusal``/``error``
    record what the second session saw. ``then`` is an optional extra action run in the same
    independent session right after the Recover press.
    """

    def __init__(
        self,
        run_id: int,
        teacher_id: int,
        *,
        settings: Settings,
        age_seconds: int | None = None,
        then: Callable[[BulkEvaluationService, Session], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.teacher_id = teacher_id
        self.settings = settings
        self.age_seconds = age_seconds or _stale_but_alive_seconds(settings)
        self.then = then
        self.invocations = 0
        self.resumed: bool | None = None
        self.refusal: str | None = None
        self.error: BaseException | None = None

    def __call__(self, record: object) -> None:
        del record
        self.invocations += 1
        storage = harness_storage(self.settings)
        try:
            with other_session() as db:
                age_run_heartbeat(db, self.run_id, seconds=self.age_seconds)
                service = BulkEvaluationService(db, settings=self.settings, storage=storage)
                try:
                    service.resume(service.get_run(self.run_id), teacher_id=self.teacher_id)
                    self.resumed = True
                except BulkEvaluationError as exc:
                    db.rollback()
                    self.resumed, self.refusal = False, str(exc)
                if self.then is not None:
                    self.then(service, db)
        except Exception as exc:  # e.g. a lock timeout: reported, never raised into the call
            self.error = exc


def _ui_clean_suggestion_ids(run: BulkEvaluationRun) -> list[int]:
    """The ids the web UI posts to ``approve-clean``.

    Mirrors ``apps/web/components/BulkEvaluationClient.tsx`` L189-199 (``cleanSuggestionIds``):
    graded, has a draft, not yet finalised, and an EMPTY ``exception_codes``.
    """

    return [
        int(item.grade_suggestion_id)
        for item in run.items
        if item.status == "graded"
        and item.grade_suggestion_id is not None
        and item.final_grade_id is None
        and not item.exception_codes
    ]


def _server_eligible_suggestion_ids(run: BulkEvaluationRun, db: Session) -> list[int]:
    """The ids ``approve_clean`` demands (``_reviewable_items``): no look at exception codes."""

    return sorted(
        int(item.grade_suggestion_id)
        for item in BulkEvaluationService._reviewable_items(db, run)
        if item.grade_suggestion_id is not None
    )


# =========================================================================== PB-8
# _finish_processing over an item a killed worker left 'running'.


def test_pb8_finishing_a_run_does_not_leave_a_killed_item_running(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=2))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(
        item_views(ctx.db, ctx.run_id)[("S002", "Q1")].status == "running",
        f"the kill must leave S002/Q1 'running': {_status_table(ctx)}",
    )

    # A stray unit starts again with a FRESH heartbeat: a duplicate chain job that was still
    # queued (PB-4 / PB-6 / resume_item all enqueue one), or the resume_item of an unrelated
    # exception item. It carries on with the pending work and then finishes the run.
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(final.settled, f"the stray unit must settle the run: {final}")

    run = _run(ctx)
    views = item_views(ctx.db, ctx.run_id)
    finished = run.status in {"review_ready", "completed", "completed_with_exceptions"}
    orphans = sorted(key for key, view in views.items() if view.status == "running")
    detail = ""
    if finished and orphans:
        resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
        retried = resume_all_items(
            ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
        )
        detail = (
            f" run-level resume -> {resumed} ({refusal!r}); resume_item -> "
            f"resumed={retried.resumed} refused={retried.refused}"
        )
    assert not (finished and orphans), (
        f"run is {run.status!r} (clean={run.clean_item_count} exceptions={run.exception_count} "
        f"processed={run.processed_items}/{run.total_items}) but {orphans} are still 'running':"
        f" {_status_table(ctx)};{detail}"
    )


def test_pb8_a_finish_over_a_killed_item_pauses_with_a_visible_uncertain_exception(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End state: paused, the killed item a visible 'uncertain' exception, no automatic retry.

    Whether the teacher's explicit retry of that item then succeeds is a separate defect (the
    killed call's GradingJob stays 'running'); see test_a_worker_killed_mid_grading_can_be_regraded.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=2))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)

    # Grading is question-major, so the kill (call 2 = S002/Q1) leaves Q2 of both students pending.
    assert _unit_elsewhere(ctx) is True  # the stray unit grades S001/Q2 ...
    assert _unit_elsewhere(ctx) is True  # ... then S002/Q2 ...
    calls_before_finish = _run(ctx).calls_used
    assert _unit_elsewhere(ctx) is False  # ... and the next finds nothing pending but the kill

    run = _run(ctx)
    views = item_views(ctx.db, ctx.run_id)
    killed = views[("S002", "Q1")]
    assert run.status == "paused", _status_table(ctx)
    assert run.calls_used == calls_before_finish
    assert run.completed_at is None  # not finished
    assert run.error is not None and "in-flight item from an interrupted worker" in run.error
    assert killed.status == "uncertain" and "provider_contract_failure" in killed.codes
    assert sorted(view.status for view in views.values()) == ["graded"] * 3 + ["uncertain"]
    assert (run.clean_item_count, run.exception_count, run.processed_items) == (3, 1, 4)


# =========================================================================== PB-6 (grade time)
# A healthy worker is inside one long grading call when the teacher presses Recover.


def test_pb6_a_recover_pressed_during_a_healthy_grading_call_does_not_block_approval(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    press = RecoverAfter(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    ctx.provider.inject(Fault("grade", callback=press, on_call=2))
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Recover callback itself failed: {press.error!r}")
    precondition(final.status == "review_ready", f"the run must still finish: {final}")
    views = item_views(ctx.db, ctx.run_id)
    precondition(
        all(view.status == "graded" for view in views.values()),
        f"the late-landing grade must have landed: {_status_table(ctx)}",
    )

    run = _service(ctx, ctx.db).get_run(ctx.run_id)
    ui_ids = _ui_clean_suggestion_ids(run)
    server_ids = _server_eligible_suggestion_ids(run, ctx.db)
    refusal = None
    try:
        _service(ctx, ctx.db).approve_clean(
            run,
            suggestion_ids=ui_ids,
            review_snapshot_sha256=str(run.review_snapshot_sha256),
            teacher_id=ctx.seeded.teacher.id,
        )
    except BulkEvaluationError as exc:
        ctx.db.rollback()
        refusal = str(exc)
    assert refusal is None, (
        f"the web UI's clean-draft list {ui_ids} was refused: {refusal!r}; the server's own "
        f"eligible set is {server_ids}; items: {_status_table(ctx)}; "
        f"Recover said resumed={press.resumed} refusal={press.refusal!r}"
    )


def test_pb6_a_late_landing_grade_drops_only_the_recover_stamp_and_keeps_other_warnings(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    unrelated = "an unrelated warning that must survive the late-landing grade"
    stamped: list[tuple[str, ...]] = []

    def annotate(_service: BulkEvaluationService, db: Session) -> None:
        item = db.scalar(
            select(BulkEvaluationItem).where(
                BulkEvaluationItem.run_id == ctx.run_id, BulkEvaluationItem.status == "uncertain"
            )
        )
        if item is None:
            return
        stamped.append(tuple(item.warnings or ()))
        item.warnings = [*(item.warnings or []), unrelated]
        db.commit()

    press = RecoverAfter(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings, then=annotate)
    ctx.provider.inject(Fault("grade", callback=press, on_call=2))
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Recover callback itself failed: {press.error!r}")
    precondition(final.status == "review_ready", f"the run must still finish: {final}")
    precondition(
        len(stamped) == 1 and bulk_module._UNCERTAIN_PROVIDER_WARNING in stamped[0],
        f"Recover must have stamped exactly one in-flight item as uncertain: {stamped}",
    )

    ctx.db.expire_all()
    items = list(
        ctx.db.scalars(
            select(BulkEvaluationItem).where(BulkEvaluationItem.run_id == ctx.run_id)
        ).all()
    )
    precondition(
        all(item.status == "graded" for item in items),
        f"the late-landing grade must have landed: {_status_table(ctx)}",
    )
    assert all(not item.exception_codes for item in items), _status_table(ctx)
    for item in items:
        assert bulk_module._UNCERTAIN_PROVIDER_WARNING not in (item.warnings or [])
    assert sum(unrelated in (item.warnings or []) for item in items) == 1
    run = _run(ctx)
    assert (run.clean_item_count, run.exception_count) == (len(items), 0)


def test_pb6_a_late_landing_grade_drops_only_provider_contract_failure_from_the_codes(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    unrelated = "image_quality"  # a code from the module's vocabulary that Recover never stamps
    stamped: list[tuple[str, ...]] = []

    def annotate(_service: BulkEvaluationService, db: Session) -> None:
        item = db.scalar(
            select(BulkEvaluationItem).where(
                BulkEvaluationItem.run_id == ctx.run_id, BulkEvaluationItem.status == "uncertain"
            )
        )
        if item is None:
            return
        stamped.append(tuple(item.exception_codes or ()))
        item.exception_codes = [*(item.exception_codes or []), unrelated]
        db.commit()

    press = RecoverAfter(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings, then=annotate)
    ctx.provider.inject(Fault("grade", callback=press, on_call=2))
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Recover callback itself failed: {press.error!r}")
    precondition(final.status == "review_ready", f"the run must still finish: {final}")
    precondition(
        stamped == [("provider_contract_failure",)],
        f"Recover must have stamped exactly one in-flight item as uncertain: {stamped}",
    )

    ctx.db.expire_all()
    items = list(
        ctx.db.scalars(
            select(BulkEvaluationItem).where(BulkEvaluationItem.run_id == ctx.run_id)
        ).all()
    )
    precondition(
        all(item.status == "graded" for item in items),
        f"the late-landing grade must have landed: {_status_table(ctx)}",
    )
    codes = [tuple(item.exception_codes or ()) for item in items]
    assert not any("provider_contract_failure" in item_codes for item_codes in codes), codes
    assert codes.count((unrelated,)) == 1 and codes.count(()) == len(items) - 1, codes


# =========================================================================== route plumbing


@dataclass
class Api:
    client: TestClient
    enqueued: list[int]
    ctx: Ctx

    def upload(self, *, maximum_provider_calls: int | None = None) -> Any:
        """POST the corpus archive to the REAL create route (what the web form does)."""

        ctx = self.ctx
        return self.client.post(
            f"/assessments/{ctx.seeded.assessment.id}/bulk-evaluation-runs",
            data={
                "grading_run_id": str(ctx.seeded.grading_run.id),
                "provider": ctx.provider.provider_name,
                "expected_model": ctx.provider.model_name,
                "marking_policy": "general",
                "maximum_provider_calls": str(
                    maximum_provider_calls or ctx.corpus.call_budget() + 2
                ),
                "local_only_confirmed": "true",
                "strict_auto_pass_confirmed": "true",
                "draft_only_confirmed": "true",
            },
            files={"file": ("bulk.zip", ctx.corpus.archive_path.read_bytes(), "application/zip")},
        )


@contextmanager
def _api(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    """The REAL routes (auth bypassed for the synthetic teacher), the RQ enqueue recorded.

    ``_enqueue`` is replaced by a recorder, so no Redis is touched and no job ever runs: a test
    decides when (and on which session) ``run_next`` is called.
    """

    with SessionLocal() as session:
        teacher = session.get(type(ctx.seeded.teacher), ctx.seeded.teacher.id)
        assert teacher is not None
        session.expunge(teacher)
    enqueued: list[int] = []
    monkeypatch.setattr(bulk_routes, "_enqueue", lambda run_id, _provider: enqueued.append(run_id))
    monkeypatch.setattr(
        bulk_routes, "brain_policy_for_profile", bulk_module.brain_policy_for_profile
    )
    app.dependency_overrides[get_current_user] = lambda: teacher
    try:
        yield Api(TestClient(app), enqueued, ctx)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _seed_for_route(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    **kwargs: Any,
) -> Ctx:
    """Like ``_start`` but NOTHING is imported: the test POSTs the archive to the real route."""

    questions = kwargs.pop("questions", 2)
    seeded = seed_assessment(db, questions=questions)
    corpus = build_zip(tmp_path / "bulk.zip", questions=questions, **kwargs)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, settings)
    return Ctx(db, settings, seeded, corpus, provider, run_id=0)


# =========================================================================== PB-7
# The authorised call limit runs out in the middle of the run.


def _budget_exhausted_mid_run(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Ctx:
    """4 students x 2 pages x 2 questions need 8 reads + 8 grades; only 11 calls are authorised.

    Intake refuses less than pages + items (16), so the cohort is imported at its exact need and
    the stored limit is lowered to 11 before anything is spent.
    """

    ctx = _start(db, settings, monkeypatch, tmp_path, students=4, budget_slack=0)
    set_authorised_limit(db, ctx.run_id, 11)
    _read_stage(ctx)
    paused = _gate_and_grade(ctx)
    run = _run(ctx)
    precondition(
        paused.status == "paused" and run.calls_used == run.authorized_call_limit == 11,
        f"the run must pause with its whole budget spent: {paused}",
    )
    views = item_views(ctx.db, ctx.run_id)
    precondition(
        any(view.status == "pending" for view in views.values())
        and any(view.status == "graded" for view in views.values()),
        f"some answers must be graded and some still waiting: {_status_table(ctx)}",
    )
    return ctx


def test_pb7_a_run_that_runs_out_of_calls_continues_after_the_teacher_raises_the_limit(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """RC-48 (fixed 2026-10-13): ``POST /bulk-evaluation-runs/{id}/call-limit`` raises the
    authorisation of the paused run (audited), and Resume then finishes the remaining items."""

    ctx = _budget_exhausted_mid_run(db_session, bulk_env, monkeypatch, tmp_path)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(not resumed and "raise this run's call limit" in (refusal or ""), refusal)
    with _api(ctx, monkeypatch) as api:
        too_low = api.client.post(
            f"/bulk-evaluation-runs/{ctx.run_id}/call-limit",
            json={"authorized_call_limit": 11, "teacher_confirmed": True},
        )
        raised = api.client.post(
            f"/bulk-evaluation-runs/{ctx.run_id}/call-limit",
            json={"authorized_call_limit": 20, "teacher_confirmed": True},
        )
    assert too_low.status_code == 409
    assert raised.status_code == 200, raised.text
    assert raised.json()["authorized_call_limit"] == 20
    assert raised.json()["status"] == "paused"  # raising does not resume by itself
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final
    assert all(view.status == "graded" for view in item_views(ctx.db, ctx.run_id).values())
    assert "bulk_evaluation_call_limit_raised" in [
        row.event_type
        for row in ctx.db.scalars(select(AuditLog).where(AuditLog.entity_id == ctx.run_id))
    ]


def test_pb7_the_call_limit_cannot_exceed_the_server_ceiling_or_change_a_running_run(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _budget_exhausted_mid_run(db_session, bulk_env, monkeypatch, tmp_path)
    session = SessionLocal()
    try:
        service = _service(ctx, session)
        run = service.get_run(ctx.run_id)
        ceiling = min(ctx.settings.bulk_max_provider_calls, 2000)
        with pytest.raises(BulkEvaluationError, match="server ceiling"):
            service.raise_call_limit(run, new_limit=ceiling + 1, teacher_id=ctx.seeded.teacher.id)
        session.rollback()
        run = service.get_run(ctx.run_id)
        run.status = "grading"
        with pytest.raises(BulkEvaluationError, match="Only a paused run"):
            service.raise_call_limit(run, new_limit=30, teacher_id=ctx.seeded.teacher.id)
    finally:
        session.rollback()
        session.close()
    assert _run(ctx).authorized_call_limit == 11  # nothing was changed


def test_pb7_policy_a_150_student_cohort_needs_more_calls_than_one_run_may_be_authorised(
    tmp_path: Path,
) -> None:
    """POLICY (pins the arithmetic, not a preferred answer): calls = pages + one assignment call
    per script that has inferred/unlabelled blocks + students x answered questions.

    Two ceilings bind: the server's ``bulk_max_provider_calls`` (default 1800, enforced in
    ``_assert_enabled`` L344) and the hard 2000 of the create route's ``Form(le=2000)`` and the
    ``ck_bulk_evaluation_runs`` CHECK. A 4-page, 9-question script costs 13 calls with a heading
    on every page and 14 when an answer runs over a page break.
    """

    settings = make_settings(tmp_path / "storage")
    students, pages, questions = 3, 4, 9
    clean = build_zip(tmp_path / "clean.zip", students=students, pages=pages, questions=questions)
    spilled = build_zip(
        tmp_path / "spilled.zip",
        students=students,
        pages=pages,
        questions=questions,
        continuation=True,
        spill=True,
    )
    assert not any(clean.needs_assignment_call(student) for student in clean.students)
    assert all(spilled.needs_assignment_call(student) for student in spilled.students)
    per_clean, remainder = divmod(clean.call_budget(), students)
    per_spilled, remainder_spilled = divmod(spilled.call_budget(), students)
    assert (per_clean, remainder) == (pages + questions, 0)
    assert (per_spilled, remainder_spilled) == (pages + 1 + questions, 0)

    cohort = 150  # the pilot's target: 150 scripts (the server caps submissions at 180)
    hard_cap = 2000
    field = Settings.model_fields["bulk_max_provider_calls"]
    assert any(getattr(item, "le", None) == hard_cap for item in field.metadata)
    assert settings.bulk_max_provider_calls == 1800
    assert settings.bulk_max_pages >= cohort * pages  # pages are NOT the binding limit
    assert cohort * per_clean == 1950 > settings.bulk_max_provider_calls
    assert cohort * per_clean <= hard_cap
    assert cohort * per_spilled == 2100 > hard_cap


def test_pb7_the_call_formula_matches_what_a_real_run_spends(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ties the arithmetic above to reality: a real 2-student, 4-page, 9-question run."""

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=4,
        questions=9,
        continuation=True,
        spill=True,
    )
    _read_stage(ctx)
    final = _gate_and_grade(ctx)
    assert final.status == "review_ready", final
    assert ctx.provider.counts == {"read_page": 8, "map": 2, "grade": 18}
    assert ctx.provider.total_calls == ctx.corpus.call_budget() == 28
    assert _run(ctx).calls_used == 28


def test_pb7_policy_the_server_ceiling_refuses_a_larger_authorization(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY: an authorization above ``bulk_max_provider_calls`` is refused before any import."""

    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "bulk.zip", students=1, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    with pytest.raises(BulkEvaluationError, match="exceed the bulk server ceiling"):
        import_zip(
            db_session,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=bulk_env,
            maximum_provider_calls=bulk_env.bulk_max_provider_calls + 1,
        )


# =========================================================================== PB-2
# A grading_service rejection BEFORE its ``try`` block used to strand the GradingJob in 'queued'
# (FIXED by F14; the probes below are now plain regression tests, no longer GAP markers).
#
# ``_process_grading`` commits a queued GradingJob (L2244-2251) and only then calls
# ``run_queued_job`` -> ``_grade_region``. Everything ``_grade_region`` rejects BEFORE its own
# ``try`` (grading_service.py L739-787: evidence changed, active rubric changed, rubric/question
# hash changed, no readable answer text) raises an HTTPException that nobody turns into a
# 'failed' job. The partial unique index ux_grading_jobs_active_answer_region
# (``status in ('queued', 'running')``) used to refuse the retry's INSERT for ever; the item now
# records its job id and the retry closes exactly that job as 'failed' before creating the next.


def _retry_then_finish(ctx: Ctx) -> DrainResult:
    """What the teacher does after a pause: Resume, retry every exception item, let it run."""

    try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None)
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _jobs(ctx: Ctx) -> list[tuple[int, str]]:
    ctx.db.expire_all()
    return [(job.answer_region_id, job.status) for job in ctx.db.scalars(select(GradingJob)).all()]


def test_pb2_blank_transcript_text_does_not_strand_the_grading_job(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The deterministic, teacher-reachable trigger (no race needed).

    The teacher blanks a block the model misread (the transcript editor allows an empty
    correction) and re-confirms the review, so the review is current and the assignment is still
    'answer_present'. Grading then resolves an empty answer and ``_grade_region`` rejects it with
    a 400 before its try block. The teacher restores the text, re-confirms and retries.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.db.expire_all()
    question = ctx.seeded.questions["Q1"]
    item = next(item for item in _run(ctx).items if item.question_id == question.id)
    submission_id = item.submission_id
    assignment = ctx.db.get(AnswerEvidenceAssignment, item.answer_evidence_assignment_id)
    precondition(assignment is not None and assignment.spans, "the Q1 answer must own a span")
    assert assignment is not None
    blocks = [(span.block.id, span.block.text) for span in assignment.spans]
    for block_id, _text in blocks:
        correct_script_transcript_block(
            block_id,
            ScriptTranscriptBlockUpdate(edited_text="", reason="synthetic: blank the block"),
            ctx.db,
            ctx.seeded.teacher,
        )
    confirm_script_transcript_review(submission_id, ctx.db, ctx.seeded.teacher)
    first = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(
        ctx.provider.counts["grade"] == 0 or first.status == "review_ready",
        f"the blank answer must be rejected before any grading call: {first}",
    )
    for block_id, text in blocks:  # the teacher restores the reading, re-confirms, retries
        correct_script_transcript_block(
            block_id,
            ScriptTranscriptBlockUpdate(edited_text=text, reason="synthetic: restore the block"),
            ctx.db,
            ctx.seeded.teacher,
        )
    confirm_script_transcript_review(submission_id, ctx.db, ctx.seeded.teacher)
    age_grading_jobs(ctx.db)  # unmanaged fake: age the stranded job past the RQ timeout
    final = _retry_then_finish(ctx)
    views = item_views(ctx.db, ctx.run_id)
    assert views[("S001", "Q1")].status == "graded", (
        f"S001/Q1 was never graded after the teacher restored the text and retried: run "
        f"{final.status!r} error={final.error!r}; items {_status_table(ctx)}; "
        f"grading jobs (region, status) {_jobs(ctx)}"
    )


def _edit_model_answer_in_the_window(
    monkeypatch: pytest.MonkeyPatch, ctx: Ctx, label: str = "Q1"
) -> list[int]:
    """Another browser tab edits a model answer between job creation and execution, once.

    The wrapper lets the real ``create_queued_transcript_grading_job`` create and commit the job,
    then edits the question from an independent session. Returns the ids of the jobs created
    while the edit was armed (empty when the edit never fired).
    """

    original = GradingService.create_queued_transcript_grading_job
    armed = {"on": True}
    created: list[int] = []

    def wrapper(self: GradingService, **kwargs: Any) -> GradingJob:
        job = original(self, **kwargs)
        if armed["on"]:
            armed["on"] = False
            created.append(job.id)
            with other_session() as other:
                question = other.get(Question, ctx.seeded.questions[label].id)
                assert question is not None
                question.model_answer = "Teacher corrected the model answer"
                other.commit()
        return job

    monkeypatch.setattr(GradingService, "create_queued_transcript_grading_job", wrapper)
    return created


def test_pb2_a_model_answer_edited_mid_run_is_held_by_the_reference_gate_and_never_graded(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A model answer edited between job creation and execution is never graded under.

    The first attempt is refused by ``GradingService`` itself (the expected-rubric-hash check,
    before the provider is called); the job the run had already created is left behind. The
    teacher's Resume + retry then meets the reference-bundle gate, which pauses the run with the
    reference-changed message BEFORE a second job is created or the provider is called. Nothing is
    graded under the changed model answer: no grade call, no GradeSuggestion, no second
    GradingJob (so the retry's INSERT that used to raise a UniqueViolation is never attempted).
    The close-out of the abandoned job once the teacher restores the model answer is pinned by
    ``test_pb2_the_retry_supersedes_the_abandoned_job_and_the_reference_gate_still_holds``.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    created = _edit_model_answer_in_the_window(monkeypatch, ctx)
    first = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(created, "the model-answer edit never fired (no job was created)")
    precondition(
        ctx.provider.counts["grade"] == 0,
        f"the changed question must be rejected BEFORE any grading call: {first}",
    )
    final = _retry_then_finish(ctx)
    assert final.status == "paused" and "Reference materials" in (final.error or ""), final
    assert ctx.provider.counts["grade"] == 0  # the gate held: no provider call at any point
    ctx.db.expire_all()
    assert ctx.db.scalar(select(func.count(GradeSuggestion.id))) == 0  # no draft grade exists
    victim = _item(ctx, "S001", "Q1")
    assert victim.status != "graded" and victim.grade_suggestion_id is None, (
        f"S001/Q1 was graded under a changed model answer: {_status_table(ctx)}"
    )
    jobs = ctx.db.scalars(select(GradingJob)).all()
    # the one job created inside the window; the retry created no second one and none succeeded
    assert [job.id for job in jobs] == created, _jobs(ctx)
    assert all(job.status != "succeeded" for job in jobs), _jobs(ctx)


def test_pb2_the_retry_supersedes_the_abandoned_job_and_the_reference_gate_still_holds(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The model answer is edited inside the window and the job it strands is closed visibly.

    Grading under a changed model answer stays refused (the reference-bundle gate pauses the run,
    no provider call). Once the teacher restores it, the retry closes the abandoned 'queued' job
    as 'failed' with a clear message, grades the answer exactly once, and touches no other job.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    question_id = ctx.seeded.questions["Q1"].id
    original = ctx.seeded.questions["Q1"].model_answer
    created = _edit_model_answer_in_the_window(monkeypatch, ctx)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(created, "the model-answer edit never fired (no job was created)")
    precondition(ctx.provider.counts["grade"] == 0, "the changed question reached the provider")

    refused = _retry_then_finish(ctx)
    assert refused.status == "paused" and "Reference materials" in (refused.error or ""), refused
    assert ctx.provider.counts["grade"] == 0  # the gate held: nothing graded under a new answer

    with other_session() as other:
        question = other.get(Question, question_id)
        assert question is not None
        question.model_answer = original
        other.commit()
    age_grading_jobs(ctx.db)  # unmanaged fake: age the stranded job past the RQ timeout
    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    assert item_views(ctx.db, ctx.run_id)[("S001", "Q1")].status == "graded"

    ctx.db.expire_all()
    abandoned = ctx.db.get(GradingJob, created[0])
    assert abandoned is not None
    assert abandoned.status == "failed"
    assert abandoned.error == "Superseded: the earlier attempt did not complete"
    assert abandoned.completed_at is not None
    statuses = Counter(job.status for job in ctx.db.scalars(select(GradingJob)).all())
    assert statuses == {"succeeded": 4, "failed": 1}  # 4 regions graded once; one job superseded


def _item(ctx: Ctx, student: str, question: str) -> BulkEvaluationItem:
    ctx.db.expire_all()
    item = ctx.db.get(
        BulkEvaluationItem, item_views(ctx.db, ctx.run_id)[(student, question)].item_id
    )
    if item is None:  # not an assert: see the module docstring
        pytest.fail(f"PRECONDITION BROKEN: no item for {student}/{question}")
    return item


def test_f14_a_killed_item_records_its_own_job_and_only_that_job_is_closed(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The item's ``grading_job_id`` is committed before the provider call, so a kill leaves it."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=2))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    killed = _item(ctx, "S002", "Q1")
    running = [job.id for job in ctx.db.scalars(select(GradingJob)) if job.status == "running"]
    precondition(killed.status == "running", f"the kill must strand the item: {killed.status}")
    assert running == [killed.grading_job_id], (running, killed.grading_job_id)

    age_run_heartbeat(ctx.db, ctx.run_id)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"stale-run recovery was refused: {refusal}")
    retried = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    precondition(retried.resumed, f"the teacher's retry found nothing to retry: {retried.refused}")
    age_grading_jobs(ctx.db)  # unmanaged fake: age the killed job past the RQ timeout
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final.error
    ctx.db.expire_all()
    closed = [job for job in ctx.db.scalars(select(GradingJob)) if job.status == "failed"]
    assert [job.id for job in closed] == running  # exactly the item's own earlier attempt


def test_f14_a_pre_try_rejection_leaves_the_item_pointing_at_the_stranded_job(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The rejection happens after the job exists: the item must already point at it."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    created = _edit_model_answer_in_the_window(monkeypatch, ctx)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(created, "the model-answer edit never fired (no job was created)")
    precondition(ctx.provider.counts["grade"] == 0, "the changed question reached the provider")
    assert _item(ctx, "S001", "Q1").grading_job_id == created[0]


def test_f14_a_foreign_active_job_on_the_region_is_left_alone_and_the_unit_fails_visibly(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only the item's OWN earlier job may be closed, never another unit's live job.

    A 'queued' job on S001/Q1's region that this item never created (another unit, or a job the
    teacher started) is live as far as the item can tell. Closing it would remove the protection
    of ux_grading_jobs_active_answer_region against two concurrent attempts. It stays untouched,
    the new job's INSERT is refused and the unit fails visibly: no provider call, no draft, the
    run pauses and the item is quarantined as uncertain.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    victim = _item(ctx, "S001", "Q1")
    precondition(victim.grading_job_id is None, "the item must not have attempted grading yet")
    region_id = victim.answer_region_id
    with other_session() as other:
        foreign = GradingJob(answer_region_id=region_id, status="queued")
        other.add(foreign)
        other.commit()
        foreign_id = foreign.id

    paused = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert paused.status == "paused", paused
    assert ctx.provider.counts["grade"] == 0  # no second provider call, nothing silently graded
    view = item_views(ctx.db, ctx.run_id)[("S001", "Q1")]
    assert view.status in {"uncertain", "exception"} and view.codes, view  # quarantined, visible
    assert view.suggestion_id is None
    ctx.db.expire_all()
    untouched = ctx.db.get(GradingJob, foreign_id)
    assert untouched is not None
    assert (untouched.status, untouched.error, untouched.completed_at) == ("queued", None, None)
    on_region = ctx.db.scalars(select(GradingJob).where(GradingJob.answer_region_id == region_id))
    assert [job.id for job in on_region] == [foreign_id]  # no second job on the region

    with other_session() as other:  # the other attempt ends: the teacher's retry then proceeds
        other_job = other.get(GradingJob, foreign_id)
        assert other_job is not None
        other_job.status = "failed"
        other.commit()
    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    assert item_views(ctx.db, ctx.run_id)[("S001", "Q1")].status == "graded"


# =========================================================================== W11
# A GradingJob that may still be live is never closed (the correction of W05 / F14).
#
# ``_process_grading`` closes an item's OWN earlier job before it creates the next one, so a worker
# killed mid-call can be re-graded. That is safe only when nothing can still be running under that
# job. 'Recover interrupted run' stamps the in-flight item 'uncertain' and 'Resume item' makes it
# 'pending' again while a HUNG (not dead) call may still be running; closing its live job would
# let a second provider call start on the same answer. So the job is closed only when provably
# not live: with a model lease, when no unexpired lease is held under that job; without one, when
# the job is older than the bulk RQ job timeout. Otherwise it is left open, the unique index
# ux_grading_jobs_active_answer_region refuses the new job and the unit fails visibly.

_SUPERSEDED = "Superseded: the earlier attempt did not complete"


def _assert_named_live_job_pause(ctx: Ctx, answer: str) -> None:
    """The pause names the answer and when to retry, never raw database text."""

    error = _run(ctx).error or ""
    assert answer in error, error
    assert "may still be running" in error and "Resume this item after" in error, error
    assert "UniqueViolation" not in error and "duplicate key" not in error, error


def _resume_the_item_and_run_the_next_unit(
    ctx: Ctx, seen: dict[str, Any]
) -> Callable[[BulkEvaluationService, Session], None]:
    """``RecoverAfter.then``: the teacher presses 'Resume item' and the worker chain starts its next
    unit, both while the ORIGINAL grading call is still running. ``seen`` records what that second
    unit left behind (no ``precondition()`` here: it must not unwind a provider call)."""

    def then(service: BulkEvaluationService, db: Session) -> None:
        item = db.scalar(
            select(BulkEvaluationItem).where(
                BulkEvaluationItem.run_id == ctx.run_id, BulkEvaluationItem.status == "uncertain"
            )
        )
        if item is None:
            seen["no_uncertain_item"] = True
            return
        item_id, job_id = item.id, item.grading_job_id
        service.resume_item(service.get_run(ctx.run_id), item, teacher_id=ctx.seeded.teacher.id)
        seen["more"] = service.run_next(ctx.run_id)
        db.expire_all()
        after, job, run = (
            db.get(BulkEvaluationItem, item_id),
            db.get(GradingJob, job_id),
            db.get(BulkEvaluationRun, ctx.run_id),
        )
        seen["item_id"], seen["job_id"] = item_id, job_id
        seen["item"] = (after.status, tuple(after.exception_codes or ())) if after else None
        seen["job"] = (job.status, job.error) if job else None
        seen["run"] = run.status if run else None

    return then


@pytest.mark.parametrize(
    "managed_local_phase", [None, "Qwen38"], ids=["unmanaged", "managed-local-lease"]
)
def test_w11_resume_item_during_a_live_call_never_closes_the_live_job_or_calls_twice(
    managed_local_phase: str | None,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover + Resume item while the ORIGINAL grading call is still running (a hung server).

    The in-flight answer is the LAST one, so once resumed it is the only item the next unit can
    pick. That unit must not close the live job: no second provider call, no second draft, the
    live job stays 'running' and the unit fails visibly (run paused, item quarantined). The late
    landing of the original call then settles the answer exactly once.
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        managed_local_phase=managed_local_phase,
    )
    _read_stage(ctx)
    _gate(ctx)
    seen: dict[str, Any] = {}
    press = RecoverAfter(
        ctx.run_id,
        ctx.seeded.teacher.id,
        settings=ctx.settings,
        then=_resume_the_item_and_run_the_next_unit(ctx, seen),
    )
    ctx.provider.inject(Fault("grade", callback=press, on_call=4))
    first = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Recover callback itself failed: {press.error!r}")
    precondition("item_id" in seen, f"the mid-call Resume item never ran: {seen}")

    assert seen["job"] == ("running", None), f"the live job was touched: {seen}"
    assert seen["run"] == "paused", seen  # the second unit failed visibly ...
    assert seen["item"] is not None and seen["item"][0] == "uncertain" and seen["item"][1], seen
    graded = [(call.students, call.question) for call in ctx.provider.calls_of("grade")]
    assert len(graded) == len(set(graded)) == 4, (
        f"an answer was sent to the provider twice: {graded}"
    )
    ctx.db.expire_all()
    assert ctx.db.scalar(select(func.count(GradeSuggestion.id))) == 4  # one draft per answer
    assert sorted(status for _region, status in _jobs(ctx)) == ["succeeded"] * 4, _jobs(ctx)
    assert all(job.error != _SUPERSEDED for job in ctx.db.scalars(select(GradingJob)))
    assert first.status == "paused", first
    assert _run(ctx).calls_used == ctx.provider.total_calls

    # The late-landing grade settled the answer once; the teacher's Resume then finishes the run.
    precondition(
        all(view.status == "graded" for view in item_views(ctx.db, ctx.run_id).values()),
        f"the late-landing grade must have landed: {_status_table(ctx)}",
    )
    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    assert ctx.provider.counts["grade"] == 4  # still one call per answer


def test_w11_a_hard_killed_managed_job_stays_open_until_its_lease_expires(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A kill -9 leaves the dead worker's lease held: the job it was grading under is not closed.

    Closing it would let the lease be reclaimed (a terminal holder job frees the slot) and the
    answer be graded again although the first call might still be running. Once the lease has
    expired the same retry closes the job visibly and re-grades.
    """

    ctx = _start(
        db_session, bulk_env, monkeypatch, tmp_path, students=2, managed_local_phase="Qwen38"
    )
    _read_stage(ctx)
    _gate(ctx)
    skipped = hard_kill_skips_lease_release(monkeypatch)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=4))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    killed = _item(ctx, "S002", "Q2")
    precondition(killed.status == "running", f"the kill must strand the item: {killed.status}")
    job_id = killed.grading_job_id
    holder = skipped[-1] if skipped else None
    precondition(
        holder is not None and holder.startswith(f"grading_job:{job_id}:"),
        f"the dead worker must still hold its lease: skipped={skipped} job={job_id}",
    )
    age_run_heartbeat(ctx.db, ctx.run_id)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"stale-run recovery was refused: {refusal}")
    retried = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    precondition(retried.resumed, f"the teacher's retry found nothing to retry: {retried.refused}")

    calls_before = ctx.provider.counts["grade"]
    blocked = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert blocked.status == "paused", blocked
    assert ctx.provider.counts["grade"] == calls_before  # no second call on the answer
    ctx.db.expire_all()
    job = ctx.db.get(GradingJob, job_id)
    assert job is not None and (job.status, job.error) == ("running", None)  # left open
    lease = read_lease(ctx.db)
    assert lease is not None and lease.holder_id == holder  # not reclaimed behind its back
    view = item_views(ctx.db, ctx.run_id)[("S002", "Q2")]
    assert view.status in {"uncertain", "exception"} and view.codes, view  # visible, not silent
    assert view.suggestion_id is None
    _assert_named_live_job_pause(ctx, "S002 / Q2")

    expire_lease(ctx.db)  # 30 minutes without a heartbeat: the slot is free
    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    ctx.db.expire_all()
    closed = ctx.db.get(GradingJob, job_id)
    assert closed is not None and (closed.status, closed.error) == ("failed", _SUPERSEDED)
    assert item_views(ctx.db, ctx.run_id)[("S002", "Q2")].status == "graded"
    assert ctx.provider.counts["grade"] == calls_before + 1  # exactly one re-grade
    final_lease = read_lease(ctx.db)
    assert final_lease is not None and final_lease.holder_id is None


def test_w11_an_unmanaged_job_is_closed_only_once_older_than_the_rq_job_timeout(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no lease to consult, a job counts as dead only past the RQ job timeout (>= 3600 s)."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=4))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    killed = _item(ctx, "S002", "Q2")
    precondition(killed.status == "running", f"the kill must strand the item: {killed.status}")
    job_id = killed.grading_job_id
    age_run_heartbeat(ctx.db, ctx.run_id)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"stale-run recovery was refused: {refusal}")
    retried = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    precondition(retried.resumed, f"the teacher's retry found nothing to retry: {retried.refused}")

    calls_before = ctx.provider.counts["grade"]
    precondition(age_grading_jobs(ctx.db, seconds=3500) == 1, "exactly the killed job is active")
    blocked = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)  # 3500 s < 3600 s
    assert blocked.status == "paused", blocked
    assert ctx.provider.counts["grade"] == calls_before
    ctx.db.expire_all()
    job = ctx.db.get(GradingJob, job_id)
    assert job is not None and (job.status, job.error) == ("running", None)
    _assert_named_live_job_pause(ctx, "S002 / Q2")

    age_grading_jobs(ctx.db, seconds=3700)  # past max(3600, the policy timeout)
    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    ctx.db.expire_all()
    closed = ctx.db.get(GradingJob, job_id)
    assert closed is not None and (closed.status, closed.error) == ("failed", _SUPERSEDED)
    assert ctx.provider.counts["grade"] == calls_before + 1


@pytest.mark.parametrize(
    "managed_local_phase", [None, "Qwen38"], ids=["unmanaged", "managed-local-lease"]
)
def test_w11_a_job_rejected_before_the_provider_is_closed_without_waiting(
    managed_local_phase: str | None,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A job stranded 'queued' never reached the provider, so the retry closes it at once.

    ``GradingService`` commits 'running' before it takes the lease or calls out, so a 'queued'
    job is provably not live for either provider kind: no aging, no waiting (the unmanaged path
    used to wait out the 3,600 s RQ timeout here).
    """

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        managed_local_phase=managed_local_phase,
    )
    _read_stage(ctx)
    _gate(ctx)
    question_id = ctx.seeded.questions["Q1"].id
    original = ctx.seeded.questions["Q1"].model_answer
    created = _edit_model_answer_in_the_window(monkeypatch, ctx)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(created, "the model-answer edit never fired (no job was created)")
    precondition(ctx.provider.counts["grade"] == 0, "the changed question reached the provider")
    with other_session() as other:
        question = other.get(Question, question_id)
        assert question is not None
        question.model_answer = original
        other.commit()

    final = _retry_then_finish(ctx)
    assert final.status == "review_ready", final.error
    ctx.db.expire_all()
    abandoned = ctx.db.get(GradingJob, created[0])
    assert abandoned is not None and (abandoned.status, abandoned.error) == ("failed", _SUPERSEDED)
    assert ctx.provider.counts["grade"] == 4  # each answer graded once
    lease = read_lease(ctx.db)
    if managed_local_phase is not None:
        assert lease is not None and lease.holder_id is None
    else:
        assert lease is None


# =========================================================================== PB-4
# Re-uploading the SAME archive, and run_next on a PAUSED run.


@pytest.mark.parametrize("state", ["queued", "review_ready"])
def test_pb4_an_idempotent_reupload_does_not_enqueue_another_worker_chain(
    state: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _seed_for_route(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    with _api(ctx, monkeypatch) as api:
        first = api.upload()
        precondition(first.status_code == 202, f"the first upload failed: {first.text[:200]}")
        ctx.run_id = first.json()["id"]
        if state == "review_ready":
            register_stored_pages(
                ctx.db, ctx.provider, ctx.corpus, ctx.seeded.assessment.id, settings=ctx.settings
            )
            _read_stage(ctx)
            finished = _gate_and_grade(ctx)
            precondition(finished.status == "review_ready", f"the run must finish: {finished}")
        second = api.upload()
        assert api.enqueued == [ctx.run_id], (
            f"run {ctx.run_id} ({state}): the first upload enqueued it once; the second upload "
            f"(HTTP {second.status_code}, body id {second.json().get('id')}) is an idempotent "
            f"hit, yet the recorded enqueue calls are {api.enqueued}"
        )


@pytest.mark.parametrize("state", ["queued", "paused"])
def test_pb4_an_idempotent_reupload_never_imports_a_second_copy(
    state: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED half of PB-4: the same archive is never imported twice (runs, scripts, items)."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    if state == "paused":
        ctx.provider.inject(Fault("read_page", RuntimeError("synthetic 500"), student="S002"))
        _read_stage(ctx)
        precondition(_run(ctx).status == "paused", "the read failure must pause the run")
    runs_before = ctx.db.scalar(select(func.count(BulkEvaluationRun.id)))
    scripts_before = ctx.db.scalar(select(func.count(Submission.id)))
    with _api(ctx, monkeypatch) as api:
        again = api.upload()
    assert again.status_code < 500, again.text[:300]  # accepted, refused, whatever: never a crash
    ctx.db.expire_all()
    assert ctx.db.scalar(select(func.count(BulkEvaluationRun.id))) == runs_before == 1
    assert ctx.db.scalar(select(func.count(Submission.id))) == scripts_before == 3


@pytest.mark.parametrize("state", ["queued", "paused"])
def test_pb4_an_idempotent_reupload_with_the_queue_down_leaves_the_existing_run_alone(
    state: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A repeat upload enqueues nothing, so a dead queue cannot 503 it or pause the existing run.

    Nor does it un-pause a paused run: that takes the teacher's Resume.
    """

    ctx = _seed_for_route(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    with _api(ctx, monkeypatch) as api:
        first = api.upload()
        precondition(first.status_code == 202, f"the first upload failed: {first.text[:200]}")
        ctx.run_id = first.json()["id"]
        if state == "paused":
            run = _run(ctx)
            run.status, run.error = "paused", "synthetic pause"
            ctx.db.commit()

        def queue_is_down(_run_id: int, _provider: str) -> None:
            raise RuntimeError("synthetic: Redis connection refused")

        monkeypatch.setattr(bulk_routes, "_enqueue", queue_is_down)
        again = api.upload()
    assert again.status_code == 202, again.text[:300]
    assert again.json()["id"] == ctx.run_id
    run = _run(ctx)
    assert (run.status, run.error) == (state, "synthetic pause" if state == "paused" else None)


def test_pb4_a_stopped_run_is_not_silently_restarted_by_a_reupload(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED half of PB-4: for a STOPPED run a re-upload is a 409 and nothing is enqueued.

    (``stopped`` is not in ``_ACTIVE_RUN_STATUSES``, so no existing run is returned; the
    identifiers of the first import are still on file and refuse the second.)
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    service = _service(ctx, ctx.db)
    service.stop(service.get_run(ctx.run_id), teacher_id=ctx.seeded.teacher.id)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert _run(ctx).status == "stopped"
    with _api(ctx, monkeypatch) as api:
        again = api.upload()
        assert again.status_code == 409, again.text[:300]
        assert "already exist" in again.json()["detail"]
        assert api.enqueued == []
    assert ctx.provider.total_calls == 0


def _paused_by_a_failed_page_read(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Ctx:
    """3 scripts; S002's page read fails once; S003 has not been read yet; the run is paused."""

    ctx = _start(db, settings, monkeypatch, tmp_path, students=3)
    ctx.provider.inject(Fault("read_page", RuntimeError("synthetic 500"), student="S002"))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed read must pause the run: {paused}")
    return ctx


def test_pb4_a_stray_worker_unit_does_not_un_pause_a_paused_run(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
    reads = ctx.provider.counts["read_page"]
    _unit_elsewhere(ctx)  # the next unit of a chain that was queued before the pause
    run = _run(ctx)
    assert run.status == "paused" and ctx.provider.counts["read_page"] == reads, (
        f"a unit ran on a paused run: status {run.status!r}/{run.stage!r} error={run.error!r}; "
        f"read calls {reads} -> {ctx.provider.counts['read_page']}; items {_status_table(ctx)}"
    )


def test_pb4_a_stray_worker_unit_cannot_strand_a_failed_script(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)  # the stray chain keeps going
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    detail = ""
    if not resumed:
        retried = resume_all_items(
            ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
        )
        detail = f"; resume_item -> resumed={retried.resumed} refused={retried.refused}"
    assert resumed, (
        f"the teacher can no longer recover the failed script: run {_run(ctx).status!r}, "
        f"resume -> {refusal!r}{detail}; items {_status_table(ctx)}"
    )


def _press_resume_item(ctx: Ctx, submission_id: int) -> str | None:
    """The teacher's 'Resume item' on a held item of one script; returns the refusal, if any."""

    with other_session() as db:
        service = _service(ctx, db)
        run = service.get_run(ctx.run_id)
        item = next(
            i
            for i in run.items
            if i.submission_id == submission_id and i.status in {"exception", "uncertain"}
        )
        try:
            service.resume_item(run, item, teacher_id=ctx.seeded.teacher.id)
        except BulkEvaluationError as exc:
            db.rollback()
            return str(exc)
    return None


def _submission_of(ctx: Ctx, student: str) -> int:
    found = ctx.db.scalar(select(Submission.id).where(Submission.student_identifier == student))
    if found is None:
        pytest.fail(f"PRECONDITION BROKEN: no submission for {student}")
    return int(found)


def test_pb4_resume_item_on_a_paused_run_is_the_teachers_explicit_resume(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``run_next`` no longer un-pauses a run, so 'Resume item' on a paused run must do it.

    Without this the click would be a no-op: the item turns pending, the run stays paused, and the
    queued unit returns at once. It is the teacher's explicit action: it clears the pause error,
    writes the existing item-resumed audit row, and the run then finishes the item.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=1))
    _read_stage(ctx)
    paused = _gate_and_grade(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed grade must pause the run: {paused}")
    retried = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    precondition(len(retried.resumed) == 1 and not retried.refused, f"item retry: {retried}")
    run = _run(ctx)
    assert (run.status, run.error) == ("grading", None), (run.status, run.stage, run.error)
    audit_events = ctx.db.scalars(
        select(AuditLog.event_type).where(
            AuditLog.entity_type == "bulk_evaluation_run", AuditLog.entity_id == ctx.run_id
        )
    ).all()
    assert "bulk_evaluation_item_resumed" in audit_events
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final
    assert {view.status for view in item_views(ctx.db, ctx.run_id).values()} == {"graded"}


def test_pb4_resume_item_on_a_run_paused_by_a_failed_read_does_not_strand_the_failed_script(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resuming an unrelated item un-pauses with the run-level checks, so S002 is read again."""

    ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
    reads = ctx.provider.counts["read_page"]
    s001 = _submission_of(ctx, "S001")
    reviewed = review_all_transcripts(
        ctx.db, ctx.run_id, ctx.seeded.teacher, only_submissions=[s001]
    )
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    refusal = _press_resume_item(ctx, s001)
    precondition(refusal is None, f"Resume item was refused: {refusal}")
    assert _run(ctx).status == "reading"
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    s002 = {
        view.status
        for (student, _), view in item_views(ctx.db, ctx.run_id).items()
        if student == "S002"
    }
    assert ctx.provider.counts["read_page"] > reads and "uncertain" not in s002, (
        f"S002 was not read again: read calls {reads} -> {ctx.provider.counts['read_page']}; "
        f"items {_status_table(ctx)}"
    )


def test_pb4_resume_item_on_a_run_paused_by_an_unknown_read_outcome_is_refused(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The run-level 'must be reconciled' refusal also guards the per-item button."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("read_page", TimeoutError("timed out"), on_call=3))
    paused = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the timed-out read must pause the run: {paused}")
    reads = ctx.provider.counts["read_page"]
    s001 = _submission_of(ctx, "S001")
    reviewed = review_all_transcripts(
        ctx.db, ctx.run_id, ctx.seeded.teacher, only_submissions=[s001]
    )
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    refusal = _press_resume_item(ctx, s001)
    assert refusal is not None and "must be reconciled" in refusal, refusal
    assert _run(ctx).status == "paused"
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)  # a stray unit stays a no-op
    assert _run(ctx).status == "paused" and ctx.provider.counts["read_page"] == reads


# =========================================================================== PB-5
# Stop semantics.


class _StopThenRetry:
    """``Fault.callback``: mid-call the teacher presses Stop and then retries an exception item.

    Both go through the REAL service on an independent session. ``retry=False`` presses Stop
    only. ``status``/``stop_requested`` are the run's state right after the last action.
    """

    def __init__(
        self, run_id: int, teacher_id: int, *, settings: Settings, retry: bool = True
    ) -> None:
        self.run_id = run_id
        self.teacher_id = teacher_id
        self.settings = settings
        self.retry = retry
        self.invocations = 0
        self.refusal: str | None = None
        self.error: BaseException | None = None
        self.status: str | None = None
        self.stop_requested: bool | None = None

    def __call__(self, record: object) -> None:
        self.invocations += 1
        try:
            with other_session() as db:
                service = BulkEvaluationService(
                    db, settings=self.settings, storage=harness_storage(self.settings)
                )
                service.stop(service.get_run(self.run_id), teacher_id=self.teacher_id)
                if self.retry:
                    run = service.get_run(self.run_id)
                    stranded = [i for i in run.items if i.status in {"exception", "uncertain"}]
                    try:
                        service.resume_item(run, stranded[0], teacher_id=self.teacher_id)
                    except BulkEvaluationError as exc:
                        db.rollback()
                        self.refusal = str(exc)
                run = service.get_run(self.run_id)
                self.status, self.stop_requested = run.status, run.stop_requested
        except Exception as exc:  # reported, never raised into the provider call
            self.error = exc


def _running_with_a_failed_item(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Ctx:
    """3 students; grading call 1 fails (S001/Q1 'uncertain'), the teacher Resumes the run."""

    ctx = _start(db, settings, monkeypatch, tmp_path, students=3)
    ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=1))
    _read_stage(ctx)
    paused = _gate_and_grade(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(paused.status == "paused", f"the failed grade must pause the run: {paused}")
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"Resume was refused: {refusal}")
    return ctx


def test_pb5_retrying_an_item_does_not_silently_cancel_the_teachers_stop(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _running_with_a_failed_item(db_session, bulk_env, monkeypatch, tmp_path)
    press = _StopThenRetry(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    ctx.provider.inject(Fault("grade", callback=press, on_call=2))
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Stop/retry callback itself failed: {press.error!r}")
    # Policy-neutral: either the retry is refused (stop stays requested) or it explicitly
    # resumes the run (status leaves 'stopping'). What must not exist is 'stopping' + no request.
    assert not (press.status == "stopping" and press.stop_requested is False), (
        f"after Stop + retry the run is {press.status!r} with stop_requested="
        f"{press.stop_requested} (retry refusal {press.refusal!r}); the worker then went on to "
        f"{final.status!r} with grade calls {ctx.provider.counts['grade']}: "
        f"{_status_table(ctx)}"
    )


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_stop_requested"),
    [
        ("stopping", "stopping", True),  # a pending teacher Stop survives the retry
        ("completed_with_exceptions", "reading", False),  # a finished run is re-opened as before
    ],
)
def test_pb5_transcript_assignment_retry_keeps_a_pending_stop_only_while_stopping(
    status: str, expected_status: str, expected_stop_requested: bool
) -> None:
    """The one-click transcript-analysis retry branch of ``resume_item`` (mocked session)."""

    db = MagicMock()
    run = BulkEvaluationRun(
        id=5,
        created_by_teacher_id=1,
        status=status,
        stage="reading",
        authorized_call_limit=20,
        calls_used=3,
        stop_requested=True,
        provider="llama_cpp_qwen38",
        model_name="qwen3.8-27b-q4km",
        import_manifest={"visual_evidence_path": "page_read"},
    )
    item = BulkEvaluationItem(
        id=21,
        run_id=5,
        submission_id=62,
        question_id=72,
        answer_evidence_assignment_id=700,
        status="exception",
        stage="read",
        exception_codes=["unassigned_ink"],
        warnings=["unassigned"],
    )
    run.items = [item]
    assignment = AnswerEvidenceAssignment(
        id=700,
        script_transcript_id=901,
        submission_id=62,
        question_id=72,
        question_node_id=82,
        assignment_version=1,
        state="ambiguous",
        coverage_complete=True,
        unassigned_block_count=9,
        is_current=True,
    )
    transcript = ScriptTranscript(
        id=901,
        source_manifest_sha256="a" * 64,
        assignment_status="complete",
        assignment_fingerprint="b" * 64,
        assignment_result_json={"mappings": [], "warnings": []},
    )
    db.get.side_effect = lambda model, object_id: {
        (AnswerEvidenceAssignment, 700): assignment,
        (ScriptTranscript, 901): transcript,
    }.get((model, object_id))
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._refresh_counts = MagicMock()
    service._audit_run = MagicMock()

    resumed = service.resume_item(run, item, teacher_id=1)

    assert (resumed.stage, resumed.status) == ("read", "pending")  # the retry itself still lands
    assert run.status == expected_status
    assert run.stop_requested is expected_stop_requested


def test_pb5_a_stop_pressed_during_a_call_is_honoured_by_the_next_unit(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED half of PB-5: Stop alone works (the in-flight call lands, nothing more is graded)."""

    ctx = _running_with_a_failed_item(db_session, bulk_env, monkeypatch, tmp_path)
    press = _StopThenRetry(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings, retry=False)
    ctx.provider.inject(Fault("grade", callback=press, on_call=2))
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert press.invocations == 1 and press.error is None
    assert (press.status, press.stop_requested) == ("stopping", True)
    assert final.status == "stopped", final
    assert ctx.provider.counts["grade"] == 2  # the failed call 1 and the in-flight call 2 only
    assert item_views(ctx.db, ctx.run_id)[("S002", "Q1")].status == "graded"  # it landed


def test_pb5_a_stop_pressed_during_a_failing_call_survives_a_later_item_retry(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stop during a grading call that then FAILS must outlive the retry click that follows.

    The failure handler turns 'stopping' into 'paused' but leaves ``stop_requested`` set. Retrying
    one item from that paused run must keep the request, so the worker ends the run 'stopped'
    on its next unit instead of silently grading the whole remaining cohort.
    """

    ctx = _running_with_a_failed_item(db_session, bulk_env, monkeypatch, tmp_path)
    press = _StopThenRetry(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings, retry=False)
    ctx.provider.inject(
        Fault("grade", RuntimeError("synthetic grader 500 during Stop"), callback=press, on_call=2)
    )
    paused = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Stop callback itself failed: {press.error!r}")
    precondition(
        paused.status == "paused" and _run(ctx).stop_requested is True,
        f"Stop + a failing call must leave a paused run with the Stop pending: {paused}",
    )
    grade_calls = ctx.provider.counts["grade"]
    precondition(grade_calls == 2, f"expected only the failed and in-flight calls: {grade_calls}")

    refusal = _press_resume_item(ctx, _submission_of(ctx, "S001"))

    assert refusal is None, refusal
    assert _run(ctx).stop_requested is True
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "stopped", final
    assert ctx.provider.counts["grade"] == grade_calls  # the Stop held: no further provider call


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_stop_requested"),
    [
        ("paused", "stopping", True),  # a Stop that a failing call left behind a pause survives
        ("stopped", "reading", False),  # an ended run is re-opened by the retry as before
    ],
)
def test_pb5_transcript_assignment_retry_keeps_a_stop_left_behind_a_pause(
    status: str, expected_status: str, expected_stop_requested: bool
) -> None:
    """The transcript-analysis retry branch of ``resume_item`` (same mocked session as above).

    Only an ended run ('stopped' here) may have its spent request cleared: there the retry
    re-opens the run to 'reading', which a still-set request would immediately end again.
    """

    test_pb5_transcript_assignment_retry_keeps_a_pending_stop_only_while_stopping(
        status, expected_status, expected_stop_requested
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP stop-on-idle-run-strands-in-stopping: stop() accepts every status except "
        "completed/completed_with_exceptions/failed/stopped (bulk_evaluation_service.py:713) and "
        "writes 'stopping' (L716) even for a PAUSED or REVIEW_READY run, which no worker unit "
        "will ever pick up (the stop route enqueues nothing). The run then sits 'stopping': "
        "run-level resume is refused (L743) and approve_clean is refused for a finished run "
        "(L1028) until the heartbeat is 10 minutes old and the teacher presses the 'Recover "
        "interrupted run' button. API-only or a stale-page click: the UI renders Stop only for "
        "active runs (BulkEvaluationClient.tsx:411)."
    ),
)
@pytest.mark.parametrize("state", ["paused", "review_ready"])
def test_pb5_stopping_a_run_nobody_is_working_on_does_not_leave_it_stopping(
    state: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if state == "paused":
        ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
    else:
        ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
        _read_stage(ctx)
        finished = _gate_and_grade(ctx)
        precondition(finished.status == "review_ready", f"the run must finish: {finished}")
    service = _service(ctx, ctx.db)
    service.stop(service.get_run(ctx.run_id), teacher_id=ctx.seeded.teacher.id)
    run = _run(ctx)
    detail = ""
    if run.status == "stopping":
        resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
        approve_refusal: str | None = "not attempted (the run was paused, not finished)"
        if state == "review_ready":
            fresh = _service(ctx, ctx.db).get_run(ctx.run_id)
            try:
                _service(ctx, ctx.db).approve_clean(
                    fresh,
                    suggestion_ids=_server_eligible_suggestion_ids(fresh, ctx.db),
                    review_snapshot_sha256=str(fresh.review_snapshot_sha256),
                    teacher_id=ctx.seeded.teacher.id,
                )
            except BulkEvaluationError as exc:
                ctx.db.rollback()
                approve_refusal = str(exc)
        detail = f"; resume -> ({resumed}, {refusal!r}); approve_clean -> {approve_refusal!r}"
    assert run.status != "stopping", (
        f"a {state} run was stop()ped and is now {run.status!r} "
        f"(stop_requested={run.stop_requested}) although no worker exists to finish it{detail}"
    )


def test_pb5_a_stopping_run_whose_worker_died_is_recoverable_once_its_heartbeat_is_stale(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED half of PB-5: 'stopping' is NOT forever. Recover works after the stale threshold.

    The worker is killed mid-grade, the teacher presses Stop (the heartbeat is still fresh, so
    nothing else can happen yet) and, once the heartbeat is stale, Recover releases the run.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    ctx.provider.inject(Fault("grade", ProcessKilled("simulated kill -9"), on_call=2))
    with pytest.raises(ProcessKilled):
        drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    service = _service(ctx, ctx.db)
    service.stop(service.get_run(ctx.run_id), teacher_id=ctx.seeded.teacher.id)
    assert _run(ctx).status == "stopping"
    age_run_heartbeat(ctx.db, ctx.run_id)  # a worker that is certainly dead: 100000 s
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert resumed, refusal
    assert _run(ctx).stop_requested is False
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert final.status == "review_ready", final
    views = item_views(ctx.db, ctx.run_id)
    assert views[("S002", "Q1")].status == "uncertain"  # the killed call is quarantined, not lost
    assert sum(view.status == "graded" for view in views.values()) == 3


# =========================================================================== PB-6 (read time)
# A healthy worker is inside ONE long page read when the teacher presses Recover.
#
# The bulk unit stamps run.heartbeat_at only when it starts (run_next L664) and when it ends;
# nothing refreshes it during a script read, which is up to pages x one call (the pilot allows
# 1800 s per Qwen call, RQ 3600 s per job: routes/bulk_evaluations.py:65) against a 600 s stale
# threshold (config.py:200) that the web UI duplicates as a hard-coded 10 minutes
# (BulkEvaluationClient.tsx:206), where it shows the 'Recover interrupted run' button.


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP false-stale-recover-pauses-live-worker: resume() treats a run whose heartbeat is "
        "older than 600 s as dead (bulk_evaluation_service.py:731-742), quarantines the "
        "in-flight items and COMMITS status='paused' BEFORE it checks whether it may proceed; "
        "the in-flight page is 'dispatched', so the Recover is then refused (L1581-1584) but the "
        "pause and the quarantine stay. The healthy worker's call lands, run_next sees 'paused' "
        "and returns False, so the self-enqueuing chain dies: the remaining scripts are never "
        "read until the teacher presses Resume a second time, with a misleading 'Interrupted "
        "provider work was quarantined as uncertain' on screen, and the in-flight script's "
        "items carry a spurious provider_contract_failure code."
    ),
)
def test_pb6_a_refused_recover_during_a_healthy_page_read_does_not_stop_the_worker(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    press = RecoverAfter(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    # read call 3 = S002's first page: S001 is done, S002 is in flight, S003 is waiting
    ctx.provider.inject(Fault("read_page", callback=press, on_call=3))
    final = _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(press.error is None, f"the Recover callback itself failed: {press.error!r}")
    assert ctx.provider.counts["read_page"] == 6 and final.status != "paused", (
        f"the healthy worker's chain stopped after the Recover press: run {final.status!r}/"
        f"{final.stage!r} error={final.error!r}; page reads {ctx.provider.counts['read_page']} "
        f"of 6; Recover said resumed={press.resumed} refusal={press.refusal!r}; items "
        f"{_status_table(ctx)}"
    )


def test_pb6_a_recover_during_a_page_read_never_dispatches_the_in_flight_page_twice(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED half of PB-6: the page reservation holds against a false-stale Recover."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    press = RecoverAfter(ctx.run_id, ctx.seeded.teacher.id, settings=ctx.settings)
    ctx.provider.inject(Fault("read_page", callback=press, on_call=3))
    _read_stage(ctx)
    assert press.invocations == 1 and press.error is None
    if _run(ctx).status == "paused":  # today: the refused Recover paused the live worker's chain
        resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
        assert resumed, refusal
        _read_stage(ctx)
    # whichever way the run got finished: every page was read, and billed, exactly once
    reads = Counter(call.image_sha256 for call in ctx.provider.calls_of("read_page"))
    assert ctx.provider.counts["read_page"] == 6
    assert all(count == 1 for count in reads.values()), reads
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert states == ["succeeded"] * 6
    assert _run(ctx).calls_used == 6


# =========================================================================== PB-10 (EXTRA)
# NOT in the brief. The resume routes commit the state change, THEN enqueue, and do not catch an
# enqueue failure (Redis down, e.g. right after a reboot of this machine).

_WORKERLESS_STATUSES = {"queued", "reading", "mapping", "transcribing", "grading"}


@pytest.mark.parametrize("route", ["run", "item"])
def test_pb10_a_queue_failure_on_a_resume_route_does_not_strand_an_active_run(
    route: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if route == "run":
        ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
        url = f"/bulk-evaluation-runs/{ctx.run_id}/resume"
    else:
        ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
        ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=2))
        _read_stage(ctx)
        _gate_and_grade(ctx)
        precondition_faults_fired(ctx.provider)
        resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
        precondition(resumed, f"Resume was refused: {refusal}")
        finished = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
        precondition(finished.status == "review_ready", f"the run must finish: {finished}")
        stranded = [v for v in item_views(ctx.db, ctx.run_id).values() if v.status == "uncertain"]
        precondition(len(stranded) == 1, f"one item must be waiting for a retry: {stranded}")
        url = f"/bulk-evaluation-runs/{ctx.run_id}/items/{stranded[0].item_id}/resume"

    def queue_is_down(_run_id: int, _provider: str) -> None:
        raise RuntimeError("synthetic: Redis connection refused")

    with _api(ctx, monkeypatch):
        monkeypatch.setattr(bulk_routes, "_enqueue", queue_is_down)
        response = TestClient(app, raise_server_exceptions=False).post(url)
    precondition(
        response.status_code >= 400,
        f"the failed enqueue must not look like success: {response.status_code}",
    )
    run = _run(ctx)
    resumed_again, refusal_again = try_resume_run(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings
    )
    assert run.status not in _WORKERLESS_STATUSES, (
        f"{route} resume route: HTTP {response.status_code}, but the run is {run.status!r}/"
        f"{run.stage!r} with no job queued anywhere; a second Resume -> "
        f"({resumed_again}, {refusal_again!r}); items {_status_table(ctx)}"
    )


def test_pb10_a_queue_failure_on_resume_is_a_visible_503_and_a_later_resume_recovers(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The failed enqueue is a visible, retryable 'paused' run and spends no provider call."""

    ctx = _paused_by_a_failed_page_read(db_session, bulk_env, monkeypatch, tmp_path)
    reads = ctx.provider.counts["read_page"]
    url = f"/bulk-evaluation-runs/{ctx.run_id}/resume"

    def queue_is_down(_run_id: int, _provider: str) -> None:
        raise RuntimeError("synthetic: Redis connection refused")

    with _api(ctx, monkeypatch) as api:
        recorder = bulk_routes._enqueue
        monkeypatch.setattr(bulk_routes, "_enqueue", queue_is_down)
        failed = api.client.post(url)
        assert failed.status_code == 503, failed.text[:300]
        assert failed.json()["detail"] == "Bulk evaluation could not be resumed"
        run = _run(ctx)
        assert run.status == "paused", (run.status, run.stage)
        assert "resume manually" in (run.error or ""), run.error
        monkeypatch.setattr(bulk_routes, "_enqueue", recorder)
        again = api.client.post(url)
        assert again.status_code == 200, again.text[:300]
        assert api.enqueued == [ctx.run_id]
    assert _run(ctx).status == "reading"
    assert ctx.provider.counts["read_page"] == reads  # nothing was dispatched by either press


def test_pb10_a_queue_failure_on_item_resume_leaves_an_already_active_run_alone(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retrying one item of a run whose own worker chain is live must not stop that chain."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    ctx.provider.inject(Fault("grade", RuntimeError("synthetic grader 500"), on_call=2))
    _read_stage(ctx)
    _gate_and_grade(ctx)
    precondition_faults_fired(ctx.provider)
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"Resume was refused: {refusal}")
    finished = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(finished.status == "review_ready", f"the run must finish: {finished}")
    stranded = [v for v in item_views(ctx.db, ctx.run_id).values() if v.status == "uncertain"]
    precondition(len(stranded) == 1, f"one item must be waiting for a retry: {stranded}")
    live = _run(ctx)
    live.status = "grading"  # a worker chain is still running; the teacher retries one item
    ctx.db.commit()

    def queue_is_down(_run_id: int, _provider: str) -> None:
        raise RuntimeError("synthetic: Redis connection refused")

    with _api(ctx, monkeypatch) as api:
        monkeypatch.setattr(bulk_routes, "_enqueue", queue_is_down)
        response = api.client.post(
            f"/bulk-evaluation-runs/{ctx.run_id}/items/{stranded[0].item_id}/resume"
        )
    assert response.status_code == 503, response.text[:300]
    run = _run(ctx)
    assert run.status == "grading" and run.error is None, (run.status, run.error)


# =========================================================================== PB-9
# Duplicate execution: two ``run_next`` units on the same run.
#
# The pilot runs ONE sequential SimpleWorker (docs/WINDOWS_TEACHER_PILOT_RUNTIME.md), so units
# never overlap today. Duplicate chains nevertheless exist (PB-4 re-upload enqueue, a Recover
# route enqueue on a falsely stale run (PB-6), a resume_item enqueue), and they become real
# overlap the moment a second worker is started to speed up a 150-script run. These probes
# interleave two real sessions at the exact windows the code leaves open.


def _hook_unit_method(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Ctx,
    method: str,
    *,
    on_call: int,
    before: bool,
) -> dict[str, Any]:
    """Run a complete second unit on another session inside the ``on_call``-th call of ``method``.

    ``before=False`` runs it right AFTER the original returned (the first unit has made its
    selection and is about to act on it with a stale view); ``before=True`` runs it right before
    the original. The inner unit is not hooked again.
    """

    original = getattr(BulkEvaluationService, method)
    state: dict[str, Any] = {"calls": 0, "armed": True, "inner_more": None}

    def wrapper(self: BulkEvaluationService, *args: Any, **kwargs: Any) -> Any:
        state["calls"] += 1
        fire = state["armed"] and state["calls"] == on_call
        if fire and before:
            state["armed"] = False
            state["inner_more"] = _unit_elsewhere(ctx)
        result = original(self, *args, **kwargs)
        if fire and not before:
            state["armed"] = False
            state["inner_more"] = _unit_elsewhere(ctx)
        return result

    monkeypatch.setattr(BulkEvaluationService, method, wrapper)
    return state


def _force_selection(
    monkeypatch: pytest.MonkeyPatch, method: str, forced: dict[str, int | None]
) -> None:
    """While ``forced['id']`` is set, ``method`` returns that item/submission instead of
    selecting: a unit whose selection predates another unit's commit of 'running'."""

    original = getattr(BulkEvaluationService, method)

    def wrapper(self: BulkEvaluationService, *args: Any, **kwargs: Any) -> Any:
        identifier = forced.get("id")
        if identifier is None:
            return original(self, *args, **kwargs)
        if method == "_next_read_submission":
            return identifier
        return self.db.get(BulkEvaluationItem, identifier)

    monkeypatch.setattr(BulkEvaluationService, method, wrapper)


def _collide_with_in_flight_unit(
    ctx: Ctx,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: Literal["read_page", "grade"],
    method: str,
) -> dict[str, Any]:
    """While the first unit is inside its ``kind`` provider call, a second unit starts that
    selected the very same (still 'running') item or script."""

    forced: dict[str, int | None] = {"id": None}
    outcome: dict[str, Any] = {}
    _force_selection(monkeypatch, method, forced)

    def second_unit(record: object) -> None:
        with other_session() as db:
            running = db.scalar(
                select(BulkEvaluationItem).where(
                    BulkEvaluationItem.run_id == ctx.run_id, BulkEvaluationItem.status == "running"
                )
            )
            if running is None:  # no precondition() here: it must not unwind a provider call
                outcome["no_running_item"] = True
                return
            forced["id"] = running.submission_id if kind == "read_page" else running.id
        try:
            outcome["inner_more"] = _unit_elsewhere(ctx)
        finally:
            forced["id"] = None

    ctx.provider.inject(Fault(kind, callback=second_unit, on_call=2))
    return outcome


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP unclaimed-item-selection-duplicates-grading: _next_grading_item is a plain SELECT "
        "of a 'pending' row (bulk_evaluation_service.py:1280-1299) and _process_grading marks it "
        "'running' with an unconditional UPDATE on the objects it loaded (L2227-2229), so two "
        "units that selected before either committed grade the same answer twice. The only "
        "backstop, ux_grading_jobs_active_answer_region, rejects the second job only while the "
        "first is still queued/running: once the first finished, the second creates a NEW job "
        "and pays a second provider call, a second GradeSuggestion, and overwrites the item's "
        "link. LATENT: needs two concurrent workers (the pilot has one SimpleWorker)."
    ),
)
def test_pb9_two_units_that_selected_the_same_pending_item_grade_it_once(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    # unit A selects its item (2nd _next_grading_item call: the first is run_next's dispatch
    # check); unit B then runs completely; A then acts on its stale selection.
    state = _hook_unit_method(monkeypatch, ctx, "_next_grading_item", on_call=2, before=False)
    final = drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(state["inner_more"] is not None, "the second unit never ran")
    precondition(final.status == "review_ready", f"the run must still finish: {final}")
    graded = [(call.students, call.question) for call in ctx.provider.calls_of("grade")]
    suggestions = ctx.db.scalar(select(func.count(GradeSuggestion.id)))
    assert len(graded) == len(set(graded)) == 4 and suggestions == 4, (
        f"{len(graded)} grading calls for {len(set(graded))} distinct answers, {suggestions} "
        f"GradeSuggestions, calls_used={_run(ctx).calls_used}; repeated: "
        f"{sorted(c for c in set(graded) if graded.count(c) > 1)}; "
        f"jobs (region, status) {_jobs(ctx)}"
    )


def test_pb9_a_unit_arriving_after_another_read_the_script_reuses_the_stored_pages(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED (for the window interleaved): reading is protected by the stored-page cache.

    Unit A has selected script S001 and loaded its items; unit B then reads the whole script.
    A carries on with its stale view: no page is billed twice and the ledger is exact.
    """

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    state = _hook_unit_method(
        monkeypatch, ctx, "_record_page_read_call_baseline", on_call=1, before=True
    )
    _read_stage(ctx)
    assert state["inner_more"] is not None
    assert ctx.provider.counts["read_page"] == 4  # 2 scripts x 2 pages, each billed once
    assert _run(ctx).calls_used == 4
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert states == ["succeeded"] * 4


def test_pb9_two_units_on_different_scripts_keep_one_consistent_ledger(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: a second unit that starts while the first is inside a page read takes the NEXT
    script (the first one's items are 'running'); calls_used equals the provider's calls."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    ran: list[bool] = []
    ctx.provider.inject(
        Fault("read_page", callback=lambda _r: ran.append(_unit_elsewhere(ctx)), on_call=1)
    )
    _read_stage(ctx)
    assert len(ran) == 1
    assert ctx.provider.counts["read_page"] == 6  # 3 scripts x 2 pages
    assert _run(ctx).calls_used == 6
    assert ctx.db.scalars(select(ScriptPageTranscript.state)).all() == ["succeeded"] * 6


def test_pb9_a_colliding_second_unit_never_bills_a_page_twice(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED (billing): a second unit that selected the script the first is reading is refused
    by the page reservation ('page 2 is already reserved'); no extra provider call is made."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    outcome = _collide_with_in_flight_unit(
        ctx, monkeypatch, kind="read_page", method="_next_read_submission"
    )
    _read_stage(ctx)
    precondition(outcome.get("inner_more") is not None, "the colliding unit never ran")
    reads = [call.image_sha256 for call in ctx.provider.calls_of("read_page")]
    assert len(reads) == len(set(reads)) == ctx.provider.counts["read_page"]  # no page twice
    states = ctx.db.scalars(select(ScriptPageTranscript.state)).all()
    assert states and set(states) == {"succeeded"}, states


def test_pb9_a_colliding_second_unit_never_bills_an_answer_twice_while_the_first_is_running(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED (billing): while the first unit's job is 'running', the unique index refuses the
    second unit's INSERT; no extra grading call and no second suggestion is made."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    _read_stage(ctx)
    _gate(ctx)
    outcome = _collide_with_in_flight_unit(
        ctx, monkeypatch, kind="grade", method="_next_grading_item"
    )
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    precondition(outcome.get("inner_more") is not None, "the colliding unit never ran")
    graded = [(call.students, call.question) for call in ctx.provider.calls_of("grade")]
    assert len(graded) == len(set(graded)), graded  # no answer graded twice
    assert ctx.db.scalar(select(func.count(GradeSuggestion.id))) == len(set(graded))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP failure-handler-quarantines-other-units-items: the defences against a second "
        "worker (the page reservation 'sees the claim', uq_script_transcript_submission_"
        "settings, ux_grading_jobs_active_answer_region) surface as exceptions that run_next's "
        "generic handler (bulk_evaluation_service.py:692-702) turns into rollback + "
        "_mark_running_uncertain(run) + _pause. _mark_running_uncertain (L2438-2456) flags EVERY "
        "'running' item of the run, not just the failing unit's, so the LOSER of a collision "
        "stamps provider_contract_failure on the WINNER's script although all of its pages "
        "were read and stored successfully (and, for a grade, on its in-flight item: see "
        "late-landing-grade-keeps-uncertain-code). Two workers started on a fresh run "
        "reproduce this on the very first unit (also: run paused with a raw UniqueViolation / "
        "'already reserved' text in run.error, both chains stopped; pausing is a defensible "
        "policy and is NOT what this asserts). LATENT: needs two concurrent workers."
    ),
)
def test_pb9_a_second_workers_collision_does_not_flag_the_first_workers_finished_script(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import threading

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=3)
    barrier = threading.Barrier(2)
    guard = threading.Lock()
    selections = {"n": 0}
    first_unit_done = threading.Event()
    original = BulkEvaluationService._next_read_submission

    def synchronised(self: BulkEvaluationService, run: BulkEvaluationRun) -> int | None:
        chosen = original(self, run)
        with guard:
            selections["n"] += 1
            rendezvous = selections["n"] <= 4  # both threads' dispatch check and processing pick
        if rendezvous:
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                pass
        return chosen

    monkeypatch.setattr(BulkEvaluationService, "_next_read_submission", synchronised)
    # whichever worker reaches the provider first waits until the other one's first unit ended
    ctx.provider.inject(
        Fault("read_page", callback=lambda _r: first_unit_done.wait(timeout=10), on_call=1)
    )
    failures: list[str] = []

    def worker() -> None:
        try:
            for _ in range(60):
                with SessionLocal() as session:
                    more = _service(ctx, session).run_next(ctx.run_id)
                first_unit_done.set()
                if not more:
                    break
        except BaseException as exc:  # noqa: BLE001 - a thread must report, not die silently
            failures.append(repr(exc))
            first_unit_done.set()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    precondition(not any(thread.is_alive() for thread in threads), "a worker thread hung")
    precondition(not failures, f"a worker raised: {failures}")
    run = _run(ctx)
    pages = ctx.db.execute(
        select(Submission.student_identifier, ScriptPageTranscript.state)
        .join(ScriptTranscript, ScriptTranscript.submission_id == Submission.id)
        .join(
            ScriptPageTranscript, ScriptPageTranscript.script_transcript_id == ScriptTranscript.id
        )
    ).all()
    fully_read = sorted(
        {student for student, _state in pages}
        - {student for student, state in pages if state != "succeeded"}
    )
    precondition(fully_read, f"no script was read completely: {pages}")
    views = item_views(ctx.db, ctx.run_id)
    flagged = sorted(
        key
        for key, view in views.items()
        if key[0] in fully_read and "provider_contract_failure" in view.codes
    )
    assert not flagged, (
        f"scripts {fully_read} were read completely (every page 'succeeded', provider calls "
        f"{ctx.provider.counts['read_page']}) yet items {flagged} carry provider_contract_failure; "
        f"run {run.status!r}/{run.stage!r} calls_used={run.calls_used} "
        f"error={(run.error or '')[:120]!r}; items {_status_table(ctx)}"
    )


# =========================================================================== PB-7 (policy pin)


def test_pb7_policy_a_stopped_cohort_cannot_be_imported_again_into_the_same_assessment(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY (pins the dead end's second wall): once a run is stopped, a fresh authorization
    for the same cohort cannot be created in the same assessment.

    ``create_from_zip`` reuses a run only for the active statuses; for a ``stopped`` one it falls
    through to ``_reject_existing_identifiers`` (bulk_evaluation_service.py:572-592), a
    deliberate guard whose message sends the teacher to 'a separate assessment'. Together with
    the fact that no code raises ``authorized_call_limit`` it is what turns the budget exhaustion
    of ``test_pb7_a_run_that_runs_out_of_calls_has_a_way_forward`` into a dead end.
    """

    ctx = _budget_exhausted_mid_run(db_session, bulk_env, monkeypatch, tmp_path)
    service = _service(ctx, ctx.db)
    service.stop(service.get_run(ctx.run_id), teacher_id=ctx.seeded.teacher.id)
    drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)
    assert _run(ctx).status == "stopped"
    with _api(ctx, monkeypatch) as api:
        again = api.upload(maximum_provider_calls=40)
    assert again.status_code == 409, again.text[:300]
    assert "already exist" in again.json()["detail"]
    assert "separate assessment" in again.json()["detail"]


# =========================================================================== RC-56/RC-57
# Worker start and launcher guards.


def test_worker_start_pauses_an_active_run_whose_worker_died_and_leaves_a_live_one_alone(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """RC-57: after a reboot or a worker restart a run no longer looks busy forever."""

    from app.services.bulk_run_guard import active_bulk_run_ids, reconcile_interrupted_bulk_runs

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2)
    fresh = _start(db_session, bulk_env, monkeypatch, tmp_path / "fresh", students=2)
    precondition(
        set(active_bulk_run_ids()) >= {ctx.run_id, fresh.run_id}, "both runs must be active"
    )
    run = ctx.db.get(BulkEvaluationRun, ctx.run_id)
    assert run is not None
    run.status = "reading"
    item = run.items[0]
    item.status = "running"
    ctx.db.commit()
    age_run_heartbeat(ctx.db, ctx.run_id)

    paused = reconcile_interrupted_bulk_runs(bulk_env)
    assert ctx.run_id in paused and fresh.run_id not in paused
    stale = _run(ctx)
    assert stale.status == "paused"
    assert "worker stopped" in (stale.error or "")
    assert ctx.db.get(BulkEvaluationItem, item.id).status == "uncertain"
    ctx.db.expire_all()
    live = ctx.db.get(BulkEvaluationRun, fresh.run_id)
    assert live is not None and live.status == "queued"
    assert ctx.run_id not in active_bulk_run_ids()


def test_the_worker_reconciles_interrupted_runs_before_it_takes_a_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import run as worker_run

    calls: list[str] = []

    class FakeWorker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append("init")

        def work(self, **kwargs: Any) -> None:
            calls.append("work")

    monkeypatch.setattr(
        worker_run, "reconcile_interrupted_bulk_runs", lambda: calls.append("reconcile")
    )
    monkeypatch.setattr(worker_run, "get_worker_class", lambda platform_name=None: FakeWorker)
    monkeypatch.setattr(worker_run, "get_default_queue", lambda: object())
    monkeypatch.setattr(worker_run, "get_redis_client", lambda: object())
    worker_run.main()
    assert calls == ["reconcile", "init", "work"]


def test_a_failing_reconcile_does_not_keep_the_worker_from_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import run as worker_run

    calls: list[str] = []

    def broken() -> None:
        raise RuntimeError("database down")

    class FakeWorker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def work(self, **kwargs: Any) -> None:
            calls.append("work")

    monkeypatch.setattr(worker_run, "reconcile_interrupted_bulk_runs", broken)
    monkeypatch.setattr(worker_run, "get_worker_class", lambda platform_name=None: FakeWorker)
    monkeypatch.setattr(worker_run, "get_default_queue", lambda: object())
    monkeypatch.setattr(worker_run, "get_redis_client", lambda: object())
    worker_run.main()
    assert calls == ["work"]


def test_the_launcher_leaves_the_worker_and_model_alone_during_an_active_bulk_run() -> None:
    """RC-56 (static): Start-TeacherPilot.ps1 checks for an active run before it stops the
    model phases or the worker, and only an explicit switch overrides that."""

    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "pilot" / "Start-TeacherPilot.ps1"
    ).read_text(encoding="utf-8")
    assert "[switch]$AllowRestartDuringBulkRun" in script
    assert "active_bulk_run_ids" in script
    guard = script.index("$protectBulkRun = ")
    assert guard < script.index("foreach ($mode in @(\"PaddleOcr\", \"Qwen\", \"Qwen38\"))")
    assert "-not $protectBulkRun" in script[script.index("if ($backendRuntimeStale)") :]
