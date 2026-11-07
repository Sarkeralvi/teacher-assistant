"""Evidence-integrity and grading-readiness probes for the Bulk Supervised pipeline (PC).

Every test drives the REAL pipeline through :mod:`tests.bulk150_harness` (fake brain provider,
synthetic archive, no network). A probe is one of

* a passing regression test that protects behaviour which is already right (REFUTED);
* a passing characterisation test that pins a policy the founder must decide (POLICY_QUESTION);
* an ``xfail(strict=True, raises=AssertionError)`` GAP test that asserts the DESIRED behaviour and
  fails today because of a production defect.

A GAP test has exactly one kind of plain ``assert``: the desired-behaviour assertion. Every other
setup check (the Fault fired, the run reached the state the scenario needs, a helper's own
expectation) goes through :func:`tests.bulk150_harness.precondition`, whose ``pytest.fail`` is not
an ``AssertionError`` and therefore shows up as a real FAILURE instead of an xfail for the wrong
reason. ``precondition`` is never called inside a Fault callback (``Failed`` is a
``BaseException`` and would unwind mid-unit like a killed worker); callbacks only record state.

The fake grader has an ORACLE (it knows ``corpus.expected_tokens``) and rates incomplete or wrong
evidence 0.40, which production then quarantines. A real model cannot know what text is missing,
so wherever a probe is about evidence the desired assertion sits at the EVIDENCE stage (before
grading), or a ``Fault('grade', transform=...)`` forces the clean 0.95 a real grader would give.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.questions import create_question, update_question
from app.api.routes.rubrics import create_rubric, update_rubric
from app.api.routes.script_transcripts import (
    correct_script_transcript_block,
    override_script_transcript_block_assignment,
    rederive_answer_evidence,
)
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import (
    AnswerEvidenceAssignment,
    BulkEvaluationItem,
    BulkEvaluationRun,
    FinalGrade,
    GradeSuggestion,
    GradingRun,
    Question,
    Rubric,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import (
    QuestionCreate,
    QuestionUpdate,
    RubricCreate,
    RubricUpdate,
    ScriptTranscriptBlockAssignmentUpdate,
    ScriptTranscriptBlockUpdate,
)
from app.services.answer_evidence_assignment import AnswerEvidenceAssignmentService
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.evidence_invalidation import EvidenceInvalidationService
from app.services.grading_service import GradingService
from app.services.local_script_page_read import LocalScriptPageReadService
from app.services.local_script_preparation import LocalScriptPreparationService
from app.services.transcript_review import transcript_review_is_current
from packages.brain.llama_cpp_qwen38_vision_provider import (
    LlamaCppQwen38VisionProvider,
    _Qwen38GradePayload,
    _Qwen38RubricItem,
)
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem
from packages.brain.schemas_qwen38 import VisualPageTranscriptOutput
from packages.ocr import coverage as ink_coverage
from tests.bulk150_harness import (  # noqa: F401
    UNASSIGNED_QUESTION,
    BlockSpec,
    Corpus,
    DrainResult,
    FakeBulkBrainProvider,
    Fault,
    PageSpec,
    Seeded,
    assert_every_answered_question_graded,
    assert_no_cross_student_evidence,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    common_students,
    drain,
    drop_block,
    harness_storage,
    import_zip,
    install_fake_brain,
    item_views,
    other_session,
    parse_tokens,
    precondition,
    precondition_faults_fired,
    render_page_png,
    resume_all_items,
    review_all_transcripts,
    seed_assessment,
    token,
    try_resume_run,
)

# =========================================================================== local helpers


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
    questions: int | list[str] = 2,
    budget_slack: int = 4,
    corpus_builder: Callable[[Path], Corpus] | None = None,
    managed_local_phase: str | None = None,
    **corpus_kwargs: Any,
) -> Ctx:
    """Seed, build the archive, install the fake brain, import (real ``create_from_zip``).

    ``corpus_builder`` (given the archive path) replaces ``build_zip`` for hand-built layouts.
    ``managed_local_phase="Qwen38"`` makes the fake take the real model lease around every
    operation, which is what enables the evidence-changed recheck in ``GradingService``.
    """

    seeded = seed_assessment(db, questions=questions)
    corpus = (
        corpus_builder(tmp_path / "pc.zip")
        if corpus_builder is not None
        else build_zip(
            tmp_path / "pc.zip",
            students=students,
            pages=pages,
            questions=questions,
            **corpus_kwargs,
        )
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
    )
    return Ctx(db, settings, seeded, corpus, provider, run.id)


def _read_stage(ctx: Ctx) -> DrainResult:
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _gate(ctx: Ctx) -> None:
    """The teacher gate through the real route functions; a refusal is a broken PRECONDITION."""

    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused, f"the teacher gate refused: {reviewed.refused}")
    resumed = resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(not resumed.refused, f"resume_item refused: {resumed.refused}")


def _grade_stage(ctx: Ctx) -> DrainResult:
    return drain(ctx.run_id, settings=ctx.settings, provider=ctx.provider)


def _run(ctx: Ctx) -> BulkEvaluationRun:
    ctx.db.expire_all()
    run = ctx.db.get(BulkEvaluationRun, ctx.run_id)
    if run is None:
        pytest.fail(f"PRECONDITION BROKEN: run {ctx.run_id} does not exist")
    return run


def _submission_id(db: Session, student: str) -> int:
    row = db.scalar(select(Submission.id).where(Submission.student_identifier == student))
    if row is None:
        pytest.fail(f"PRECONDITION BROKEN: no submission for {student}")
    return int(row)


def _transcript(db: Session, student: str) -> ScriptTranscript:
    db.expire_all()
    row = db.scalar(
        select(ScriptTranscript)
        .where(
            ScriptTranscript.submission_id == _submission_id(db, student),
            ScriptTranscript.status != "superseded",
        )
        .order_by(ScriptTranscript.id.desc())
    )
    if row is None:
        pytest.fail(f"PRECONDITION BROKEN: no transcript for {student}")
    return row


def _block(db: Session, student: str, page_no: int, block_index: int) -> ScriptTranscriptBlock:
    transcript = _transcript(db, student)
    page = next((p for p in transcript.pages if p.page_no == page_no), None)
    if page is None:
        pytest.fail(f"PRECONDITION BROKEN: {student} has no page {page_no}")
    block = next((b for b in page.blocks if b.block_index == block_index), None)
    if block is None:
        pytest.fail(f"PRECONDITION BROKEN: {student} p{page_no} has no block {block_index}")
    return block


def _current_assignments(db: Session, student: str) -> dict[str, AnswerEvidenceAssignment]:
    """``question label -> current assignment`` of the student's current transcript."""

    transcript = _transcript(db, student)
    result: dict[str, AnswerEvidenceAssignment] = {}
    for assignment in AnswerEvidenceAssignmentService(db).current_assignments(transcript.id):
        question = db.get(Question, assignment.question_id)
        assert question is not None
        result[question.question_no] = assignment
    return result


def _span_block_ids(assignment: AnswerEvidenceAssignment) -> list[int]:
    return [span.script_transcript_block_id for span in assignment.spans]


def _status_of(ctx: Ctx, student: str, question: str) -> tuple[str, str, tuple[str, ...]]:
    view = item_views(ctx.db, ctx.run_id)[(student, question)]
    return view.status, view.stage, view.codes


# =========================================================================== hand-built corpus

SAME = "<same as truth>"


@dataclass(frozen=True)
class Seg:
    """One block of a hand-built page: ``truth`` owns it, ``label`` is what the model reports."""

    truth: str  # canonical owner (``UNASSIGNED_QUESTION`` for writing nobody owns)
    label: str | None = SAME
    source: Literal["heading", "continuation", "inferred"] = "heading"
    cont: bool = False


def custom_corpus(
    path: Path,
    layouts: dict[str, list[list[Seg]]],
    *,
    labels: tuple[str, ...],
    size: tuple[int, int] = (480, 640),
) -> Corpus:
    """A corpus for layouts ``build_zip`` cannot express: ``layouts[student][page] = [Seg, ...]``.

    Blocks are stacked top-to-bottom in the order given, exactly as ``_page_blocks`` lays them
    out, and every block embeds its provenance token, so ``assert_no_cross_student_evidence``
    and the fake grader work unchanged.
    """

    specs: dict[tuple[str, int], PageSpec] = {}
    members: dict[str, bytes] = {}
    for student, pages in layouts.items():
        for page_no, segs in enumerate(pages, start=1):
            band = 900 // max(len(segs), 1)
            height = max(20, band - 20)
            blocks: list[BlockSpec] = []
            for index, seg in enumerate(segs):
                top = 50 + index * band
                reported = seg.truth if seg.label == SAME else seg.label
                blocks.append(
                    BlockSpec(
                        page_no=page_no,
                        block_no=index + 1,
                        owner=student,
                        question=seg.truth,
                        reported_label=reported,
                        label_source=seg.source,
                        continues_from_previous=seg.cont,
                        bbox=(100, top, 900, min(1000, top + height)),
                        text=f"{token(student, seg.truth, page_no, index + 1)} body {seg.truth}",
                    )
                )
            specs[(student, page_no)] = PageSpec(blocks=tuple(blocks))
            members[f"{student}/page{page_no}.png"] = render_page_png(
                specs[(student, page_no)], size
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for member, content in members.items():
            archive.writestr(member, content)
    students = tuple(layouts)
    return Corpus(
        archive_path=path,
        layout="images",
        labels=labels,
        students=students,
        sources={student: student for student in students},
        pages=specs,
        page_counts={student: len(layouts[student]) for student in students},
        names={student: f"Student {student}" for student in students},
        page_size=size,
    )


# =========================================================================== PC-3: leave unassigned


def _leave_unassigned(ctx: Ctx, student: str, block: ScriptTranscriptBlock) -> None:
    """What the review screen does for 'Leave unassigned': override with a null label, re-derive."""

    override_script_transcript_block_assignment(
        block.id,
        ScriptTranscriptBlockAssignmentUpdate(question_label=None, continues_from_previous=False),
        ctx.db,
        ctx.seeded.teacher,
    )
    rederive_answer_evidence(_submission_id(ctx.db, student), ctx.db, ctx.seeded.teacher)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP leave-unassigned-absorbed-by-previous-question: the review screen's 'Leave "
        "unassigned' sends question_label=null; effective_question_label then returns None and "
        "resolve_block_ownership (answer_evidence_assignment.py:230-239) treats the block as an "
        "unlabelled one that follows the question above it on the same page "
        "(same_page_reading_order), so the block is silently attached to the PREVIOUS question."
    ),
)
def test_leave_unassigned_does_not_attach_the_block_to_the_previous_question(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, pages=1, questions=2)
    _read_stage(ctx)
    q2_block = _block(ctx.db, "S001", 1, 1)  # page 1 reads [Q1 heading block, Q2 heading block]
    precondition(
        q2_block.question_label_raw == "Q2" and not q2_block.assignment_override_active,
        f"block 1 should be the un-overridden Q2 block: {q2_block.question_label_raw!r}",
    )
    before = _current_assignments(ctx.db, "S001")
    precondition(
        _span_block_ids(before["Q2"]) == [q2_block.id] and before["Q2"].state == "answer_present",
        "Q2 must own its own block before the override",
    )
    q2_block_id = q2_block.id

    _leave_unassigned(ctx, "S001", q2_block)

    after = _current_assignments(ctx.db, "S001")
    block = ctx.db.get(ScriptTranscriptBlock, q2_block_id)
    precondition(
        block is not None
        and block.assignment_override_active
        and block.teacher_question_label is None
        and block.effective_question_label is None,
        "the null-label override was not recorded",
    )
    owners = [label for label, item in after.items() if q2_block_id in _span_block_ids(item)]
    assert owners == [], (
        f"the block the teacher left unassigned is owned by {owners} "
        f"(bases: {[(s.assignment_basis) for s in after['Q1'].spans]})"
    )


def test_leave_unassigned_on_the_first_block_of_a_page_is_honoured(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """BOUNDS the defect above: with nothing before it the block stays unplaced, so the
    transcript confirmation is refused until the teacher assigns it."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, pages=1, questions=2)
    _read_stage(ctx)
    first_block = _block(ctx.db, "S001", 1, 0)
    first_id = first_block.id
    _leave_unassigned(ctx, "S001", first_block)
    after = _current_assignments(ctx.db, "S001")
    assert all(first_id not in _span_block_ids(item) for item in after.values())
    assert any(item.unassigned_block_count for item in after.values())
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    assert any("Assign every visible writing block" in v for v in reviewed.refused.values()), (
        reviewed
    )


# =========================================================================== PC-4: grade sanity


def _force_grade(
    *,
    score: str,
    max_score: str,
    confidence: Any = Decimal("0.95"),
    breakdown_max: str | None = None,
) -> Callable[[GradeSuggestionOutput], GradeSuggestionOutput]:
    """``Fault.transform`` that returns the grade a (mis)behaving real model could return.

    Built with ``model_copy(update=...)`` so that NOTHING is validated inside the fake: if the
    value is bad, it is ``BrainAdapter.grade_answer_region`` (adapter.py:381) that must say so.
    """

    def transform(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
        item = RubricBreakdownItem(
            criterion_id="accuracy",
            criterion="Accuracy",
            max_marks=Decimal(breakdown_max or max_score),
            awarded_marks=Decimal(score),
            reason="forced by the PC-4 probe",
            evidence=None,
            confidence=Decimal("0.95"),
        )
        return output.model_copy(
            update={
                "score": Decimal(score),
                "max_score": Decimal(max_score),
                "confidence": confidence,
                "rubric_breakdown": [item],
            }
        )

    return transform


def _grade_one_question_with(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transform: Callable[[GradeSuggestionOutput], GradeSuggestionOutput],
) -> tuple[Ctx, DrainResult]:
    ctx = _start(db, settings, monkeypatch, tmp_path, students=1, pages=1, questions=1)
    fault = ctx.provider.inject(Fault("grade", transform=transform, on_call=1))
    _read_stage(ctx)
    _gate(ctx)
    final = _grade_stage(ctx)
    precondition(fault.fired == 1, f"the grade transform fired {fault.fired} times")
    precondition(
        "transformed" in ctx.provider.calls_of("grade")[0].verdict, "the grade was not altered"
    )
    return ctx, final


def test_a_draft_scored_against_the_wrong_maximum_is_not_a_clean_draft(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx, final = _grade_one_question_with(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        _force_grade(score="8", max_score="10"),
    )
    question = ctx.seeded.questions["Q1"]
    precondition(Decimal(question.total_marks) == Decimal("5.00"), "Q1 must be a 5-mark question")
    precondition(final.status in {"review_ready", "completed_with_exceptions"}, f"run: {final}")
    suggestion = ctx.db.scalar(select(GradeSuggestion))
    precondition(
        suggestion is not None
        and suggestion.max_score == Decimal("10.00")
        and suggestion.score == Decimal("8.00"),
        "the forged 8/10 draft was not stored as such",
    )
    view = item_views(ctx.db, ctx.run_id)[("S001", "Q1")]
    assert view.status != "graded", (
        f"item is a CLEAN draft ({view.status}/{view.stage}, {list(view.codes)}) although "
        f"suggestion.max_score={suggestion.max_score} != "
        f"question.total_marks={question.total_marks}"
    )


def _approve_every_clean_draft(ctx: Ctx) -> tuple[int, int]:
    """The teacher's one-click 'approve clean drafts' (real ``approve_clean``)."""

    db = SessionLocal()
    try:
        service = BulkEvaluationService(db, settings=ctx.settings, storage=harness_storage())
        run = service.get_run(ctx.run_id)
        snapshot = service.review_snapshot_hash(run)
        ids = [
            int(item.grade_suggestion_id)
            for item in run.items
            if item.status == "graded" and item.grade_suggestion_id is not None
        ]
        approved, already, _ = service.approve_clean(
            run,
            suggestion_ids=ids,
            review_snapshot_sha256=snapshot,
            teacher_id=ctx.seeded.teacher.id,
        )
        return approved, already
    finally:
        db.close()


def test_no_final_score_can_exceed_the_marks_of_its_question(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx, final = _grade_one_question_with(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        _force_grade(score="8", max_score="10"),
    )
    precondition(final.status in {"review_ready", "completed_with_exceptions"}, f"run: {final}")
    _approve_every_clean_draft(ctx)
    ctx.db.expire_all()
    marks = Decimal(ctx.seeded.questions["Q1"].total_marks)
    over = [
        (row.id, row.final_score)
        for row in ctx.db.scalars(select(FinalGrade)).all()
        if row.final_score > marks
    ]
    assert over == [], f"FinalGrade rows above the question's {marks} marks: {over}"


@pytest.mark.parametrize(
    ("confidence", "expected_codes"),
    [
        pytest.param(Decimal("0.95"), ["provider_contract_failure"], id="confident-draft"),
        pytest.param(
            Decimal("0.40"),
            ["provider_contract_failure", "verification_disagreement"],
            id="low-confidence-draft",
        ),
    ],
)
def test_a_wrong_maximum_is_quarantined_with_a_visible_code_and_warning(
    confidence: Decimal,
    expected_codes: list[str],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """F02 regression: the wrong-scale draft is an exception item that names expected vs got, is
    kept for the teacher (suggestion linked, never offered as clean) and stays visible even when
    the low-confidence gate would have quarantined it anyway."""

    ctx, final = _grade_one_question_with(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        _force_grade(score="8", max_score="10", confidence=confidence),
    )
    precondition(final.status in {"review_ready", "completed_with_exceptions"}, f"run: {final}")
    item = _items(ctx, "S001")["Q1"]
    assert item.status == "exception"
    assert item.stage == "review"
    assert set(expected_codes) <= set(item.exception_codes or [])
    assert "Draft grade maximum mismatch: expected 5.00, got 10.00" in (item.warnings or [])
    assert item.grade_suggestion_id is not None
    assert item.final_grade_id is None
    approved, already = _approve_every_clean_draft(ctx)
    assert (approved, already) == (0, 0)
    ctx.db.expire_all()
    assert ctx.db.scalar(select(func.count()).select_from(FinalGrade)) == 0


def _pilot_payload(
    *, score: str = "5", max_score: str = "5", criterion_id: str = "accuracy", marks: str = "5"
) -> _Qwen38GradePayload:
    return _Qwen38GradePayload(
        score=Decimal(score),
        max_score=Decimal(max_score),
        confidence=Decimal("0.9"),
        rubric_breakdown=[
            _Qwen38RubricItem(
                criterion_id=criterion_id,
                criterion="Accuracy",
                criterion_status="met",
                max_marks=Decimal(marks),
                awarded_marks=Decimal(score),
                reason="synthetic",
                confidence=Decimal("0.9"),
            )
        ],
        detected_answer_summary="synthetic",
        major_errors=[],
        feedback_to_student="synthetic",
        review_flags=["synthetic"],
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"score": "8", "max_score": "10", "marks": "10"}, "changed the question maximum"),
        ({"criterion_id": "invented"}, "does not match the pinned rubric"),
        ({"marks": "4", "score": "4"}, "changed a pinned rubric criterion maximum"),
    ],
    ids=["wrong-maximum", "invented-criterion", "changed-criterion-maximum"],
)
def test_the_pilot_provider_rejects_a_grade_that_leaves_the_pinned_rubric(
    kwargs: dict[str, str], message: str
) -> None:
    """REFUTED for the pilot stack (severity context for the GAPs above): the real Qwen 3.8
    provider validates max_score against the question's marks and the breakdown against the
    pinned rubric before the adapter ever sees the grade, so those GAPs need a provider that
    skips this contract: the cloud/CLI profiles the bulk route also accepts (claude_cli,
    codex_cli, antigravity, openai) validate only ``GradeSuggestionOutput``."""

    rubric = {"total_marks": "5.00", "criteria": [{"id": "accuracy", "max_marks": "5.00"}]}
    assert _pilot_payload().score == Decimal("5")  # the unmodified payload is the valid case
    LlamaCppQwen38VisionProvider._validate_grade_contract(_pilot_payload(), Decimal("5"), rubric)
    with pytest.raises(ValueError, match=message):
        LlamaCppQwen38VisionProvider._validate_grade_contract(
            _pilot_payload(**kwargs), Decimal("5"), rubric
        )


MALFORMED_GRADES = [
    pytest.param({"confidence": "nan"}, id="confidence-nan-string"),
    pytest.param({"confidence": Decimal("NaN")}, id="confidence-nan-decimal"),
    pytest.param({"confidence": None}, id="confidence-none"),
    pytest.param({"confidence": Decimal("1.5")}, id="confidence-above-one"),
    pytest.param({"confidence": Decimal("-0.1")}, id="confidence-negative"),
    pytest.param({"confidence": "high"}, id="confidence-word"),
    pytest.param({"score": Decimal("11")}, id="score-above-own-max"),
    pytest.param({"max_score": Decimal("0")}, id="max-score-zero"),
    pytest.param({"score": None}, id="score-none"),
]


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")
@pytest.mark.parametrize("update", MALFORMED_GRADES)
def test_a_malformed_grade_is_rejected_and_never_stored_as_a_draft(
    update: dict[str, Any],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: NaN/None/out-of-range confidence and a score above the maximum are rejected by
    ``GradeSuggestionOutput.model_validate`` in the adapter. Nothing is stored, the item is
    quarantined 'uncertain' (never a clean draft) and the run pauses (fail closed)."""

    def transform(output: GradeSuggestionOutput) -> GradeSuggestionOutput:
        return output.model_copy(update=update)

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=1, pages=1, questions=1)
    fault = ctx.provider.inject(Fault("grade", transform=transform, on_call=1))
    _read_stage(ctx)
    _gate(ctx)
    final = _grade_stage(ctx)
    precondition(fault.fired == 1, "the malformed-grade transform never fired")
    call = ctx.provider.calls_of("grade")[0]
    precondition(call.outcome == "ok" and "transformed" in call.verdict, f"{call}")

    assert final.status == "paused", final
    assert ctx.db.scalar(select(func.count(GradeSuggestion.id))) == 0
    status, _stage, codes = _status_of(ctx, "S001", "Q1")
    assert (status, codes) == ("uncertain", ("provider_contract_failure",))
    assert ctx.db.scalar(select(func.count(FinalGrade.id))) == 0


# =========================================================================== PC-1: partial omission


def _blank_page_transform() -> Callable[[Any], Any]:
    """``Fault.transform``: the model declares a page that carries ink 'blank' (no blocks)."""

    def transform(output: Any) -> Any:
        del output
        return VisualPageTranscriptOutput(blocks=[], is_blank_page=True)

    return transform


def _count_ink_checks(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Counting delegates (behaviour unchanged) around every CPU ink-coverage entry point."""

    counts = {"assemble": 0, "detect_unassigned_content": 0, "measure_uncovered_ink": 0}
    original_assemble = LocalScriptPageReadService.assemble
    original_detect = LocalScriptPreparationService._detect_unassigned_content
    original_measure = ink_coverage.measure_uncovered_ink

    def assemble(self: Any, *args: Any, **kwargs: Any) -> Any:
        counts["assemble"] += 1
        return original_assemble(self, *args, **kwargs)

    def detect(self: Any, *args: Any, **kwargs: Any) -> Any:
        counts["detect_unassigned_content"] += 1
        return original_detect(self, *args, **kwargs)

    def measure(*args: Any, **kwargs: Any) -> Any:
        counts["measure_uncovered_ink"] += 1
        return original_measure(*args, **kwargs)

    monkeypatch.setattr(LocalScriptPageReadService, "assemble", assemble)
    monkeypatch.setattr(LocalScriptPreparationService, "_detect_unassigned_content", detect)
    monkeypatch.setattr(ink_coverage, "measure_uncovered_ink", measure)
    return counts


def _items(ctx: Ctx, student: str) -> dict[str, BulkEvaluationItem]:
    ctx.db.expire_all()
    rows = ctx.db.execute(
        select(BulkEvaluationItem, Question.question_no)
        .join(Question, Question.id == BulkEvaluationItem.question_id)
        .where(
            BulkEvaluationItem.run_id == ctx.run_id,
            BulkEvaluationItem.submission_id == _submission_id(ctx.db, student),
        )
    ).all()
    return {label: item for item, label in rows}


GENERIC_GATE_CODES = {"evidence_review_required"}


def _automatic_signals(ctx: Ctx, student: str) -> list[str]:
    """Anything beyond the generic 'a teacher must confirm the transcript' prompt that every
    item of every script carries: an extra exception code, or a warning that mentions ink."""

    signals: list[str] = []
    for label, item in _items(ctx, student).items():
        for code in item.exception_codes or []:
            if code not in GENERIC_GATE_CODES:
                signals.append(f"{label}: code {code}")
        for warning in item.warnings or []:
            if "ink" in warning.lower():
                signals.append(f"{label}: warning {warning!r}")
    return signals


def _stored_page_ink(ctx: Ctx, student: str, page_no: int, kept_blocks: list[int]) -> Any:
    """Positive control: run the real CPU detector on the STORED page image, with only the
    blocks the (faulty) read kept as 'covered' boxes."""

    submission_id = _submission_id(ctx.db, student)
    page = ctx.db.scalar(
        select(SubmissionPage).where(
            SubmissionPage.submission_id == submission_id, SubmissionPage.page_no == page_no
        )
    )
    precondition(page is not None, f"no stored page {student}/p{page_no}")
    assert page is not None
    raw = harness_storage(ctx.settings).resolve_relative(page.image_path).read_bytes()
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
    spec = ctx.corpus.page_spec(student, page_no)
    boxes = [
        (
            spec.blocks[i].bbox[0] * width / 1000,
            spec.blocks[i].bbox[1] * height / 1000,
            spec.blocks[i].bbox[2] * width / 1000,
            spec.blocks[i].bbox[3] * height / 1000,
        )
        for i in kept_blocks
    ]
    return ink_coverage.measure_uncovered_ink(raw, boxes, image_width=width, image_height=height)


def _partial_omission_ctx(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Ctx:
    """S001: Q1 = p1 + p2 + top of p3 (three blocks), Q2 = bottom of p3 + p4."""

    ctx = _start(db, settings, monkeypatch, tmp_path, students=2, pages=4, questions=2, spill=True)
    precondition(
        len(ctx.corpus.expected_tokens("S001", "Q1")) == 3
        and [b.question for b in ctx.corpus.page_spec("S001", 3).blocks] == ["Q1", "Q2"],
        "the corpus must hold Q1 in three blocks, with Q1's last block above Q2's on page 3",
    )
    return ctx


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP bulk-path-skips-ink-coverage-check: with prepare(persist_legacy_artifacts=False) "
        "(bulk_evaluation_service.py:1396) local_script_page_read.py:250-282 returns BEFORE "
        "assemble(), so the CPU 'uncovered ink' hard blocker (L619-633) never runs for a bulk "
        "read. One of three blocks of S001's Q1 is silently omitted although its ink is on the "
        "page: the item gets only the generic 'confirm the transcript' prompt."
    ),
)
def test_a_block_the_model_omitted_leaves_a_signal_before_grading(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _partial_omission_ctx(db_session, bulk_env, monkeypatch, tmp_path)
    counts = _count_ink_checks(monkeypatch)
    fault = ctx.provider.inject(Fault("read_page", transform=drop_block(0), on_call=3))
    _read_stage(ctx)
    bulk_counts = dict(counts)  # BEFORE the positive control below calls the detector itself
    precondition_faults_fired(ctx.provider)
    call = ctx.provider.calls_of("read_page")[2]
    precondition(
        call.students == ("S001",) and call.page_no == 3 and "transformed" in call.verdict,
        f"read #3 must be S001's page 3, altered: {call}",
    )
    precondition(fault.fired == 1 and len(call.tokens) == 1, f"tokens kept: {call.tokens}")
    # The omitted block is Q1's p3 block (above Q2's): the evidence for Q1 now has 2 of 3 blocks.
    assignments = _current_assignments(ctx.db, "S001")
    precondition(
        assignments["Q1"].state == "answer_present" and len(assignments["Q1"].spans) == 2,
        f"Q1 should hold exactly the two surviving blocks: {assignments['Q1'].state}",
    )
    # The page really carries ink outside the kept block, and the real detector sees it.
    coverage = _stored_page_ink(ctx, "S001", 3, kept_blocks=[1])
    precondition(
        coverage is not None
        and coverage.uncovered_pixels > 0
        and coverage.ratio > ctx.settings.local_script_unassigned_ink_warn_above,
        f"the CPU detector would flag the omitted block: {coverage and coverage.ratio}",
    )
    signals = _automatic_signals(ctx, "S001")
    codes = {k: v.exception_codes for k, v in _items(ctx, "S001").items()}
    assert signals, (
        "no automatic signal for S001 although a block is missing from its transcript; "
        f"ink-coverage entry points called on the bulk read path: {bulk_counts}; "
        f"item codes: {codes}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP bulk-path-skips-ink-coverage-check: end effect. The partial evidence (2 of 3 "
        "blocks) reaches a CLEAN graded draft with no exception code and no warning once the "
        "teacher confirms the transcript; a real grader cannot know a block is missing (the "
        "fake's oracle is replaced by a forced clean 0.95 grade)."
    ),
)
def test_partial_evidence_does_not_become_a_clean_unflagged_draft(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _partial_omission_ctx(db_session, bulk_env, monkeypatch, tmp_path)
    read_fault = ctx.provider.inject(Fault("read_page", transform=drop_block(0), on_call=3))
    ctx.provider.inject(
        Fault("grade", transform=_force_grade(score="5", max_score="5"), times=None)
    )
    _read_stage(ctx)
    precondition(read_fault.fired == 1, "the omission transform never fired")
    review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    _grade_stage(ctx)
    partial = [
        call
        for call in ctx.provider.calls_of("grade")
        if call.question == "Q1" and "S001" in call.students
    ]
    for call in partial:  # the scenario only means something if grading saw the partial text
        precondition(len(call.tokens) == 2, f"S001/Q1 grading saw {call.tokens}")
    item = _items(ctx, "S001")["Q1"]
    clean_and_silent = item.status == "graded" and not item.exception_codes and not item.warnings
    assert not clean_and_silent, (
        f"S001/Q1 is a clean graded draft (confidence {item.grading_confidence}) built from "
        f"{len(partial[0].tokens) if partial else '?'} of 3 blocks, with no code and no warning"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP bulk-path-skips-ink-coverage-check: a page falsely declared blank "
        "(is_blank_page=True, no blocks) although it carries ink is accepted as blank when the "
        "question also has evidence on other pages. S001's Q1 loses its middle page and stays "
        "answer_present."
    ),
)
def test_a_false_blank_middle_page_of_a_multi_page_answer_leaves_a_signal(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _partial_omission_ctx(db_session, bulk_env, monkeypatch, tmp_path)
    fault = ctx.provider.inject(Fault("read_page", transform=_blank_page_transform(), on_call=2))
    _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    call = ctx.provider.calls_of("read_page")[1]
    precondition(call.students == ("S001",) and call.page_no == 2, f"read #2: {call}")
    precondition(fault.fired == 1, "the blank transform fired more than once")
    assignments = _current_assignments(ctx.db, "S001")
    precondition(
        assignments["Q1"].state == "answer_present" and len(assignments["Q1"].spans) == 2,
        "Q1 should keep its page-1 and page-3 blocks only",
    )
    # The 'blank' page is not blank: the real CPU detector finds ink on the stored image.
    coverage = _stored_page_ink(ctx, "S001", 2, kept_blocks=[])
    precondition(coverage is not None and not coverage.is_blank, "page 2 holds no ink")
    signals = _automatic_signals(ctx, "S001")
    assert signals, "a page with ink was accepted as blank and nothing but the generic prompt shows"


def test_a_falsely_blank_only_page_fails_closed_as_missing_answer(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CONTRAST (REFUTED sub-claim): when the falsely-blank page held a question's ONLY
    evidence, that question is quarantined as ``missing_answer``; it can never be graded."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=2, questions=2)
    ctx.provider.inject(Fault("read_page", transform=_blank_page_transform(), on_call=2))
    _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    call = ctx.provider.calls_of("read_page")[1]
    precondition(call.students == ("S001",) and call.page_no == 2, f"read #2: {call}")
    assert _status_of(ctx, "S001", "Q2") == ("exception", "read", ("missing_answer",))
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused, f"gate: {reviewed.refused}")
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    _grade_stage(ctx)
    assert _status_of(ctx, "S001", "Q2") == ("exception", "read", ("missing_answer",))
    graded_q2 = [
        c for c in ctx.provider.calls_of("grade") if c.question == "Q2" and "S001" in c.students
    ]
    assert graded_q2 == []
    assert _status_of(ctx, "S002", "Q2")[0] == "graded"


def test_a_page_the_model_read_with_very_low_confidence_carries_no_signal(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY_QUESTION (low): ``ScriptTranscriptBlock.confidence`` is stored but nothing on the
    page-read path consults it (``bulk_transcription_auto_pass_min_confidence`` is applied only to
    the legacy ``_process_transcription`` stage, bulk_evaluation_service.py:2059). A page whose
    every block the model rates 0.05 therefore reaches a clean draft exactly like a 0.97 page.
    The mandatory transcript review is the only control; this pins that there is no extra flag."""

    def lose_confidence(output: VisualPageTranscriptOutput) -> VisualPageTranscriptOutput:
        blocks = [
            block.model_copy(update={"confidence": Decimal("0.05")}) for block in output.blocks
        ]
        return output.model_copy(update={"blocks": blocks})

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=2)
    fault = ctx.provider.inject(Fault("read_page", transform=lose_confidence, on_call=1))
    _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    call = ctx.provider.calls_of("read_page")[0]
    precondition(
        fault.fired == 1 and call.students == ("S001",),
        f"the first read must be S001's page: {call}",
    )
    precondition(
        {_block(ctx.db, "S001", 1, i).confidence for i in (0, 1)} == {Decimal("0.05")},
        "the stored blocks must carry the 0.05 confidence",
    )
    for item in _items(ctx, "S001").values():
        assert item.exception_codes == ["evidence_review_required"], item.exception_codes
    _gate(ctx)
    _grade_stage(ctx)
    for question in ("Q1", "Q2"):
        assert _status_of(ctx, "S001", question) == ("graded", "review", ())
    assert all(not item.warnings for item in _items(ctx, "S001").values())


# =========================================================================== PC-2: reference drift
# Nothing binds a bulk run to the reference bundle it was authorised with. ``reference_bundle_
# sha256`` is written at intake and read only for the duplicate-archive check
# (bulk_evaluation_service.py:172) and the workbook summary (L1232); ``_process_grading`` loads the
# ACTIVE rubric fresh for every item and pins ``expected_rubric_hash`` computed from those very
# rows a few lines earlier (L2233-2257), so that pin can only ever match. The only guard is the
# finalization-time fingerprint (``EvidenceInvalidationService``): it covers model answer, question
# text and rubric JSON but not ``total_marks``, and neither the question nor the rubric route ever
# calls ``supersede_stale_suggestions``.

SPLIT_RUBRIC: dict[str, Any] = {
    "total_marks": "5.00",
    "criteria": [
        {"id": "accuracy", "name": "Accuracy", "description": "Synthetic", "max_marks": "3.00"},
        {"id": "method", "name": "Method", "description": "Synthetic", "max_marks": "2.00"},
    ],
}
REFERENCE_EDITS = ["rubric_json", "new_rubric_version", "model_answer", "question_text"]


def _step(ctx: Ctx) -> bool:
    """One real ``run_next`` unit in a fresh session, exactly as the worker runs it.

    Grading is question-major (``order_by(question_id, id)``), so with one question every call
    grades the next student: this is how a probe stops between two students.
    """

    session = SessionLocal()
    try:
        service = BulkEvaluationService(
            session, settings=ctx.settings, storage=harness_storage(ctx.settings)
        )
        return service.run_next(ctx.run_id)
    finally:
        session.close()


def _edit_reference(ctx: Ctx, kind: str) -> None:
    """Edit Q1's reference material through the REAL route functions, as a teacher would."""

    db, teacher = ctx.db, ctx.seeded.teacher
    question = ctx.seeded.questions["Q1"]
    rubric = db.scalar(
        select(Rubric).where(Rubric.question_id == question.id, Rubric.is_active.is_(True))
    )
    precondition(rubric is not None, "Q1 has no active rubric to edit")
    assert rubric is not None
    if kind == "rubric_json":
        update_rubric(rubric.id, RubricUpdate(rubric_json=SPLIT_RUBRIC), db, teacher)
    elif kind == "new_rubric_version":
        update_rubric(rubric.id, RubricUpdate(is_active=False), db, teacher)
        create_rubric(
            question.id,
            RubricCreate(version=2, rubric_json=SPLIT_RUBRIC, is_active=True),
            db,
            teacher,
        )
    elif kind == "model_answer":
        update_question(
            question.id, QuestionUpdate(model_answer="A reworded model answer"), db, teacher
        )
    elif kind == "question_text":
        update_question(
            question.id,
            QuestionUpdate(question_text="SYNQ|Q1| Synthetic question Q1, reworded"),
            db,
            teacher,
        )
    else:
        pytest.fail(f"unknown reference edit {kind!r}")


def _bundle_hashes(ctx: Ctx) -> tuple[str, str]:
    """``(hash the run was authorised with, hash of the reference material right now)``."""

    run = _run(ctx)
    grading_run = ctx.db.get(GradingRun, run.grading_run_id)
    precondition(grading_run is not None, "the run's grading run is missing")
    assert grading_run is not None
    service = BulkEvaluationService(
        ctx.db, settings=ctx.settings, storage=harness_storage(ctx.settings)
    )
    return run.reference_bundle_sha256, service.reference_bundle_hash(
        run.assessment_id, grading_run
    )


def _finish_grading(ctx: Ctx) -> None:
    _read_stage(ctx)
    _gate(ctx)
    final = _grade_stage(ctx)
    precondition(final.status == "review_ready", f"expected a review-ready run: {final}")


def _approve_or_refusal(ctx: Ctx) -> HTTPException | None:
    """``approve_clean`` over the exact clean snapshot; the refusal when finalization says no.

    Since RC-03 the service pre-checks every draft and refuses the whole batch with a
    ``BulkEvaluationError`` (the route's 409) before anything is written.
    """

    try:
        _approve_every_clean_draft(ctx)
    except HTTPException as exc:
        ctx.db.rollback()
        return exc
    except BulkEvaluationError as exc:
        ctx.db.rollback()
        return HTTPException(status_code=409, detail=str(exc))
    return None


@pytest.mark.parametrize("kind", REFERENCE_EDITS)
def test_a_reference_edit_between_two_students_is_graded_without_any_signal(
    kind: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _read_stage(ctx)
    _gate(ctx)
    _step(ctx)  # grades S001/Q1 under the original reference
    views = item_views(ctx.db, ctx.run_id)
    precondition(
        views[("S001", "Q1")].status == "graded" and views[("S002", "Q1")].status == "pending",
        f"exactly S001 must be graded so far: {[(k, v.status) for k, v in views.items()]}",
    )
    authorised, before = _bundle_hashes(ctx)
    precondition(authorised == before, "the bundle hash moved before any edit")
    _edit_reference(ctx, kind)
    authorised_after, current = _bundle_hashes(ctx)
    precondition(
        authorised_after == authorised and current != authorised,
        f"the edit {kind!r} did not change the reference bundle hash",
    )
    _grade_stage(ctx)

    run = _run(ctx)
    items = {student: _items(ctx, student)["Q1"] for student in ("S001", "S002")}
    clean_hashes = {
        student: item.rubric_snapshot_sha256
        for student, item in items.items()
        if item.status == "graded"
    }
    signals = [
        *([f"run.status={run.status}"] if run.status in {"paused", "failed", "stopped"} else []),
        *([f"run.error={run.error!r}"] if run.error else []),
        *[
            f"{student}: {item.status} {item.exception_codes} {item.warnings}"
            for student, item in items.items()
            if item.exception_codes or item.warnings
        ],
    ]
    mixed = len(set(clean_hashes.values())) > 1
    assert not (mixed and not signals), (
        f"after the {kind!r} edit two clean drafts of Q1 carry different rubric snapshots "
        f"{ {k: v[:12] for k, v in clean_hashes.items()} } and the run authorised "
        f"{authorised[:12]} but now stands on {current[:12]}; run.status={run.status!r}, "
        f"no run-level or item-level signal"
    )


@pytest.mark.parametrize("kind", REFERENCE_EDITS)
def test_a_reference_edit_pauses_the_run_before_any_further_provider_call(
    kind: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The run stops BEFORE the next draft: no provider call, no budget spent, the remaining item
    untouched, a plain-language reason, and resuming without restoring the reference re-pauses."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _read_stage(ctx)
    _gate(ctx)
    _step(ctx)  # grades S001/Q1 under the original reference
    precondition(
        _status_of(ctx, "S001", "Q1")[0] == "graded"
        and _status_of(ctx, "S002", "Q1")[:2] == ("pending", "grading"),
        "exactly S001 must be graded so far",
    )
    grade_calls = ctx.provider.counts["grade"]
    calls_used = _run(ctx).calls_used
    _edit_reference(ctx, kind)

    assert _step(ctx) is False
    run = _run(ctx)
    assert run.status == "paused", run.status
    assert run.error is not None and "Reference materials" in run.error, run.error
    assert "restore them or start a new run" in run.error, run.error
    assert run.calls_used == calls_used
    assert ctx.provider.counts["grade"] == grade_calls
    second = _items(ctx, "S002")["Q1"]
    assert (second.status, second.stage) == ("pending", "grading")
    assert second.provider_call_count == 0
    assert second.grade_suggestion_id is None and second.grading_job_id is None
    assert not second.exception_codes

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"a paused run must be resumable: {refusal}")
    assert _step(ctx) is False
    again = _run(ctx)
    assert again.status == "paused" and again.calls_used == calls_used
    assert ctx.provider.counts["grade"] == grade_calls


@pytest.mark.parametrize("kind", ["rubric_json", "model_answer"])
def test_a_run_paused_by_a_reference_edit_resumes_once_the_reference_is_restored(
    kind: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _read_stage(ctx)
    _gate(ctx)
    _step(ctx)
    question = ctx.seeded.questions["Q1"]
    original_answer = question.model_answer
    rubric = ctx.db.scalar(
        select(Rubric).where(Rubric.question_id == question.id, Rubric.is_active.is_(True))
    )
    precondition(rubric is not None, "Q1 has no active rubric")
    assert rubric is not None
    rubric_id, original_rubric = rubric.id, dict(rubric.rubric_json)
    _edit_reference(ctx, kind)
    _step(ctx)
    precondition(_run(ctx).status == "paused", "the edit must pause the run")

    update_rubric(rubric_id, RubricUpdate(rubric_json=original_rubric), ctx.db, ctx.seeded.teacher)
    update_question(
        question.id, QuestionUpdate(model_answer=original_answer), ctx.db, ctx.seeded.teacher
    )
    authorised, current = _bundle_hashes(ctx)
    precondition(authorised == current, "restoring the edit must restore the bundle hash")
    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"a paused run must be resumable: {refusal}")
    final = _grade_stage(ctx)

    assert final.status == "review_ready", final
    items = {student: _items(ctx, student)["Q1"] for student in ("S001", "S002")}
    assert {item.status for item in items.values()} == {"graded"}
    assert len({item.rubric_snapshot_sha256 for item in items.values()}) == 1


def test_references_reopened_for_confirmation_mid_run_pause_the_run_before_the_next_draft(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Re-uploading or re-extracting the reference PDFs clears the questions/rubrics confirmation
    (grading_runs.py, reference_extraction_service.py). The bundle can then no longer be read as
    'confirmed', which is also a change: the run pauses instead of grading on unconfirmed
    references."""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _read_stage(ctx)
    _gate(ctx)
    _step(ctx)
    grade_calls = ctx.provider.counts["grade"]
    grading_run = ctx.db.get(GradingRun, _run(ctx).grading_run_id)
    precondition(grading_run is not None, "the run's grading run is missing")
    assert grading_run is not None
    grading_run.questions_confirmed_at = None
    grading_run.rubrics_confirmed_at = None
    ctx.db.commit()

    assert _step(ctx) is False
    run = _run(ctx)
    assert run.status == "paused" and "Reference materials" in (run.error or ""), run.error
    assert ctx.provider.counts["grade"] == grade_calls
    assert _status_of(ctx, "S002", "Q1")[:2] == ("pending", "grading")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP stale-draft-offered-as-clean-after-reference-edit: after the rubric / model answer / "
        "question text is edited the existing drafts are stale for the finalization gate, but "
        "nothing marks them (the question and rubric routes never call supersede_stale_"
        "suggestions, so superseded_at stays null) and _reviewable_items still offers them as "
        "clean, so approve_clean can only end in a 409 from the stale one."
    ),
)
@pytest.mark.parametrize("kind", REFERENCE_EDITS)
def test_a_draft_that_a_reference_edit_made_stale_is_not_offered_for_bulk_approval(
    kind: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _finish_grading(ctx)
    _edit_reference(ctx, kind)
    ctx.db.expire_all()
    guard = EvidenceInvalidationService(ctx.db)
    status_by_suggestion = {
        row.id: guard.suggestion_evidence_status(row)
        for row in ctx.db.scalars(select(GradeSuggestion)).all()
    }
    precondition(
        status_by_suggestion and set(status_by_suggestion.values()) == {"stale"},
        f"the fingerprint should treat both drafts as stale after {kind!r}: {status_by_suggestion}",
    )
    run = BulkEvaluationService(
        ctx.db, settings=ctx.settings, storage=harness_storage(ctx.settings)
    ).get_run(ctx.run_id)
    offered = [
        int(item.grade_suggestion_id)
        for item in BulkEvaluationService._reviewable_items(ctx.db, run)
        if item.grade_suggestion_id is not None
    ]
    stale_offered = [sid for sid in offered if status_by_suggestion.get(sid) != "current"]
    superseded = [
        row.id
        for row in ctx.db.scalars(select(GradeSuggestion)).all()
        if row.superseded_at is not None
    ]
    assert stale_offered == [], (
        f"drafts {stale_offered} are stale for the finalization gate ({status_by_suggestion}) "
        f"but are offered for bulk approval; superseded_at is set on {superseded}"
    )


@pytest.mark.parametrize("kind", REFERENCE_EDITS)
def test_a_reference_edit_after_grading_is_refused_at_finalization(
    kind: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED sub-claim: the edit IS caught, but only at the irreversible step. The fingerprint
    covers model answer, question text and rubric JSON/id/version, so ``approve_clean`` is refused
    with a 409 and no FinalGrade is written. (Visibility before that click: see the GAP above.)"""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _finish_grading(ctx)
    _edit_reference(ctx, kind)
    refusal = _approve_or_refusal(ctx)
    assert refusal is not None and refusal.status_code == 409, refusal
    assert "evidence" in str(refusal.detail).lower(), refusal.detail
    ctx.db.expire_all()
    assert ctx.db.scalar(select(func.count(FinalGrade.id))) == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP fingerprint-omits-question-total-marks: EvidenceInvalidationService."
        "fingerprint_for_region (evidence_invalidation.py:131-154) digests model answer, question "
        "text and rubric but NOT question.total_marks (rubric_snapshot_hash does). The question "
        "route lets a teacher change the marks without re-validating the rubric, so drafts graded "
        "out of 5 stay 'current' and approve_clean finalizes 5.00 on a question now worth 3."
    ),
)
def test_a_marks_edit_after_grading_is_not_finalized_against_the_old_marks(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _finish_grading(ctx)
    question = ctx.seeded.questions["Q1"]
    update_question(
        question.id, QuestionUpdate(total_marks=Decimal("3.00")), ctx.db, ctx.seeded.teacher
    )
    ctx.db.expire_all()
    suggestions = ctx.db.scalars(select(GradeSuggestion)).all()
    precondition(
        Decimal(ctx.db.get(Question, question.id).total_marks) == Decimal("3.00")  # type: ignore[union-attr]
        and {row.max_score for row in suggestions} == {Decimal("5.00")},
        "the drafts must be out of 5 while the question is now out of 3",
    )
    _approve_or_refusal(ctx)
    ctx.db.expire_all()
    marks = Decimal(ctx.db.get(Question, question.id).total_marks)  # type: ignore[union-attr]
    stale_finals = [
        (row.id, row.final_score)
        for row in ctx.db.scalars(select(FinalGrade)).all()
        if row.final_score > marks
        or ctx.db.get(GradeSuggestion, row.suggestion_id).max_score != marks  # type: ignore[union-attr]
    ]
    assert stale_finals == [], (
        f"FinalGrade rows {stale_finals} were finalized from drafts graded out of 5.00 although "
        f"the question is now worth {marks}"
    )


def test_a_rubric_deactivated_mid_run_fails_closed_and_the_item_can_be_resumed(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED sub-claim: with no active rubric ``_process_grading`` (L2233-2241) quarantines the
    item as ``stale_evidence`` and makes NO provider call; re-activating the rubric and resuming
    grades it. (A rubric that is replaced rather than removed is the GAP above.)"""

    ctx = _start(db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=1)
    _read_stage(ctx)
    _gate(ctx)
    _step(ctx)
    rubric = ctx.db.scalar(select(Rubric))
    precondition(rubric is not None, "no rubric")
    assert rubric is not None
    update_rubric(rubric.id, RubricUpdate(is_active=False), ctx.db, ctx.seeded.teacher)
    _grade_stage(ctx)
    assert _status_of(ctx, "S002", "Q1") == ("exception", "grading", ("stale_evidence",))
    assert [c.students for c in ctx.provider.calls_of("grade")] == [("S001",)]
    update_rubric(rubric.id, RubricUpdate(is_active=True), ctx.db, ctx.seeded.teacher)
    resumed = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    assert not resumed.refused and len(resumed.resumed) == 1, resumed
    _grade_stage(ctx)
    assert _status_of(ctx, "S002", "Q1")[0] == "graded"


# =========================================================================== PC-6: review gate
# The teacher's transcript confirmation is bound to a snapshot of every block's text, revision,
# label and override plus every assignment (transcript_review.current_review_snapshot), so any
# correction after the gate makes ``transcript_review_is_current`` false. ``_process_grading``
# (L2204-2218) and ``resume_item`` (L843-852) both re-check it.


def _correct_block(
    ctx: Ctx, student: str, page_no: int, block_index: int, suffix: str = " (teacher-corrected)"
) -> int:
    """A teacher correction through the real route; the provenance token stays in the text."""

    block = _block(ctx.db, student, page_no, block_index)
    block_id, text = block.id, block.effective_text
    correct_script_transcript_block(
        block_id,
        ScriptTranscriptBlockUpdate(edited_text=f"{text}{suffix}", reason="synthetic correction"),
        ctx.db,
        ctx.seeded.teacher,
    )
    return block_id


def _gated(db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Ctx:
    """Two students, one page, two questions: read, teacher gate, every item pending 'grading'."""

    ctx = _start(db, settings, monkeypatch, tmp_path, students=2, pages=1, questions=2)
    _read_stage(ctx)
    _gate(ctx)
    views = item_views(ctx.db, ctx.run_id)
    precondition(
        len(views) == 4
        and {(v.status, v.stage) for v in views.values()} == {("pending", "grading")},
        "every item must be waiting to be graded: "
        f"{[(k, v.status, v.stage) for k, v in views.items()]}",
    )
    return ctx


def test_a_block_corrected_after_the_gate_is_not_graded_and_cannot_be_resumed(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: with the items already waiting to be graded, a correction to ONE block of S001
    pulls both of S001's items back to ``evidence_review_required`` (the ``_process_grading``
    re-check), no provider call is made for them, and ``resume_item`` refuses them until the
    teacher confirms the transcript again. S002 is untouched."""

    ctx = _gated(db_session, bulk_env, monkeypatch, tmp_path)
    _correct_block(ctx, "S001", 1, 0)
    _grade_stage(ctx)
    for question in ("Q1", "Q2"):
        assert _status_of(ctx, "S001", question) == (
            "exception",
            "read",
            ("evidence_review_required",),
        )
        assert _status_of(ctx, "S002", question)[0] == "graded"
    assert not [c for c in ctx.provider.calls_of("grade") if "S001" in c.students]

    outcome = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    assert not outcome.resumed and len(outcome.refused) == 2, outcome
    assert all("Review and confirm" in message for message in outcome.refused.values()), outcome
    _grade_stage(ctx)
    assert not [c for c in ctx.provider.calls_of("grade") if "S001" in c.students]


def test_after_the_teacher_confirms_again_the_corrected_text_is_what_gets_graded(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED (positive path): re-confirming only S001 and resuming grades S001 on the CORRECTED
    text and nothing else is graded twice."""

    ctx = _gated(db_session, bulk_env, monkeypatch, tmp_path)
    _correct_block(ctx, "S001", 1, 0)
    _grade_stage(ctx)
    reviewed = review_all_transcripts(
        ctx.db,
        ctx.run_id,
        ctx.seeded.teacher,
        only_submissions=[_submission_id(ctx.db, "S001")],
    )
    assert not reviewed.refused, reviewed
    resumed = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    assert not resumed.refused and len(resumed.resumed) == 2, resumed
    _grade_stage(ctx)
    calls = ctx.provider.calls_of("grade")
    assert len(calls) == 4, [(c.students, c.question) for c in calls]
    corrected = [c for c in calls if "(teacher-corrected)" in c.evidence_text]
    assert [(c.students, c.question) for c in corrected] == [(("S001",), "Q1")]
    assert {v.status for v in item_views(ctx.db, ctx.run_id).values()} == {"graded"}
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, provider=ctx.provider)


def test_a_bulk_answer_region_cannot_be_graded_through_the_per_region_entry_points(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED sub-claim ('graded without a current teacher review via another entry point'):
    every route in ``routes/grading.py`` queues through ``create_queued_grading_job``, which
    demands a confirmed segment (or a verified mapping) that a transcript compatibility region
    never has, so the review gate cannot be sidestepped by grading the region directly."""

    ctx = _gated(db_session, bulk_env, monkeypatch, tmp_path)
    _correct_block(ctx, "S001", 1, 0)  # the review is stale as well
    item = _items(ctx, "S001")["Q1"]
    precondition(item.answer_region_id is not None, "S001/Q1 has no compatibility region")
    service = GradingService(ctx.db, use_configured_adapter=False)
    with pytest.raises(HTTPException) as refusal:
        service.create_queued_grading_job(int(item.answer_region_id))  # type: ignore[arg-type]
    assert refusal.value.status_code == 400
    assert "missing confirmed answer segment" in str(refusal.value.detail)
    assert ctx.provider.calls_of("grade") == []


def test_the_internal_transcript_job_factory_does_not_itself_check_the_review(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY_QUESTION (low, defence in depth): ``GradingService.create_queued_transcript_
    grading_job`` and ``_grade_region`` (grading_service.py:650-766) verify the assignment but
    never ``transcript_review_is_current``; only ``BulkEvaluationService._process_grading``
    does. No route or worker reaches the factory except through that guarded caller, so this
    pins the layering: the gate lives in the bulk layer, not in GradingService."""

    ctx = _gated(db_session, bulk_env, monkeypatch, tmp_path)
    _correct_block(ctx, "S001", 1, 0)
    transcript = _transcript(ctx.db, "S001")
    precondition(
        not transcript_review_is_current(ctx.db, transcript), "the review is still current"
    )
    item = _items(ctx, "S001")["Q1"]
    precondition(
        item.answer_region_id is not None and item.answer_evidence_assignment_id is not None,
        "S001/Q1 is missing its region or assignment",
    )
    job = GradingService(ctx.db, use_configured_adapter=False).create_queued_transcript_grading_job(
        answer_region_id=int(item.answer_region_id),  # type: ignore[arg-type]
        assignment_id=int(item.answer_evidence_assignment_id),  # type: ignore[arg-type]
    )
    assert job.status == "queued"
    assert ctx.provider.calls_of("grade") == []


def _edit_block_during_call(
    ctx: Ctx, block_id: int, text: str, errors: list[str]
) -> Callable[[Any], None]:
    """``Fault.callback``: the teacher corrects a block from ANOTHER session while the grading
    call is in flight. Never raises (``Failed`` would unwind the unit like a killed worker)."""

    def callback(record: Any) -> None:
        del record
        try:
            with other_session() as other:
                teacher = other.get(User, ctx.seeded.teacher.id)
                correct_script_transcript_block(
                    block_id,
                    ScriptTranscriptBlockUpdate(edited_text=f"{text} (corrected mid-call)"),
                    other,
                    teacher,  # type: ignore[arg-type]
                )
        except Exception as exc:  # recorded; the test body turns it into a precondition
            errors.append(repr(exc))

    return callback


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP grade-result-not-rechecked-after-provider-call: a teacher correction that lands "
        "while a grading call is in flight is not noticed when the result comes back. "
        "_process_grading (bulk_evaluation_service.py:2252-2282) stores the draft bound to the "
        "fingerprint taken BEFORE the call (grading_service.py:789,946), then marks the item "
        "clean 'graded'; the GradingEvidenceChangedError recheck (L849-863) runs only for "
        "managed-local providers and BEFORE the provider call, so it does not cover this window "
        "on the pilot stack either (see the managed-local variant). The draft is born stale and "
        "unmarked."
    ),
)
@pytest.mark.parametrize(
    "managed_local_phase", [None, "Qwen38"], ids=["unmanaged", "managed-local-pilot"]
)
def test_a_correction_during_the_grading_call_does_not_leave_a_clean_draft(
    managed_local_phase: str | None,
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
        pages=1,
        questions=1,
        managed_local_phase=managed_local_phase,
    )
    _read_stage(ctx)
    _gate(ctx)
    block = _block(ctx.db, "S001", 1, 0)
    errors: list[str] = []
    fault = ctx.provider.inject(
        Fault(
            "grade",
            callback=_edit_block_during_call(ctx, block.id, block.effective_text, errors),
            on_call=1,
        )
    )
    _grade_stage(ctx)
    precondition(fault.fired == 1 and not errors, f"the mid-call edit did not happen: {errors}")
    first = ctx.provider.calls_of("grade")[0]
    precondition(
        first.students == ("S001",) and "corrected" not in first.evidence_text,
        f"the first grading call must be S001's, on the text BEFORE the edit: {first}",
    )
    transcript = _transcript(ctx.db, "S001")
    suggestion = ctx.db.scalar(
        select(GradeSuggestion).where(
            GradeSuggestion.answer_region_id == _items(ctx, "S001")["Q1"].answer_region_id
        )
    )
    precondition(suggestion is not None, "S001 has no draft")
    assert suggestion is not None
    guard = EvidenceInvalidationService(ctx.db)
    precondition(
        not transcript_review_is_current(ctx.db, transcript)
        and guard.suggestion_evidence_status(suggestion) == "stale",
        "the draft must be stale for the finalization gate and the review no longer current",
    )
    status, stage, _codes = _status_of(ctx, "S001", "Q1")
    run = BulkEvaluationService(
        ctx.db, settings=ctx.settings, storage=harness_storage(ctx.settings)
    ).get_run(ctx.run_id)
    offered = {
        item.grade_suggestion_id for item in BulkEvaluationService._reviewable_items(ctx.db, run)
    }
    # Either the item stops being a clean draft or the clean set no longer offers the stale
    # draft: both are fixes of the same defect.
    assert status != "graded" or suggestion.id not in offered, (
        f"S001/Q1 is a clean {status}/{stage} draft, offered for bulk approval, although the "
        f"transcript was corrected while it was being graded (draft {suggestion.id}: evidence "
        f"status {guard.suggestion_evidence_status(suggestion)}, "
        f"superseded_at={suggestion.superseded_at}; managed_local_phase={managed_local_phase})"
    )


def test_a_correction_while_the_model_is_starting_is_caught_before_any_provider_call(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED (the window the recheck at grading_service.py:849-863 DOES cover): the teacher
    corrects a block after the evidence fingerprint was taken but before the managed-local model
    answers (a ``verify`` Fault, which runs inside the lease, stands in for the model starting).
    The grade is never requested, no draft exists, the run pauses and the item is quarantined
    ``uncertain``; resuming the run alone does not grade it, the teacher must confirm the
    corrected transcript again, and then the CORRECTED text is graded.
    (Observation, low: the item carries the code ``provider_contract_failure`` although no
    provider failed, and one teacher edit pauses the whole run.)"""

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=2,
        pages=1,
        questions=1,
        managed_local_phase="Qwen38",
    )
    _read_stage(ctx)
    _gate(ctx)
    block = _block(ctx.db, "S001", 1, 0)
    errors: list[str] = []
    fault = ctx.provider.inject(
        Fault(
            "verify",
            callback=_edit_block_during_call(ctx, block.id, block.effective_text, errors),
            on_call=len(ctx.provider.verify_calls) + 1,
        )
    )
    paused = _grade_stage(ctx)
    precondition(fault.fired == 1 and not errors, f"the edit did not happen: {errors}")
    assert paused.status == "paused" and "evidence changed" in (paused.error or "").lower(), paused
    assert ctx.provider.calls_of("grade") == []
    assert ctx.db.scalar(select(func.count(GradeSuggestion.id))) == 0
    assert _status_of(ctx, "S001", "Q1")[0] == "uncertain"

    resumed, refusal = try_resume_run(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    precondition(resumed, f"the run could not be resumed: {refusal}")
    _grade_stage(ctx)
    assert _status_of(ctx, "S002", "Q1")[0] == "graded"
    assert _status_of(ctx, "S001", "Q1")[0] == "uncertain"
    blocked = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    assert not blocked.resumed and len(blocked.refused) == 1, blocked
    assert "Review and confirm" in next(iter(blocked.refused.values()))

    reviewed = review_all_transcripts(
        ctx.db, ctx.run_id, ctx.seeded.teacher, only_submissions=[_submission_id(ctx.db, "S001")]
    )
    precondition(not reviewed.refused, f"{reviewed}")
    resumed_items = resume_all_items(
        ctx.run_id, ctx.seeded.teacher, settings=ctx.settings, only_stage=None
    )
    assert len(resumed_items.resumed) == 1 and not resumed_items.refused, resumed_items
    _grade_stage(ctx)
    assert _status_of(ctx, "S001", "Q1")[0] == "graded"
    calls = [c for c in ctx.provider.calls_of("grade") if "S001" in c.students]
    assert len(calls) == 1 and "(corrected mid-call)" in calls[0].evidence_text


# =========================================================================== PC-5: canonical unit
# Out-of-order answers, an answer split over non-adjacent pages, a duplicated label on one page,
# a continuation that spills over a page break, writing that matches no question. The SAFE outcome
# is either the right text on the right question, or an item that needs the teacher: never text
# that is silently dropped and never a clean draft that lacks part of the answer. (A label that
# matches NO canonical question - 'Q9' - is already proven by the harness smoke xfail
# 'a hallucinated question label does not strand the script': the run pauses with no assignment
# at all, so no evidence can leak; it is not duplicated here.)

STRAY = Seg(UNASSIGNED_QUESTION, label=None, source="continuation")


def _layout_corpus(
    layouts: dict[str, list[list[Seg]]], labels: tuple[str, ...]
) -> Callable[[Path], Corpus]:
    return lambda path: custom_corpus(path, layouts, labels=labels)


def _tokens_of(ctx: Ctx, assignment: AnswerEvidenceAssignment) -> list[str]:
    return [
        ctx.db.get(ScriptTranscriptBlock, span.script_transcript_block_id).text.split(" ")[0]  # type: ignore[union-attr]
        for span in sorted(assignment.spans, key=lambda item: item.order_index)
    ]


def test_a_script_answered_in_reverse_order_reaches_the_right_questions(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: Q3 before Q1 changes nothing, because ownership is by canonical label (grouped,
    not sequential: answer_evidence_assignment.py:298-309) and every question gets its own text."""

    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=3,
        pages=3,
        questions=3,
        out_of_order=["S002"],
    )
    precondition(
        [b.question for b in ctx.corpus.page_spec("S002", 1).blocks] == ["Q3"]
        and [b.question for b in ctx.corpus.page_spec("S001", 1).blocks] == ["Q1"],
        "S002 must answer in reverse order and S001 in order",
    )
    _read_stage(ctx)
    _gate(ctx)
    final = _grade_stage(ctx)
    precondition(final.status == "review_ready", f"{final}")
    assert_every_answered_question_graded(ctx.corpus, item_views(ctx.db, ctx.run_id))
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)
    assignments = _current_assignments(ctx.db, "S002")
    assert _tokens_of(ctx, assignments["Q1"]) == [token("S002", "Q1", 3, 1)]
    assert _tokens_of(ctx, assignments["Q3"]) == [token("S002", "Q3", 1, 1)]


def test_an_answer_split_over_non_adjacent_pages_is_one_piece_of_evidence_in_page_order(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: Q1 on pages 1 and 4 (Q2, Q3 in between) is ONE assignment whose spans run in
    page order; the questions in between keep their own page."""

    layouts = {
        "S001": [[Seg("Q1")], [Seg("Q2")], [Seg("Q3")], [Seg("Q1")]],
        "S002": [[Seg("Q1")], [Seg("Q2")], [Seg("Q3")], [Seg("Q3")]],
    }
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        questions=3,
        corpus_builder=_layout_corpus(layouts, ("Q1", "Q2", "Q3")),
    )
    _read_stage(ctx)
    _gate(ctx)
    final = _grade_stage(ctx)
    precondition(final.status == "review_ready", f"{final}")
    assignments = _current_assignments(ctx.db, "S001")
    assert _tokens_of(ctx, assignments["Q1"]) == [
        token("S001", "Q1", 1, 1),
        token("S001", "Q1", 4, 1),
    ]
    assert [span.page_no for span in assignments["Q1"].spans] == [1, 4]
    assert _tokens_of(ctx, assignments["Q2"]) == [token("S001", "Q2", 2, 1)]
    assert_every_answered_question_graded(ctx.corpus, item_views(ctx.db, ctx.run_id))
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)


def test_a_model_claimed_continuation_on_a_later_page_needs_the_teacher_before_it_is_graded(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: when page 4 carries an UNLABELLED continuation of Q1 (the model, not a heading,
    says whose it is) the label rule would hand it to Q3 (the question on page 3). The
    whole-script mapping call decides instead, but its decision is only an inference: all three
    questions are ``inferred_question_label`` exceptions until the teacher confirms ownership."""

    layouts = {
        "S001": [
            [Seg("Q1")],
            [Seg("Q2")],
            [Seg("Q3")],
            [Seg("Q1", label=None, source="continuation", cont=True)],
        ]
    }
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=1,
        questions=3,
        corpus_builder=_layout_corpus(layouts, ("Q1", "Q2", "Q3")),
    )
    _read_stage(ctx)
    precondition(ctx.provider.counts["map"] == 1, "the whole-script mapping call must run")
    for question in ("Q1", "Q2", "Q3"):
        assert _status_of(ctx, "S001", question) == (
            "exception",
            "read",
            ("inferred_question_label",),
        )
    assert _tokens_of(ctx, _current_assignments(ctx.db, "S001")["Q1"]) == [
        token("S001", "Q1", 1, 1),
        token("S001", "Q1", 4, 1),
    ]
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    precondition(not reviewed.refused and reviewed.ownership_confirmed, f"{reviewed}")
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    _grade_stage(ctx)
    assert_every_answered_question_graded(ctx.corpus, item_views(ctx.db, ctx.run_id))
    assert_no_cross_student_evidence(ctx.db, ctx.run_id, corpus=ctx.corpus, provider=ctx.provider)


def test_a_label_repeated_on_one_page_is_merged_into_one_answer_without_a_signal(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY_QUESTION (low): Q1, Q2, Q1 on one page. Both Q1 blocks are attached to Q1 by their
    explicit label and graded together, Q2 keeps the block between them; nothing marks the
    repeat. That is right when the student returned to Q1, wrong when the model read a margin
    note as a second 'Q1' heading, and the pipeline cannot tell the two apart. The mandatory
    transcript review is what the founder relies on; this pins that there is no extra flag."""

    layouts = {"S001": [[Seg("Q1"), Seg("Q2"), Seg("Q1")], [Seg("Q3")]]}
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=1,
        questions=3,
        corpus_builder=_layout_corpus(layouts, ("Q1", "Q2", "Q3")),
    )
    _read_stage(ctx)
    assignments = _current_assignments(ctx.db, "S001")
    assert _tokens_of(ctx, assignments["Q1"]) == [
        token("S001", "Q1", 1, 1),
        token("S001", "Q1", 1, 3),
    ]
    assert {span.assignment_basis for span in assignments["Q1"].spans} == {"explicit_label"}
    assert _tokens_of(ctx, assignments["Q2"]) == [token("S001", "Q2", 1, 2)]
    for item in _items(ctx, "S001").values():
        assert item.exception_codes == ["evidence_review_required"] and item.warnings == [
            "A teacher must confirm the current transcript and question evidence before draft "
            "grading"
        ], (item.exception_codes, item.warnings)
    _gate(ctx)
    _grade_stage(ctx)
    assert_every_answered_question_graded(ctx.corpus, item_views(ctx.db, ctx.run_id))


def test_writing_that_matches_no_question_is_never_graded_and_never_dropped(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: S001 opens page 1 with writing that answers nothing (no label, no question
    above it). The whole-script mapping leaves it unassigned, so BOTH of S001's questions become
    ``unassigned_transcript_block`` exceptions, the stray text is in no question's evidence yet
    stays counted, the teacher gate refuses to confirm the script, and no grading call is ever
    made for S001. S002 is unaffected."""

    layouts = {
        "S001": [[STRAY, Seg("Q1"), Seg("Q2")]],
        "S002": [[Seg("Q1"), Seg("Q2")]],
    }
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        questions=2,
        corpus_builder=_layout_corpus(layouts, ("Q1", "Q2")),
    )
    _read_stage(ctx)
    stray = _block(ctx.db, "S001", 1, 0)
    assignments = _current_assignments(ctx.db, "S001")
    precondition(stray.text.startswith(token("S001", UNASSIGNED_QUESTION, 1, 1)), stray.text)
    assert all(stray.id not in _span_block_ids(item) for item in assignments.values())
    assert {item.unassigned_block_count for item in assignments.values()} == {1}
    for question in ("Q1", "Q2"):
        assert _status_of(ctx, "S001", question) == (
            "exception",
            "read",
            ("unassigned_transcript_block",),
        )
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    s001 = _submission_id(ctx.db, "S001")
    assert "Assign every visible writing block" in reviewed.refused[s001]
    assert _submission_id(ctx.db, "S002") in reviewed.confirmed
    outcome = resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    assert len(outcome.refused) == 2 and len(outcome.resumed) == 2, outcome
    _grade_stage(ctx)
    assert not [c for c in ctx.provider.calls_of("grade") if "S001" in c.students]
    assert _status_of(ctx, "S001", "Q1")[0] == "exception"
    assert _status_of(ctx, "S002", "Q1")[0] == _status_of(ctx, "S002", "Q2")[0] == "graded"


def test_a_stray_block_can_only_clear_the_gate_by_being_assigned_or_blanked(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POLICY_QUESTION (medium for 150 real scripts): the review screen has no 'this is not an
    answer' decision for a single block. The gate (script_transcripts.py:236-243) demands every
    writing block be ASSIGNED, and 'Leave unassigned' cannot satisfy it. Pinned escape routes:

    * assign the stray block to a question (S001): the gate opens, but the stray text is now part
      of that question's evidence (a forced misattribution);
    * blank its text through a correction (S002): the gate opens and the evidence is clean, the
      model's original text stays on the block (revision 1);
    * classify the whole page 'non_answer' is the third way and would drop real answers too."""

    layouts = {
        "S001": [[STRAY, Seg("Q1"), Seg("Q2")]],
        "S002": [[STRAY, Seg("Q1"), Seg("Q2")]],
    }
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        questions=2,
        corpus_builder=_layout_corpus(layouts, ("Q1", "Q2")),
    )
    _read_stage(ctx)
    teacher = ctx.seeded.teacher
    stray_1 = _block(ctx.db, "S001", 1, 0)
    stray_2 = _block(ctx.db, "S002", 1, 0)
    stray_1_id, stray_2_id, original_text = stray_1.id, stray_2.id, stray_2.text

    override_script_transcript_block_assignment(
        stray_1_id,
        ScriptTranscriptBlockAssignmentUpdate(question_label="Q1", continues_from_previous=False),
        ctx.db,
        teacher,
    )
    rederive_answer_evidence(_submission_id(ctx.db, "S001"), ctx.db, teacher)
    correct_script_transcript_block(
        stray_2_id,
        ScriptTranscriptBlockUpdate(edited_text="", reason="not an answer"),
        ctx.db,
        teacher,
    )
    rederive_answer_evidence(_submission_id(ctx.db, "S002"), ctx.db, teacher)

    reviewed = review_all_transcripts(ctx.db, ctx.run_id, teacher)
    assert not reviewed.refused and len(reviewed.confirmed) == 2, reviewed
    one = _current_assignments(ctx.db, "S001")
    two = _current_assignments(ctx.db, "S002")
    assert stray_1_id in _span_block_ids(one["Q1"]), "assigned stray text must join Q1's evidence"
    assert stray_2_id not in {sid for item in two.values() for sid in _span_block_ids(item)}
    blanked = ctx.db.get(ScriptTranscriptBlock, stray_2_id)
    assert blanked is not None and blanked.text == original_text
    assert blanked.edited_text == "" and blanked.revision == 1


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP canonical-label-uniqueness-case-sensitive: the question route accepts 'Q1' and 'q1' "
        "side by side (questions.py:21-35 compares labels exactly) and create_from_zip accepts "
        "them (_load_references checks no label), but resolve_block_ownership folds case "
        "(answer_evidence_assignment.py:200-207) and raises 'Canonical question labels must be "
        "unique'. The run is only refused AFTER the first script's pages were read (provider "
        "calls spent), and the first script's items are marked 'provider_contract_failure' "
        "although no provider failed."
    ),
)
def test_case_variant_question_labels_are_refused_before_any_page_is_read(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    try:
        ctx = _start(
            db_session, bulk_env, monkeypatch, tmp_path, students=2, pages=1, questions=["Q1", "q1"]
        )
    except BulkEvaluationError:
        return  # refused at intake: the desired behaviour
    read = _read_stage(ctx)
    precondition(
        read.status == "paused" and "must be unique" in (read.error or ""),
        f"the case-variant labels must stop the run at the first assignment: {read}",
    )
    precondition(
        ctx.provider.counts["read_page"] == 1 and read.calls_used == 1,
        f"exactly the first script's page was read before the stop: {ctx.provider.counts}",
    )
    codes = {k: v.codes for k, v in item_views(ctx.db, ctx.run_id).items() if v.codes}
    assert ctx.provider.counts["read_page"] == 0, (
        f"{ctx.provider.counts['read_page']} provider page read(s) were spent before the run "
        f"stopped on {read.error!r}; item codes {codes}"
    )


def test_the_question_route_treats_labels_that_differ_only_by_case_as_distinct(
    db_session: Session,
) -> None:
    """Premise of the GAP above, run through the REAL route: an exact duplicate is refused (409)
    but ``q1`` next to ``Q1`` is created without complaint."""

    seeded = seed_assessment(db_session, questions=["Q1"])
    teacher = seeded.teacher
    payload = {"question_text": "x", "model_answer": "y", "total_marks": Decimal("5")}
    created = create_question(
        seeded.assessment.id, QuestionCreate(question_no="q1", **payload), db_session, teacher
    )
    assert created.question_no == "q1"
    for duplicate in ("Q1", " Q1 "):
        with pytest.raises(HTTPException) as refusal:
            create_question(
                seeded.assessment.id,
                QuestionCreate(question_no=duplicate, **payload),
                db_session,
                teacher,
            )
        assert refusal.value.status_code == 409


def test_a_continuation_the_model_leaves_unassigned_is_not_graded_as_part_of_the_answer(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: the answer to Q1 spills onto page 2 as an unlabelled continuation. The label rule
    alone would attach it to Q1 (declared continuation), but the whole-script mapping is
    authoritative and says 'unassigned', so S001's block stays visibly unplaced: no clean draft
    of Q1 built from page 1 alone, the gate refuses, no grading call for S001."""

    def leave_unassigned(output: dict[str, Any]) -> dict[str, Any]:
        for mapping in output["mappings"]:
            kept = []
            for reference in mapping["block_references"]:
                orders = [
                    order
                    for order in reference["block_orders"]
                    if not (reference["page_no"] == 2 and order == 1)
                ]
                if orders:
                    kept.append({**reference, "block_orders": orders})
            mapping["block_references"] = kept
            if not kept:
                mapping["status"] = "not_found"
        output["unassigned_block_references"].append({"page_no": 2, "block_orders": [1]})
        return output

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
    )
    precondition(
        ctx.corpus.page_spec("S001", 2).blocks[0].continues_from_previous
        and ctx.corpus.page_spec("S001", 2).blocks[0].question == "Q1",
        "page 2 must open with an unlabelled continuation of Q1",
    )
    fault = ctx.provider.inject(Fault("map", transform=leave_unassigned, on_call=1))
    _read_stage(ctx)
    precondition_faults_fired(ctx.provider)
    precondition(fault.fired == 1, "the mapping transform did not fire")
    assignments = _current_assignments(ctx.db, "S001")
    carried = _block(ctx.db, "S001", 2, 0)
    assert carried.id not in {sid for item in assignments.values() for sid in _span_block_ids(item)}
    assert {item.unassigned_block_count for item in assignments.values()} == {1}
    assert _status_of(ctx, "S001", "Q1")[2] == ("unassigned_transcript_block",)
    reviewed = review_all_transcripts(ctx.db, ctx.run_id, ctx.seeded.teacher)
    assert "Assign every visible writing block" in reviewed.refused[_submission_id(ctx.db, "S001")]
    resume_all_items(ctx.run_id, ctx.seeded.teacher, settings=ctx.settings)
    _grade_stage(ctx)
    assert not [c for c in ctx.provider.calls_of("grade") if "S001" in c.students]
    assert _status_of(ctx, "S002", "Q1")[0] == "graded"


# =========================================================================== PC-7: isolation


def test_eight_students_out_of_order_with_a_shared_page_stay_isolated_end_to_end(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: 8 students x 3 pages x 3 questions, four of them answering in reverse order and
    S003/S004 handing in a byte-identical page 2. After the real teacher gate every answered
    question is graded, each assignment holds exactly its own tokens, and not one read, mapping or
    grading call saw more than one student (a shared page names its two owners, by design)."""

    reversed_students = ("S003", "S004", "S007", "S008")
    ctx = _start(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        students=8,
        pages=3,
        questions=3,
        out_of_order=reversed_students,
        shared_pages=[(["S003", "S004"], 2)],
        budget_slack=8,
    )
    corpus = ctx.corpus
    precondition(
        corpus.page_spec("S003", 2) == corpus.page_spec("S004", 2)
        and corpus.page_spec("S003", 2).blocks[0].owner == "S003+S004"
        and corpus.page_spec("S001", 1).blocks[0].question == "Q1"
        and corpus.page_spec("S007", 1).blocks[0].question == "Q3",
        "the corpus must hold one shared page and a mix of in-order and reversed scripts",
    )
    read = _read_stage(ctx)
    precondition(read.status != "paused", f"{read}")
    _gate(ctx)
    final = _grade_stage(ctx)
    assert final.status == "review_ready", final

    inspected = assert_no_cross_student_evidence(
        ctx.db, ctx.run_id, corpus=corpus, provider=ctx.provider
    )
    precondition(inspected >= 24 * 2, f"only {inspected} evidence texts were inspected")
    assert_every_answered_question_graded(corpus, item_views(ctx.db, ctx.run_id))
    assert ctx.provider.counts == {"read_page": 24, "map": 0, "grade": 24}
    assert ctx.provider.total_calls == corpus.call_budget()

    checked = 0
    for kind in ("read_page", "map", "grade"):
        for call in ctx.provider.calls_of(kind):
            found = parse_tokens(" ".join(call.tokens) + " " + call.evidence_text)
            assert found and common_students(found), (kind, call.index, call.tokens)
            named = {student for item in found for student in item.students}
            if not named & {"S003", "S004"}:
                assert len(named) == 1, (kind, call.index, sorted(named))
            else:
                assert named <= {"S003", "S004"}, (kind, call.index, sorted(named))
            checked += 1
    assert checked == 48, checked
