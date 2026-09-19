"""Durability, reuse and state-distinctness of the persisted script transcript.

These tests run against the real database. They exercise
``LocalScriptPageReadService._read_pages`` and ``ScriptTranscriptStore``
directly: that is where the source read, the reuse decision and the per-page
commit live. The provider is a counting fake, so every assertion about how many
requests were made is measured, not assumed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import (
    Assessment,
    Course,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
    User,
)
from app.services.local_script_page_read import (
    LocalScriptPageReadError,
    LocalScriptPageReadService,
)
from app.services.script_transcript_store import (
    PageAlreadyReservedError,
    PageReconciliationRequiredError,
    ScriptTranscriptError,
    ScriptTranscriptStore,
    classify_block_text,
    classify_dispatch_failure,
    transcription_settings_fingerprint,
)
from packages.brain.schemas_qwen38 import (
    VISUAL_PAGE_READ_PROMPT_VERSION,
    VisualPageBlock,
    VisualPageTranscriptOutput,
)

CLEANUP_MODELS = (
    ScriptTranscriptBlock,
    ScriptPageTranscript,
    ScriptTranscript,
    SubmissionPage,
    Submission,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(api_root / "alembic.ini")), "head")
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()


def _write_page_image(path: Path, *, ink: bool, seed: int = 0) -> None:
    image = Image.new("RGB", (1000, 1000), "white")
    if ink:
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, 920, 920), fill="black")
        # Shift one pixel per seed so a "changed page" is genuinely different
        # bytes rather than a renamed identical file.
        draw.rectangle((10, 10 + seed, 20, 20 + seed), fill="black")
    image.save(path)


def _seed_submission(db: Session, tmp_path: Path, page_count: int) -> Submission:
    teacher = User(
        name="Teacher",
        email=f"transcript-{uuid4().hex}@example.com",
        password_hash="x",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code=f"C{uuid4().hex[:6]}", title="Course")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Midterm",
        assessment_type="exam",
        total_marks=Decimal("50.00"),
    )
    db.add(assessment)
    db.flush()
    submission = Submission(
        assessment_id=assessment.id,
        student_identifier="S-001",
        status="ready",
    )
    db.add(submission)
    db.flush()
    for page_no in range(1, page_count + 1):
        path = tmp_path / f"page-{page_no}.png"
        _write_page_image(path, ink=True, seed=page_no)
        db.add(
            SubmissionPage(
                submission_id=submission.id,
                page_no=page_no,
                image_path=str(path),
            )
        )
    db.commit()
    db.refresh(submission)
    return submission


def _output(*labels: str, blank: bool = False) -> VisualPageTranscriptOutput:
    blocks = [
        VisualPageBlock(
            question_label=label,
            bbox=[50, 100 + index * 300, 950, 350 + index * 300],
            text=f"{label} working",
            continues_from_previous=False,
            label_source="heading",
            confidence=Decimal("0.94"),
        )
        for index, label in enumerate(labels)
    ]
    return VisualPageTranscriptOutput(blocks=blocks, is_blank_page=blank)


class _CountingAdapter:
    """A brain adapter that records every page request it is asked to make."""

    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = list(outputs)
        self.calls = 0
        self.runtime = SimpleNamespace(managed_local_phase=None)

    def read_page(self, **_kwargs: Any) -> VisualPageTranscriptOutput:
        result = self._outputs[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


def _service(db: Session, adapter: _CountingAdapter) -> LocalScriptPageReadService:
    storage = SimpleNamespace(resolve_relative=lambda path: Path(path))
    return LocalScriptPageReadService(
        db,
        settings=Settings(_env_file=None, LOCAL_SCRIPT_UNASSIGNED_INK_WARN_ABOVE=Decimal("0.35")),
        storage=storage,
        qwen_adapter=adapter,
    )


def _policy(adapter: _CountingAdapter) -> SimpleNamespace:
    return SimpleNamespace(
        provider="mock",
        model="mock-vision-1",
        adapter=adapter,
    )


def _questions(*labels: str) -> list[Any]:
    return [
        SimpleNamespace(id=index, question_no=label)
        for index, label in enumerate(labels, start=1)
    ]


def _read(
    service: LocalScriptPageReadService,
    submission: Submission,
    adapter: _CountingAdapter,
    *,
    maximum_page_read_calls: int = 10,
) -> Any:
    pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
    return service._read_pages(
        submission=submission,
        pages=pages,
        questions=_questions("Q1", "Q2"),
        references=[],
        policy=_policy(adapter),
        maximum_page_read_calls=maximum_page_read_calls,
    )


def test_each_successful_page_is_committed_with_its_blocks(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=2)
    adapter = _CountingAdapter([_output("Q1"), _output("Q2")])

    source = _read(_service(db_session, adapter), submission, adapter)

    assert adapter.calls == 2
    assert source.calls_used == 2
    assert source.reused_page_count == 0
    transcript = db_session.get(ScriptTranscript, source.transcript_id)
    assert transcript is not None
    assert transcript.status == "complete"
    assert transcript.prompt_version == VISUAL_PAGE_READ_PROMPT_VERSION
    assert [page.page_no for page in transcript.pages] == [1, 2]
    assert [page.state for page in transcript.pages] == ["succeeded", "succeeded"]
    blocks = [block for page in transcript.pages for block in page.blocks]
    assert [block.text for block in blocks] == ["Q1 working", "Q2 working"]
    assert [block.question_label_raw for block in blocks] == ["Q1", "Q2"]
    assert [block.observed_heading_text for block in blocks] == ["Q1", "Q2"]
    # Reading order is global across the script, not restarted per page.
    assert [block.reading_order for block in blocks] == [0, 1]
    assert all(block.unresolved is False for block in blocks)

    # Durability, proved from a connection that never saw the writing session:
    # a pending flush would be invisible here.
    other = SessionLocal()
    try:
        persisted = other.get(ScriptTranscript, source.transcript_id)
        assert persisted is not None
        assert [
            block.text for page in persisted.pages for block in page.blocks
        ] == ["Q1 working", "Q2 working"]
    finally:
        other.close()


def test_an_unchanged_source_is_reused_without_any_provider_request(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=3)
    first_adapter = _CountingAdapter([_output("Q1"), _output("Q2"), _output("Q1")])
    first = _read(_service(db_session, first_adapter), submission, first_adapter)
    assert first.calls_used == 3

    # A second preparation pass, exactly as a remap or a rubric change would
    # trigger. It must not pay to read the same pages again.
    second_adapter = _CountingAdapter([])
    second = _read(_service(db_session, second_adapter), submission, second_adapter)

    assert second_adapter.calls == 0
    assert second.calls_used == 0
    assert second.reused_page_count == 3
    assert second.transcript_id == first.transcript_id
    # The reused transcript must reconstruct the same source text, not a
    # placeholder standing in for it.
    assert [block.text for output in second.outputs for block in output.blocks] == [
        "Q1 working",
        "Q2 working",
        "Q1 working",
    ]


def test_a_cached_script_is_not_refused_by_the_call_budget(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=3)
    adapter = _CountingAdapter([_output("Q1"), _output("Q2"), _output("Q1")])
    _read(_service(db_session, adapter), submission, adapter, maximum_page_read_calls=3)

    cached_adapter = _CountingAdapter([])
    source = _read(
        _service(db_session, cached_adapter),
        submission,
        cached_adapter,
        maximum_page_read_calls=0,
    )

    assert source.calls_used == 0
    assert source.reused_page_count == 3


def test_the_budget_is_enforced_on_pages_that_still_need_a_read(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=3)
    adapter = _CountingAdapter([_output("Q1"), _output("Q2"), _output("Q1")])

    with pytest.raises(LocalScriptPageReadError, match="page-read call limit"):
        _read(_service(db_session, adapter), submission, adapter, maximum_page_read_calls=2)

    assert adapter.calls == 0


def test_a_known_failure_on_a_later_page_keeps_the_earlier_pages_and_records_the_reason(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=3)
    adapter = _CountingAdapter(
        [_output("Q1"), RuntimeError("provider rejected the request"), _output("Q2")]
    )

    with pytest.raises(LocalScriptPageReadError, match="failed safely"):
        _read(_service(db_session, adapter), submission, adapter)

    assert adapter.calls == 2
    transcript = db_session.scalars(select(ScriptTranscript)).one()
    assert transcript.status == "failed"
    stored = {page.page_no: page for page in transcript.pages}
    assert stored[1].state == "succeeded"
    assert [block.text for block in stored[1].blocks] == ["Q1 working"]
    # The failed page keeps its own terminal state and reason. It is never
    # blank, so a blank answer cannot be reconstructed from it.
    assert stored[2].state == "failed"
    assert stored[2].is_blank_page is False
    assert "provider rejected the request" in (stored[2].error or "")
    assert stored[2].reservation_id is None
    assert 3 not in stored

    # Restart recovery: a process that dies here still finds page 1 stored.
    other = SessionLocal()
    try:
        survivor = other.scalars(
            select(ScriptPageTranscript).where(ScriptPageTranscript.page_no == 1)
        ).one()
        assert survivor.state == "succeeded"
        assert [block.text for block in survivor.blocks] == ["Q1 working"]
    finally:
        other.close()

    # The page already paid for is reused on the retry; only the known-failed
    # page and the page never reached are read again.
    retry_adapter = _CountingAdapter([_output("Q2"), _output("Q1")])
    retry = _read(_service(db_session, retry_adapter), submission, retry_adapter)

    assert retry_adapter.calls == 2
    assert retry.reused_page_count == 1
    assert retry.calls_used == 2


def test_a_timeout_is_not_retried_and_demands_an_explicit_reconciliation(
    db_session: Session, tmp_path: Path
) -> None:
    """A provider that timed out may already have produced and billed output.

    Reading the page again would be a blind resubmission, so the page keeps
    'unknown_outcome' and nothing automatic touches it.
    """
    submission = _seed_submission(db_session, tmp_path, page_count=2)
    adapter = _CountingAdapter([_output("Q1"), TimeoutError("no response")])

    with pytest.raises(LocalScriptPageReadError, match="outcome is unknown"):
        _read(_service(db_session, adapter), submission, adapter)

    transcript = db_session.scalars(select(ScriptTranscript)).one()
    stored = {page.page_no: page for page in transcript.pages}
    assert stored[2].state == "unknown_outcome"
    assert stored[2].is_blank_page is False

    # A second attempt refuses rather than redispatching, and spends nothing.
    blocked_adapter = _CountingAdapter([])
    with pytest.raises(LocalScriptPageReadError, match="unresolved provider outcome"):
        _read(_service(db_session, blocked_adapter), submission, blocked_adapter)
    assert blocked_adapter.calls == 0

    # Only an explicit decision releases it, and it is recorded.
    store = ScriptTranscriptStore(db_session)
    store.reconcile_page(
        transcript=transcript,
        submission_page_id=stored[2].submission_page_id,
        resolution="failed",
        note="teacher confirmed the provider produced nothing",
    )
    db_session.refresh(stored[2])
    assert stored[2].state == "failed"
    assert stored[2].reconciled_at is not None
    assert "teacher confirmed" in (stored[2].error or "")

    resumed_adapter = _CountingAdapter([_output("Q2")])
    resumed = _read(_service(db_session, resumed_adapter), submission, resumed_adapter)
    assert resumed_adapter.calls == 1
    assert resumed.reused_page_count == 1


def test_a_page_already_claimed_by_another_worker_is_not_dispatched_twice(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=1)
    page = submission.pages[0]
    digest = hashlib.sha256(Path(page.image_path).read_bytes()).hexdigest()
    store = ScriptTranscriptStore(db_session)
    transcript = store.get_or_create(
        submission_id=submission.id,
        provider="mock",
        model_name="mock-vision-1",
        prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
        ordered_page_hashes=[digest],
    )
    store.reserve_page(
        transcript=transcript,
        submission_page_id=page.id,
        page_no=page.page_no,
        page_order=0,
        source_image_sha256=digest,
        holder_id="worker-a",
    )

    with pytest.raises(PageAlreadyReservedError, match="already reserved"):
        store.reserve_page(
            transcript=transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=0,
            source_image_sha256=digest,
            holder_id="worker-b",
        )


def test_an_expired_claim_becomes_an_unknown_outcome_not_a_free_retry(
    db_session: Session, tmp_path: Path
) -> None:
    """A worker that died mid-call leaves an outcome nobody observed."""
    submission = _seed_submission(db_session, tmp_path, page_count=1)
    page = submission.pages[0]
    digest = hashlib.sha256(Path(page.image_path).read_bytes()).hexdigest()
    store = ScriptTranscriptStore(db_session)
    transcript = store.get_or_create(
        submission_id=submission.id,
        provider="mock",
        model_name="mock-vision-1",
        prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
        ordered_page_hashes=[digest],
    )
    store.reserve_page(
        transcript=transcript,
        submission_page_id=page.id,
        page_no=page.page_no,
        page_order=0,
        source_image_sha256=digest,
        holder_id="worker-that-died",
    )
    stored = transcript.pages[0]
    stored.reserved_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    with pytest.raises(PageReconciliationRequiredError, match="unresolved provider outcome"):
        store.reserve_page(
            transcript=transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=0,
            source_image_sha256=digest,
            holder_id="worker-b",
        )
    db_session.refresh(stored)
    assert stored.state == "unknown_outcome"
    assert "never reported an outcome" in (stored.error or "")


def test_classification_separates_a_known_failure_from_an_unobserved_one() -> None:
    assert classify_dispatch_failure(ValueError("schema mismatch")) == "failed"
    assert classify_dispatch_failure(RuntimeError("bad request")) == "failed"
    assert classify_dispatch_failure(TimeoutError("x")) == "unknown_outcome"
    assert classify_dispatch_failure(RuntimeError("request timed out")) == "unknown_outcome"
    assert (
        classify_dispatch_failure(RuntimeError("connection reset by peer")) == "unknown_outcome"
    )


def test_a_changed_source_page_supersedes_the_previous_transcript(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=2)
    first_adapter = _CountingAdapter([_output("Q1"), _output("Q2")])
    first = _read(_service(db_session, first_adapter), submission, first_adapter)

    pages = sorted(submission.pages, key=lambda item: item.page_no)
    _write_page_image(Path(pages[1].image_path), ink=True, seed=97)

    second_adapter = _CountingAdapter([_output("Q1"), _output("Q2")])
    second = _read(_service(db_session, second_adapter), submission, second_adapter)

    assert second.transcript_id != first.transcript_id
    assert second.calls_used == 2
    assert second.reused_page_count == 0
    superseded = db_session.get(ScriptTranscript, first.transcript_id)
    assert superseded is not None
    # The prior version stays readable rather than being deleted.
    assert superseded.status == "superseded"
    assert len(superseded.pages) == 2


def test_a_different_model_does_not_reuse_another_models_transcript(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=1)
    adapter = _CountingAdapter([_output("Q1")])
    service = _service(db_session, adapter)
    pages = sorted(submission.pages, key=lambda item: item.page_no)
    service._read_pages(
        submission=submission,
        pages=pages,
        questions=_questions("Q1"),
        references=[],
        policy=SimpleNamespace(provider="mock", model="model-a", adapter=adapter),
        maximum_page_read_calls=1,
    )

    other_adapter = _CountingAdapter([_output("Q1")])
    other = _service(db_session, other_adapter)._read_pages(
        submission=submission,
        pages=pages,
        questions=_questions("Q1"),
        references=[],
        policy=SimpleNamespace(provider="mock", model="model-b", adapter=other_adapter),
        maximum_page_read_calls=1,
    )

    assert other_adapter.calls == 1
    assert other.reused_page_count == 0


def test_a_blank_page_is_only_storable_on_a_successful_read(
    db_session: Session, tmp_path: Path
) -> None:
    submission = _seed_submission(db_session, tmp_path, page_count=1)
    store = ScriptTranscriptStore(db_session)
    page = submission.pages[0]
    digest = hashlib.sha256(Path(page.image_path).read_bytes()).hexdigest()
    transcript = store.get_or_create(
        submission_id=submission.id,
        provider="mock",
        model_name="mock-vision-1",
        prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
        ordered_page_hashes=[digest],
    )

    blank = store.record_page_success(
        transcript=transcript,
        submission_page_id=page.id,
        page_no=page.page_no,
        page_order=0,
        source_image_sha256=digest,
        output=VisualPageTranscriptOutput(blocks=[], is_blank_page=True),
        reading_order_start=0,
    )
    assert blank.state == "succeeded"
    assert blank.is_blank_page is True

    with pytest.raises(ScriptTranscriptError, match="terminal page failure state"):
        store.record_page_failure(
            transcript=transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=0,
            source_image_sha256=digest,
            state="succeeded",
            error="not a failure",
        )
    with pytest.raises(ScriptTranscriptError, match="must record why it failed"):
        store.record_page_failure(
            transcript=transcript,
            submission_page_id=page.id,
            page_no=page.page_no,
            page_order=0,
            source_image_sha256=digest,
            state="missing_page",
            error="   ",
        )
    db_session.rollback()


def test_unreadable_writing_is_not_a_successful_block() -> None:
    assert classify_block_text("clean answer") == (False, None)
    assert classify_block_text("   ") == (True, "empty_block_text")
    assert classify_block_text(
        "first line [visible writing unresolved — thinking review required]"
    ) == (True, "unresolved_visible_writing")


def test_the_reuse_fingerprint_covers_every_transcription_relevant_setting() -> None:
    base = {
        "provider": "mock",
        "model_name": "m",
        "prompt_version": "p",
    }
    baseline = transcription_settings_fingerprint(**base)
    assert baseline != transcription_settings_fingerprint(**{**base, "model_name": "m2"})
    assert baseline != transcription_settings_fingerprint(**{**base, "prompt_version": "p2"})
    assert baseline != transcription_settings_fingerprint(**{**base, "provider": "other"})
    assert baseline != transcription_settings_fingerprint(**base, schema_version="v99")
    assert baseline != transcription_settings_fingerprint(
        **base, preprocessing={"pipeline": "deskew", "version": 1}
    )
    assert baseline == transcription_settings_fingerprint(**base)
