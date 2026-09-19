"""Durable, question-independent persistence for a complete script read.

The one-call-per-page read already produced a full-page transcript; it only ever
existed in a local variable, so a crash discarded every paid page read and a
remap or rubric change re-read the whole script. This store owns the source
evidence instead:

* one page's read is committed the moment it succeeds, before the next page is
  dispatched, so completed work survives a restart;
* a page is reused only when the source image and every transcription-relevant
  setting are byte-identical, so reuse can never silently cross a model, prompt,
  schema or preprocessing change;
* a page that did not succeed keeps its own terminal state, so "no answer" can
  never be reconstructed from a failed or missing read.

Question assignment is deliberately absent here. The transcript is the source
record; which question a block answers is a separately versioned decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import ScriptPageTranscript, ScriptTranscript, ScriptTranscriptBlock
from packages.brain.schemas_qwen38 import (
    UNRESOLVED_VISIBLE_WRITING,
    VisualPageBlock,
    VisualPageTranscriptOutput,
)

# Bumped when the persisted block/page shape changes in a way that makes an
# older stored transcript unsafe to reuse.
SCRIPT_TRANSCRIPT_SCHEMA_VERSION = "script-transcript-v1"

# The page-read path sends the rendered page image unmodified. Naming that
# explicitly rather than hard-coding an empty digest means introducing any
# preprocessing changes the fingerprint and invalidates reuse by construction.
NO_PREPROCESSING = {"pipeline": "rendered_page_bytes", "version": 1}

# Markers the transcription prompt uses to keep writing it could not resolve
# visible instead of guessing it. A block carrying one is evidence that needs a
# teacher, never a successful transcription.
_UNRESOLVED_TEXT_MARKERS = (
    UNRESOLVED_VISIBLE_WRITING,
    "[illegible crossed writing]",
    "[unclear correction]",
)


SUCCEEDED = "succeeded"
DISPATCHED = "dispatched"
UNKNOWN_OUTCOME = "unknown_outcome"
FAILED = "failed"
UNREADABLE = "unreadable"
MISSING_PAGE = "missing_page"

# A page whose outcome nobody can determine is never redispatched automatically.
# It is the one state that requires a person to decide what happened.
NON_RETRIABLE_STATES = frozenset({UNKNOWN_OUTCOME})

# Substrings that mean "the request may have been received, executed and billed
# even though we never saw the answer". Matching is on the exception's class
# name and its message, because adapters wrap provider errors in their own types.
_AMBIGUOUS_FAILURE_MARKERS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection closed",
    "broken pipe",
    "incompleteread",
    "remotedisconnected",
)


class ScriptTranscriptError(RuntimeError):
    """A transcript could not be stored or reused safely."""


class PageAlreadyReservedError(ScriptTranscriptError):
    """Another worker holds the claim on this page; do not dispatch it."""


class PageReconciliationRequiredError(ScriptTranscriptError):
    """A previous call's outcome is unknown and must be resolved by a person."""


def classify_dispatch_failure(exc: BaseException) -> str:
    """Decide whether a failed call's outcome is known or merely unobserved.

    A contract violation or an explicit provider rejection is a known failure
    and may be read again. A timeout or a dropped connection is not: the
    provider may have produced and charged for output we never received, so the
    page keeps ``unknown_outcome`` and is excluded from automatic retry.
    """

    if isinstance(exc, TimeoutError):
        return UNKNOWN_OUTCOME
    haystack = f"{type(exc).__name__} {exc}".casefold()
    if any(marker in haystack for marker in _AMBIGUOUS_FAILURE_MARKERS):
        return UNKNOWN_OUTCOME
    return FAILED


@dataclass(frozen=True)
class PageReuse:
    """One page's reuse decision, taken before any provider dispatch."""

    page_transcript: ScriptPageTranscript | None
    reusable: bool
    reason: str


def _canonical_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def transcription_settings_fingerprint(
    *,
    provider: str,
    model_name: str,
    prompt_version: str,
    schema_version: str = SCRIPT_TRANSCRIPT_SCHEMA_VERSION,
    preprocessing: dict[str, Any] | None = None,
) -> str:
    """Digest everything that could change what the model would read."""

    return _canonical_digest(
        {
            "provider": provider,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "preprocessing": preprocessing if preprocessing is not None else NO_PREPROCESSING,
        }
    )


def preprocessing_fingerprint(preprocessing: dict[str, Any] | None = None) -> str:
    return _canonical_digest(preprocessing if preprocessing is not None else NO_PREPROCESSING)


def source_manifest_sha256(ordered_page_hashes: list[str]) -> str:
    """Digest the ordered source pages, so page order is part of identity."""

    return hashlib.sha256("".join(ordered_page_hashes).encode("ascii")).hexdigest()


def classify_block_text(text: str) -> tuple[bool, str | None]:
    """Decide whether a block's text is resolved source evidence."""

    if not text.strip():
        return True, "empty_block_text"
    for marker in _UNRESOLVED_TEXT_MARKERS:
        if marker in text:
            return True, "unresolved_visible_writing"
    return False, None


class ScriptTranscriptStore:
    """Read and write the durable source transcript for one submission."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(
        self,
        *,
        submission_id: int,
        provider: str,
        model_name: str,
        prompt_version: str,
        ordered_page_hashes: list[str],
        preprocessing: dict[str, Any] | None = None,
        schema_version: str = SCRIPT_TRANSCRIPT_SCHEMA_VERSION,
    ) -> ScriptTranscript:
        """Return the transcript row for this exact source and settings.

        Committed immediately so a page read that starts after it can never be
        left with no parent row to attach to.
        """

        fingerprint = transcription_settings_fingerprint(
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            schema_version=schema_version,
            preprocessing=preprocessing,
        )
        manifest = source_manifest_sha256(ordered_page_hashes)
        existing = self.db.scalars(
            select(ScriptTranscript)
            .options(selectinload(ScriptTranscript.pages).selectinload(ScriptPageTranscript.blocks))
            .where(
                ScriptTranscript.submission_id == submission_id,
                ScriptTranscript.settings_fingerprint == fingerprint,
                ScriptTranscript.source_manifest_sha256 == manifest,
            )
        ).first()
        if existing is not None:
            # A superseded row must not silently come back to life; a caller
            # that wants to read again gets a fresh in-progress transcript.
            if existing.status == "superseded":
                existing.status = "in_progress"
            existing.page_count = len(ordered_page_hashes)
            self.db.commit()
            return existing

        transcript = ScriptTranscript(
            submission_id=submission_id,
            settings_fingerprint=fingerprint,
            provider=provider,
            model_name=model_name,
            prompt_version=prompt_version,
            schema_version=schema_version,
            preprocessing_fingerprint=preprocessing_fingerprint(preprocessing),
            source_manifest_sha256=manifest,
            page_count=len(ordered_page_hashes),
            status="in_progress",
        )
        self.db.add(transcript)
        self.db.commit()
        return transcript

    def supersede_stale(
        self,
        *,
        submission_id: int,
        keep_transcript_id: int | None = None,
    ) -> int:
        """Mark every other transcript for this submission superseded.

        Called when the source pages change. The rows are kept, not deleted, so
        a prior version of the evidence stays readable and auditable.
        """

        stale = self.db.scalars(
            select(ScriptTranscript).where(
                ScriptTranscript.submission_id == submission_id,
                ScriptTranscript.status != "superseded",
            )
        ).all()
        changed = 0
        for transcript in stale:
            if keep_transcript_id is not None and transcript.id == keep_transcript_id:
                continue
            transcript.status = "superseded"
            changed += 1
        if changed:
            self.db.commit()
        return changed

    def reuse_decision(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        source_image_sha256: str,
    ) -> PageReuse:
        """Decide reuse before dispatch, never after paying for a call."""

        stored = self.db.scalars(
            select(ScriptPageTranscript)
            .options(selectinload(ScriptPageTranscript.blocks))
            .where(
                ScriptPageTranscript.script_transcript_id == transcript.id,
                ScriptPageTranscript.submission_page_id == submission_page_id,
            )
        ).first()
        if stored is None:
            return PageReuse(page_transcript=None, reusable=False, reason="no_stored_page")
        if stored.source_image_sha256 != source_image_sha256:
            return PageReuse(page_transcript=stored, reusable=False, reason="source_image_changed")
        if stored.state != SUCCEEDED:
            return PageReuse(
                page_transcript=stored,
                reusable=False,
                reason=f"stored_page_state_{stored.state}",
            )
        if (
            stored.provider != transcript.provider
            or stored.model_name != transcript.model_name
            or stored.prompt_version != transcript.prompt_version
            or stored.schema_version != transcript.schema_version
        ):
            return PageReuse(page_transcript=stored, reusable=False, reason="provenance_changed")
        return PageReuse(page_transcript=stored, reusable=True, reason="cached_page_transcript")

    def reserve_page(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        page_no: int,
        page_order: int,
        source_image_sha256: str,
        holder_id: str,
        reservation_stale_after_seconds: int = 900,
    ) -> str:
        """Claim a page before its request is dispatched, and commit the claim.

        The commit is what makes this a reservation rather than an intention: a
        second worker, a double-clicked button or a restarted job sees the claim
        instead of paying for the same page again.

        Refuses outright when a previous attempt left the page in
        ``unknown_outcome``. That is the blind-resubmission case the reservation
        exists to prevent, and only a person can settle it.
        """

        stored = self.db.scalars(
            select(ScriptPageTranscript).where(
                ScriptPageTranscript.script_transcript_id == transcript.id,
                ScriptPageTranscript.submission_page_id == submission_page_id,
            )
        ).first()
        now = datetime.now(UTC)
        if stored is not None:
            if stored.state in NON_RETRIABLE_STATES:
                raise PageReconciliationRequiredError(
                    f"page {page_no} has an unresolved provider outcome and must be "
                    "reconciled before it can be read again"
                )
            if stored.state == DISPATCHED:
                reserved_at = stored.reserved_at
                if reserved_at is not None and reserved_at.tzinfo is None:
                    reserved_at = reserved_at.replace(tzinfo=UTC)
                age = (now - reserved_at).total_seconds() if reserved_at else None
                if age is not None and age < reservation_stale_after_seconds:
                    raise PageAlreadyReservedError(
                        f"page {page_no} is already reserved by {stored.reserved_by!r}"
                    )
                # An expired claim is not evidence that the call failed; it is
                # evidence that nobody knows. Settle it rather than retrying.
                stored.state = UNKNOWN_OUTCOME
                stored.error = (
                    f"a page read reserved by {stored.reserved_by!r} never reported an "
                    "outcome; the provider may have produced and billed a result"
                )
                self.db.commit()
                raise PageReconciliationRequiredError(
                    f"page {page_no} has an unresolved provider outcome and must be "
                    "reconciled before it can be read again"
                )

        reservation_id = uuid4().hex
        stored = self._replace_page_row(
            transcript=transcript,
            submission_page_id=submission_page_id,
            page_no=page_no,
            page_order=page_order,
            source_image_sha256=source_image_sha256,
            state=DISPATCHED,
            is_blank_page=False,
            error=None,
            provider_request_count=0,
            latency_ms=None,
            repair_pass=(stored.repair_pass if stored is not None else 0),
            raw_output_json=None,
            reservation_id=reservation_id,
            reserved_at=now,
            reserved_by=holder_id,
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            # Another worker inserted the claim between our read and our write.
            self.db.rollback()
            raise PageAlreadyReservedError(
                f"page {page_no} was reserved by another worker"
            ) from exc
        return reservation_id

    def reconcile_page(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        resolution: str,
        note: str,
    ) -> ScriptPageTranscript:
        """Settle an unknown outcome explicitly. Never called automatically.

        ``resolution='failed'`` records that the call produced nothing usable
        and makes the page readable again. ``resolution='missing_page'`` records
        that the source page itself cannot be read. Neither infers anything
        about what the provider did; both require a person to say so.
        """

        if resolution not in {FAILED, MISSING_PAGE}:
            raise ScriptTranscriptError(
                f"{resolution!r} is not a reconciliation outcome a person can record"
            )
        if not note.strip():
            raise ScriptTranscriptError("a reconciliation must record who decided what")
        stored = self.db.scalars(
            select(ScriptPageTranscript).where(
                ScriptPageTranscript.script_transcript_id == transcript.id,
                ScriptPageTranscript.submission_page_id == submission_page_id,
            )
        ).first()
        if stored is None:
            raise ScriptTranscriptError("no stored page read to reconcile")
        if stored.state not in NON_RETRIABLE_STATES:
            raise ScriptTranscriptError(
                f"page {stored.page_no} is in state {stored.state!r} and needs no reconciliation"
            )
        stored.state = resolution
        stored.error = f"{stored.error or 'outcome unknown'} | reconciled: {note.strip()}"
        stored.reconciled_at = datetime.now(UTC)
        stored.reservation_id = None
        stored.reserved_at = None
        self.db.commit()
        return stored

    def unresolved_pages(self, transcript: ScriptTranscript) -> list[ScriptPageTranscript]:
        """Pages whose provider outcome nobody has been able to determine."""

        return [page for page in transcript.pages if page.state in NON_RETRIABLE_STATES]

    def record_page_success(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        page_no: int,
        page_order: int,
        source_image_sha256: str,
        output: VisualPageTranscriptOutput,
        reading_order_start: int,
        provider_request_count: int = 1,
        latency_ms: int | None = None,
        repair_pass: int = 0,
    ) -> ScriptPageTranscript:
        """Persist and commit one successful page read immediately.

        The commit is the point of this method. It happens before the caller
        dispatches the next page, so an interrupted run keeps every page it has
        already paid for.
        """

        stored = self._replace_page_row(
            transcript=transcript,
            submission_page_id=submission_page_id,
            page_no=page_no,
            page_order=page_order,
            source_image_sha256=source_image_sha256,
            state="succeeded",
            is_blank_page=output.is_blank_page,
            error=None,
            provider_request_count=provider_request_count,
            latency_ms=latency_ms,
            repair_pass=repair_pass,
            raw_output_json=output.model_dump(mode="json"),
        )
        for index, block in enumerate(_ordered_blocks(output)):
            unresolved, reason = classify_block_text(block.text)
            stored.blocks.append(
                ScriptTranscriptBlock(
                    block_index=index,
                    reading_order=reading_order_start + index,
                    text=block.text,
                    # The provider schema carries the label it matched, not a
                    # separate observed heading string. Only a block that
                    # claims it saw a heading may record one; inferred and
                    # continuation blocks must not imply visible heading text.
                    observed_heading_text=(
                        block.question_label if block.label_source == "heading" else None
                    ),
                    question_label_raw=block.question_label,
                    label_source=block.label_source,
                    continues_from_previous=block.continues_from_previous,
                    confidence=block.confidence,
                    bbox_json={"normalized_bbox": list(block.bbox), "scale": 1000},
                    unresolved=unresolved,
                    unresolved_reason=reason,
                )
            )
        self.db.commit()
        return stored

    def record_page_failure(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        page_no: int,
        page_order: int,
        source_image_sha256: str,
        state: str,
        error: str,
        provider_request_count: int = 1,
        repair_pass: int = 0,
    ) -> ScriptPageTranscript:
        """Persist a page's terminal non-success state with its reason."""

        if state not in {UNREADABLE, MISSING_PAGE, FAILED, UNKNOWN_OUTCOME}:
            raise ScriptTranscriptError(f"{state!r} is not a terminal page failure state")
        if not error.strip():
            raise ScriptTranscriptError("a failed page read must record why it failed")
        stored = self._replace_page_row(
            transcript=transcript,
            submission_page_id=submission_page_id,
            page_no=page_no,
            page_order=page_order,
            source_image_sha256=source_image_sha256,
            state=state,
            is_blank_page=False,
            error=error,
            provider_request_count=provider_request_count,
            latency_ms=None,
            repair_pass=repair_pass,
            raw_output_json=None,
        )
        self.db.commit()
        return stored

    def _replace_page_row(
        self,
        *,
        transcript: ScriptTranscript,
        submission_page_id: int,
        page_no: int,
        page_order: int,
        source_image_sha256: str,
        state: str,
        is_blank_page: bool,
        error: str | None,
        provider_request_count: int,
        latency_ms: int | None,
        repair_pass: int,
        raw_output_json: dict[str, Any] | None,
        reservation_id: str | None = None,
        reserved_at: datetime | None = None,
        reserved_by: str | None = None,
    ) -> ScriptPageTranscript:
        stored = self.db.scalars(
            select(ScriptPageTranscript)
            .options(selectinload(ScriptPageTranscript.blocks))
            .where(
                ScriptPageTranscript.script_transcript_id == transcript.id,
                ScriptPageTranscript.submission_page_id == submission_page_id,
            )
        ).first()
        if stored is None:
            stored = ScriptPageTranscript(
                script_transcript_id=transcript.id,
                submission_page_id=submission_page_id,
            )
            self.db.add(stored)
        else:
            stored.blocks.clear()
            self.db.flush()
        stored.page_no = page_no
        stored.page_order = page_order
        stored.source_image_sha256 = source_image_sha256
        stored.state = state
        stored.is_blank_page = is_blank_page
        stored.error = error
        stored.provider = transcript.provider
        stored.model_name = transcript.model_name
        stored.prompt_version = transcript.prompt_version
        stored.schema_version = transcript.schema_version
        stored.provider_request_count = provider_request_count
        stored.latency_ms = latency_ms
        stored.repair_pass = repair_pass
        stored.raw_output_json = raw_output_json
        # A terminal write releases the claim; a reservation write takes one.
        # Both are set before the flush, because
        # ``ck_script_page_transcript_reservation_is_complete`` is checked on
        # the insert, not at the end of the transaction.
        stored.reservation_id = reservation_id
        stored.reserved_at = reserved_at
        if reserved_by is not None:
            stored.reserved_by = reserved_by
        self.db.flush()
        return stored

    def load_page_output(
        self,
        page_transcript: ScriptPageTranscript,
    ) -> VisualPageTranscriptOutput:
        """Rebuild the provider output from stored blocks, not from the raw JSON.

        Reading it back through the same schema is what proves the persisted
        blocks are sufficient on their own; the raw payload is retained for
        audit, not as the working representation.
        """

        if page_transcript.state != "succeeded":
            raise ScriptTranscriptError(
                f"page {page_transcript.page_no} did not succeed and has no reusable transcript"
            )
        blocks: list[VisualPageBlock] = []
        for block in sorted(page_transcript.blocks, key=lambda item: item.block_index):
            bbox = (block.bbox_json or {}).get("normalized_bbox")
            if not bbox:
                # Every page now round-trips through this method, so a
                # substituted placeholder box would flow straight into region
                # stabilization and crop generation. Fail loudly instead.
                raise ScriptTranscriptError(
                    f"stored block {block.id} on page {page_transcript.page_no} "
                    "has no source geometry"
                )
            blocks.append(
                VisualPageBlock(
                    question_label=block.question_label_raw,
                    bbox=list(bbox),
                    text=block.text,
                    continues_from_previous=block.continues_from_previous,
                    label_source=block.label_source,
                    confidence=block.confidence if block.confidence is not None else 0,
                )
            )
        return VisualPageTranscriptOutput(
            blocks=blocks,
            is_blank_page=page_transcript.is_blank_page,
        )

    def mark_complete(self, transcript: ScriptTranscript) -> None:
        transcript.status = "complete"
        self.db.commit()

    def mark_failed(self, transcript: ScriptTranscript) -> None:
        transcript.status = "failed"
        self.db.commit()


def _ordered_blocks(output: VisualPageTranscriptOutput) -> list[VisualPageBlock]:
    """Sort blocks into reading order, the same order assembly relies on."""

    return [
        block
        for _index, block in sorted(
            enumerate(output.blocks),
            key=lambda item: (
                int(item[1].bbox[1]),
                int(item[1].bbox[3]),
                int(item[1].bbox[0]),
                item[0],
            ),
        )
    ]
