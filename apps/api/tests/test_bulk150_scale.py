"""Scale and capacity probes for the Bulk Supervised pipeline (fake provider, pipeline OVERHEAD).

WHAT IS MEASURED: the cost of everything the product does around the model: ZIP intake, page
persistence, the per-script transcript store, the teacher gate, the per-item resume, the grading
bookkeeping, the aggregate reads the UI polls, approval and export. The provider is the in-process
fake, so a "read" or a "grade" costs microseconds here.

WHAT IS NOT MEASURED (read this before quoting a number): the wall-clock of the real model. A
real run spends its time inside 600 page reads and 900 grading calls on one llama.cpp slot, i.e.
tens of seconds each; the per-unit overhead measured here is an ADDITIVE floor, not a forecast.
Synthetic pages are 480x640 mostly-white PNGs, so disk and RSS figures are a floor too (real
scans are one to two orders of magnitude larger).

Run the heavy scenarios with ``TA_BULK150_SCALE=1`` (they are skipped otherwise, so the normal
suite stays fast). ``TA_BULK150_STUDENTS`` overrides the headline cohort size (default 150) and
``TA_BULK150_METRICS=<file>`` appends every metrics line to that file as it is produced, so a run
that is killed still leaves its partial measurements behind. Every metrics line is a single
``BULK150_SCALE {json}`` line on stdout (use ``--capture=no`` to see it).

Reproduce the headline run::

    $env:TA_BULK150_SCALE = '1'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_api_tests.ps1 -Key pe \
        --capture=no \
        "tests/test_bulk150_scale.py::test_headline_150_students_x_4_pages_x_6_questions"

Wall-clock is NEVER asserted. The deterministic quantities that are (statement counts, rows read
per unit, call budgets, final item states, ledger agreement) are.

Sections: the measurement rig and the 150-student headline run, the N-scaling curve and the PDF
variant (all ``TA_BULK150_SCALE=1``); the deterministic cost-model pin; capacity boundaries (page
cap, submission cap, archive bytes, call-budget arithmetic and ceilings, limit sources, the
UI/server ceiling mismatch); an authorisation that is too small (grading and reading stage, the
dead end that follows, stop, exact budget); and a worker killed BETWEEN units (6 students in the
fast suite, 30 behind the guard). Known defects are strict ``GAP`` xfails; behaviour that is a
product decision is pinned by a passing test.

Run everything heavy, in one invocation (about 8 minutes, nothing else may use the same key)::

    $env:TA_BULK150_SCALE = '1'
    $env:TA_BULK150_METRICS = '<file>.jsonl'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_api_tests.ps1 -Key pe -q -rA \
        --capture=no \
        "tests/test_bulk150_scale.py::test_headline_150_students_x_4_pages_x_6_questions" \
        "tests/test_bulk150_scale.py::test_scaling_curve_point" \
        "tests/test_bulk150_scale.py::test_pdf_layout_30_students_x_4_pages_x_6_questions" \
        "tests/test_bulk150_scale.py::test_a_worker_killed_between_units_converges_to_the_uninterrupted_result_30_students"
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import threading
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from app.api.routes.bulk_evaluations import (
    download_bulk_results,
    list_bulk_evaluation_exceptions,
    list_bulk_evaluation_runs,
    read_bulk_evaluation_run,
)
from app.core.config import Settings
from app.db.session import SessionLocal, engine
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    AnswerRegion,
    AuditLog,
    BulkEvaluationItem,
    BulkEvaluationRun,
    GradeSuggestion,
    GradingJob,
    Question,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
)
from app.schemas import BulkEvaluationRunRead
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from tests.bulk150_harness import (  # noqa: F401
    CLEANUP_MODELS,
    Corpus,
    DrainResult,
    FakeBulkBrainProvider,
    HarnessError,
    ItemView,
    ProcessKilled,
    Seeded,
    age_run_heartbeat,
    assert_every_answered_question_graded,
    assert_no_cross_student_evidence,
    assert_no_final_grades,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    drain,
    harness_storage,
    import_zip,
    install_fake_brain,
    item_views,
    make_settings,
    precondition,
    read_lease,
    register_stored_pages,
    resume_all_items,
    review_all_transcripts,
    seed_assessment,
    set_authorised_limit,
    try_resume_run,
)

SCALE_ENABLED = os.environ.get("TA_BULK150_SCALE") == "1"
_EXHAUSTED_REFUSAL = (
    "The authorised call limit is exhausted; raise this run's call limit, then resume"
)
scale_only = pytest.mark.skipif(
    not SCALE_ENABLED, reason="heavy scale scenario: set TA_BULK150_SCALE=1 to run it"
)
HEADLINE_STUDENTS = int(os.environ.get("TA_BULK150_STUDENTS", "150"))
METRICS_FILE = os.environ.get("TA_BULK150_METRICS")


# --------------------------------------------------------------------------- measurement


def emit(tag: str, **fields: Any) -> None:
    """One machine-readable metrics line (stdout, and ``TA_BULK150_METRICS`` when set)."""

    line = "BULK150_SCALE " + json.dumps({"tag": tag, **fields}, default=str, sort_keys=True)
    print(line, flush=True)
    if METRICS_FILE:
        with open(METRICS_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class SqlCounter:
    """Counts statements, their time and the rows SELECTs returned on the application engine."""

    def __init__(self) -> None:
        self.statements = 0
        self.seconds = 0.0
        self.select_rows = 0
        self.selects = 0

    def _before(self, conn: Any, *_args: Any) -> None:
        conn.info.setdefault("bulk150_t0", []).append(time.perf_counter())

    def _after(self, conn: Any, cursor: Any, statement: str, *_args: Any) -> None:
        started = conn.info["bulk150_t0"].pop()
        self.seconds += time.perf_counter() - started
        self.statements += 1
        if statement.lstrip()[:6].upper() == "SELECT":
            self.selects += 1
            rowcount = cursor.rowcount
            if isinstance(rowcount, int) and rowcount > 0:
                self.select_rows += rowcount

    def __enter__(self) -> SqlCounter:
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(engine, "before_cursor_execute", self._before)
        event.remove(engine, "after_cursor_execute", self._after)

    def snapshot(self) -> tuple[int, float, int, int]:
        return self.statements, self.seconds, self.select_rows, self.selects


def _current_rss() -> int:
    """Resident set size of this process in bytes, or 0 when ``psutil`` is not installed.

    ``psutil`` is not a declared dependency of ``apps/api`` (not in ``[project.optional-
    dependencies].dev``), so it is imported lazily: a missing module must not turn into a
    collection error that fails the whole suite in CI. RSS is a reported metric only.
    """

    try:
        import psutil
    except ImportError:
        return 0
    return int(psutil.Process().memory_info().rss)


class RssSampler:
    """Peak resident set size of THIS process while the block runs (50 ms sampling thread).

    Reports 0 for every figure when ``psutil`` is unavailable (see :func:`_current_rss`).
    """

    def __init__(self, interval: float = 0.05) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.start = 0
        self.peak = 0
        self.end = 0

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.peak = max(self.peak, _current_rss())

    def __enter__(self) -> RssSampler:
        self.start = self.peak = _current_rss()
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.end = _current_rss()
        self.peak = max(self.peak, self.end)


def dir_bytes(root: Path) -> int:
    total = 0
    for current, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
    return total


TABLES: dict[str, Any] = {
    "submissions": Submission,
    "submission_pages": SubmissionPage,
    "bulk_items": BulkEvaluationItem,
    "script_transcripts": ScriptTranscript,
    "page_transcripts": ScriptPageTranscript,
    "blocks": ScriptTranscriptBlock,
    "assignments": AnswerEvidenceAssignment,
    "spans": AnswerEvidenceSpan,
    "answer_regions": AnswerRegion,
    "grading_jobs": GradingJob,
    "suggestions": GradeSuggestion,
    "audit_logs": AuditLog,
}


def table_counts() -> dict[str, int]:
    session = SessionLocal()
    try:
        return {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in TABLES.items()
        }
    finally:
        session.close()


def mib(value: float) -> float:
    return round(value / (1024 * 1024), 3)


class PhaseMeter:
    """Wall time, SQL, peak RSS and disk growth per named phase, emitted as it finishes."""

    def __init__(self, sql: SqlCounter, storage_root: Path, scenario: str) -> None:
        self.sql = sql
        self.storage_root = storage_root
        self.scenario = scenario
        self.phases: dict[str, dict[str, Any]] = {}

    @contextmanager
    def measure(self, name: str, **extra: Any) -> Iterator[dict[str, Any]]:
        record: dict[str, Any] = dict(extra)
        before_sql = self.sql.snapshot()
        before_disk = dir_bytes(self.storage_root)
        started = time.perf_counter()
        with RssSampler() as rss:
            yield record
        wall = time.perf_counter() - started
        after_sql = self.sql.snapshot()
        record.update(
            wall_s=round(wall, 3),
            statements=after_sql[0] - before_sql[0],
            sql_s=round(after_sql[1] - before_sql[1], 3),
            select_rows=after_sql[2] - before_sql[2],
            rss_start_mib=mib(rss.start),
            rss_peak_mib=mib(rss.peak),
            rss_end_mib=mib(rss.end),
            disk_written_mib=mib(dir_bytes(self.storage_root) - before_disk),
        )
        self.phases[name] = record
        emit("phase", scenario=self.scenario, phase=name, **record)


@dataclass
class UnitRecord:
    index: int
    seconds: float
    statements: int
    select_rows: int
    kind: str


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))]


def _slope(values: list[float]) -> float:
    """Least-squares slope of ``values`` against their index."""

    count = len(values)
    if count < 2:
        return 0.0
    mean_x = (count - 1) / 2
    mean_y = sum(values) / count
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(range(count), values, strict=True))
    return numerator / sum((x - mean_x) ** 2 for x in range(count))


def _quartile_ratio(values: list[float]) -> float | None:
    """Mean of the last quarter over the mean of the first quarter (1.0 = no drift)."""

    quarter = len(values) // 4
    if quarter < 1:
        return None
    first = sum(values[:quarter]) / quarter
    last = sum(values[-quarter:]) / quarter
    return round(last / first, 3) if first else None


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 5),
        "p50": round(_percentile(ordered, 0.5), 5),
        "p95": round(_percentile(ordered, 0.95), 5),
        "max": round(ordered[-1], 5),
        "sum": round(sum(values), 3),
    }


def summarize_units(units: list[UnitRecord]) -> dict[str, Any]:
    seconds = [unit.seconds for unit in units]
    statements = [float(unit.statements) for unit in units]
    rows = [float(unit.select_rows) for unit in units]
    return {
        "units": len(units),
        "seconds": stats(seconds),
        "slope_ms_per_unit": round(_slope(seconds) * 1000, 5),
        "q4_over_q1_seconds": _quartile_ratio(seconds),
        "statements": stats(statements),
        "select_rows": stats(rows),
        "q4_over_q1_select_rows": _quartile_ratio(rows),
    }


@dataclass
class TimedDrain:
    result: DrainResult
    units: list[UnitRecord] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[UnitRecord]:
        return [unit for unit in self.units if unit.kind == kind]


def timed_drain(
    run_id: int,
    *,
    settings: Settings,
    provider: FakeBulkBrainProvider,
    sql: SqlCounter,
    max_units: int | None = None,
    after_unit: Callable[[int, UnitRecord], None] | None = None,
) -> TimedDrain:
    """The harness ``drain`` loop (fresh session per unit) with per-unit measurements.

    ``after_unit(units_done, record)`` runs BETWEEN units, after the unit committed and its
    session closed; raising :class:`ProcessKilled` from it models a worker that dies at a unit
    boundary (never mid-call).
    """

    storage = harness_storage(settings)
    sizing = SessionLocal()
    try:
        sized = sizing.get(BulkEvaluationRun, run_id)
        if sized is None:
            raise HarnessError(f"run {run_id} does not exist")
        limit = max_units or (sized.total_items * 2 + sized.total_submissions + 10)
    finally:
        sizing.close()
    units: list[UnitRecord] = []
    started = time.perf_counter()
    while True:
        if len(units) >= limit:
            raise HarnessError(f"run {run_id} did not settle within {limit} units")
        before_counts = dict(provider.counts)
        before_sql = sql.snapshot()
        session = SessionLocal()
        t0 = time.perf_counter()
        try:
            more = BulkEvaluationService(session, settings=settings, storage=storage).run_next(
                run_id
            )
        finally:
            session.close()
        elapsed = time.perf_counter() - t0
        after_sql = sql.snapshot()
        delta = {kind: provider.counts[kind] - before_counts[kind] for kind in before_counts}
        kind = next((name for name in ("read_page", "map", "grade") if delta[name]), "other")
        record = UnitRecord(
            index=len(units),
            seconds=elapsed,
            statements=after_sql[0] - before_sql[0],
            select_rows=after_sql[2] - before_sql[2],
            kind=kind,
        )
        units.append(record)
        if after_unit is not None:
            after_unit(len(units), record)
        if not more:
            break
    seconds = time.perf_counter() - started
    check = SessionLocal()
    try:
        run = check.get(BulkEvaluationRun, run_id)
        if run is None:
            raise HarnessError(f"run {run_id} vanished while it was being drained")
        result = DrainResult(
            units=len(units),
            seconds=seconds,
            status=run.status,
            stage=run.stage,
            calls_used=run.calls_used,
            authorized_call_limit=run.authorized_call_limit,
            error=run.error,
            provider_counts=provider.counts,
            harness_errors=tuple(provider.harness_errors),
        )
    finally:
        check.close()
    return TimedDrain(result=result, units=units)


def _submission_ids(db: Session, assessment_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Submission.id)
            .where(Submission.assessment_id == assessment_id)
            .order_by(Submission.id)
        ).all()
    )


def timed_gate(
    db: Session,
    run_id: int,
    seeded: Seeded,
    sql: SqlCounter,
) -> tuple[list[UnitRecord], dict[int, str], int]:
    """The teacher gate, one submission at a time, through the real route functions."""

    units: list[UnitRecord] = []
    refused: dict[int, str] = {}
    confirmed = 0
    for index, submission_id in enumerate(_submission_ids(db, seeded.assessment.id)):
        before = sql.snapshot()
        t0 = time.perf_counter()
        outcome = review_all_transcripts(
            db, run_id, seeded.teacher, only_submissions=[submission_id]
        )
        elapsed = time.perf_counter() - t0
        after = sql.snapshot()
        units.append(UnitRecord(index, elapsed, after[0] - before[0], after[2] - before[2], "gate"))
        refused.update(outcome.refused)
        confirmed += len(outcome.confirmed)
    return units, refused, confirmed


def timed_resume_items(
    run_id: int, seeded: Seeded, settings: Settings, sql: SqlCounter
) -> tuple[list[UnitRecord], dict[int, str]]:
    """Resume every held item the way the UI does: one request (fresh session) per item.

    Each request loads the run with ALL its items (the route's ``_owned_run``) and then
    resumes one item, which is what the "2. Resume Qn grading" button triggers.
    """

    storage = harness_storage(settings)
    lister = SessionLocal()
    try:
        item_ids = list(
            lister.scalars(
                select(BulkEvaluationItem.id)
                .where(
                    BulkEvaluationItem.run_id == run_id,
                    BulkEvaluationItem.status.in_(("exception", "uncertain")),
                    BulkEvaluationItem.stage == "read",
                )
                .order_by(BulkEvaluationItem.id)
            ).all()
        )
    finally:
        lister.close()
    units: list[UnitRecord] = []
    refused: dict[int, str] = {}
    for index, item_id in enumerate(item_ids):
        before = sql.snapshot()
        session = SessionLocal()
        t0 = time.perf_counter()
        try:
            service = BulkEvaluationService(session, settings=settings, storage=storage)
            run = service.get_run(run_id)
            item = session.get(BulkEvaluationItem, item_id)
            if item is None:
                raise HarnessError(f"item {item_id} vanished")
            try:
                service.resume_item(run, item, teacher_id=seeded.teacher.id)
            except BulkEvaluationError as exc:
                session.rollback()
                refused[item_id] = str(exc)
        finally:
            session.close()
        elapsed = time.perf_counter() - t0
        after = sql.snapshot()
        units.append(
            UnitRecord(index, elapsed, after[0] - before[0], after[2] - before[2], "resume")
        )
    return units, refused


def aggregate_reads(run_id: int, seeded: Seeded, sql: SqlCounter, *, label: str) -> dict[str, Any]:
    """Time the reads the UI polls: run read (+ serialisation), /exceptions, snapshot hash."""

    out: dict[str, Any] = {}

    def timed(name: str, call: Callable[[Session], Any]) -> Any:
        session = SessionLocal()
        before = sql.snapshot()
        t0 = time.perf_counter()
        try:
            value = call(session)
        finally:
            session.close()
        after = sql.snapshot()
        out[name] = {
            "s": round(time.perf_counter() - t0, 4),
            "statements": after[0] - before[0],
            "select_rows": after[2] - before[2],
        }
        return value

    def read_run(session: Session) -> int:
        run = read_bulk_evaluation_run(run_id, session, seeded.teacher)
        return len(BulkEvaluationRunRead.model_validate(run).model_dump_json())

    out["run_read_json_bytes"] = timed("GET_run", read_run)

    def list_runs(session: Session) -> int:
        """The UI's 5-second poll while a run is active: every run WITH all its items."""

        rows = list_bulk_evaluation_runs(seeded.assessment.id, session, seeded.teacher)
        return sum(len(BulkEvaluationRunRead.model_validate(r).model_dump_json()) for r in rows)

    out["list_runs_json_bytes"] = timed("GET_assessment_runs_poll", list_runs)
    exceptions = timed(
        "GET_exceptions", lambda s: list_bulk_evaluation_exceptions(run_id, s, seeded.teacher)
    )
    out["exceptions_listed"] = len(exceptions)

    def snapshot(session: Session) -> str:
        service = BulkEvaluationService(session)
        return service.review_snapshot_hash(service.get_run(run_id))

    timed("review_snapshot_hash", snapshot)
    emit("aggregate_reads", label=label, **out)
    return out


# --------------------------------------------------------------------------- scenario runner


def item_digest(views: dict[tuple[str, str], ItemView]) -> str:
    """Stable fingerprint of every item's outcome (ids excluded, they differ between runs)."""

    rows = sorted(
        (v.student, v.question, v.status, v.stage, list(v.codes), v.provider_calls)
        for v in views.values()
    )
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()[:16]


@dataclass
class Scenario:
    students: int
    pages: int
    questions: int
    layout: str
    seeded: Seeded
    corpus: Corpus
    provider: FakeBulkBrainProvider
    settings: Settings
    run_id: int
    meter: PhaseMeter
    read: TimedDrain | None = None
    grade: TimedDrain | None = None
    gate_units: list[UnitRecord] = field(default_factory=list)
    resume_units: list[UnitRecord] = field(default_factory=list)
    digest: str = ""
    summary: dict[str, Any] = field(default_factory=dict)


def run_scenario(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    students: int,
    pages: int = 4,
    questions: int = 6,
    layout: str = "images",
    slack: int = 2,
    approve: bool = True,
    name: str | None = None,
    managed_local: bool = False,
) -> Scenario:
    """The whole real pipeline with every phase measured, then the end-state assertions."""

    scenario_name = name or f"{layout}-{students}x{pages}x{questions}"
    storage_root = Path(bulk_env.local_storage_root)
    with SqlCounter() as sql:
        meter = PhaseMeter(sql, storage_root, scenario_name)
        seeded = seed_assessment(db, questions=questions)

        t0 = time.perf_counter()
        corpus = build_zip(
            tmp_path / f"{scenario_name}.zip",
            students=students,
            pages=pages,
            questions=questions,
            layout=layout,  # type: ignore[arg-type]
        )
        corpus_build_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        corpus.pixel_owners()  # warm the oracle so register_stored_pages does not pay for it
        pixel_oracle_s = time.perf_counter() - t0
        budget = corpus.call_budget()
        limit = budget + slack
        emit(
            "corpus",
            scenario=scenario_name,
            students=students,
            pages_per_student=pages,
            questions=questions,
            layout=layout,
            total_pages=corpus.total_pages,
            items=students * questions,
            call_budget=budget,
            authorized_limit=limit,
            zip_mib=mib(corpus.archive_path.stat().st_size),
            harness_corpus_build_s=round(corpus_build_s, 2),
            harness_pixel_identity_s=round(pixel_oracle_s, 2),
        )
        provider = FakeBulkBrainProvider(
            corpus, managed_local_phase="Qwen38" if managed_local else None
        )
        install_fake_brain(monkeypatch, provider, bulk_env)

        with meter.measure("intake"):
            run = import_zip(
                db,
                seeded=seeded,
                corpus=corpus,
                provider=provider,
                settings=bulk_env,
                maximum_provider_calls=limit,
                register=False,
            )
        run_id = run.id
        precondition(
            (run.total_submissions, run.total_pages, run.total_items)
            == (students, corpus.total_pages, students * questions),
            f"intake counted {run.total_submissions}/{run.total_pages}/{run.total_items}",
        )
        with meter.measure("register_pages_harness_only") as record:
            record["pages"] = register_stored_pages(
                db, provider, corpus, seeded.assessment.id, settings=bulk_env
            )

        scenario = Scenario(
            students, pages, questions, layout, seeded, corpus, provider, bulk_env, run_id, meter
        )
        with meter.measure("drain_read") as record:
            scenario.read = timed_drain(run_id, settings=bulk_env, provider=provider, sql=sql)
            record["status"] = scenario.read.result.status
            record["units"] = scenario.read.result.units
            record["unit_summary"] = summarize_units(scenario.read.units)
        precondition(
            scenario.read.result.status == "completed_with_exceptions",
            f"the read stage must end held for the gate: {scenario.read.result}",
        )
        scenario.summary["counts_after_read"] = table_counts()
        scenario.summary["aggregate_after_read"] = aggregate_reads(
            run_id, seeded, sql, label="after_read_all_items_held"
        )

        with meter.measure("teacher_gate") as record:
            gate_units, refused, confirmed = timed_gate(db, run_id, seeded, sql)
            record["confirmed"] = confirmed
            record["unit_summary"] = summarize_units(gate_units)
        scenario.gate_units = gate_units
        precondition(not refused, f"the teacher gate refused: {dict(list(refused.items())[:3])}")

        with meter.measure("resume_items") as record:
            resume_units, resume_refused = timed_resume_items(run_id, seeded, bulk_env, sql)
            record["items"] = len(resume_units)
            record["unit_summary"] = summarize_units(resume_units)
        scenario.resume_units = resume_units
        precondition(
            not resume_refused, f"resume refused: {dict(list(resume_refused.items())[:3])}"
        )

        with meter.measure("drain_grade") as record:
            scenario.grade = timed_drain(run_id, settings=bulk_env, provider=provider, sql=sql)
            record["status"] = scenario.grade.result.status
            record["units"] = scenario.grade.result.units
            record["unit_summary"] = summarize_units(scenario.grade.units)
        scenario.summary["aggregate_after_grade"] = aggregate_reads(
            run_id, seeded, sql, label="after_grading_review_ready"
        )
        scenario.summary["counts_final"] = table_counts()

        verify_scenario(db, scenario, meter)
        if approve:
            approve_and_export(db, scenario, meter)
        emit(
            "summary",
            scenario=scenario_name,
            digest=scenario.digest,
            phases={key: value["wall_s"] for key, value in meter.phases.items()},
            peak_rss_mib=max(value["rss_peak_mib"] for value in meter.phases.values()),
            counts_final=scenario.summary["counts_final"],
            total_statements=sql.statements,
            calls=provider.counts,
        )
    return scenario


def verify_scenario(db: Session, scenario: Scenario, meter: PhaseMeter) -> None:
    """End-state assertions of the headline scenario (deterministic, no wall-clock)."""

    corpus, provider, run_id = scenario.corpus, scenario.provider, scenario.run_id
    assert scenario.grade is not None and scenario.read is not None
    final = scenario.grade.result
    assert final.status == "review_ready", final
    assert not final.harness_errors, final.harness_errors
    with meter.measure("verify_item_views_harness_only"):
        views = item_views(db, run_id)
    assert len(views) == scenario.students * scenario.questions
    # every item graded (every question is answered in this corpus) or explained
    assert_every_answered_question_graded(corpus, views)
    scenario.digest = item_digest(views)
    per_student: dict[str, set[str]] = {}
    for (student, _question), view in views.items():
        per_student.setdefault(student, set()).add(view.status)
    assert all(statuses == {"graded"} for statuses in per_student.values()), {
        s: st for s, st in per_student.items() if st != {"graded"}
    }
    db.expire_all()
    run = db.get(BulkEvaluationRun, run_id)
    assert run is not None
    assert (run.clean_item_count, run.exception_count, run.processed_items) == (
        len(views),
        0,
        len(views),
    )
    # the ledger equals what the provider really served, inside the authorisation
    assert run.calls_used == provider.total_calls == corpus.call_budget()
    assert provider.total_calls <= run.authorized_call_limit
    assert provider.counts["read_page"] == corpus.total_pages
    reads = Counter(call.image_sha256 for call in provider.calls_of("read_page"))
    assert max(reads.values()) == 1, "a page image was read more than once"
    with meter.measure("verify_cross_student_harness_only") as record:
        record["evidence_texts_inspected"] = assert_no_cross_student_evidence(
            db, run_id, corpus=corpus, provider=provider
        )
    assert_no_final_grades(db, run_id)


def approve_and_export(db: Session, scenario: Scenario, meter: PhaseMeter) -> None:
    run_id, seeded = scenario.run_id, scenario.seeded
    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=scenario.settings)
        run = service.get_run(run_id)
        snapshot = service.review_snapshot_hash(run)
        suggestion_ids = [
            int(item.grade_suggestion_id)
            for item in run.items
            if item.status == "graded" and item.grade_suggestion_id is not None
        ]
        with meter.measure("approve_clean") as record:
            approved, already, _ = service.approve_clean(
                run,
                suggestion_ids=suggestion_ids,
                review_snapshot_sha256=snapshot,
                teacher_id=seeded.teacher.id,
            )
            record["approved"] = approved
        assert (approved, already) == (len(suggestion_ids), 0)
        with meter.measure("export_workbook") as record:
            workbook = service.build_results_workbook(service.get_run(run_id))
            record["xlsx_kib"] = round(len(workbook) / 1024, 1)
        refreshed = service.get_run(run_id)
        assert refreshed.status == "completed"
        assert refreshed.approved_count == len(suggestion_ids)
    finally:
        session.close()


def purge_database(db: Session) -> None:
    """Empty every table between sizes of a curve (the fixture only cleans around the test)."""

    db.rollback()
    for model in CLEANUP_MODELS:
        db.execute(delete(model))
    db.commit()


# --------------------------------------------------------------------------- fast smoke


def test_scale_measurement_code_runs_end_to_end_on_a_small_cohort(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The measurement rig itself is regression-tested on 6 students (images) in the fast suite."""

    scenario = run_scenario(
        db_session, bulk_env, monkeypatch, tmp_path, students=6, pages=4, questions=6
    )
    assert scenario.corpus.call_budget() == 6 * 4 + 6 * 6
    assert scenario.meter.phases["intake"]["statements"] > 0
    assert scenario.meter.phases["drain_grade"]["unit_summary"]["units"] >= 36
    assert scenario.digest


@scale_only
def test_headline_150_students_x_4_pages_x_6_questions(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = run_scenario(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=HEADLINE_STUDENTS,
        pages=4,
        questions=6,
        layout="images",
    )
    assert scenario.corpus.call_budget() == HEADLINE_STUDENTS * (4 + 6)


@scale_only
@pytest.mark.parametrize("students", [10, 20, 40, 80], ids=lambda n: f"n{n}")
def test_scaling_curve_point(
    students: int,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One point of the N-scaling curve (images, 4 pages, 6 questions); see the module docstring.

    Each point is its own test so it starts from a clean database: the per-unit cost of a run
    must not be contaminated by the rows of the previous size.
    """

    scenario = run_scenario(
        db_session, bulk_env, monkeypatch, tmp_path, students=students, pages=4, questions=6
    )
    assert scenario.corpus.call_budget() == students * 10


@scale_only
def test_pdf_layout_30_students_x_4_pages_x_6_questions(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The PDF intake path (one real PDF per student, rasterised at 2x by the intake)."""

    scenario = run_scenario(
        db_session, bulk_env, monkeypatch, tmp_path, students=30, pages=4, questions=6, layout="pdf"
    )
    assert scenario.corpus.call_budget() == 30 * 10


# --------------------------------------------------------------------------- deterministic scaling


def _grade_unit_shape(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    students: int,
) -> dict[str, float]:
    purge_database(db)
    scenario = run_scenario(
        db,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=students,
        pages=2,
        questions=3,
        approve=True,
        name=f"shape-{students}",
    )
    assert scenario.grade is not None and scenario.read is not None
    grade = [u for u in scenario.grade.units if u.kind == "grade"]
    read = [u for u in scenario.read.units if u.kind == "read_page"]
    resume = scenario.resume_units
    return {
        "items": float(students * 3),
        "grade_statements": float(max(u.statements for u in grade)),
        "grade_rows": float(grade[0].select_rows),
        "read_statements": float(max(u.statements for u in read)),
        "read_rows": float(read[0].select_rows),
        "resume_statements": float(max(u.statements for u in resume)),
        "resume_rows": float(resume[0].select_rows),
        "finish_statements": float(scenario.grade.units[-1].statements),
        "approve_statements": float(scenario.meter.phases["approve_clean"]["statements"]),
    }


def test_per_unit_statement_count_is_flat_and_rows_read_grow_at_most_linearly_in_items(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PINS today's (acceptable) cost model so a regression to O(N^2) per unit is noticed.

    ``run_next`` loads the run with ALL its items (``get_run``), twice per unit, and
    ``_refresh_counts`` loads them again, so the ROWS a grading unit reads grow linearly with the
    number of items: that is O(N^2) rows over a whole run. The STATEMENT count per unit, however,
    must not depend on N (no per-item query). Both facts are asserted deterministically; the
    wall-clock consequence is only printed.
    """

    small = _grade_unit_shape(db_session, bulk_env, monkeypatch, tmp_path / "a", 4)
    large = _grade_unit_shape(db_session, bulk_env, monkeypatch, tmp_path / "b", 12)
    emit("per_unit_shape", small=small, large=large)
    item_ratio = large["items"] / small["items"]
    for statements in ("grade_statements", "read_statements", "resume_statements"):
        assert large[statements] == small[statements], f"{statements} depends on N"
    for rows in ("grade_rows", "read_rows", "resume_rows"):
        assert large[rows] <= small[rows] * item_ratio * 1.25, f"{rows} grows faster than linearly"
        assert large[rows] >= small[rows], f"{rows} fell as N grew (the probe is broken)"
    # The two paths the per-unit pin above does NOT cover grow with N: the finishing unit and
    # ``approve_clean`` (one lock/approve cycle per item, plus, since RC-03, an evidence pre-check
    # of every draft so a refusal names all stale drafts and writes nothing: about 27 statements
    # per item). Pinned as "no worse than today", not as "flat".
    items_delta = large["items"] - small["items"]
    finish_growth = large["finish_statements"] - small["finish_statements"]
    assert 0 <= finish_growth <= items_delta * 1.1, finish_growth
    assert large["approve_statements"] <= large["items"] * 30
    assert large["approve_statements"] - small["approve_statements"] <= items_delta * 30


def mean_unit(units: list[UnitRecord], kind: str | None = None) -> dict[str, float]:
    chosen = [unit for unit in units if kind is None or unit.kind == kind]
    return {
        "units": float(len(chosen)),
        "statements": round(sum(u.statements for u in chosen) / len(chosen), 1),
        "ms": round(1000 * sum(u.seconds for u in chosen) / len(chosen), 2),
    }


def test_the_managed_local_lease_adds_statements_per_unit_and_leaves_no_lease_behind(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The pilot's path takes the managed-local model lease around every provider operation.

    Every other measurement here uses the plain fake (``managed_local_phase=None``), so the
    lease's bookkeeping (a database write/commit cycle per operation) is NOT in those numbers.
    This compares 6 students with and without it: the per-unit statement count rises and the
    run still ends clean with the lease released (the phase SWITCH stays off: no model server is
    ever touched).
    """

    kwargs: dict[str, Any] = {"students": 6, "pages": 4, "questions": 6, "approve": False}
    plain = run_scenario(
        db_session, bulk_env, monkeypatch, tmp_path / "plain", name="plain-6", **kwargs
    )
    plain_lease = read_lease(db_session)
    precondition(plain_lease is None, f"the plain fake must not touch the lease: {plain_lease}")
    purge_database(db_session)
    managed = run_scenario(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path / "managed",
        name="managed-6",
        managed_local=True,
        **kwargs,
    )
    lease = read_lease(db_session)
    precondition(lease is not None, "the managed-local lease never ran")
    assert plain.read is not None and plain.grade is not None
    assert managed.read is not None and managed.grade is not None
    figures = {
        "read": (
            mean_unit(plain.read.units, "read_page"),
            mean_unit(managed.read.units, "read_page"),
        ),
        "grade": (mean_unit(plain.grade.units, "grade"), mean_unit(managed.grade.units, "grade")),
    }
    emit("managed_local_overhead", plain_vs_managed=figures, calls=managed.provider.counts)
    assert lease is not None and lease.holder_id is None, "the lease must be released at the end"
    assert managed.digest == plain.digest  # the same item outcomes
    for plain_unit, managed_unit in figures.values():
        assert managed_unit["statements"] > plain_unit["statements"]


# --------------------------------------------------------------------------- capacity boundaries


def file_count(root: Path) -> int:
    return sum(len(files) for _current, _dirs, files in os.walk(root))


def limited_settings(bulk_env: Settings, **overrides: Any) -> Settings:
    """Settings with the SAME storage roots as ``bulk_env`` and some capacity knobs changed."""

    return make_settings(Path(bulk_env.local_storage_root), **overrides)


@dataclass
class OverCap:
    """What one real intake of an over-cap PDF cohort did before it was refused."""

    cap: int
    students: int
    pages: int
    rendered: list[int]
    at_cleanup: dict[str, int]
    wasted_s: float
    refusal: str | None
    files_before: int
    root: Path
    provider: FakeBulkBrainProvider


def intake_over_the_page_cap(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> OverCap:
    """Boundary 1: 5 pages x 150 students = 750 > 720 (the hard page cap), scaled down 5x.

    30 students x 5 PDF pages = 150 pages against a cap of 144 (= 720 * 30 / 150), so the real
    intake, including the PDF rasterisation, runs in the fast suite. ``_import_unit`` and
    ``_cleanup_submissions`` are wrapped (not replaced) to see how much work was done before the
    refusal and what was on disk at the moment of the clean-up.
    """

    cap, students, pages = 144, 30, 5
    settings = limited_settings(bulk_env, BULK_MAX_PAGES=cap)
    seeded = seed_assessment(db, questions=6)
    corpus = build_zip(
        tmp_path / "over.zip", students=students, pages=pages, questions=6, layout="pdf"
    )
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, settings)
    root = Path(bulk_env.local_storage_root)
    rendered: list[int] = []
    at_cleanup: dict[str, int] = {}
    original_import = BulkEvaluationService._import_unit
    original_cleanup = BulkEvaluationService._cleanup_submissions

    def counting_import(self: BulkEvaluationService, **kwargs: Any) -> Any:
        submission = original_import(self, **kwargs)
        rendered.append(len(submission.pages))
        return submission

    def spying_cleanup(self: BulkEvaluationService, submission_ids: list[int]) -> None:
        at_cleanup.update(
            files=file_count(root), bytes=dir_bytes(root), scripts=len(submission_ids)
        )
        original_cleanup(self, submission_ids)

    monkeypatch.setattr(BulkEvaluationService, "_import_unit", counting_import)
    monkeypatch.setattr(BulkEvaluationService, "_cleanup_submissions", spying_cleanup)
    files_before = file_count(root)
    refusal: str | None = None
    t0 = time.perf_counter()
    try:
        import_zip(
            db,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=settings,
            register=False,
        )
    except BulkEvaluationError as exc:
        refusal = str(exc)
    wasted_s = time.perf_counter() - t0
    return OverCap(
        cap, students, pages, rendered, at_cleanup, wasted_s, refusal, files_before, root, provider
    )


def test_an_over_cap_cohort_is_rejected_cleanly_and_the_wasted_work_is_measured(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The rejection leaves nothing behind: no rows, no files, no run, no provider call.

    How much work happened BEFORE the refusal is measured and printed here and is the subject of
    the GAP test below (``page-cap-enforced-after-rasterising``).
    """

    over = intake_over_the_page_cap(db_session, bulk_env, monkeypatch, tmp_path)
    crossing = 720 // 5 + 1
    emit(
        "boundary_pages",
        scaled=dict(
            students=over.students,
            pages=over.students * over.pages,
            cap=over.cap,
            scripts_rendered=len(over.rendered),
            pages_rendered=sum(over.rendered),
            files_at_rejection=over.at_cleanup.get("files"),
            mib_at_rejection=mib(over.at_cleanup.get("bytes", 0)),
            seconds_until_rejection=round(over.wasted_s, 2),
        ),
        full_scale=dict(
            students=150,
            pages=750,
            cap=720,
            crossing_student=crossing,
            pages_rendered_before_rejection=crossing * 5,
        ),
    )
    assert over.refusal is not None and f"{over.cap}-page bulk limit" in over.refusal
    db_session.expire_all()
    assert db_session.scalar(select(func.count(Submission.id))) == 0
    assert db_session.scalar(select(func.count(SubmissionPage.id))) == 0
    assert db_session.scalar(select(func.count(BulkEvaluationRun.id))) == 0
    assert file_count(over.root) == over.files_before
    assert over.provider.total_calls == 0


def test_an_over_cap_cohort_is_refused_before_any_script_is_rendered(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    over = intake_over_the_page_cap(db_session, bulk_env, monkeypatch, tmp_path)
    precondition(
        over.refusal is not None and f"{over.cap}-page bulk limit" in over.refusal,
        f"the cohort must be refused for the page cap: {over.refusal!r}",
    )
    assert not over.rendered, (
        f"{len(over.rendered)} scripts / {sum(over.rendered)} pages were rendered and stored "
        f"({mib(over.at_cleanup.get('bytes', 0))} MiB on disk) before the {over.cap}-page cap "
        "was enforced"
    )


def test_the_submission_limit_is_checked_before_any_script_is_rendered(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Contrast to the page cap: 181 students (cap 180) is refused during archive inspection."""

    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "many.zip", students=181, pages=1, questions=1, layout="images")
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    rendered: list[int] = []
    original_import = BulkEvaluationService._import_unit

    def counting_import(self: BulkEvaluationService, **kwargs: Any) -> Any:
        rendered.append(1)
        return original_import(self, **kwargs)

    monkeypatch.setattr(BulkEvaluationService, "_import_unit", counting_import)
    with pytest.raises(BulkEvaluationError, match="180-submission limit"):
        import_zip(
            db_session,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=bulk_env,
            register=False,
        )
    assert rendered == []
    assert file_count(Path(bulk_env.local_storage_root)) == 0


def test_call_budget_arithmetic_and_the_two_ceilings(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Boundary 2 (arithmetic): what 150 x 4 pages x Q questions needs, against the ceilings.

    The task's premise "150 x 4 x 9 needs more than 2000 calls" is FALSE for plain pages: it needs
    150*4 + 150*9 = 1950. It exceeds 2000 only if EVERY script also triggers the whole-transcript
    assignment call (one extra call per script that has unlabelled/inferred continuation blocks:
    +150 = 2100, the worst case) or with 10 questions (2100). The ceiling that bites first is
    ``bulk_max_provider_calls``, whose DEFAULT is 1800 (config.py:344), below 1950.

    Corpus note: the harness only writes a continuation block when an answer spans a page break,
    which needs fewer questions than pages (4 pages x 2 questions). 4 pages x 9 questions never
    spans, so the "+1 per script" closed form is verified on the 4x2 corpus.
    """

    def budget(students: int, pages: int, questions: int, continuation: Any = False) -> int:
        corpus = build_zip(
            tmp_path / f"b-{students}-{pages}-{questions}-{continuation}.zip",
            students=students,
            pages=pages,
            questions=questions,
            continuation=continuation,
        )
        return corpus.call_budget()

    # the closed form is verified on a real corpus, then applied at 150 students
    assert budget(3, 4, 9) == 3 * 4 + 3 * 9
    assert budget(3, 4, 2) == 3 * 4 + 3 * 2
    assert budget(3, 4, 2, "unlabeled") == 3 * 4 + 3 + 3 * 2  # +1 assignment call per script
    assert budget(3, 4, 2, "inferred") == 3 * 4 + 3 + 3 * 2

    def need(questions: int, *, continuation: bool = False) -> int:
        return 150 * 4 + (150 if continuation else 0) + 150 * questions

    table = {
        "150x4x6": need(6),
        "150x4x7": need(7),
        "150x4x8": need(8),
        "150x4x9": need(9),
        "150x4x9+continuation": need(9, continuation=True),
        "150x4x10": need(10),
    }
    emit(
        "boundary_calls",
        needs=table,
        default_ceiling=bulk_env.bulk_max_provider_calls,
        hard_field_max=2000,
        largest_questions_with_headroom_at_default_ceiling=7,
    )
    assert table == {
        "150x4x6": 1500,
        "150x4x7": 1650,
        "150x4x8": 1800,
        "150x4x9": 1950,
        "150x4x9+continuation": 2100,
        "150x4x10": 2100,
    }
    assert bulk_env.bulk_max_provider_calls == 1800
    assert table["150x4x6"] <= 1800 < table["150x4x9"] <= 2000 < table["150x4x10"]
    # 8 questions need EXACTLY the default ceiling, so no slack is possible, and a run authorised
    # for exactly the calls it needs ends 'paused' instead of 'review_ready' (the exact-budget
    # defect, tests/test_bulk150_harness_smoke.py::
    # test_a_run_authorised_for_exactly_the_calls_it_needs_still_finishes): at the default
    # ceiling the largest 150 x 4-page cohort that can finish cleanly has 7 questions.
    assert table["150x4x8"] == bulk_env.bulk_max_provider_calls
    assert table["150x4x7"] + 2 <= bulk_env.bulk_max_provider_calls
    # The designed maximum (180 scripts, the 720-page cap = 4 pages each, and 6 questions) needs
    # 180 * (4 + 6) = 1800 calls, which IS the default ceiling: that cohort can never be given any
    # slack, so it always meets the exact-budget defect above.
    assert 180 * (4 + 6) == bulk_env.bulk_max_provider_calls == 180 * 4 + 180 * 6

    # the server enforces the ceiling at intake, before a byte of the archive is staged
    seeded = seed_assessment(db_session, questions=2)
    corpus = build_zip(tmp_path / "tiny.zip", students=2, pages=2, questions=2)
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
            register=False,
        )
    # ... and no configuration can raise the ceiling above 2000, the largest the form accepts
    with pytest.raises(ValueError, match="BULK_MAX_PROVIDER_CALLS"):
        limited_settings(bulk_env, BULK_MAX_PROVIDER_CALLS=2001)
    assert limited_settings(bulk_env, BULK_MAX_PROVIDER_CALLS=2000).bulk_max_provider_calls == 2000


REPO_ROOT = Path(__file__).resolve().parents[3]
BULK_LIMIT_KEYS = ("BULK_MAX_SUBMISSIONS", "BULK_MAX_PAGES", "BULK_MAX_PROVIDER_CALLS")


def parse_env_template(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a committed ENV TEMPLATE (never a real ``.env``)."""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_the_shipped_env_template_and_runbook_limits_admit_the_headline_cohort(
    bulk_env: Settings,
) -> None:
    """POLICY pin: the shipped ``.env.example`` limits are the schema bounds (RC-53, fixed).

    ``.env.example`` used to say 50 submissions / 500 pages, so a pilot configured from the
    template refused a 150-script cohort. Since 2026-10-12 it ships 180 / 720 / 2000, the
    ``le=`` bounds in ``config.py`` (the code default for calls stays 1800). The runbook is
    pinned to the same figures. THE LIVE ENVIRONMENT FILE IS NOT READ here.
    """

    template = parse_env_template(REPO_ROOT / ".env.example")
    precondition(
        all(key in template for key in BULK_LIMIT_KEYS), f"template lacks limits: {template}"
    )
    runbook = (REPO_ROOT / "docs" / "BULK_SUPERVISED_RUNBOOK.md").read_text(encoding="utf-8")
    code_defaults = Settings(_env_file=None)
    from_template = limited_settings(bulk_env, **{key: template[key] for key in BULK_LIMIT_KEYS})
    emit(
        "limit_sources",
        template={key: template[key] for key in BULK_LIMIT_KEYS},
        code_defaults=dict(
            BULK_MAX_SUBMISSIONS=code_defaults.bulk_max_submissions,
            BULK_MAX_PAGES=code_defaults.bulk_max_pages,
            BULK_MAX_PROVIDER_CALLS=code_defaults.bulk_max_provider_calls,
        ),
        runbook_line=next(line for line in runbook.splitlines() if "submissions" in line),
    )
    assert "180 submissions, 720 pages" in runbook
    assert "50 submissions, 500 pages" not in runbook
    assert (
        from_template.bulk_max_submissions,
        from_template.bulk_max_pages,
        from_template.bulk_max_provider_calls,
    ) == (180, 720, 2000)
    assert (
        code_defaults.bulk_max_submissions,
        code_defaults.bulk_max_pages,
        code_defaults.bulk_max_provider_calls,
    ) == (180, 720, 1800)
    # The headline cohort (150 x 4 pages x 6 questions = 600 pages, 1,500 calls) fits.
    assert from_template.bulk_max_submissions >= 150
    assert from_template.bulk_max_pages >= 150 * 4
    assert from_template.bulk_max_provider_calls >= 150 * 4 + 150 * 6


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP ui-default-call-limit-above-server-default-ceiling: the bulk form pre-fills "
        "MAX_CALL_LIMIT=2000 (BulkEvaluationClient.tsx:52,70) but BULK_MAX_PROVIDER_CALLS "
        "defaults to 1800 (config.py:344), so the first, default submission is refused"
    ),
)
def test_the_calls_the_ui_pre_fills_are_accepted_by_a_default_configured_server(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = (REPO_ROOT / "apps" / "web" / "components" / "BulkEvaluationClient.tsx").read_text(
        encoding="utf-8"
    )
    match = re.search(r"const MAX_CALL_LIMIT = (\d+);", source)
    precondition(
        match is not None and "useState(MAX_CALL_LIMIT)" in source,
        "the UI no longer pre-fills the call limit with MAX_CALL_LIMIT",
    )
    ui_default = int(match.group(1)) if match else 0
    precondition(
        "BULK_MAX_PROVIDER_CALLS" not in os.environ,
        "the process environment overrides the server's default ceiling",
    )
    precondition(
        bulk_env.bulk_max_provider_calls == Settings(_env_file=None).bulk_max_provider_calls,
        "the probe must run against the default server configuration",
    )
    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "tiny.zip", students=2, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    refusal: str | None = None
    try:
        import_zip(
            db_session,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=bulk_env,
            maximum_provider_calls=ui_default,
            register=False,
        )
    except BulkEvaluationError as exc:
        refusal = str(exc)
    assert refusal is None, (
        f"the form's default authorisation of {ui_default} calls was refused by a default "
        f"server (ceiling {bulk_env.bulk_max_provider_calls}): {refusal}"
    )


def test_the_page_cap_accepts_exactly_the_cap_and_refuses_one_script_more(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The page cap is ``>``: a cohort of exactly ``bulk_max_pages`` pages is accepted.

    Scaled down 18x (cap 40 = 10 students x 4 pages instead of 720 = 180 x 4).
    """

    settings = limited_settings(bulk_env, BULK_MAX_PAGES=40)
    seeded = seed_assessment(db_session, questions=2)
    exact = build_zip(tmp_path / "exact.zip", students=10, pages=4, questions=2)
    provider = FakeBulkBrainProvider(exact)
    install_fake_brain(monkeypatch, provider, settings)
    run = import_zip(
        db_session,
        seeded=seeded,
        corpus=exact,
        provider=provider,
        settings=settings,
        register=False,
    )
    assert (run.total_submissions, run.total_pages, run.total_items) == (10, 40, 20)

    # one script (4 pages) more, into a fresh assessment, is refused
    other = seed_assessment(db_session, questions=2)
    over = build_zip(tmp_path / "over.zip", students=11, pages=4, questions=2)
    with pytest.raises(BulkEvaluationError, match="40-page bulk limit"):
        import_zip(
            db_session,
            seeded=other,
            corpus=over,
            provider=provider,
            settings=settings,
            register=False,
        )


def test_the_archive_byte_cap_is_enforced_while_staging_before_anything_is_rendered(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``BULK_MAX_ARCHIVE_BYTES`` (default 1 GiB, floor 1 MiB) bites during the upload copy.

    A real 150 x 4-page scan set is 600 page images: at 1.5 MiB a page that is 0.9 GiB (accepted),
    at 2 MiB a page it is 1.2 GiB (refused). The check fires in ``_stage_archive`` (before the
    archive is even opened), and the staging file is removed.
    """

    settings = limited_settings(bulk_env, BULK_MAX_ARCHIVE_BYTES=1_048_576)
    seeded = seed_assessment(db_session, questions=1)
    corpus = build_zip(tmp_path / "big.zip", students=60, pages=4, questions=1, layout="images")
    size = corpus.archive_path.stat().st_size
    precondition(size > 1_048_576, f"the probe archive must exceed 1 MiB, it is {size} bytes")
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, settings)
    rendered: list[int] = []
    original_import = BulkEvaluationService._import_unit

    def counting_import(self: BulkEvaluationService, **kwargs: Any) -> Any:
        rendered.append(1)
        return original_import(self, **kwargs)

    monkeypatch.setattr(BulkEvaluationService, "_import_unit", counting_import)
    with pytest.raises(BulkEvaluationError, match="configured bulk archive limit"):
        import_zip(
            db_session,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=settings,
            register=False,
        )
    emit(
        "boundary_archive_bytes", archive_bytes=size, cap=1_048_576, scripts_rendered=len(rendered)
    )
    assert rendered == []
    root = Path(bulk_env.local_storage_root)
    assert [p for p in (root / "uploads" / "bulk_staging").glob("*.zip")] == []
    assert db_session.scalar(select(func.count(Submission.id))) == 0
    assert provider.total_calls == 0


# --------------------------------------------------------------------------- authorisation spent


@dataclass
class Spent:
    """A run whose authorised provider calls ran out part-way through grading."""

    seeded: Seeded
    corpus: Corpus
    provider: FakeBulkBrainProvider
    run_id: int
    need: int
    limit: int
    drained: DrainResult
    zip_path: Path


def run_with_authorisation(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    students: int = 10,
    pages: int = 4,
    questions: int = 6,
    limit: int | None = None,
    fraction: float = 0.7,
) -> Spent:
    """Authorise ``limit`` calls (default ``fraction`` of the clean-run need), then run the flow.

    Intake refuses an authorisation below pages + items, so a smaller limit is reached by
    importing at the clean-run need and lowering the stored limit before anything is spent.
    Read stage, teacher gate, per-item resume, grading drain: the same sequence as the headline
    run. The result is whatever state the pipeline ends in.
    """

    seeded = seed_assessment(db, questions=questions)
    corpus = build_zip(tmp_path / "spent.zip", students=students, pages=pages, questions=questions)
    need = corpus.call_budget()
    authorised = limit if limit is not None else int(need * fraction)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(
        db,
        seeded=seeded,
        corpus=corpus,
        provider=provider,
        settings=bulk_env,
        maximum_provider_calls=max(authorised, need),
    )
    run_id = run.id
    if authorised < need:
        set_authorised_limit(db, run_id, authorised)
    read = drain(run_id, settings=bulk_env, provider=provider)
    precondition(
        read.status == "completed_with_exceptions",
        f"the read stage must end held for the gate: {read}",
    )
    gate = review_all_transcripts(db, run_id, seeded.teacher)
    precondition(not gate.refused, f"gate refused: {gate.refused}")
    resumed = resume_all_items(run_id, seeded.teacher, settings=bulk_env)
    precondition(not resumed.refused, f"resume refused: {dict(list(resumed.refused.items())[:3])}")
    precondition(
        len(resumed.resumed) == students * questions,
        f"resumed {len(resumed.resumed)} of {students * questions} items",
    )
    drained = drain(run_id, settings=bulk_env, provider=provider)
    return Spent(seeded, corpus, provider, run_id, need, authorised, drained, corpus.archive_path)


def status_matrix(db: Session, run_id: int) -> dict[str, dict[str, int]]:
    """``question -> {status: count}`` of a run's items."""

    matrix: dict[str, Counter[str]] = {}
    for (_student, question), view in item_views(db, run_id).items():
        matrix.setdefault(question, Counter())[f"{view.status}/{view.stage}"] += 1
    return {question: dict(sorted(counter.items())) for question, counter in sorted(matrix.items())}


def test_an_authorisation_below_pages_plus_items_is_refused_at_intake_and_a_lowered_run_pauses(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Boundary 2, scaled 15x: 10 students x 4 pages x 6 questions, 70% of the call budget.

    Intake compares the authorisation with the cohort's minimum need (pages + items = 100) and
    REFUSES a smaller one, naming the minimum: a run that cannot read and grade every item can
    only end exhausted (see the dead-end tests below). The exhausted-run end state is still
    reachable by lowering the stored limit after a valid import (``set_authorised_limit``), and
    this test pins it: the pipeline spends the limit exactly (never one call over), reads every
    page first, then grades QUESTION-MAJOR (``_next_grading_item``): the grading calls run out
    after Q1..Q3 of every student, so ALL ten students are left with a half-graded script. The
    run ends ``paused``.
    """

    seeded_refused = seed_assessment(db_session, questions=6)
    refused_corpus = build_zip(tmp_path / "refused.zip", students=10, pages=4, questions=6)
    refused_provider = FakeBulkBrainProvider(refused_corpus)
    install_fake_brain(monkeypatch, refused_provider, bulk_env)
    with pytest.raises(BulkEvaluationError) as refusal:
        import_zip(
            db_session,
            seeded=seeded_refused,
            corpus=refused_corpus,
            provider=refused_provider,
            settings=bulk_env,
            maximum_provider_calls=70,
            register=False,
        )
    message = str(refusal.value)
    assert "Authorized provider calls (70) are below the minimum" in message
    assert "(100: 40 page reads + 60 gradings)" in message
    assert "Whole-transcript assignment calls" in message
    assert db_session.scalar(select(func.count(BulkEvaluationRun.id))) == 0
    assert db_session.scalar(select(func.count(Submission.id))) == 0
    assert refused_provider.total_calls == 0

    spent = run_with_authorisation(
        db_session, bulk_env, monkeypatch, tmp_path, students=10, pages=4, questions=6
    )
    db_session.expire_all()
    run = db_session.get(BulkEvaluationRun, spent.run_id)
    assert run is not None
    matrix = status_matrix(db_session, spent.run_id)
    emit(
        "boundary_calls_spent",
        need=spent.need,
        authorised=spent.limit,
        run_status=run.status,
        error=run.error,
        calls_used=run.calls_used,
        provider_calls=spent.provider.counts,
        matrix=matrix,
        clean=run.clean_item_count,
        processed=run.processed_items,
    )
    assert (spent.need, spent.limit) == (100, 70)
    assert (run.status, run.stage) == ("paused", "grading")
    assert run.error == "Authorized provider-call limit reached"
    # the ledger and the provider agree and the authorisation is never overrun
    assert run.calls_used == spent.provider.total_calls == spent.limit
    assert spent.provider.counts["read_page"] == 40 and spent.provider.counts["grade"] == 30
    # question-major order: Q1..Q3 graded for every student, Q4..Q6 untouched for every student
    for question in ("Q1", "Q2", "Q3"):
        assert matrix[question] == {"graded/review": 10}
    for question in ("Q4", "Q5", "Q6"):
        assert matrix[question] == {"pending/grading": 10}
    assert (run.clean_item_count, run.exception_count, run.approved_count) == (30, 0, 0)
    assert_no_final_grades(db_session, spent.run_id)


def test_after_the_authorisation_is_spent_nothing_can_resume_approve_or_export(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PINS the dead end: every teacher action on the spent run is refused.

    ``resume`` (limit exhausted), ``resume_item`` on a pending item (only exception/uncertain
    items can be resumed), ``approve_clean`` (status ``paused`` is not reviewable) and the
    export route (status ``paused``) all refuse, so the 30 graded drafts are stranded.
    """

    spent = run_with_authorisation(db_session, bulk_env, monkeypatch, tmp_path)
    teacher = spent.seeded.teacher
    resumed, refusal = try_resume_run(spent.run_id, teacher, settings=bulk_env)
    assert not resumed and refusal == _EXHAUSTED_REFUSAL

    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=bulk_env)
        run = service.get_run(spent.run_id)
        pending = next(item for item in run.items if item.status == "pending")
        with pytest.raises(BulkEvaluationError, match="Only an exception or uncertain item"):
            service.resume_item(run, pending, teacher_id=teacher.id)
        graded = [
            int(item.grade_suggestion_id)
            for item in run.items
            if item.status == "graded" and item.grade_suggestion_id is not None
        ]
        assert len(graded) == 30
        with pytest.raises(BulkEvaluationError, match="not ready for teacher approval"):
            service.approve_clean(
                run,
                suggestion_ids=graded,
                review_snapshot_sha256=service.review_snapshot_hash(run),
                teacher_id=teacher.id,
            )
        with pytest.raises(HTTPException) as export:
            download_bulk_results(spent.run_id, session, teacher)
        assert export.value.status_code == 409
    finally:
        session.close()
    assert_no_final_grades(db_session, spent.run_id)


def test_re_importing_the_cohort_after_exhaustion_cannot_start_a_new_run(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PINS the two ways the error message's "new run" can fail (see the GAP test below).

    * the SAME archive is idempotent while the old run is active (``paused`` counts as active):
      ``create_from_zip`` hands back the old run with its old, spent authorisation;
    * a DIFFERENT archive of the same cohort is refused: the student identifiers already exist
      in the assessment ("import it into a separate assessment").
    """

    spent = run_with_authorisation(db_session, bulk_env, monkeypatch, tmp_path)
    bigger = spent.need + 2
    again = import_zip(
        db_session,
        seeded=spent.seeded,
        corpus=spent.corpus,
        provider=spent.provider,
        settings=bulk_env,
        maximum_provider_calls=bigger,
        register=False,
    )
    emit(
        "reimport_same_archive",
        old_run=spent.run_id,
        returned_run=again.id,
        returned_limit=again.authorized_call_limit,
        requested_limit=bigger,
        returned_status=again.status,
    )
    assert again.id == spent.run_id
    assert again.authorized_call_limit == spent.limit != bigger
    assert again.status == "paused"

    repacked = tmp_path / "repacked.zip"
    with (
        zipfile.ZipFile(spent.zip_path) as source,
        zipfile.ZipFile(repacked, "w", compression=zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            target.writestr(info.filename, source.read(info))
    with pytest.raises(BulkEvaluationError, match="student identifier.*already exist"):
        import_zip(
            db_session,
            seeded=spent.seeded,
            corpus=spent.corpus,
            provider=spent.provider,
            settings=bulk_env,
            maximum_provider_calls=bigger,
            archive_path=repacked,
            register=False,
        )


READ_BUDGET_ERROR = (
    "Pages still needing a source read exceed the explicitly authorized page-read call limit"
)


def read_stage_with_authorisation(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    limit: int = 35,
) -> tuple[Seeded, Corpus, FakeBulkBrainProvider, int, DrainResult]:
    """10 students x 4 pages (40 page reads) authorised for ``limit`` calls, read stage drained.

    Imported at the clean-run need (intake refuses less than pages + items), then lowered.
    """

    seeded = seed_assessment(db, questions=6)
    corpus = build_zip(tmp_path / "midread.zip", students=10, pages=4, questions=6)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    need = corpus.call_budget()
    run = import_zip(
        db,
        seeded=seeded,
        corpus=corpus,
        provider=provider,
        settings=bulk_env,
        maximum_provider_calls=max(limit, need),
    )
    if limit < need:
        set_authorised_limit(db, run.id, limit)
    read = drain(run.id, settings=bulk_env, provider=provider)
    return seeded, corpus, provider, run.id, read


def test_an_authorisation_that_runs_out_during_reading_pauses_between_scripts_and_resume_spins(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Boundary 2, read-stage variant: 10 students x 4 pages, authorisation 35 of 40 page reads.

    PINS today's behaviour: the budget is checked per SCRIPT before any of its pages is read, so
    no script is ever half read (8 scripts = 32 calls are read, the 9th needs 4 > 3 remaining);
    3 authorised calls are left unspent. The run pauses. ``resume`` is ACCEPTED (35 > 32 calls
    used) but the next unit pauses again with the same message and nothing is read: a Resume that
    cannot make progress. The 8 read scripts can still go through the teacher gate; the other two
    are refused. (How the two unread scripts' items are LABELLED is the GAP test below.)
    """

    seeded, corpus, provider, run_id, read = read_stage_with_authorisation(
        db_session, bulk_env, monkeypatch, tmp_path
    )
    db_session.expire_all()
    first = status_matrix(db_session, run_id)
    assert (read.status, read.stage, read.error) == ("paused", "reading", READ_BUDGET_ERROR)
    assert read.calls_used == provider.counts["read_page"] == 32 < 35
    assert Counter(db_session.scalars(select(ScriptPageTranscript.state)).all()) == {
        "succeeded": 32
    }
    for question in corpus.labels:
        assert first[question].get("exception/read") == 8
        assert sum(first[question].values()) == 10

    resumed, refusal = try_resume_run(run_id, seeded.teacher, settings=bulk_env)
    assert resumed and refusal is None
    again = drain(run_id, settings=bulk_env, provider=provider)
    assert (again.status, again.error) == ("paused", READ_BUDGET_ERROR)
    assert again.calls_used == provider.counts["read_page"] == 32 and again.units == 1
    db_session.expire_all()
    second = status_matrix(db_session, run_id)
    emit(
        "boundary_calls_spent_in_read",
        authorised=35,
        need=corpus.call_budget(),
        calls_used=again.calls_used,
        first_pause=first["Q1"],
        after_resume=second["Q1"],
    )
    for question in corpus.labels:
        assert second[question].get("exception/read") == 8

    gate = review_all_transcripts(db_session, run_id, seeded.teacher)
    assert len(gate.confirmed) == 8
    assert len(gate.refused) == 2
    # An unread script either has a transcript row without successful pages or (never reached
    # since Resume revives every read-stage 'uncertain' item, RC-38) no transcript at all.
    assert all(
        "successful, reviewable transcript" in text or text == "no transcript"
        for text in gate.refused.values()
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP budget-refusal-mislabelled-provider-contract-failure: a script refused for budget "
        "before any provider call is stamped 'uncertain'/provider_contract_failure by "
        "run_next's quarantine (bulk_evaluation_service.py:677-691), and each Resume extends it "
        "to the next unread script"
    ),
)
def test_a_script_refused_for_budget_before_any_provider_call_is_not_blamed_on_the_provider(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seeded, corpus, provider, run_id, read = read_stage_with_authorisation(
        db_session, bulk_env, monkeypatch, tmp_path
    )
    precondition(
        (read.status, read.error) == ("paused", READ_BUDGET_ERROR),
        f"the read stage must pause on the page-read budget: {read}",
    )
    precondition(
        read.calls_used == provider.counts["read_page"] == 32,
        f"32 page reads were expected: {read.calls_used} / {provider.counts}",
    )
    read_students = {s for call in provider.calls_of("read_page") for s in call.students}
    undispatched = set(corpus.students) - read_students
    precondition(len(undispatched) == 2, f"two scripts must be unread: {sorted(undispatched)}")
    views = item_views(db_session, run_id)
    blamed = sorted(
        (view.student, view.question)
        for view in views.values()
        if view.student in undispatched and "provider_contract_failure" in view.codes
    )
    assert not blamed, (
        f"{len(blamed)} items of scripts that never reached the provider are stamped "
        f"provider_contract_failure, e.g. {blamed[:2]}"
    )


def test_after_the_gate_every_item_needs_its_own_resume_and_no_bulk_action_exists(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY pin (teacher workload at scale): grading starts one item at a time.

    After the read stage the run is ``completed_with_exceptions`` with EVERY item held, so the
    run-level resume refuses; the only action that starts grading is the per-item
    ``/items/{id}/resume`` (the UI's "2. Resume Qn grading" button, one per question per script,
    BulkEvaluationClient.tsx:443-453). Resuming one item grades exactly that item. For 150 x 6
    that was 900 clicks AFTER the teacher had already confirmed every transcript; since RC-68
    (2026-10-13) the bulk release below does it in one action and this per-item path stays.
    """

    from app.api.routes.bulk_evaluations import router

    students, questions = 4, 3
    seeded = seed_assessment(db_session, questions=questions)
    corpus = build_zip(tmp_path / "gate.zip", students=students, pages=2, questions=questions)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(db_session, seeded=seeded, corpus=corpus, provider=provider, settings=bulk_env)
    run_id = run.id
    read = drain(run_id, settings=bulk_env, provider=provider)
    precondition(read.status == "completed_with_exceptions", f"read stage: {read}")
    gate = review_all_transcripts(db_session, run_id, seeded.teacher)
    precondition(len(gate.confirmed) == students and not gate.refused, f"gate: {gate.refused}")
    assert status_matrix(db_session, run_id) == {
        label: {"exception/read": students} for label in corpus.labels
    }

    resumed, refusal = try_resume_run(run_id, seeded.teacher, settings=bulk_env)
    assert not resumed and refusal == "Only a paused or stopped bulk run can resume"
    resume_routes = sorted(route.path for route in router.routes if "resume" in route.path)
    assert len(resume_routes) == 2, resume_routes
    assert resume_routes[0].endswith("/{run_id}/items/{item_id}/resume")
    assert resume_routes[1].endswith("/{run_id}/resume")

    # one item resumed -> exactly one item graded; the other 11 stay held
    storage = harness_storage(bulk_env)
    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=bulk_env, storage=storage)
        service_run = service.get_run(run_id)
        first = next(item for item in service_run.items if item.status == "exception")
        service.resume_item(service_run, first, teacher_id=seeded.teacher.id)
    finally:
        session.close()
    final = drain(run_id, settings=bulk_env, provider=provider)
    db_session.expire_all()
    refreshed = db_session.get(BulkEvaluationRun, run_id)
    assert refreshed is not None
    emit(
        "gate_resume_per_item",
        items=students * questions,
        final_status=final.status,
        graded=refreshed.clean_item_count,
        held=refreshed.exception_count,
        grade_calls=provider.counts["grade"],
    )
    assert final.status == "review_ready"
    assert (refreshed.clean_item_count, refreshed.exception_count) == (1, students * questions - 1)
    assert provider.counts["grade"] == 1


def test_one_release_action_starts_grading_for_every_reviewed_script_and_only_those(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """RC-68: ``POST /bulk-evaluation-runs/{id}/release-reviewed`` replaces the per-item clicks.

    Three of four scripts are reviewed; one is not. One release action resumes exactly the nine
    reviewed items (no provider call during the release itself), names the three held ones with
    the reason, and the worker then grades the nine.
    """

    students, questions = 4, 3
    seeded = seed_assessment(db_session, questions=questions)
    corpus = build_zip(tmp_path / "release.zip", students=students, pages=2, questions=questions)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(db_session, seeded=seeded, corpus=corpus, provider=provider, settings=bulk_env)
    run_id = run.id
    read = drain(run_id, settings=bulk_env, provider=provider)
    precondition(read.status == "completed_with_exceptions", f"read stage: {read}")
    submissions = sorted(
        db_session.scalars(
            select(BulkEvaluationItem.submission_id)
            .where(BulkEvaluationItem.run_id == run_id)
            .distinct()
        ).all()
    )
    gate = review_all_transcripts(
        db_session, run_id, seeded.teacher, only_submissions=submissions[:3]
    )
    precondition(len(gate.confirmed) == 3 and not gate.refused, f"gate: {gate.refused}")
    calls_before = provider.total_calls

    storage = harness_storage(bulk_env)
    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=bulk_env, storage=storage)
        released, skipped = service.release_reviewed_to_grading(
            service.get_run(run_id), teacher_id=seeded.teacher.id
        )
        skipped_submissions = {item.submission_id for item, _ in skipped}
        reasons = {reason for _, reason in skipped}
    finally:
        session.close()
    assert len(released) == 3 * questions
    assert skipped_submissions == {submissions[3]} and len(skipped) == questions
    assert reasons == {"the transcript review is not confirmed for the current transcript"}
    assert provider.total_calls == calls_before  # releasing sends nothing

    final = drain(run_id, settings=bulk_env, provider=provider)
    db_session.expire_all()
    refreshed = db_session.get(BulkEvaluationRun, run_id)
    assert refreshed is not None
    assert final.status == "review_ready"
    assert (refreshed.clean_item_count, refreshed.exception_count) == (9, 3)
    assert provider.counts["grade"] == 9
    events = db_session.scalars(
        select(AuditLog.event_type).where(AuditLog.entity_id == run_id)
    ).all()
    assert "bulk_evaluation_reviewed_released_to_grading" in events


def test_ten_students_authorised_for_exactly_their_calls_still_reach_review_ready(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The scaled form of the designed maximum (180 x 4 x 6 = the 1800-call default ceiling)."""

    spent = run_with_authorisation(db_session, bulk_env, monkeypatch, tmp_path, fraction=1.0)
    precondition(spent.limit == spent.need == 100, f"limit {spent.limit}, need {spent.need}")
    precondition(
        spent.provider.counts == {"read_page": 40, "map": 0, "grade": 60},
        f"all the work must have been done: {spent.provider.counts}",
    )
    matrix = status_matrix(db_session, spent.run_id)
    precondition(
        all(row == {"graded/review": 10} for row in matrix.values()),
        f"every item must be graded: {matrix}",
    )
    assert spent.drained.status == "review_ready", spent.drained


def test_stopping_the_spent_run_does_not_open_a_way_out_either(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PINS the obvious teacher action: press Stop on the paused, spent run.

    ``stopped`` is not an active status, so the same-archive dedupe no longer returns the old
    run; but the cohort's identifiers still exist in the assessment, so the re-import is refused;
    ``resume`` still says the limit is exhausted; approve and export refuse a ``stopped`` run.
    The only exit left is a SEPARATE assessment, which pays for all 40 page reads (and the
    teacher gate) again. At 150 students that is every page read over again.
    """

    spent = run_with_authorisation(db_session, bulk_env, monkeypatch, tmp_path)
    teacher = spent.seeded.teacher
    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=bulk_env)
        stopping = service.stop(service.get_run(spent.run_id), teacher_id=teacher.id)
        assert stopping.status == "stopping"
    finally:
        session.close()
    final = drain(spent.run_id, settings=bulk_env, provider=spent.provider)
    precondition(final.status == "stopped", f"a stop request must end in 'stopped': {final}")
    assert final.calls_used == spent.limit == spent.provider.total_calls

    with pytest.raises(BulkEvaluationError, match="student identifier.*already exist"):
        import_zip(
            db_session,
            seeded=spent.seeded,
            corpus=spent.corpus,
            provider=spent.provider,
            settings=bulk_env,
            maximum_provider_calls=spent.need + 2,
            register=False,
        )
    resumed, refusal = try_resume_run(spent.run_id, teacher, settings=bulk_env)
    assert not resumed and refusal == _EXHAUSTED_REFUSAL
    session = SessionLocal()
    try:
        service = BulkEvaluationService(session, settings=bulk_env)
        run = service.get_run(spent.run_id)
        graded = [
            int(item.grade_suggestion_id)
            for item in run.items
            if item.status == "graded" and item.grade_suggestion_id is not None
        ]
        with pytest.raises(BulkEvaluationError, match="not ready for teacher approval"):
            service.approve_clean(
                run,
                suggestion_ids=graded,
                review_snapshot_sha256=service.review_snapshot_hash(run),
                teacher_id=teacher.id,
            )
        with pytest.raises(HTTPException) as export:
            download_bulk_results(spent.run_id, session, teacher)
        assert export.value.status_code == 409
    finally:
        session.close()
    assert len(graded) == 30
    # ... and a SEPARATE assessment is the documented way out: it re-reads every page
    other = seed_assessment(db_session, questions=6)
    rerun = import_zip(
        db_session,
        seeded=other,
        corpus=spent.corpus,
        provider=spent.provider,
        settings=bulk_env,
        maximum_provider_calls=spent.need + 2,
    )
    assert rerun.id != spent.run_id and rerun.total_pages == 40
    emit(
        "exhaustion_exit_cost",
        graded_drafts_stranded=len(graded),
        page_reads_to_repeat=rerun.total_pages,
        calls_spent_on_stranded_run=spent.limit,
        calls_needed_for_the_rerun=spent.need,
    )


# --------------------------------------------------------------------------- kill between units


class KillAtUnit:
    """``timed_drain(after_unit=...)``: the worker dies right AFTER unit ``n`` committed.

    The kill is between units on purpose (never mid-call): the known dispatched-page and
    killed-mid-grading defects belong to other probes. ``ProcessKilled`` is a ``BaseException``,
    so no production ``except Exception`` can absorb it.
    """

    def __init__(self, unit: int | None) -> None:
        self.unit = unit
        self.fired: list[int] = []

    def __call__(self, units_done: int, _record: UnitRecord) -> None:
        if self.unit is not None and units_done == self.unit:
            self.fired.append(units_done)
            raise ProcessKilled()


@dataclass
class Converged:
    """The end state of one pipeline execution, comparable between runs (ids excluded)."""

    items: dict[tuple[str, str], tuple[Any, ...]]
    digest: str
    calls: dict[str, int]
    calls_used: int
    status: str
    units: dict[str, int]
    suggestion_rows: int
    jobs: int
    max_suggestions_per_item: int
    max_reads_per_page: int
    kills: int
    wall_s: float


def item_ledger(db: Session, run_id: int) -> dict[tuple[str, str], tuple[Any, ...]]:
    """``(student, question) -> (status, stage, codes, calls, suggestions, jobs, score, conf)``."""

    db.expire_all()
    rows = db.execute(
        select(
            Submission.student_identifier,
            Question.question_no,
            BulkEvaluationItem.status,
            BulkEvaluationItem.stage,
            BulkEvaluationItem.exception_codes,
            BulkEvaluationItem.provider_call_count,
            BulkEvaluationItem.answer_region_id,
            BulkEvaluationItem.grade_suggestion_id,
        )
        .join(Submission, Submission.id == BulkEvaluationItem.submission_id)
        .join(Question, Question.id == BulkEvaluationItem.question_id)
        .where(BulkEvaluationItem.run_id == run_id)
    ).all()
    suggestions = Counter(db.scalars(select(GradeSuggestion.answer_region_id)).all())
    jobs = Counter(db.scalars(select(GradingJob.answer_region_id)).all())
    drafts = {
        row.id: (str(row.score), str(row.confidence))
        for row in db.scalars(select(GradeSuggestion)).all()
    }
    return {
        (student, question): (
            status,
            stage,
            tuple(codes or ()),
            calls,
            suggestions[region],
            jobs[region],
            *drafts.get(suggestion_id, (None, None)),
        )
        for student, question, status, stage, codes, calls, region, suggestion_id in rows
    }


Restart = str  # "redrain": the queue re-delivers the job; "resume": the teacher presses Resume


def pipeline(
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    corpus: Corpus,
    *,
    kill_read_units: Sequence[int] = (),
    kill_grade_units: Sequence[int] = (),
    restart: Restart = "redrain",
) -> Converged:
    """The whole flow on a fresh database; optionally kill the worker at unit boundaries.

    ``kill_read_units`` / ``kill_grade_units`` list, per kill, the 1-based unit number WITHIN the
    drain that follows the previous restart (each restart counts from 1 again). After a kill the
    run is restarted the way production would restart it: ``redrain`` calls ``run_next`` again
    (the queue delivers the next job), ``resume`` ages the run's heartbeat and presses the real
    ``resume`` (the teacher's recovery button).
    """

    purge_database(db)
    seeded = seed_assessment(db, questions=len(corpus.labels))
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, bulk_env)
    run = import_zip(db, seeded=seeded, corpus=corpus, provider=provider, settings=bulk_env)
    run_id = run.id
    kills = 0
    units: dict[str, int] = {"read": 0, "grade": 0}
    started = time.perf_counter()

    def drive(phase: str, kill_units: Sequence[int]) -> None:
        nonlocal kills
        for attempt in range(len(kill_units) + 1):
            killer = KillAtUnit(kill_units[attempt] if attempt < len(kill_units) else None)
            try:
                with SqlCounter() as sql:
                    result = timed_drain(
                        run_id,
                        settings=bulk_env,
                        provider=provider,
                        sql=sql,
                        after_unit=killer,
                    )
            except ProcessKilled:
                kills += 1
                units[phase] += killer.fired[0]
                db.expire_all()
                state = db.get(BulkEvaluationRun, run_id)
                precondition(
                    state is not None and state.status in {"reading", "grading", "mapping"},
                    f"after a kill between units the run must still look active: {state}",
                )
                if restart == "resume":
                    age_run_heartbeat(db, run_id)
                    resumed, refusal = try_resume_run(run_id, seeded.teacher, settings=bulk_env)
                    precondition(resumed, f"resume refused after a between-units kill: {refusal}")
                continue
            units[phase] += result.result.units
            return
        raise HarnessError(f"the {phase} stage did not settle after {len(kill_units)} kills")

    drive("read", kill_read_units)
    gate = review_all_transcripts(db, run_id, seeded.teacher)
    precondition(not gate.refused, f"gate refused: {gate.refused}")
    resumed_items = resume_all_items(run_id, seeded.teacher, settings=bulk_env)
    precondition(not resumed_items.refused, f"resume refused: {resumed_items.refused}")
    drive("grade", kill_grade_units)
    wall = time.perf_counter() - started

    views = item_views(db, run_id)
    ledger = item_ledger(db, run_id)
    db.expire_all()
    final = db.get(BulkEvaluationRun, run_id)
    assert final is not None
    reads = Counter(call.image_sha256 for call in provider.calls_of("read_page"))
    return Converged(
        items=ledger,
        digest=item_digest(views),
        calls=dict(provider.counts),
        calls_used=final.calls_used,
        status=final.status,
        units=units,
        suggestion_rows=int(db.scalar(select(func.count(GradeSuggestion.id))) or 0),
        jobs=int(db.scalar(select(func.count(GradingJob.id))) or 0),
        max_suggestions_per_item=max(entry[4] for entry in ledger.values()),
        max_reads_per_page=max(reads.values()),
        kills=kills,
        wall_s=round(wall, 2),
    )


def kill_plan(students: int, questions: int, kind: str, seed: int = 150) -> dict[str, list[int]]:
    """Two kills per stage, as per-drain unit numbers (a clean drain is scripts + 1, items + 1).

    ``seeded``: random boundaries strictly inside each drain. ``edges``: right after the very
    first unit, and then just before the finishing unit of the restarted drain.
    """

    rng = random.Random(seed)
    plan: dict[str, list[int]] = {}
    for phase, total in (("read", students + 1), ("grade", students * questions + 1)):
        if kind == "edges":
            plan[phase] = [1, total - 1 - 1]  # after unit 1; then before the finishing unit
        else:
            first = rng.randint(2, total - 4)
            second = rng.randint(1, total - first - 2)
            plan[phase] = [first, second]
    return plan


def assert_converged(clean: Converged, killed: Converged, *, label: str) -> None:
    assert killed.kills == 4, f"{label}: all four kills must have fired, not {killed.kills}"
    assert clean.status == killed.status == "review_ready", (clean.status, killed.status)
    # same end state, item by item: status, stage, codes, calls, suggestion/job rows, score
    assert set(clean.items) == set(killed.items)
    differing = {key for key in clean.items if clean.items[key] != killed.items[key]}
    assert not differing, f"{label}: {len(differing)} items differ, e.g. " + str(
        [(key, clean.items[key], killed.items[key]) for key in sorted(differing)[:2]]
    )
    assert clean.digest == killed.digest
    # no repeated provider work and no double drafts
    assert killed.calls == clean.calls, (clean.calls, killed.calls)
    assert killed.calls_used == clean.calls_used == sum(clean.calls.values())
    assert killed.max_reads_per_page == 1 and clean.max_reads_per_page == 1
    assert killed.max_suggestions_per_item == 1 and killed.suggestion_rows == clean.suggestion_rows
    assert killed.jobs == clean.jobs
    # the killed worker did not redo a unit: same total number of units
    assert killed.units == clean.units, (clean.units, killed.units)


def converge_matrix(
    students: int,
    db: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Uninterrupted baseline, then every (restart, plan) variant with four kills each."""

    questions = 6
    corpus = build_zip(tmp_path / "resilience.zip", students=students, pages=4, questions=questions)
    clean = pipeline(db, bulk_env, monkeypatch, corpus)
    precondition(clean.status == "review_ready", f"the baseline must finish: {clean.status}")
    for restart in ("redrain", "resume"):
        for kind in ("seeded", "edges"):
            plan = kill_plan(students, questions, kind)
            killed = pipeline(
                db,
                bulk_env,
                monkeypatch,
                corpus,
                kill_read_units=plan["read"],
                kill_grade_units=plan["grade"],
                restart=restart,
            )
            emit(
                "resilience",
                students=students,
                restart=restart,
                plan_kind=kind,
                plan=plan,
                clean_units=clean.units,
                killed_units=killed.units,
                clean_wall_s=clean.wall_s,
                killed_wall_s=killed.wall_s,
                calls=killed.calls,
                digest=killed.digest,
                suggestion_rows=killed.suggestion_rows,
            )
            assert_converged(clean, killed, label=f"n{students}/{restart}/{kind}")
    assert clean.calls["read_page"] == students * 4
    assert clean.calls["grade"] == students * questions


def test_a_worker_killed_between_units_converges_to_the_uninterrupted_result_small(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """6 students x 4 pages x 6 questions; four kills (two per stage), four restart variants."""

    converge_matrix(6, db_session, bulk_env, monkeypatch, tmp_path)


@scale_only
def test_a_worker_killed_between_units_converges_to_the_uninterrupted_result_30_students(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The moderate-scale resilience scenario: 30 students x 4 pages x 6 questions."""

    converge_matrix(30, db_session, bulk_env, monkeypatch, tmp_path)


def test_the_convergence_check_is_not_vacuous() -> None:
    """Seed each kind of divergence into a copy of a result and watch the comparator catch it."""

    base = Converged(
        items={("S001", "Q1"): ("graded", "review", (), 1, 1, 1, "4.00", "0.9500")},
        digest="d",
        calls={"read_page": 4, "map": 0, "grade": 1},
        calls_used=5,
        status="review_ready",
        units={"read": 2, "grade": 2},
        suggestion_rows=1,
        jobs=1,
        max_suggestions_per_item=1,
        max_reads_per_page=1,
        kills=4,
        wall_s=0.0,
    )
    assert_converged(base, replace(base), label="identical")
    seeded_faults = {
        "a different draft score": {
            "items": {("S001", "Q1"): ("graded", "review", (), 1, 1, 1, "3.00", "0.9500")}
        },
        "an item left pending": {
            "items": {("S001", "Q1"): ("pending", "grading", (), 0, 0, 0, None, None)}
        },
        "a page read twice": {"max_reads_per_page": 2},
        "a duplicate draft": {"max_suggestions_per_item": 2},
        "one more provider call": {"calls": {"read_page": 5, "map": 0, "grade": 1}},
        "a redone unit": {"units": {"read": 3, "grade": 2}},
        "a run that never finished": {"status": "paused"},
        "a kill that never fired": {"kills": 3},
    }
    for label, change in seeded_faults.items():
        with pytest.raises(AssertionError):
            assert_converged(base, replace(base, **change), label=label)
