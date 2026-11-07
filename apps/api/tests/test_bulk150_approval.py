"""Approval and export probes for the bulk supervised pipeline (role ``pa``).

Everything here drives the REAL path with the synthetic harness (fake brain, no network):
ZIP intake -> page read -> teacher transcript gate -> draft grading -> ``review_ready``, and then
the teacher's approval surface. Teacher actions go through the real HTTP routes with a
``TestClient`` (a real bearer token for the harness teacher), because that is exactly what the
web UI calls: ``GET /bulk-evaluation-runs/{id}`` for the hash it shows, ``POST .../approve-clean``,
``POST /grade-suggestions/{id}/approve|edit|reject``, ``GET .../results.xlsx``.

A test marked ``xfail(strict=True, raises=AssertionError, reason="GAP <root_cause_key>: ...")``
asserts the CORRECT behaviour and fails today. A GAP test contains exactly one kind of plain
``assert``: the desired-behaviour assertion. Every setup check goes through
:func:`tests.bulk150_harness.precondition` (``pytest.fail`` is not an ``AssertionError``), so a
broken scenario is a real FAILURE and never a silent wrong-reason XFAIL.

Unmarked tests are regression tests for behaviour that is already right (REFUTED probes) or
characterisations that pin a current behaviour whose rightness is a product decision
(POLICY_QUESTION probes). Nothing here edits production code.
"""

from __future__ import annotations

import csv
import json
import re
import threading
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import create_access_token
from app.core.config import Settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerEvidenceAssignment,
    AuditLog,
    BulkEvaluationRun,
    FinalGrade,
    GradeSuggestion,
    Question,
    ScriptTranscriptBlock,
    Submission,
    User,
)
from app.services.bulk_evaluation_service import BulkEvaluationService
from app.services.final_grade_service import FinalGradeService, neutralize_formula_cells
from packages.brain.schemas import GradeSuggestionOutput
from tests.bulk150_harness import (  # noqa: F401
    Corpus,
    DrainResult,
    FakeBulkBrainProvider,
    Fault,
    Seeded,
    assert_no_final_grades,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    drain,
    harness_storage,
    import_zip,
    install_fake_brain,
    item_views,
    precondition,
    precondition_faults_fired,
    resume_all_items,
    review_all_transcripts,
    seed_assessment,
)

API_ROOT = Path(__file__).resolve().parents[1]
STUDENTS = ("S001", "S002", "S003")


# --------------------------------------------------------------------------- scenario helpers


@dataclass
class Ctx:
    db: Session
    settings: Settings
    seeded: Seeded
    corpus: Corpus
    provider: FakeBulkBrainProvider
    run_id: int
    last_drain: DrainResult | None = None

    @property
    def teacher(self) -> User:
        return self.seeded.teacher


def _rewrite_manifest_names(archive: Path, names: Mapping[str, str]) -> None:
    """Replace ``student_name`` in the archive's manifest.csv, keyed by student identifier.

    ``build_zip`` always writes ``Student <identifier>``, which can never start with a spreadsheet
    trigger character, so a probe that needs hostile names has to rewrite the manifest itself.
    """

    with zipfile.ZipFile(archive) as source:
        members = {info.filename: source.read(info) for info in source.infolist()}
    precondition("manifest.csv" in members, "the synthetic archive has no manifest.csv to rewrite")
    rows = list(csv.DictReader(StringIO(members["manifest.csv"].decode("utf-8"))))
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["source", "student_identifier", "student_name"])
    for row in rows:
        identifier = row["student_identifier"]
        writer.writerow([row["source"], identifier, names.get(identifier, row["student_name"])])
    members["manifest.csv"] = buffer.getvalue().encode("utf-8")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as target:
        for name, content in members.items():
            target.writestr(name, content)


def _start(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    students: int = 3,
    questions: int = 2,
    pages: int = 2,
    manifest_names: Mapping[str, str] | None = None,
    **corpus_kwargs: Any,
) -> Ctx:
    seeded = seed_assessment(db, questions=questions)
    corpus = build_zip(
        tmp_path / "bulk.zip", students=students, pages=pages, questions=questions, **corpus_kwargs
    )
    if manifest_names is not None:
        _rewrite_manifest_names(corpus.archive_path, manifest_names)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, settings)
    run = import_zip(db, seeded=seeded, corpus=corpus, provider=provider, settings=settings)
    return Ctx(db, settings, seeded, corpus, provider, run.id)


def _no_final_grades(db: Session, run_id: int) -> None:
    """:func:`assert_no_final_grades` as a PRECONDITION (a bare assert would be absorbed)."""

    try:
        assert_no_final_grades(db, run_id)
    except AssertionError as exc:
        pytest.fail(f"PRECONDITION BROKEN: a final grade exists before the teacher acted: {exc}")


def _review_ready(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    before_grading: Callable[[Ctx], None] | None = None,
    expect_exceptions: int | None = 0,
    require_review_ready: bool = True,
    **kwargs: Any,
) -> Ctx:
    """Intake -> read -> teacher gate -> resume -> grade, up to ``review_ready``.

    ``expect_exceptions=None`` skips the graded-draft count (a probe whose fix may quarantine
    the item must not turn into a broken precondition); ``require_review_ready=False`` also
    skips the final-status check and leaves the settled drain in ``ctx.last_drain``.
    """

    ctx = _start(db, settings, monkeypatch, tmp_path, **kwargs)
    first = drain(ctx.run_id, settings=settings, provider=ctx.provider, strict_harness=True)
    precondition(
        first.status == "completed_with_exceptions",
        f"read stage did not settle as expected: {first}",
    )
    _no_final_grades(db, ctx.run_id)
    reviewed = review_all_transcripts(db, ctx.run_id, ctx.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    resumed = resume_all_items(ctx.run_id, ctx.teacher, settings=settings)
    precondition(not resumed.refused, f"resume refused: {resumed.refused}")
    _no_final_grades(db, ctx.run_id)
    if before_grading is not None:
        before_grading(ctx)
    final = drain(ctx.run_id, settings=settings, provider=ctx.provider, strict_harness=True)
    ctx.last_drain = final
    if not require_review_ready:
        return ctx
    precondition(final.status == "review_ready", f"grading did not reach review_ready: {final}")
    views = item_views(db, ctx.run_id)
    graded = [v for v in views.values() if v.status == "graded"]
    if expect_exceptions is not None:
        precondition(
            len(graded) == len(views) - expect_exceptions,
            f"expected {len(views) - expect_exceptions} graded drafts, got "
            f"{[(k, v.status, v.codes) for k, v in views.items() if v.status != 'graded']}",
        )
    precondition(
        all(call.verdict.startswith("ok") for call in ctx.provider.calls_of("grade")),
        "a grade call did not see clean evidence",
    )
    _no_final_grades(db, ctx.run_id)
    return ctx


class Api:
    """The teacher's HTTP surface, with a real bearer token (what the web UI sends)."""

    def __init__(self, teacher: User) -> None:
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(teacher)}"}

    def run(self, run_id: int) -> dict[str, Any]:
        response = self.client.get(f"/bulk-evaluation-runs/{run_id}", headers=self.headers)
        precondition(response.status_code == 200, f"GET run failed: {response.text}")
        return response.json()

    def approve_clean(self, run_id: int, ids: list[int], snapshot: str) -> Any:
        return self.client.post(
            f"/bulk-evaluation-runs/{run_id}/approve-clean",
            headers=self.headers,
            json={
                "suggestion_ids": ids,
                "review_snapshot_sha256": snapshot,
                "teacher_confirmed": True,
            },
        )

    def finalize(self, kind: str, suggestion_id: int, **body: Any) -> Any:
        return self.client.post(
            f"/grade-suggestions/{suggestion_id}/{kind}", headers=self.headers, json=body
        )

    def results(self, run_id: int) -> Any:
        return self.client.get(f"/bulk-evaluation-runs/{run_id}/results.xlsx", headers=self.headers)

    def correct_block(self, block_id: int, text: str) -> Any:
        return self.client.patch(
            f"/script-transcript-blocks/{block_id}",
            headers=self.headers,
            json={"edited_text": text, "reason": "synthetic teacher fix"},
        )


def ui_clean_ids(run_json: dict[str, Any]) -> list[int]:
    """The ids the web UI posts: BulkEvaluationClient.tsx ``cleanSuggestionIds`` (L189-201)."""

    return [
        item["grade_suggestion_id"]
        for item in run_json["items"]
        if item["status"] == "graded"
        and item["grade_suggestion_id"] is not None
        and item["final_grade_id"] is None
        and not item["exception_codes"]
    ]


def _suggestion_id(ctx: Ctx, student: str, question: str) -> int:
    view = item_views(ctx.db, ctx.run_id)[(student, question)]
    precondition(view.suggestion_id is not None, f"{student}/{question} has no draft")
    assert view.suggestion_id is not None
    return view.suggestion_id


def _run(ctx: Ctx) -> BulkEvaluationRun:
    ctx.db.expire_all()
    run = ctx.db.get(BulkEvaluationRun, ctx.run_id)
    precondition(run is not None, f"run {ctx.run_id} does not exist")
    assert run is not None
    return run


def _final_grade_count(db: Session) -> int:
    db.expire_all()
    return int(db.scalar(select(func.count(FinalGrade.id))) or 0)


def _audit_events(db: Session) -> list[str]:
    db.expire_all()
    return [row.event_type for row in db.scalars(select(AuditLog).order_by(AuditLog.id)).all()]


@contextmanager
def _service(settings: Settings) -> Iterator[tuple[BulkEvaluationService, Session]]:
    """A fresh session + the real service, the way a request or worker unit gets one."""

    db = SessionLocal()
    try:
        yield BulkEvaluationService(db, settings=settings, storage=harness_storage(settings)), db
    finally:
        db.rollback()
        db.close()


def _stored_hash(ctx: Ctx) -> str | None:
    return _run(ctx).review_snapshot_sha256


# =========================================================================== PA-1
# The hash the UI posts is the one the run read returns. Since RC-01 was fixed the read routes
# compute it live (the stored value dates from the end of processing), so a per-item
# finalization, which drops that item from the clean set, no longer wedges the bulk approval.


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        pytest.param("approve", {}, id="approve"),
        pytest.param("edit", {"final_score": "3.00"}, id="edit"),
        pytest.param("reject", {"teacher_comment": "no"}, id="reject"),
    ],
)
def test_pa1_hash_shown_by_the_run_survives_an_individual_finalization(
    kind: str,
    body: dict[str, Any],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    before = api.run(ctx.run_id)
    precondition(len(ui_clean_ids(before)) == 6, "expected six clean drafts offered")

    one = _suggestion_id(ctx, "S001", "Q1")
    done = api.finalize(kind, one, **body)
    precondition(done.status_code in (200, 201), f"per-item {kind} failed: {done.text}")

    # The teacher refreshes the page: exactly what the UI does before pressing the button.
    after = api.run(ctx.run_id)
    ids = ui_clean_ids(after)
    precondition(len(ids) == 5 and one not in ids, f"the UI should now offer 5 drafts: {ids}")
    precondition(after["status"] == "review_ready", f"run status moved: {after['status']}")

    response = api.approve_clean(ctx.run_id, ids, after["review_snapshot_sha256"])
    assert response.status_code == 200, f"{response.status_code} {response.text}"


def test_pa1_control_a_freshly_computed_hash_is_accepted_after_an_individual_finalization(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The run read publishes the hash the service computes NOW, not the stored one."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    one = _suggestion_id(ctx, "S001", "Q1")
    assert api.finalize("approve", one).status_code == 201
    shown = api.run(ctx.run_id)["review_snapshot_sha256"]

    with _service(bulk_env) as (service, db):
        run = service.get_run(ctx.run_id)
        fresh = service.review_snapshot_hash(run)
        ids = [
            int(item.grade_suggestion_id)
            for item in service._reviewable_items(db, run)  # noqa: SLF001
        ]
        assert len(ids) == 5
        assert shown == fresh
        assert run.review_snapshot_sha256 != fresh  # the stored value is stale; not shown
        approved, already, snapshot = service.approve_clean(
            run, suggestion_ids=ids, review_snapshot_sha256=fresh, teacher_id=ctx.teacher.id
        )
    assert (approved, already, snapshot) == (5, 0, fresh)
    assert _final_grade_count(ctx.db) == 6
    assert _run(ctx).status == "completed"


def test_pa1b_run_completes_when_every_draft_was_finalized_individually(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    for student in STUDENTS:
        for question in ("Q1", "Q2"):
            done = api.finalize("approve", _suggestion_id(ctx, student, question))
            precondition(done.status_code == 201, f"per-item approve failed: {done.text}")
    run = api.run(ctx.run_id)
    precondition(ui_clean_ids(run) == [], "nothing should be left for the bulk approval")
    precondition(_final_grade_count(ctx.db) == 6, "six final grades expected")

    # Every answer has a teacher-approved final grade; the bulk run should be done and exportable.
    export = api.results(ctx.run_id)
    assert (run["status"], export.status_code) == ("completed", 200), (
        f"run={run['status']!r} results.xlsx={export.status_code} {export.text}"
    )


def test_pa1c_the_approval_preview_lists_every_clean_draft_per_student_and_writes_nothing(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Founder decision 2026-10-12: a bulk approval shows a per-student summary first."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    one = _suggestion_id(ctx, "S001", "Q1")
    assert api.finalize("approve", one).status_code == 201
    run = api.run(ctx.run_id)
    response = api.client.get(
        f"/bulk-evaluation-runs/{ctx.run_id}/approval-preview", headers=api.headers
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["review_snapshot_sha256"] == run["review_snapshot_sha256"]
    assert (preview["student_count"], preview["draft_count"]) == (3, 5)
    assert sorted(row["suggestion_id"] for row in preview["rows"]) == sorted(ui_clean_ids(run))
    assert one not in {row["suggestion_id"] for row in preview["rows"]}
    first = preview["rows"][0]
    assert {"student_identifier", "question_label", "score", "max_score", "confidence"} <= set(
        first
    )
    assert [row["student_identifier"] for row in preview["rows"]] == sorted(
        row["student_identifier"] for row in preview["rows"]
    )
    assert _final_grade_count(ctx.db) == 1  # the preview wrote nothing

    approved = api.approve_clean(
        ctx.run_id,
        [row["suggestion_id"] for row in preview["rows"]],
        preview["review_snapshot_sha256"],
    )
    assert approved.status_code == 200, approved.text
    assert _final_grade_count(ctx.db) == 6
    after = api.client.get(
        f"/bulk-evaluation-runs/{ctx.run_id}/approval-preview", headers=api.headers
    )
    assert after.status_code == 409  # the run is completed: nothing left to approve


def test_pa1b_control_assessment_level_export_is_the_fallback_for_approved_grades(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The assessment-level export agrees with the bulk one after per-item approval."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    for student in STUDENTS:
        for question in ("Q1", "Q2"):
            assert (
                api.finalize("approve", _suggestion_id(ctx, student, question)).status_code == 201
            )
    assert api.results(ctx.run_id).status_code == 200  # the run completed (RC-02 fixed)
    assert "bulk_evaluation_completed_by_individual_review" in _audit_events(ctx.db)
    fallback = api.client.get(
        f"/assessments/{ctx.seeded.assessment.id}/export/final-grades.xlsx", headers=api.headers
    )
    assert fallback.status_code == 200
    rows = list(
        load_workbook(BytesIO(fallback.content))["Final Grades"].iter_rows(values_only=True)
    )
    assert len(rows) == 1 + 6


# =========================================================================== PA-2
# A draft goes stale after grading. Two ways:
# * flagged: the teacher corrects a transcript block through the route. The route supersedes the
#   draft, and (RC-04 fixed) its bulk item becomes a visible 'stale_evidence' exception, so it is
#   no longer offered for bulk approval.
# * unflagged: the evidence moves through a write site that does not supersede anything. The
#   draft still looks clean; (RC-03/RC-05 fixed) approve_clean checks every draft before writing,
#   refuses the whole batch naming the stale one, and writes nothing.


def _first_span_block(ctx: Ctx, student: str, question: str) -> ScriptTranscriptBlock:
    db = ctx.db
    db.expire_all()
    submission = db.scalar(select(Submission).where(Submission.student_identifier == student))
    question_row = db.scalar(select(Question).where(Question.question_no == question))
    precondition(submission is not None and question_row is not None, "student/question missing")
    assert submission is not None and question_row is not None
    assignment = db.scalar(
        select(AnswerEvidenceAssignment).where(
            AnswerEvidenceAssignment.submission_id == submission.id,
            AnswerEvidenceAssignment.question_id == question_row.id,
            AnswerEvidenceAssignment.is_current.is_(True),
        )
    )
    precondition(assignment is not None and assignment.spans, "no current evidence assignment")
    assert assignment is not None
    return sorted(assignment.spans, key=lambda span: span.order_index)[0].block


def _make_stale(ctx: Ctx, api: Api, student: str = "S002", question: str = "Q1") -> int:
    """Teacher corrects one block of ``student``'s ``question`` answer AFTER it was graded."""

    suggestion_id = _suggestion_id(ctx, student, question)
    block = _first_span_block(ctx, student, question)
    # The provenance token stays in the corrected text: only the evidence identity moves.
    done = api.correct_block(block.id, f"{block.effective_text} (teacher-corrected)")
    precondition(done.status_code == 200, f"block correction failed: {done.text}")
    db = ctx.db
    db.expire_all()
    suggestion = db.get(GradeSuggestion, suggestion_id)
    precondition(suggestion is not None, "suggestion vanished")
    assert suggestion is not None
    precondition(
        suggestion.source_evidence_fingerprint is not None,
        "the draft recorded no evidence fingerprint, so the staleness gate cannot fire",
    )
    precondition(suggestion.superseded_at is not None, "the correction did not supersede the draft")
    return suggestion_id


def _make_stale_unflagged(ctx: Ctx, student: str = "S002", question: str = "Q1") -> int:
    """Move the evidence behind a graded draft WITHOUT superseding it (a write site that forgot).

    Bumping the block revision changes the evidence fingerprint and nothing else.
    """

    suggestion_id = _suggestion_id(ctx, student, question)
    block = _first_span_block(ctx, student, question)
    block.revision = int(block.revision or 0) + 1
    ctx.db.commit()
    ctx.db.expire_all()
    suggestion = ctx.db.get(GradeSuggestion, suggestion_id)
    precondition(suggestion is not None and suggestion.superseded_at is None, "draft superseded")
    item = item_views(ctx.db, ctx.run_id)[(student, question)]
    precondition(item.status == "graded", f"expected the item to stay graded, got {item.status}")
    return suggestion_id


@dataclass
class StaleApproval:
    stale_id: int
    all_ids: list[int]
    posted_hash: str
    status_code: int
    detail: str


def _approve_all_with_one_stale(ctx: Ctx, api: Api) -> StaleApproval:
    """Post the exact six-draft snapshot the UI shows while S002/Q1 is (unflagged) stale."""

    stale_id = _make_stale_unflagged(ctx)
    run = api.run(ctx.run_id)
    all_ids = ui_clean_ids(run)
    precondition(len(all_ids) == 6 and stale_id in all_ids, f"snapshot has {all_ids}")
    precondition(
        any(sid < stale_id for sid in all_ids),
        "no draft sorts ahead of the stale one, so nothing would be committed before the refusal",
    )
    response = api.approve_clean(ctx.run_id, all_ids, run["review_snapshot_sha256"])
    detail = response.json().get("detail", "") if response.status_code >= 400 else ""
    return StaleApproval(
        stale_id, all_ids, run["review_snapshot_sha256"], response.status_code, str(detail)
    )


def test_pa2_a_refused_approve_clean_does_not_leave_a_partial_approval(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    result = _approve_all_with_one_stale(ctx, api)
    committed = _final_grade_count(ctx.db)
    run = _run(ctx)
    state = (
        f"HTTP {result.status_code} {result.detail!r}; FinalGrade rows committed={committed} of "
        f"{len(result.all_ids)}; run.status={run.status!r}; audit tail={_audit_events(ctx.db)[-3:]}"
    )
    assert result.status_code == 409, state
    assert committed == 0, state
    assert run.status == "review_ready", state
    assert "bulk_evaluation_clean_drafts_approved" not in _audit_events(ctx.db), state


def test_pa2_a_superseded_draft_is_not_offered_as_clean(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    stale_id = _make_stale(ctx, api)
    run = api.run(ctx.run_id)
    assert stale_id not in ui_clean_ids(run), (
        f"the UI would still offer superseded draft {stale_id} for approval: "
        f"{ui_clean_ids(run)}; run clean_item_count={run['clean_item_count']}"
    )
    item = next(i for i in run["items"] if i["grade_suggestion_id"] == stale_id)
    assert item["status"] == "exception"
    assert "stale_evidence" in item["exception_codes"]
    assert (run["clean_item_count"], run["exception_count"]) == (5, 1)
    # The remaining five are approvable with the hash the run shows.
    response = api.approve_clean(ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"])
    assert response.status_code == 200, response.text
    assert _final_grade_count(ctx.db) == 5


def test_pa2_the_remaining_drafts_can_be_approved_after_the_stale_one_is_rejected(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    first = _approve_all_with_one_stale(ctx, api)
    precondition(first.status_code == 409, f"expected the stale refusal, got {first.status_code}")
    rejected = api.finalize("reject", first.stale_id, teacher_comment="stale evidence")
    precondition(rejected.status_code == 201, f"reject of a stale draft failed: {rejected.text}")

    run = api.run(ctx.run_id)  # the teacher refreshes, as the error message tells them to
    ids = ui_clean_ids(run)
    precondition(len(ids) == 5, f"expected 5 remaining clean drafts, the UI offers {ids}")
    response = api.approve_clean(ctx.run_id, ids, run["review_snapshot_sha256"])
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    assert _final_grade_count(ctx.db) == 6


def test_pa2_the_stale_refusal_identifies_which_draft_is_stale(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    result = _approve_all_with_one_stale(ctx, api)
    precondition(
        result.status_code == 409 and "evidence" in result.detail.lower(),
        f"expected the stale-evidence refusal, got {result.status_code} {result.detail!r}",
    )
    assert "S002" in result.detail, result.detail
    assert re.search(r"\bQ1\b", result.detail) is not None, result.detail
    assert str(result.stale_id) in result.detail, result.detail
    assert "nothing was approved" in result.detail.lower(), result.detail


def test_pa2_a_failure_inside_the_write_loop_still_writes_nothing(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A draft that passes the pre-check and is then refused while writing (a race) rolls the
    whole batch back: the earlier final grades of the same batch are not kept."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    original = FinalGradeService.approve_suggestion
    calls: list[int] = []

    def refuse_the_fourth(self: FinalGradeService, suggestion_id: int, *args: Any, **kwargs: Any):
        calls.append(suggestion_id)
        if len(calls) == 4:
            raise HTTPException(status_code=409, detail="synthetic race: evidence moved")
        return original(self, suggestion_id, *args, **kwargs)

    monkeypatch.setattr(FinalGradeService, "approve_suggestion", refuse_the_fourth)
    run = api.run(ctx.run_id)
    response = api.approve_clean(ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"])
    precondition(len(calls) == 4, f"the write loop should have reached the 4th draft: {calls}")
    assert response.status_code == 409, response.text
    assert "nothing was approved" in response.json()["detail"].lower()
    assert _final_grade_count(ctx.db) == 0
    assert _run(ctx).status == "review_ready"
    assert all(view.status == "graded" for view in item_views(ctx.db, ctx.run_id).values())


def test_pa2_a_superseded_draft_whose_item_was_not_quarantined_is_still_never_approvable(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Defence in depth: whatever write site superseded a draft without quarantining its item,
    the approval set (and its hash) leaves the draft out."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    stale_id = _suggestion_id(ctx, "S002", "Q2")
    suggestion = ctx.db.get(GradeSuggestion, stale_id)
    precondition(suggestion is not None, "draft missing")
    assert suggestion is not None
    suggestion.superseded_at = datetime.now(UTC)
    suggestion.superseded_reason = "synthetic write site"
    ctx.db.commit()
    precondition(
        item_views(ctx.db, ctx.run_id)[("S002", "Q2")].status == "graded",
        "the item must stay graded for this probe",
    )
    preview = api.client.get(
        f"/bulk-evaluation-runs/{ctx.run_id}/approval-preview", headers=api.headers
    ).json()
    ids = [row["suggestion_id"] for row in preview["rows"]]
    assert stale_id not in ids and len(ids) == 5, ids
    response = api.approve_clean(ctx.run_id, ids, preview["review_snapshot_sha256"])
    assert response.status_code == 200, response.text
    assert _final_grade_count(ctx.db) == 5


def test_pa2_the_refusal_names_every_stale_draft_at_once(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """All drafts are checked before anything is written, so one refusal lists every stale one
    (the teacher does not discover them one refresh at a time)."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    first = _make_stale_unflagged(ctx, "S001", "Q2")
    second = _make_stale_unflagged(ctx, "S003", "Q1")
    run = api.run(ctx.run_id)
    response = api.approve_clean(ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"])
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "2 draft(s)" in detail and str(first) in detail and str(second) in detail, detail
    assert _final_grade_count(ctx.db) == 0


def test_pa2_characterisation_what_a_teacher_can_and_cannot_do_with_a_stale_draft(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pins the recovery surface for a draft superseded by a transcript correction."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    stale_id = _make_stale(ctx, api)

    # Per-item approve/edit of a stale draft is refused at the irreversible step ...
    approve = api.finalize("approve", stale_id)
    edit = api.finalize("edit", stale_id, final_score="2.00")
    assert approve.status_code == 409 and "evidence" in approve.json()["detail"].lower()
    assert edit.status_code == 409
    assert _final_grade_count(ctx.db) == 0

    # ... the per-item batch route skips only the stale one and names it in its errors ...
    ids = sorted(int(i["grade_suggestion_id"]) for i in api.run(ctx.run_id)["items"])
    batch = api.client.post(
        f"/assessments/{ctx.seeded.assessment.id}/final-grades/approve-selected",
        headers=api.headers,
        json={"grade_suggestion_ids": ids},
    )
    body = batch.json()
    assert batch.status_code == 200
    assert (body["approved_count"], body["failed_count"]) == (5, 1)
    assert str(stale_id) in body["errors"][0]

    # ... and rejecting the stale draft is allowed (recording a rejection of stale evidence).
    rejected = api.finalize("reject", stale_id, teacher_comment="stale")
    assert rejected.status_code == 201
    assert _final_grade_count(ctx.db) == 6


def test_pa2_a_stale_exception_can_be_resumed_and_is_regraded_on_the_current_evidence(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Since RC-04 the stale item is an exception, so Resume re-grades it (one more call)."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    stale_id = _make_stale(ctx, api)
    # The correction reopened the transcript gate: the teacher confirms the corrected transcript.
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    with _service(bulk_env) as (service, db):
        run = service.get_run(ctx.run_id)
        item = next(i for i in run.items if i.grade_suggestion_id == stale_id)
        service.resume_item(run, item, teacher_id=ctx.teacher.id)
    settled = drain(ctx.run_id, settings=bulk_env, provider=ctx.provider, strict_harness=True)
    assert settled.status == "review_ready", settled
    view = item_views(ctx.db, ctx.run_id)[("S002", "Q1")]
    assert view.status == "graded"
    assert view.suggestion_id is not None and view.suggestion_id != stale_id
    run_json = api.run(ctx.run_id)
    ids = ui_clean_ids(run_json)
    assert len(ids) == 6 and stale_id not in ids
    response = api.approve_clean(ctx.run_id, ids, run_json["review_snapshot_sha256"])
    assert response.status_code == 200, response.text
    assert _final_grade_count(ctx.db) == 6


# =========================================================================== PA-3
# Replay / double submit. REFUTED for duplicates: the second identical POST creates nothing.
# It is also NOT an idempotent success: it is refused with 409 (see the characterisation).


def _low_confidence(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
    return output.model_copy(update={"confidence": Decimal("0.40")})


def _event_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in _audit_events(db):
        counts[event] = counts.get(event, 0) + 1
    return counts


def test_pa3_replaying_approve_clean_on_a_completed_run_creates_nothing_twice(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    ids, posted = ui_clean_ids(run), run["review_snapshot_sha256"]

    first = api.approve_clean(ctx.run_id, ids, posted)
    assert first.status_code == 200
    assert (first.json()["approved_count"], first.json()["already_approved_count"]) == (6, 0)
    grades = ctx.db.scalars(select(FinalGrade).order_by(FinalGrade.id)).all()
    ids_before = [fg.id for fg in grades]
    audit_before = _event_counts(ctx.db)
    assert audit_before["bulk_evaluation_clean_drafts_approved"] == 1
    assert audit_before["final_grade.approved"] == 6

    second = api.approve_clean(ctx.run_id, ids, posted)  # the double click / client retry
    assert second.status_code == 409
    assert "not ready for teacher approval" in second.json()["detail"]

    ctx.db.expire_all()
    assert [fg.id for fg in ctx.db.scalars(select(FinalGrade).order_by(FinalGrade.id)).all()] == (
        ids_before
    )
    assert _event_counts(ctx.db) == audit_before  # no second run-level or per-grade audit row
    assert _run(ctx).status == "completed"


def test_pa3_replaying_approve_clean_on_a_run_with_exceptions_is_refused_by_the_hash(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fault = Fault("grade", transform=_low_confidence, student="S003", question="Q2")
    ctx = _review_ready(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        before_grading=lambda c: c.provider.inject(fault),
        expect_exceptions=1,
    )
    precondition_faults_fired(ctx.provider)
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    ids, posted = ui_clean_ids(run), run["review_snapshot_sha256"]
    precondition(len(ids) == 5, f"expected five clean drafts and one exception: {ids}")

    first = api.approve_clean(ctx.run_id, ids, posted)
    assert first.status_code == 200
    assert _run(ctx).status == "completed_with_exceptions"
    count, audit = _final_grade_count(ctx.db), _event_counts(ctx.db)
    assert count == 5

    # The status gate now passes (completed_with_exceptions is allowed), so the replay reaches
    # the snapshot check. approve_clean stored the PRE-approval hash on the run, and the live
    # hash of the now-empty clean set differs, so the replay fails closed.
    second = api.approve_clean(ctx.run_id, ids, posted)
    assert second.status_code == 409
    assert second.json()["detail"] == "Clean draft set changed; refresh before approving"
    assert (_final_grade_count(ctx.db), _event_counts(ctx.db)) == (count, audit)


def test_pa3_approve_clean_of_another_teachers_run_is_a_404_and_changes_nothing(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    run = Api(ctx.teacher).run(ctx.run_id)
    stranger = User(
        name="Other Teacher",
        email=f"bulk150-other-{ctx.run_id}@example.invalid",
        password_hash="synthetic-only",
        role="teacher",
    )
    db_session.add(stranger)
    db_session.commit()
    response = Api(stranger).approve_clean(
        ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"]
    )
    assert response.status_code == 404
    assert _final_grade_count(ctx.db) == 0


def test_pa3_a_concurrent_double_submit_creates_each_final_grade_once(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED for duplicates: two simultaneous identical POSTs (a double click) race on the
    answer-region row locks; whichever interleaving happens, no grade or audit row is doubled.
    """

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    run = Api(ctx.teacher).run(ctx.run_id)
    ids, posted = ui_clean_ids(run), run["review_snapshot_sha256"]
    barrier = threading.Barrier(2)
    answers: list[tuple[int, str]] = []

    def post() -> None:
        api = Api(ctx.teacher)
        barrier.wait(timeout=30)
        response = api.approve_clean(ctx.run_id, ids, posted)
        answers.append((response.status_code, response.text[:120]))

    threads = [threading.Thread(target=post) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    precondition(len(answers) == 2, f"a request never returned: {answers}")

    # One request wins; the other is refused (hash moved under it, or the row was taken first).
    assert sorted(code for code, _ in answers) == [200, 409], answers
    ctx.db.expire_all()
    grades = ctx.db.scalars(select(FinalGrade)).all()
    assert len(grades) == 6
    assert len({fg.answer_region_id for fg in grades}) == 6  # one final grade per answer
    counts = _event_counts(ctx.db)
    assert counts["final_grade.approved"] == 6
    assert counts["bulk_evaluation_clean_drafts_approved"] == 1
    assert _run(ctx).status == "completed"


# =========================================================================== PA-5
# No FinalGrade without a teacher call.


def _spy_save_final_grade(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    original = FinalGradeService._save_final_grade  # noqa: SLF001

    def spy(self: FinalGradeService, **kwargs: Any) -> Any:
        calls.append({k: v for k, v in kwargs.items() if k != "suggestion"})
        return original(self, **kwargs)

    monkeypatch.setattr(FinalGradeService, "_save_final_grade", spy)
    return calls


def test_pa5_no_final_grade_exists_at_any_drain_stage_until_the_teacher_approves(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved = _spy_save_final_grade(monkeypatch)
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path)
    db = ctx.db
    assert_no_final_grades(db, ctx.run_id)  # right after intake

    first = drain(ctx.run_id, settings=bulk_env, provider=ctx.provider, strict_harness=True)
    assert first.status == "completed_with_exceptions"
    assert_no_final_grades(db, ctx.run_id)  # after the read stage

    reviewed = review_all_transcripts(db, ctx.run_id, ctx.teacher)
    assert not reviewed.refused
    assert_no_final_grades(db, ctx.run_id)  # after the teacher's transcript gate

    resumed = resume_all_items(ctx.run_id, ctx.teacher, settings=bulk_env)
    assert len(resumed.resumed) == 6
    assert_no_final_grades(db, ctx.run_id)  # after resume, before any grading call

    final = drain(ctx.run_id, settings=bulk_env, provider=ctx.provider, strict_harness=True)
    assert final.status == "review_ready"
    assert ctx.provider.counts["grade"] == 6
    assert_no_final_grades(db, ctx.run_id)  # after grading: 6 drafts, still needs_review=True
    assert saved == []  # nothing in the pipeline ever reached the final-grade writer

    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    approval = api.approve_clean(ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"])
    assert approval.status_code == 200
    assert [(c["approval_status"], c["teacher_id"]) for c in saved] == [
        ("approved", ctx.teacher.id)
    ] * 6


@pytest.mark.parametrize(
    "case", ["wrong_hash", "subset_of_ids", "foreign_id", "duplicate_id", "unconfirmed"]
)
def test_pa5_a_refused_or_malformed_approval_creates_no_final_grade(
    case: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved = _spy_save_final_grade(monkeypatch)
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    ids, posted = ui_clean_ids(run), run["review_snapshot_sha256"]
    body: dict[str, Any] = {
        "suggestion_ids": ids,
        "review_snapshot_sha256": posted,
        "teacher_confirmed": True,
    }
    expected = 409
    if case == "wrong_hash":
        body["review_snapshot_sha256"] = "0" * 64
    elif case == "subset_of_ids":
        body["suggestion_ids"] = ids[:-1]
    elif case == "foreign_id":
        body["suggestion_ids"] = [*ids[:-1], max(ids) + 1000]
    elif case == "duplicate_id":
        body["suggestion_ids"] = [*ids, ids[0]]
    else:
        body["teacher_confirmed"] = False
        expected = 422
    response = api.client.post(
        f"/bulk-evaluation-runs/{ctx.run_id}/approve-clean", headers=api.headers, json=body
    )
    assert response.status_code == expected, response.text
    assert saved == []
    assert_no_final_grades(ctx.db, ctx.run_id)
    assert _run(ctx).status == "review_ready"


# Every place app/ and packages/ may create a final grade, by a mechanical scan. The assertion
# is a backstop: a second writer has to be a conscious, reviewed decision.
_CREATION = re.compile(
    r"(?<!class )\bFinalGrade\(|insert\(\s*FinalGrade|INSERT\s+INTO\s+final_grades"
)
_CALLER = re.compile(
    r"\.(approve_suggestion|edit_suggestion|reject_suggestion|finalize_suggestion|"
    r"approve_selected_suggestions|_save_final_grade)\("
)


def _scan(pattern: re.Pattern[str]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for root in ("app", "packages"):
        for path in sorted((API_ROOT / root).rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    hits.append((path.relative_to(API_ROOT).as_posix(), number))
    return hits


def test_pa5_final_grades_are_constructed_in_exactly_one_place() -> None:
    hits = _scan(_CREATION)
    assert [path for path, _ in hits] == ["app/services/final_grade_service.py"], hits


def test_pa5_only_the_review_routes_and_approve_clean_call_the_final_grade_writer() -> None:
    callers = {path for path, _ in _scan(_CALLER)}
    assert callers == {
        "app/api/routes/final_grades.py",  # finalize / approve / edit / reject / approve-selected
        "app/services/bulk_evaluation_service.py",  # approve_clean
        "app/services/final_grade_service.py",  # the service's own delegation
    }, sorted(callers)


# =========================================================================== PA-6
# Approval audit completeness and data minimisation.


def test_pa6_approve_clean_audit_rows_name_the_actor_run_snapshot_and_drafts_without_text(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    ids, posted = ui_clean_ids(run), run["review_snapshot_sha256"]
    assert api.approve_clean(ctx.run_id, ids, posted).status_code == 200

    db = ctx.db
    db.expire_all()
    run_rows = db.scalars(
        select(AuditLog).where(AuditLog.event_type == "bulk_evaluation_clean_drafts_approved")
    ).all()
    assert len(run_rows) == 1
    row = run_rows[0]
    assert (row.actor_type, row.actor_id) == ("teacher", ctx.teacher.id)
    assert (row.entity_type, row.entity_id) == ("bulk_evaluation_run", ctx.run_id)
    payload = row.payload_json
    assert payload["review_snapshot_sha256"] == posted
    assert payload["suggestion_ids"] == sorted(ids)
    assert (payload["approved_count"], payload["already_approved_count"]) == (6, 0)

    grades = {fg.id: fg for fg in db.scalars(select(FinalGrade)).all()}
    final_rows = db.scalars(
        select(AuditLog).where(AuditLog.event_type == "final_grade.approved")
    ).all()
    assert len(final_rows) == 6
    assert {r.entity_id for r in final_rows} == set(grades)
    for audit in final_rows:
        assert (audit.actor_type, audit.actor_id) == ("teacher", ctx.teacher.id)
        assert audit.entity_type == "final_grade"
        assert audit.payload_json["suggestion_id"] in ids
        assert audit.payload_json["approval_status"] == "approved"
        assert audit.payload_json["upsert_created"] is True

    # Data minimisation: no transcript text, provenance token, student identifier or name in
    # ANY audit row of the run (the approval rows included).
    haystack = json.dumps([r.payload_json for r in db.scalars(select(AuditLog)).all()])
    for forbidden in ("SYN150", "answer for", "Student S", *STUDENTS):
        assert forbidden not in haystack, forbidden


# =========================================================================== PA-4
# The results workbook. ``build_results_workbook`` (bulk) and ``build_final_grades_workbook``
# (assessment level) write every string through ``Sheet.append``. openpyxl turns a string that
# STARTS WITH "=" into a formula cell (``data_type == 'f'``); a string starting with + - or @ stays
# an inert shared string in xlsx, so only "=" is a spreadsheet-formula risk here.

_FORMULA_LABEL = '=HYPERLINK("http://example.invalid/x","click")'
_EXPORT_SHEETS = ["Approved Scores", "Student Totals", "Exceptions", "Run Summary"]


def _load(content: bytes) -> Workbook:
    return load_workbook(BytesIO(content))  # formulas are read back as text, never evaluated


def _cells(workbook: Workbook) -> list[tuple[str, Any]]:
    return [
        (sheet.title, cell)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ]


def _formula_cells(content: bytes) -> list[str]:
    return [
        f"{title}!{cell.coordinate}={cell.value!r}"
        for title, cell in _cells(_load(content))
        if cell.data_type == "f"
    ]


def _raw_formula_elements(content: bytes) -> list[str]:
    """``<f>`` elements in the sheet XML: what Excel would actually evaluate on open."""

    found: list[str] = []
    with zipfile.ZipFile(BytesIO(content)) as package:
        for name in package.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                found.extend(re.findall(r"<f>([^<]*)</f>", package.read(name).decode("utf-8")))
    return found


def _package_text(content: bytes) -> str:
    """Every part of the xlsx package, decompressed (sheets, shared strings, properties)."""

    with zipfile.ZipFile(BytesIO(content)) as package:
        return "\n".join(
            package.read(name).decode("utf-8", "replace") for name in package.namelist()
        )


def _sheet_rows(content: bytes, sheet: str) -> list[tuple[Any, ...]]:
    return list(_load(content)[sheet].iter_rows(values_only=True))


def _approve_clean_and_export(ctx: Ctx, api: Api) -> bytes:
    run = api.run(ctx.run_id)
    ids = ui_clean_ids(run)
    precondition(ids, "no clean drafts to approve")
    approved = api.approve_clean(ctx.run_id, ids, run["review_snapshot_sha256"])
    precondition(
        approved.status_code == 200, f"approve-clean failed: {approved.status_code} {approved.text}"
    )
    exported = api.results(ctx.run_id)
    precondition(
        exported.status_code == 200, f"results.xlsx failed: {exported.status_code} {exported.text}"
    )
    return exported.content


def _one_exception(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    **kwargs: Any,
) -> Ctx:
    """Six drafts, five clean and S003/Q2 quarantined (low confidence): the run ends mixed."""

    fault = Fault("grade", transform=_low_confidence, student="S003", question="Q2")
    ctx = _review_ready(
        db,
        settings,
        monkeypatch,
        tmp_path,
        before_grading=lambda c: c.provider.inject(fault),
        expect_exceptions=1,
        **kwargs,
    )
    precondition_faults_fired(ctx.provider)
    return ctx


@pytest.mark.parametrize("scenario", ["identifier-from-folder-name", "student-name-from-manifest"])
def test_pa4a_a_student_label_starting_with_equals_is_not_exported_as_a_formula(
    scenario: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if scenario == "identifier-from-folder-name":
        ctx = _review_ready(
            db_session, bulk_env, monkeypatch, tmp_path, identifiers=("=S001", "S002", "S003")
        )
        needle = "S001"
    else:
        ctx = _review_ready(
            db_session,
            bulk_env,
            monkeypatch,
            tmp_path,
            manifest=True,
            manifest_names={"S001": _FORMULA_LABEL},
        )
        needle = "HYPERLINK"
    content = _approve_clean_and_export(ctx, Api(ctx.teacher))
    texts = [str(cell.value) for _, cell in _cells(_load(content))]
    precondition(
        any(needle in text for text in texts),
        f"the {scenario} label never reached the workbook, so a 'no formula' result is vacuous",
    )
    formulas = _formula_cells(content)
    assert not formulas, (
        f"{len(formulas)} cell(s) are live formulas, e.g. {formulas[:3]}; "
        f"raw <f> elements in the sheet XML: {_raw_formula_elements(content)[:3]}"
    )


def test_pa4a_control_plus_minus_at_prefixes_stay_inert_text_in_xlsx(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED for + - @: openpyxl only treats a leading '=' as a formula, the rest are strings."""

    names = {"-S001": "+1+1", "@S002": "-2+3", "S003": "@SUM(1+1)"}
    ctx = _review_ready(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        manifest=True,
        identifiers=tuple(names),
        manifest_names=names,
    )
    content = _approve_clean_and_export(ctx, Api(ctx.teacher))
    labels = {*names, *names.values()}
    cells = [(title, cell) for title, cell in _cells(_load(content)) if cell.value in labels]
    assert {cell.value for _, cell in cells} == labels  # every hostile label really is exported
    assert {cell.data_type for _, cell in cells} == {"s"}
    assert _formula_cells(content) == []
    assert _raw_formula_elements(content) == []


def test_pa4a_neutralize_formula_cells_only_turns_leading_equals_text_into_inert_strings() -> None:
    """The visible text is unchanged and every other cell keeps its type (numbers stay numeric)."""

    workbook = Workbook()
    sheet = workbook.active
    sheet.append([_FORMULA_LABEL, "=S001", "+1", "plain", 7, Decimal("2.5"), True])
    assert [cell.data_type for cell in sheet[1][:2]] == ["f", "f"]  # openpyxl's own behaviour
    neutralize_formula_cells(workbook)
    reloaded = _load(_save(workbook))
    cells = list(reloaded.active[1])
    assert [cell.value for cell in cells[:5]] == [_FORMULA_LABEL, "=S001", "+1", "plain", 7]
    assert [cell.data_type for cell in cells[:5]] == ["s", "s", "s", "s", "n"]
    assert cells[5].value == 2.5 and cells[5].data_type == "n"
    assert cells[6].value is True and cells[6].data_type == "b"
    assert _formula_cells(_save(workbook)) == []
    assert _raw_formula_elements(_save(workbook)) == []


def _save(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _feedback(text: str) -> Callable[[GradeSuggestionOutput], GradeSuggestionOutput]:
    def transform(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
        return output.model_copy(update={"feedback_to_student": text})

    return transform


def test_pa4a_model_feedback_is_not_exported_as_a_formula_by_the_assessment_export(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fault = Fault("grade", transform=_feedback(_FORMULA_LABEL), student="S001", question="Q1")
    ctx = _review_ready(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        before_grading=lambda c: c.provider.inject(fault),
    )
    precondition_faults_fired(ctx.provider)
    api = Api(ctx.teacher)
    done = api.finalize("approve", _suggestion_id(ctx, "S001", "Q1"))
    precondition(done.status_code == 201, f"per-item approve failed: {done.text}")
    export = api.client.get(
        f"/assessments/{ctx.seeded.assessment.id}/export/final-grades.xlsx", headers=api.headers
    )
    precondition(export.status_code == 200, f"assessment export failed: {export.text}")
    texts = [str(cell.value) for _, cell in _cells(_load(export.content))]
    precondition(any("HYPERLINK" in text for text in texts), "the model feedback never exported")
    formulas = _formula_cells(export.content)
    assert not formulas, f"live formula cell(s) from model-authored text: {formulas[:3]}"


def test_pa4b_policy_an_incomplete_student_row_carries_the_partial_approved_totals(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY_QUESTION: pins the current convention (partial total + an INCOMPLETE flag).

    The assessment-level summary uses the same convention
    (``test_final_grade_review_api.py::test_assessment_summary_keeps_new_ungraded_submission_separate``).
    Whether a gradebook paste of the ``approved_score`` column should be able to pick up a
    partial figure is a founder decision.
    """

    ctx = _one_exception(db_session, bulk_env, monkeypatch, tmp_path)
    content = _approve_clean_and_export(ctx, Api(ctx.teacher))
    assert _run(ctx).status == "completed_with_exceptions"
    totals = {row[0]: row for row in _sheet_rows(content, "Student Totals")[1:]}
    # (identifier, name, approved_score, approved_max_marks, approved_questions, expected, status)
    assert totals["S001"][2:] == (10, 10, 2, 2, "COMPLETE")
    assert totals["S003"][2:] == (5, 5, 1, 2, "INCOMPLETE")  # a partial 5/5, flagged INCOMPLETE
    rows = {(row[0], row[2]): row for row in _sheet_rows(content, "Approved Scores")[1:]}
    assert rows[("S003", "Q1")][4:6] == (5, "APPROVED")
    assert rows[("S003", "Q2")][4:6] == (None, "INCOMPLETE")  # the quarantined answer has no score


@pytest.mark.parametrize(
    ("kind", "body", "stored_status", "q2", "total", "open_exceptions"),
    [
        pytest.param(
            "edit",
            {"final_score": "3.00"},
            "edited",
            (3, "EDITED"),
            (8, 10, 2, 2, "COMPLETE"),
            [],
            id="edit",
        ),
        pytest.param(
            "reject",
            {"teacher_comment": "no"},
            "rejected",
            (None, "REJECTED"),
            (5, 5, 1, 2, "INCOMPLETE"),
            [("S003", "Q2")],
            id="reject",
        ),
    ],
)
def test_pa4c_policy_an_edited_answer_is_final_and_a_rejected_one_stays_incomplete(
    kind: str,
    body: dict[str, Any],
    stored_status: str,
    q2: tuple[Any, str],
    total: tuple[Any, ...],
    open_exceptions: list[tuple[str, str]],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY (founder decision 2026-10-12, RC-70): a teacher-edited grade is final and counts
    in the totals, labelled EDITED; a rejected draft is no grade, labelled REJECTED, and the
    student stays INCOMPLETE. The assessment-level export follows the same rule
    (``test_final_grade_review_api.py::test_export_xlsx_contains_headers_rows_and_safe_fields``).
    """

    ctx = _one_exception(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    cleared = api.approve_clean(ctx.run_id, ui_clean_ids(run), run["review_snapshot_sha256"])
    precondition(cleared.status_code == 200, f"approve-clean failed: {cleared.text}")
    done = api.finalize(kind, _suggestion_id(ctx, "S003", "Q2"), **body)
    precondition(done.status_code == 201, f"per-item {kind} of the exception failed: {done.text}")
    exported = api.results(ctx.run_id)
    precondition(exported.status_code == 200, f"results.xlsx failed: {exported.text}")

    final = ctx.db.scalar(select(FinalGrade).where(FinalGrade.id == done.json()["id"]))
    assert final is not None and final.approval_status == stored_status  # the teacher did decide
    rows = {(row[0], row[2]): row for row in _sheet_rows(exported.content, "Approved Scores")[1:]}
    row = rows[("S003", "Q2")]
    assert (row[4], row[5]) == q2
    assert row[7] == final.id  # the row carries the teacher's final_grade_id
    totals = {row[0]: row for row in _sheet_rows(exported.content, "Student Totals")[1:]}
    assert totals["S003"][2:] == total
    exceptions = _sheet_rows(exported.content, "Exceptions")[1:]
    assert [(row[0], row[1]) for row in exceptions] == open_exceptions


def test_pa4d_the_workbook_never_contains_answer_text(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: no transcript text, model summary, feedback or provenance token is exported."""

    ctx = _one_exception(db_session, bulk_env, monkeypatch, tmp_path)
    db = ctx.db
    db.expire_all()
    blocks = db.scalars(select(ScriptTranscriptBlock)).all()
    summaries = [
        str((s.raw_response_json or {}).get("detected_answer_summary"))
        for s in db.scalars(select(GradeSuggestion)).all()
    ]
    precondition(
        any("SYN150" in block.effective_text for block in blocks)
        and all("SYN150" in text for text in summaries)
        and len(summaries) == 6,
        "the answer text this probe looks for is not in the database, so absence is vacuous",
    )
    content = _approve_clean_and_export(ctx, Api(ctx.teacher))
    assert _load(content).sheetnames == _EXPORT_SHEETS
    precondition(
        len(_sheet_rows(content, "Approved Scores")) == 1 + 6
        and len(_sheet_rows(content, "Exceptions")) == 1 + 1,
        "the workbook is missing the rows that would carry answer text if it leaked",
    )
    haystack = _package_text(content)
    for forbidden in (
        "SYN150",
        "answer for",
        "Synthetic draft feedback",
        "synthetic grader verdict",
        "saw:",
        *(block.effective_text[:20] for block in blocks),
    ):
        assert forbidden not in haystack, forbidden


# =========================================================================== PA-7
# Score scale. The adapter re-validates every provider output (score >= 0, score <= the OUTPUT's
# max_score, breakdown sums to score), but nothing compares the output's max_score with the
# question's total_marks, and approval compares the final score only with the DRAFT's max_score.


def _declare_scale(
    score: str, max_score: str
) -> Callable[[GradeSuggestionOutput], GradeSuggestionOutput]:
    """A self-consistent draft on the wrong scale (the adapter's own validation passes it)."""

    def transform(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
        breakdown = [
            item.model_copy(
                update={"max_marks": Decimal(max_score), "awarded_marks": Decimal(score)}
            )
            for item in output.rubric_breakdown
        ]
        return output.model_copy(
            update={
                "score": Decimal(score),
                "max_score": Decimal(max_score),
                "rubric_breakdown": breakdown,
            }
        )

    return transform


def _grades_off_the_question_scale(db: Session) -> list[str]:
    db.expire_all()
    rows = db.execute(
        select(FinalGrade, GradeSuggestion, Question)
        .join(GradeSuggestion, GradeSuggestion.id == FinalGrade.suggestion_id)
        .join(Question, Question.id == GradeSuggestion.question_id)
    ).all()
    return [
        f"{question.question_no}: final_score={final.final_score} draft_max={suggestion.max_score} "
        f"question.total_marks={question.total_marks}"
        for final, suggestion, question in rows
        if suggestion.max_score != question.total_marks or final.final_score > question.total_marks
    ]


@pytest.mark.parametrize(
    ("score", "declared_max"),
    [
        pytest.param("10.00", "10.00", id="inflated-10-of-10-on-a-5-mark-question"),
        pytest.param("3.00", "3.00", id="deflated-3-of-3-on-a-5-mark-question"),
    ],
)
def test_pa7_a_draft_on_the_wrong_scale_never_becomes_an_approved_final_grade(
    score: str,
    declared_max: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fault = Fault(
        "grade", transform=_declare_scale(score, declared_max), student="S002", question="Q1"
    )
    ctx = _review_ready(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        before_grading=lambda c: c.provider.inject(fault),
        expect_exceptions=None,  # a fix may quarantine the draft: only the outcome is asserted
    )
    precondition_faults_fired(ctx.provider)
    precondition(
        ctx.seeded.questions["Q1"].total_marks == Decimal("5.00"), "Q1 is not a 5-mark question"
    )
    api = Api(ctx.teacher)
    run = api.run(ctx.run_id)
    ids = ui_clean_ids(run)
    approval = api.approve_clean(ctx.run_id, ids, run["review_snapshot_sha256"]) if ids else None
    precondition(
        approval is None or approval.status_code in (200, 409),
        f"approve-clean answered {approval.status_code if approval else None}",
    )
    export = api.results(ctx.run_id)
    row = None
    if export.status_code == 200:
        sheet = _sheet_rows(export.content, "Approved Scores")[1:]
        row = next((r for r in sheet if (r[0], r[2]) == ("S002", "Q1")), None)
    off_scale = _grades_off_the_question_scale(ctx.db)
    assert not off_scale, (
        f"approve-clean HTTP {approval.status_code if approval else None}; the item was offered "
        f"as clean: {run['clean_item_count']} clean items; off-scale approved grades: {off_scale}; "
        f"results.xlsx S002/Q1 row (student, name, question, max_marks, approved_score, "
        f"status)={row[:6] if row else None}"
    )


@pytest.mark.parametrize(
    "score",
    [pytest.param("9.00", id="score-above-its-own-max"), pytest.param("-1.00", id="negative")],
)
def test_pa7_control_provider_output_outside_its_own_scale_never_becomes_a_draft(
    score: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED for score > max / score < 0: the adapter re-validates and refuses the output.

    OBSERVATION, deliberately not asserted (it belongs to the pipeline-resilience area, and
    whether it is a defect is a policy call): the refused output does not quarantine the one item,
    the run is left ``paused`` ("502: AI provider failed: 1 validation error ...") until a teacher
    resumes it, so one malformed model reply stalls every remaining grading call of the run.
    """

    def corrupt(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
        return output.model_copy(update={"score": Decimal(score)})  # model_copy skips validation

    fault = Fault("grade", transform=corrupt, student="S002", question="Q1")
    ctx = _review_ready(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        before_grading=lambda c: c.provider.inject(fault),
        expect_exceptions=None,
        require_review_ready=False,
    )
    precondition_faults_fired(ctx.provider)
    db = ctx.db
    db.expire_all()
    out_of_range = [
        (s.id, s.score, s.max_score)
        for s in db.scalars(select(GradeSuggestion)).all()
        if s.score < 0 or s.score > s.max_score
    ]
    view = item_views(db, ctx.run_id)[("S002", "Q1")]
    assert out_of_range == [], f"drafts outside their own scale: {out_of_range}"
    assert view.status != "graded", f"S002/Q1 is {view.status}/{view.stage} {view.codes}"
    assert _final_grade_count(db) == 0


def test_pa7_control_a_teacher_edit_above_the_drafts_own_max_is_refused(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED for the per-item path: ``_save_final_grade`` bounds the score by the DRAFT's max."""

    ctx = _review_ready(db_session, bulk_env, monkeypatch, tmp_path)
    api = Api(ctx.teacher)
    suggestion_id = _suggestion_id(ctx, "S001", "Q1")
    over = api.finalize("edit", suggestion_id, final_score="5.01")
    assert over.status_code == 422
    assert "cannot exceed" in over.json()["detail"]
    assert _final_grade_count(ctx.db) == 0
    assert api.finalize("edit", suggestion_id, final_score="5.00").status_code == 201  # boundary
