"""Deterministic, in-process harness for the real Bulk Supervised pipeline (test only).

The harness drives the production code path

    ZIP intake -> per-page read -> whole-transcript assignment -> teacher
    transcript-review gate -> draft grading -> run completion

with a FAKE brain provider and no network, model server, Redis or worker. The only
production seam that is replaced is provider construction: ``brain_policy_for_profile``
inside ``app.services.bulk_evaluation_service`` is patched to hand back a policy built from
an injected :class:`~packages.brain.adapter.BrainAdapter`.

What is REAL: ``BulkEvaluationService`` (``create_from_zip``, ``run_next``, ``resume``,
``resume_item``, ``approve_clean``), ``_assert_enabled``, ``_validate_authorization``,
``transcript_review_is_current`` (none of them is patched), the page-read and whole-transcript
assignment services, GradingService, and the teacher transcript gate, which is driven through
the real route FUNCTIONS (``classify_script_transcript_page``,
``confirm_current_answer_evidence_ownership``, ``confirm_script_transcript_review``).

What is SKIPPED or simulated (truthfully, so a green run is not over-read):

* the route layer: HTTP routing, authentication, ``get_owned_assessment_or_404`` ownership, the
  422 confirmations (``strict_auto_pass_confirmed``, ``draft_only_confirmed``,
  ``local_only_confirmed``), RQ enqueueing, ``job_timeout`` and the enqueue-failure pause.
  ``import_zip``, ``try_resume_run``, ``resume_all_items`` and ``drain`` call the service
  directly, and ``drain`` replaces the RQ job chain;
* the managed-local lease: the fake declares ``managed_local_phase=None`` unless it is built
  with ``FakeBulkBrainProvider(corpus, managed_local_phase="Qwen38")``, in which case the real
  ``LocalModelLeaseService`` runs (the phase SWITCH stays off, it would drive real servers);
* upstream confirmations are SEEDED, not driven: ``seed_assessment`` writes
  ``questions_confirmed_at``, ``rubrics_confirmed_at``, ``status='grading_ready'`` and
  ``QuestionNode.teacher_confirmed`` directly; ``age_page_reservations`` / ``age_run_heartbeat``
  write timestamps (time travel);
* provider construction: ``BrainAdapter.for_profile`` (profile catalog, API-key, data-boundary
  and model-hash pins) is bypassed; the fake is named provider ``mock``;
* teacher judgement: ``review_all_transcripts`` rubber-stamps (blank -> ``non_answer``, else
  ``answer_content``, confirm ownership blindly), so it proves the gate MECHANICS only.

Settings have ONE truth: ``bulk_env`` sets the environment so that ``get_settings()`` agrees
with :func:`make_settings` on every flag (and refuses to start if they differ);
``COHORT_MODEL_GRADING_ENABLED`` and ``LOCAL_AI_PHASE_SWITCH_ENABLED`` stay false.

Design rules
------------
* Everything the fake provider returns is derived ONLY from the page image it is
  given (through a registry keyed by the sha256 of the STORED page image, because
  ``create_from_zip`` re-encodes every page to PNG; WHICH page an image is comes from its
  decoded pixels, never from the database's claim, see :func:`register_stored_pages`)
  or from the text it is handed.
* Every transcript block embeds a provenance token::

      SYN150|<student_identifier>|<question_label>|p<page_no>|b<block_no>

  so any leakage of text between students or questions is detectable by string
  inspection, in the stored evidence, the compatibility region, and the grade.
* Nothing here touches ``E:\\teacher-assistant\\data`` or any real artefact. Test files
  must keep storage inside ``tmp_path`` (see :func:`bulk150_env`).
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pymupdf
import pytest
from alembic.config import Config
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.routes.script_transcripts import (
    classify_script_transcript_page,
    confirm_current_answer_evidence_ownership,
    confirm_script_transcript_review,
    reconcile_script_transcript_page,
)
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal, engine
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrBand,
    AnswerRegionOcrCandidate,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    BatchEvidencePrepRun,
    BulkEvaluationItem,
    BulkEvaluationRun,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingDispatchItem,
    GradingDispatchRun,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    GradingRun,
    LocalModelLease,
    Question,
    QuestionImportJob,
    QuestionNode,
    ReferencePageOcrRun,
    Rubric,
    RubricExtractionCriterion,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    ScriptTranscriptBlockRevision,
    Submission,
    SubmissionPage,
    User,
)
from app.schemas import ScriptTranscriptPageClassificationUpdate, ScriptTranscriptReconcileRequest
from app.services import bulk_evaluation_service as bulk_module
from app.services.answer_evidence_assignment import AnswerEvidenceAssignmentService
from app.services.bulk_evaluation_service import BulkEvaluationError, BulkEvaluationService
from app.services.local_model_call_guard import clear_local_model_call_authorization
from app.services.local_model_lease_service import LEASE_KEY, LocalModelLeaseService
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainTransport,
)
from packages.brain.policy import brain_policy_from_settings
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy, RubricBreakdownItem
from packages.brain.schemas_qwen38 import VisualPageBlock, VisualPageTranscriptOutput
from packages.brain.transcript_assignment import (
    FULL_TRANSCRIPT_ASSIGNMENT_PROMPT_VERSION,
    FullTranscriptAssignmentOutput,
    TranscriptBlockReference,
    TranscriptQuestionAssignment,
)

__all__ = [
    "BULK_ENV_FLAGS",
    "CLEANUP_MODELS",
    "BlockSpec",
    "CallRecord",
    "Corpus",
    "DrainResult",
    "FakeBulkBrainProvider",
    "Fault",
    "HarnessError",
    "HarnessStorage",
    "ItemView",
    "PageSpec",
    "ProcessKilled",
    "RecoverMidCall",
    "ResumeOutcome",
    "ReviewOutcome",
    "Seeded",
    "UnregisteredPageError",
    "age_grading_jobs",
    "age_page_reservations",
    "age_run_heartbeat",
    "assert_continuations_isolated",
    "assert_disposable_database",
    "assert_every_answered_question_graded",
    "assert_no_cross_student_evidence",
    "assert_no_final_grades",
    "assert_settings_agree",
    "build_zip",
    "bulk150_db_session",
    "bulk150_env",
    "bulk_environment",
    "common_students",
    "drain",
    "drain_unit_budget",
    "drop_block",
    "empty_non_blank_page",
    "expire_lease",
    "hallucinate_label",
    "hard_kill_skips_lease_release",
    "harness_storage",
    "import_zip",
    "install_fake_brain",
    "item_views",
    "leave_lease_held",
    "make_settings",
    "other_session",
    "parse_tokens",
    "pdf_from_pngs",
    "pixel_digest",
    "precondition",
    "precondition_faults_fired",
    "read_lease",
    "reconcile_unknown_pages",
    "register_stored_pages",
    "render_page_png",
    "require_active_storage",
    "resume_all_items",
    "reverse_blocks",
    "review_all_transcripts",
    "seed_assessment",
    "set_authorised_limit",
    "token",
    "try_resume_run",
]

PROVIDER_NAME = "mock"
MODEL_NAME = "bulk150-fake-v1"
TOKEN_PREFIX = "SYN150"
TOKEN_RE = re.compile(r"SYN150\|([^|\s]+)\|([^|\s]+)\|p(\d+)\|b(\d+)")
QUESTION_TAG_RE = re.compile(r"SYNQ\|([^|\s]+)\|")
UNASSIGNED_QUESTION = "-"

# Every ORM table, child-before-parent (the reverse of ``Base.metadata.sorted_tables``).
# ``test_cleanup_models_cover_every_table`` fails when a migration adds a table that is
# missing here, or when a child is listed after one of its parents.
CLEANUP_MODELS = (
    AuditLog,
    BulkEvaluationItem,
    FinalGrade,
    AnswerRegionOcrCandidate,
    GradingDispatchItem,
    GradeSuggestion,
    AnswerRegionOcrBand,
    ScriptTranscriptBlockRevision,
    GradingQueueItem,
    GradingJob,
    AnswerRegionSegment,
    AnswerRegionOcrRun,
    AnswerRegionMapping,
    AnswerEvidenceSpan,
    ScriptTranscriptBlock,
    AnswerRegion,
    ScriptPageTranscript,
    ReferencePageOcrRun,
    GradingDispatchRun,
    BulkEvaluationRun,
    AnswerEvidenceAssignment,
    SubmissionPage,
    ScriptTranscript,
    Rubric,
    RubricExtractionCriterion,
    QuestionNode,
    GradingRun,
    GradingQueueRun,
    Submission,
    Question,
    QuestionImportJob,
    ExtractionRun,
    BatchEvidencePrepRun,
    Assessment,
    Course,
    User,
    LocalModelLease,
)


class HarnessError(RuntimeError):
    """The harness itself was misused (not a product failure)."""


class UnregisteredPageError(HarnessError):
    """The fake provider was handed an image whose sha256 nobody registered."""


class ProcessKilled(BaseException):
    """Simulates the worker process dying mid-call (deliberately not an ``Exception``).

    It derives from ``BaseException`` so no production ``except Exception`` handler can
    catch it: the run, items, page reservation and ledger rows stay exactly as they were
    committed at the moment of death, which is what recovery code has to cope with.

    LIMIT, read this before trusting a kill test: this is GRACEFUL ``BaseException`` unwinding,
    not ``kill -9``. Every ``finally`` and ``with`` block between the provider call and the
    test still runs. In particular ``LocalModelLeaseService.hold`` releases the model lease in
    its ``finally`` (a database write and commit that a real kill would never perform), so
    with the managed-local fake (``managed_local_phase=...``) a ``ProcessKilled`` leaves NO
    stale lease behind. Use :func:`leave_lease_held` after the kill to model the hard-kill
    case in which the lease row is still held by the dead worker.
    """


# --------------------------------------------------------------------------- tokens


def token(student: str, question: str, page_no: int, block_no: int) -> str:
    return f"{TOKEN_PREFIX}|{student}|{question}|p{page_no}|b{block_no}"


@dataclass(frozen=True)
class Token:
    student: str
    question: str
    page_no: int
    block_no: int

    @property
    def text(self) -> str:
        return token(self.student, self.question, self.page_no, self.block_no)

    @property
    def students(self) -> tuple[str, ...]:
        return tuple(self.student.split("+"))


def parse_tokens(text: str | None) -> list[Token]:
    return [
        Token(match.group(1), match.group(2), int(match.group(3)), int(match.group(4)))
        for match in TOKEN_RE.finditer(text or "")
    ]


# --------------------------------------------------------------------------- corpus


@dataclass(frozen=True)
class BlockSpec:
    """One block the fake provider reports for a page."""

    page_no: int
    block_no: int  # 1-based position in reading (bbox) order on the page
    owner: str  # student field of the token; "A+B" for a byte-identical shared page
    question: str  # TRUE owning question; UNASSIGNED_QUESTION for writing nobody owns
    reported_label: str | None  # what the provider reports as the block's label
    label_source: Literal["heading", "continuation", "inferred"]
    continues_from_previous: bool
    bbox: tuple[int, int, int, int]
    text: str

    @property
    def token(self) -> str:
        return token(self.owner, self.question, self.page_no, self.block_no)


@dataclass(frozen=True)
class PageSpec:
    blocks: tuple[BlockSpec, ...]
    is_blank: bool = False

    def __post_init__(self) -> None:
        if self.is_blank and self.blocks:
            raise HarnessError("a blank page cannot carry blocks")

    def content_key(self) -> tuple[Any, ...]:
        return (
            self.is_blank,
            tuple((b.token, b.reported_label, b.label_source) for b in self.blocks),
        )


@dataclass
class Corpus:
    """What the synthetic archive contains, and what correct evidence looks like."""

    archive_path: Path
    layout: str
    labels: tuple[str, ...]
    students: tuple[str, ...]
    sources: dict[str, str]  # student identifier -> ZIP source (member or folder)
    pages: dict[tuple[str, int], PageSpec]
    page_counts: dict[str, int]
    continuation: Literal[False, "unlabeled", "inferred"] = False
    shared: tuple[tuple[tuple[str, ...], int], ...] = ()
    out_of_order: tuple[str, ...] = ()
    manifest: bool = False
    names: dict[str, str] = field(default_factory=dict)
    page_size: tuple[int, int] = (480, 640)
    image_format: Literal["png", "jpg"] = "png"
    _pixel_owners: dict[str, tuple[tuple[str, int], ...]] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    # -- derived views --------------------------------------------------------

    def page_spec(self, student: str, page_no: int) -> PageSpec:
        return self.pages[(student, page_no)]

    def pixel_owners(self) -> dict[str, tuple[tuple[str, int], ...]]:
        """``pixel digest -> ((student, page_no), ...)`` of the page images production stores.

        The digests are regenerated from the page SPECS (the oracle), not read back from the
        archive or the database, by the same conversion the intake applies to a member:
        image members are decoded to RGB, PDF pages are rasterised at the intake's 2x zoom.
        Byte-identical pages (shared pages, blank pages) have several owners.
        """

        if self._pixel_owners is None:
            index: dict[str, list[tuple[str, int]]] = {}
            for student in self.students:
                for page_no, image in enumerate(_expected_stored_images(self, student), start=1):
                    with image:
                        index.setdefault(pixel_digest(image), []).append((student, page_no))
            self._pixel_owners = {key: tuple(value) for key, value in index.items()}
        return self._pixel_owners

    @property
    def total_pages(self) -> int:
        return sum(self.page_counts.values())

    def expected_tokens(self, student: str, question: str) -> list[str]:
        """Provenance tokens correct evidence for (student, question) must contain."""

        found: list[str] = []
        for page_no in range(1, self.page_counts[student] + 1):
            for block in self.pages[(student, page_no)].blocks:
                if block.question == question:
                    found.append(block.token)
        return found

    def expected_by_owner_question(self) -> dict[tuple[str, str], list[str]]:
        """Index used by the fake grader, where only the token's owner field is known."""

        index: dict[tuple[str, str], set[str]] = {}
        for page in self.pages.values():
            for block in page.blocks:
                index.setdefault((block.owner, block.question), set()).add(block.token)
        return {key: sorted(value) for key, value in index.items()}

    def needs_assignment_call(self, student: str) -> bool:
        """True when the student's script triggers the whole-transcript assignment call."""

        for page_no in range(1, self.page_counts[student] + 1):
            for block in self.pages[(student, page_no)].blocks:
                if block.reported_label is None or block.label_source == "inferred":
                    return True
        return False

    def answered_questions(self, student: str) -> list[str]:
        return [label for label in self.labels if self.expected_tokens(student, label)]

    def call_budget(self) -> int:
        """Exact number of provider calls a clean run is expected to use."""

        reads = self.total_pages
        maps = sum(1 for student in self.students if self.needs_assignment_call(student))
        grades = sum(len(self.answered_questions(student)) for student in self.students)
        return reads + maps + grades


def _default_identifiers(count: int) -> list[str]:
    return [f"S{index:03d}" for index in range(1, count + 1)]


def _plan_pages(
    labels: Sequence[str], pages: int, *, reverse: bool, spill: bool = False
) -> list[list[tuple[str, bool]]]:
    """Spread questions over pages: ``[(question, is_continuation), ...]`` per page.

    ``spill`` makes an answer run over the page break: when page *n* ends on question X and
    page *n+1* opens a different question Y, page *n+1* first carries a continuation of X
    (above Y's heading), the classic case where a continuation and a new question share a page.
    """

    order = list(reversed(labels)) if reverse else list(labels)
    total = len(order)
    plan: list[list[tuple[str, bool]]] = [[] for _ in range(pages)]
    for index, label in enumerate(order):
        first = (index * pages) // total
        last = max(first, ((index + 1) * pages) // total - 1)
        for page_index in range(first, last + 1):
            plan[page_index].append((label, page_index > first))
    if spill:
        for page_index in range(1, pages):
            carried = plan[page_index - 1][-1][0] if plan[page_index - 1] else None
            opening = plan[page_index][0] if plan[page_index] else None
            if (
                carried is not None
                and opening is not None
                and not opening[1]
                and opening[0] != carried
            ):
                plan[page_index].insert(0, (carried, True))
    return plan


def _page_blocks(
    *,
    owner: str,
    page_no: int,
    segments: list[tuple[str, bool]],
    continuation: Literal[False, "unlabeled", "inferred"],
) -> tuple[BlockSpec, ...]:
    count = len(segments)
    if count > 40:
        raise HarnessError("too many answer segments on one page")
    band = 900 // max(count, 1)
    height = max(20, band - 20)
    blocks: list[BlockSpec] = []
    for index, (label, is_continuation) in enumerate(segments):
        top = 50 + index * band
        bbox = (100, top, 900, min(1000, top + height))
        block_no = index + 1
        body = f"answer for {label} on page {page_no}"
        text = f"{token(owner, label, page_no, block_no)} {body}"
        if is_continuation and continuation == "unlabeled":
            reported: str | None = None
            source: Literal["heading", "continuation", "inferred"] = "continuation"
        elif is_continuation and continuation == "inferred":
            reported = label
            source = "inferred"
        else:
            reported = label
            source = "heading"
        blocks.append(
            BlockSpec(
                page_no=page_no,
                block_no=block_no,
                owner=owner,
                question=label,
                reported_label=reported,
                label_source=source,
                continues_from_previous=is_continuation and bool(continuation),
                bbox=bbox,
                text=text,
            )
        )
    return tuple(blocks)


def render_page_png(
    page: PageSpec, size: tuple[int, int] = (480, 640), *, fmt: str = "PNG"
) -> bytes:
    """Deterministic page image: every block is drawn as inked text at its bbox."""

    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for block in page.blocks:
        x1, y1, x2, y2 = block.bbox
        box = (x1 * width // 1000, y1 * height // 1000, x2 * width // 1000, y2 * height // 1000)
        draw.rectangle(box, outline="black")
        draw.text((box[0] + 4, box[1] + 4), block.text[:60], fill="black")
    buffer = BytesIO()
    if fmt.upper() in {"JPG", "JPEG"}:
        image.save(buffer, format="JPEG", quality=70)
    else:
        image.save(buffer, format="PNG")
    return buffer.getvalue()


def pdf_from_pngs(pngs: Sequence[bytes], size: tuple[int, int]) -> bytes:
    doc = pymupdf.open()
    try:
        for png in pngs:
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_image(page.rect, stream=png)
        return doc.tobytes()
    finally:
        doc.close()


_pdf_from_pngs = pdf_from_pngs  # former private name, kept for older sibling modules

# The intake rasterises every PDF page at this zoom (submission_processing._store_pdf_pages).
INTAKE_PDF_ZOOM = 2


def pixel_digest(image: Image.Image) -> str:
    """Identity of what a page LOOKS like: sha256 of its decoded RGB pixels plus its size."""

    rgb = image.convert("RGB")
    digest = hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode("ascii"))
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def _expected_stored_images(corpus: Corpus, student: str) -> Iterator[Image.Image]:
    """The page images production stores for ``student``, regenerated from the corpus specs."""

    count = corpus.page_counts[student]
    if corpus.layout == "images":
        for page_no in range(1, count + 1):
            png = render_page_png(
                corpus.pages[(student, page_no)], corpus.page_size, fmt=corpus.image_format
            )
            yield Image.open(BytesIO(png)).convert("RGB")
        return
    pngs = [
        render_page_png(corpus.pages[(student, page_no)], corpus.page_size)
        for page_no in range(1, count + 1)
    ]
    pdf = _pdf_from_pngs(pngs, corpus.page_size)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for index in range(len(doc)):
            pixmap = doc.load_page(index).get_pixmap(
                matrix=pymupdf.Matrix(INTAKE_PDF_ZOOM, INTAKE_PDF_ZOOM), alpha=False
            )
            yield Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def build_zip(
    path: Path,
    *,
    students: int = 3,
    pages: int = 2,
    questions: int | Sequence[str] = 2,
    layout: Literal["pdf", "images", "folders"] = "images",
    manifest: bool = False,
    identifiers: Sequence[str] | None = None,
    continuation: bool | Literal["unlabeled", "inferred"] = False,
    spill: bool = False,
    out_of_order: Sequence[str] = (),
    blank_pages: Sequence[tuple[str, int]] = (),
    shared_pages: Sequence[tuple[Sequence[str], int]] = (),
    page_size: tuple[int, int] = (480, 640),
    image_format: Literal["png", "jpg"] = "png",
    wrapper: str | None = None,
    compression: int = zipfile.ZIP_STORED,
) -> Corpus:
    """Write a synthetic bulk archive and describe exactly what is in it.

    ``layout``: ``pdf`` = one real PDF per student at the ZIP root; ``images`` = one folder
    per student holding numbered images; ``folders`` = one folder per student holding a
    single PDF. ``questions`` is a count (labels ``Q1..Qn``) or the explicit labels.

    ``continuation``: ``False`` writes a heading on every page a question touches;
    ``"unlabeled"``/``True`` writes later pages of a multi-page answer as unlabelled
    continuation blocks; ``"inferred"`` labels them but marks ``label_source='inferred'``.
    Either non-False value makes the script trigger the whole-transcript assignment call.
    ``spill``: answers also run over page breaks into a page that opens another question, so
    a continuation block sits above that question's heading (see :func:`_plan_pages`).

    ``out_of_order``: students (by identifier) who answer the questions in reverse order.
    ``blank_pages``: ``(student, page_no)`` pairs replaced by a genuinely blank page.
    ``shared_pages``: ``((student_a, student_b), page_no)``: those students hand in a
    byte-identical page image, and the provider returns the same blocks for it (owner field
    ``"a+b"``). The page number must be the same for both, because the token embeds it.
    ``wrapper``: put every member under one top-level folder (a probe layout).
    """

    labels = (
        tuple(f"Q{index}" for index in range(1, questions + 1))
        if isinstance(questions, int)
        else tuple(questions)
    )
    if not labels or len(set(labels)) != len(labels):
        raise HarnessError("question labels must be nonempty and unique")
    ids = list(identifiers) if identifiers is not None else _default_identifiers(students)
    if len(set(ids)) != len(ids):
        raise HarnessError("student identifiers must be unique")
    for identifier in ids:
        if not re.fullmatch(r"[^|\s+]+", identifier):
            raise HarnessError(f"identifier {identifier!r} cannot be embedded in a token")
    mode: Literal[False, "unlabeled", "inferred"] = (
        "unlabeled" if continuation is True else continuation
    )
    shared_owner: dict[tuple[str, int], str] = {}
    shared_norm: list[tuple[tuple[str, ...], int]] = []
    for owners, page_no in shared_pages:
        owner_tuple = tuple(owners)
        if len(owner_tuple) < 2 or any(owner not in ids for owner in owner_tuple):
            raise HarnessError("shared_pages needs two or more known students")
        shared_norm.append((owner_tuple, page_no))
        for owner in owner_tuple:
            shared_owner[(owner, page_no)] = "+".join(sorted(owner_tuple))
    blank_set = {(student, page_no) for student, page_no in blank_pages}

    page_specs: dict[tuple[str, int], PageSpec] = {}
    for identifier in ids:
        plan = _plan_pages(labels, pages, reverse=identifier in set(out_of_order), spill=spill)
        for page_index, segments in enumerate(plan):
            page_no = page_index + 1
            if (identifier, page_no) in blank_set:
                page_specs[(identifier, page_no)] = PageSpec(blocks=(), is_blank=True)
                continue
            owner = shared_owner.get((identifier, page_no), identifier)
            page_specs[(identifier, page_no)] = PageSpec(
                blocks=_page_blocks(
                    owner=owner, page_no=page_no, segments=segments, continuation=mode
                )
            )
    page_counts = {identifier: pages for identifier in ids}

    use_manifest = manifest
    sources: dict[str, str] = {}
    names: dict[str, str] = {}
    members: dict[str, bytes] = {}
    prefix = f"{wrapper.strip('/')}/" if wrapper else ""
    extension = "jpg" if image_format == "jpg" else "png"
    for index, identifier in enumerate(ids, start=1):
        base = f"scan_{index:04d}" if use_manifest else identifier
        names[identifier] = f"Student {identifier}"
        pngs = [
            render_page_png(page_specs[(identifier, page_no)], page_size, fmt=image_format)
            for page_no in range(1, pages + 1)
        ]
        if layout == "pdf":
            member = f"{prefix}{base}.pdf"
            members[member] = _pdf_from_pngs(
                [
                    render_page_png(page_specs[(identifier, p)], page_size)
                    for p in range(1, pages + 1)
                ],
                page_size,
            )
            sources[identifier] = member
        elif layout == "folders":
            member = f"{prefix}{base}/script.pdf"
            members[member] = _pdf_from_pngs(
                [
                    render_page_png(page_specs[(identifier, p)], page_size)
                    for p in range(1, pages + 1)
                ],
                page_size,
            )
            sources[identifier] = f"{prefix}{base}"
        elif layout == "images":
            for page_no, png in enumerate(pngs, start=1):
                members[f"{prefix}{base}/page{page_no}.{extension}"] = png
            sources[identifier] = f"{prefix}{base}"
        else:
            raise HarnessError(f"unknown layout {layout!r}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for member, content in members.items():
            archive.writestr(member, content)
        if use_manifest:
            buffer = StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(["source", "student_identifier", "student_name"])
            for identifier in ids:
                writer.writerow([sources[identifier], identifier, names[identifier]])
            archive.writestr("manifest.csv", buffer.getvalue().encode("utf-8"))
    return Corpus(
        archive_path=path,
        layout=layout,
        labels=labels,
        students=tuple(ids),
        sources=sources,
        pages=page_specs,
        page_counts=page_counts,
        continuation=mode,
        shared=tuple(shared_norm),
        out_of_order=tuple(out_of_order),
        manifest=use_manifest,
        names=names,
        page_size=page_size,
        image_format=image_format,
    )


# --------------------------------------------------------------------------- provider


CallKind = Literal["read_page", "map", "grade", "verify"]


@dataclass
class CallRecord:
    # ``verify`` records live in ``provider.verify_calls``, never in ``provider.calls``: a
    # model-availability probe is not a billed call and must not move ``counts``/``total_calls``.
    kind: CallKind
    index: int  # 1-based, within this kind
    seq: int  # 1-based, across all billed kinds (0 for verify)
    students: tuple[str, ...] = ()
    question: str | None = None
    page_no: int | None = None
    image_sha256: str | None = None
    evidence_text: str = ""
    tokens: tuple[str, ...] = ()
    open_continuations: tuple[str, ...] = ()
    question_labels: tuple[str, ...] = ()
    verdict: str = ""
    outcome: str = "ok"


@dataclass
class Fault:
    """Make a matching provider call fail, misbehave, or run arbitrary code.

    ``kind`` selects the method: ``read_page``, ``map``, ``grade``, or ``verify``.
    ``verify`` is ``verify_available_model``, which ``hold_brain_execution`` calls BEFORE any
    page row or reservation exists (so it models "the model server is down" with nothing yet
    committed). It is also called once by the ``create_from_zip`` preflight, so ``on_call=1`` is
    that preflight and ``on_call=2`` is the first script's read.

    ``on_call`` is the 1-based index among calls of that kind. ``student``/``page_sha``/
    ``question`` narrow the match (read: the page's owner students, which holds BOTH students
    for a byte-identical shared page, so use ``on_call`` there; grade: the students named by
    the evidence tokens). ``times`` limits how many times it fires (``None`` = every match).

    The effect is one of:

    * ``exc``: an exception instance or a factory taking the :class:`CallRecord` (use
      :class:`ProcessKilled` for process death). Raised at the ``when`` timing point;
    * ``transform``: a callable that receives the output the fake is about to return (a
      ``VisualPageTranscriptOutput`` for ``read_page``, the assignment ``dict`` for ``map``, a
      ``GradeSuggestionOutput`` for ``grade``) and returns what to return instead. The recorded
      ``tokens`` of a read follow the transformed blocks. See :func:`drop_block`,
      :func:`hallucinate_label`, :func:`empty_non_blank_page` and :func:`reverse_blocks`;
    * ``callback`` (optionally in addition): a callable run with the record at the same point,
      during the provider call, e.g. :class:`RecoverMidCall`, another session pressing Recover.

    ``when`` is the timing, ``"before"`` (default) or ``"after"``. ``"after"`` computes and
    records the output first and then raises: the provider produced and billed an answer that
    nobody ever saw. For backward compatibility a callable ``when`` is still accepted as an
    extra match predicate (timing ``before``); ``predicate`` is the explicit spelling and can
    be combined with ``when="after"``.

    ``fired`` counts applications, transforms included, and :meth:`assert_fired` fails when a
    mis-targeted Fault silently never triggered.
    """

    kind: CallKind
    exc: BaseException | Callable[[CallRecord], BaseException] | None = None
    on_call: int | None = None
    student: str | None = None
    page_sha: str | None = None
    question: str | None = None
    when: Literal["before", "after"] | Callable[[CallRecord], bool] | None = None
    times: int | None = 1
    fired: int = 0
    transform: Callable[[Any], Any] | None = None
    callback: Callable[[CallRecord], Any] | None = None
    predicate: Callable[[CallRecord], bool] | None = None
    timing: Literal["before", "after"] = field(default="before", init=False)

    def __post_init__(self) -> None:
        if callable(self.when):
            if self.predicate is None:
                self.predicate = self.when
        elif self.when in (None, "before"):
            pass
        elif self.when == "after":
            self.timing = "after"
        else:
            raise HarnessError(
                f"Fault.when must be 'before', 'after' or a predicate: {self.when!r}"
            )
        if self.exc is None and self.transform is None and self.callback is None:
            raise HarnessError("a Fault needs an exc, a transform or a callback")
        if self.exc is not None and self.transform is not None:
            raise HarnessError("a Fault is either an exception or a transform, not both")
        if self.kind == "verify" and (self.transform is not None or self.timing == "after"):
            raise HarnessError("a verify Fault has no output: use exc/callback with when='before'")

    def matches(self, record: CallRecord) -> bool:
        if record.kind != self.kind:
            return False
        if self.times is not None and self.fired >= self.times:
            return False
        if self.on_call is not None and record.index != self.on_call:
            return False
        if self.student is not None and self.student not in record.students:
            return False
        if self.page_sha is not None and record.image_sha256 != self.page_sha:
            return False
        if self.question is not None and record.question != self.question:
            return False
        return self.predicate is None or self.predicate(record)

    def build(self, record: CallRecord) -> BaseException:
        """Count one firing and return the exception to raise (``exc`` must be set)."""

        self.fired += 1
        assert self.exc is not None
        return self.exc(record) if callable(self.exc) else self.exc

    def assert_fired(self) -> None:
        if not self.fired:
            raise HarnessError(f"{self!r} never fired: it matched no provider call")


@dataclass
class _PageEntry:
    spec: PageSpec
    students: set[str] = field(default_factory=set)
    pages: set[tuple[str, int]] = field(default_factory=set)


class FakeBulkBrainProvider(BrainProvider):
    """Records every call and answers deterministically from its inputs only.

    * ``read_page`` is answered from the registry keyed by sha256 of the STORED page image.
    * ``map_submission_answers_from_ocr_pages`` assigns each block to the question named in
      its own provenance token.
    * ``grade`` learns the question from the ``SYNQ|<label>|`` tag that :func:`seed_assessment`
      writes into every question's text, and the student only from the tokens inside the
      evidence it is handed (production sends no student identity in the grading prompt, so
      a complete substitution by ONE other student is invisible to the grader and is caught
      only by :func:`assert_no_cross_student_evidence`). Confidence is 0.95 when the evidence
      is single-student, single-question and exactly the expected token set, else 0.40.
    * Every call is recorded in ``calls`` (counted per kind in ``counts``) before any injected
      :class:`Fault` can raise, because a failed call was still dispatched.
    * ``verify_available_model`` is the model-availability probe ``hold_brain_execution`` runs
      before each operation. Its calls are recorded in ``verify_calls`` and are NOT billed
      calls: they never move ``counts``, ``calls`` or ``total_calls``.

    ``managed_local_phase`` (default ``None``) is the opt-in switch for the managed-local path:
    ``FakeBulkBrainProvider(corpus, managed_local_phase="Qwen38")`` makes
    ``hold_brain_execution`` take the REAL ``LocalModelLeaseService`` lease around every
    operation (the preflight, each script read, each grade) and enables the evidence-changed
    recheck in GradingService that the pilot's managed-local Qwen runs. The phase SWITCH stays
    off (``LOCAL_AI_PHASE_SWITCH_ENABLED=false``), so no model server is ever touched. Build
    the provider BEFORE :func:`install_fake_brain`: ``BrainAdapter`` copies the phase at
    construction.
    """

    provider_name = PROVIDER_NAME
    model_name = MODEL_NAME
    capabilities = frozenset(
        {
            BrainCapability.VISUAL_PAGE_READ,
            BrainCapability.OCR_ANSWER_MAPPING,
            BrainCapability.GRADING,
        }
    )
    execution_location = BrainExecutionLocation.LOCAL
    transport = BrainTransport.IN_PROCESS
    image_input_mode = BrainImageInputMode.NONE
    managed_local_phase: str | None = None

    CLEAN_CONFIDENCE = Decimal("0.95")
    LOW_CONFIDENCE = Decimal("0.40")

    def __init__(self, corpus: Corpus, *, managed_local_phase: str | None = None) -> None:
        if managed_local_phase not in (None, "PaddleOcr", "Qwen", "Qwen38"):
            raise HarnessError(f"unknown managed_local_phase {managed_local_phase!r}")
        self.managed_local_phase = managed_local_phase
        self.corpus = corpus
        self.verify_calls: list[CallRecord] = []
        # Harness misuse seen from inside a provider call (e.g. an unregistered page). run_next
        # turns any Exception into a 'paused' run that looks like a product failure; this list
        # is how a test tells the two apart (see ``drain(strict_harness=True)``).
        self.harness_errors: list[str] = []
        self.registry: dict[str, _PageEntry] = {}
        self.calls: list[CallRecord] = []
        self.faults: list[Fault] = []
        # Intake mis-assignments tolerated by ``register_stored_pages(strict_identity=False)``.
        self.identity_mismatches: list[str] = []
        # (student, page_no) -> other student whose blocks are (wrongly) returned.
        self.leak: dict[tuple[str, int], str] = {}
        # "reading" returns blocks top-to-bottom; "reversed" returns them bottom-to-top, i.e.
        # NOT in the bbox order the transcript store persists them in.
        self.emit_order: Literal["reading", "reversed"] = "reading"
        self._counters: Counter[str] = Counter()

    # -- registry / recording -----------------------------------------------------

    def register(self, sha256: str, spec: PageSpec, *, student: str, page_no: int) -> None:
        entry = self.registry.get(sha256)
        if entry is None:
            entry = _PageEntry(spec=spec)
            self.registry[sha256] = entry
        elif entry.spec.content_key() != spec.content_key():
            raise HarnessError(
                f"two different expected pages produced identical image bytes ({sha256[:12]})"
            )
        entry.students.add(student)
        entry.pages.add((student, page_no))

    def inject(self, fault: Fault) -> Fault:
        self.faults.append(fault)
        return fault

    @property
    def counts(self) -> dict[str, int]:
        return {kind: self._counters[kind] for kind in ("read_page", "map", "grade")}

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    def calls_of(self, kind: str) -> list[CallRecord]:
        if kind == "verify":
            return list(self.verify_calls)
        return [record for record in self.calls if record.kind == kind]

    def assert_faults_fired(self) -> None:
        """Fail when an injected Fault matched no call (a mis-targeted Fault is silent)."""

        for fault in self.faults:
            fault.assert_fired()

    def _fire(self, record: CallRecord, timing: Literal["before", "after"]) -> None:
        """Run every exception/callback Fault that is due at ``timing`` for ``record``."""

        for fault in self.faults:
            if fault.transform is not None or fault.timing != timing or not fault.matches(record):
                continue
            fault.fired += 1
            if fault.callback is not None:
                fault.callback(record)
            if fault.exc is not None:
                exc = fault.exc(record) if callable(fault.exc) else fault.exc
                prefix = "raised" if timing == "before" else "raised_after"
                record.outcome = f"{prefix}:{type(exc).__name__}"
                raise exc

    def _begin(self, kind: Literal["read_page", "map", "grade"], **fields: Any) -> CallRecord:
        self._counters[kind] += 1
        record = CallRecord(
            kind=kind, index=self._counters[kind], seq=len(self.calls) + 1, **fields
        )
        self.calls.append(record)
        self._fire(record, "before")
        return record

    def _transform(self, record: CallRecord, output: Any) -> tuple[Any, bool]:
        """Apply every matching transform Fault to the output about to be returned."""

        applied = False
        for fault in self.faults:
            if fault.transform is None or not fault.matches(record):
                continue
            fault.fired += 1
            if fault.callback is not None:
                fault.callback(record)
            output = fault.transform(output)
            record.verdict = f"{record.verdict} transformed".strip()
            applied = True
        return output, applied

    def _complete(self, record: CallRecord, output: Any) -> Any:
        """Transform, then raise any ``when='after'`` Fault: output computed but never seen."""

        output, transformed = self._transform(record, output)
        if transformed and isinstance(output, VisualPageTranscriptOutput):
            record.tokens = tuple(t.text for b in output.blocks for t in parse_tokens(b.text))
        self._fire(record, "after")
        return output

    def verify_available_model(self) -> None:
        """The availability probe; recorded apart from the billed calls (see class docstring)."""

        record = CallRecord(kind="verify", index=len(self.verify_calls) + 1, seq=0)
        self.verify_calls.append(record)
        self._fire(record, "before")

    # -- BrainProvider contract -----------------------------------------------------

    def read_page(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        question_labels: list[str],
        question_references: list[dict[str, Any]] | None = None,
        open_continuations: list[str] | None = None,
    ) -> VisualPageTranscriptOutput:
        del mime_type, question_references
        sha = hashlib.sha256(image_bytes).hexdigest()
        entry = self.registry.get(sha)
        record = self._begin(
            "read_page",
            students=tuple(sorted(entry.students)) if entry else (),
            page_no=min((page for _s, page in entry.pages), default=None) if entry else None,
            image_sha256=sha,
            open_continuations=tuple(open_continuations or ()),
            question_labels=tuple(question_labels),
        )
        if entry is None:
            record.outcome = "unregistered"
            message = f"no expected page registered for image {sha[:16]}"
            self.harness_errors.append(message)
            raise UnregisteredPageError(message)
        spec = entry.spec
        for (student, page_no), other in self.leak.items():
            if (student, page_no) in entry.pages:
                spec = self.corpus.page_spec(other, page_no)
                record.verdict = f"leaked:{other}"
        emitted = (
            list(reversed(spec.blocks)) if self.emit_order == "reversed" else list(spec.blocks)
        )
        blocks = [
            VisualPageBlock(
                question_label=block.reported_label,
                bbox=list(block.bbox),
                text=block.text,
                continues_from_previous=block.continues_from_previous,
                label_source=block.label_source,
                confidence=Decimal("0.97"),
            )
            for block in emitted
        ]
        record.tokens = tuple(block.token for block in emitted)
        return self._complete(
            record, VisualPageTranscriptOutput(blocks=blocks, is_blank_page=spec.is_blank)
        )

    def map_submission_answers_from_ocr_pages(
        self,
        *,
        pages: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        texts = " ".join(
            str(block.get("text") or "") for page in pages for block in page.get("blocks", [])
        )
        found = parse_tokens(texts)
        record = self._begin(
            "map",
            students=tuple(sorted({s for t in found for s in t.students})),
            evidence_text=texts,
            tokens=tuple(t.text for t in found),
            question_labels=tuple(str(q["question_no"]) for q in questions),
        )
        owner_by_label: dict[str, list[tuple[int, int]]] = {}
        unassigned: dict[int, list[int]] = {}
        for page in pages:
            page_no = int(page.get("page_no") or page.get("page") or 0)
            for block in page.get("blocks", []):
                parsed = parse_tokens(str(block.get("text") or ""))
                order = int(block["order"])
                if not parsed or parsed[0].question == UNASSIGNED_QUESTION:
                    unassigned.setdefault(page_no, []).append(order)
                    continue
                owner_by_label.setdefault(parsed[0].question, []).append((page_no, order))
        mappings: list[TranscriptQuestionAssignment] = []
        for question in questions:
            label = str(question["question_no"])
            refs: dict[int, list[int]] = {}
            for page_no, order in owner_by_label.get(label, []):
                refs.setdefault(page_no, []).append(order)
            mappings.append(
                TranscriptQuestionAssignment(
                    question_id=int(question["question_id"]),
                    question_no=label,
                    status="mapped" if refs else "not_found",
                    block_references=[
                        TranscriptBlockReference(page_no=page_no, block_orders=orders)
                        for page_no, orders in sorted(refs.items())
                    ],
                    confidence=Decimal("0.95"),
                )
            )
        output = FullTranscriptAssignmentOutput(
            contract_version=FULL_TRANSCRIPT_ASSIGNMENT_PROMPT_VERSION,  # type: ignore[arg-type]
            mappings=mappings,
            unassigned_block_references=[
                TranscriptBlockReference(page_no=page_no, block_orders=orders)
                for page_no, orders in sorted(unassigned.items())
            ],
            non_answer_block_references=[],
        )
        record.verdict = "mapped"
        return self._complete(record, output.model_dump(mode="json"))

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.MOCK_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del answer_image_path, task_name, model_policy, messages, image_data_url
        tag = QUESTION_TAG_RE.search(question_text)
        label = tag.group(1) if tag else None
        evidence = student_answer_text or ""
        found = parse_tokens(evidence)
        # Single-student means the tokens' student sets INTERSECT (a shared page's token
        # names both students); then the call is attributed to those students.
        owners = common_students(found)
        everyone = {s for t in found for s in t.students}
        record = self._begin(
            "grade",
            students=tuple(sorted(owners or everyone)),
            question=label,
            evidence_text=evidence,
            tokens=tuple(t.text for t in found),
        )
        questions_seen = {t.question for t in found}
        clean = bool(found) and bool(owners) and questions_seen == {label}
        reason = "ok"
        if not found:
            reason = "no_provenance_token"
        elif not owners:
            reason = "mixed_students"
        elif questions_seen != {label}:
            reason = "wrong_question"
        elif not any(
            sorted({t.text for t in found}) == sorted(self.corpus.expected_tokens(student, label))
            for student in owners
            if student in self.corpus.students
        ):
            clean = False
            reason = "incomplete_or_extra_evidence"
        record.verdict = reason
        criteria = rubric_json.get("criteria", [])
        breakdown = [
            RubricBreakdownItem(
                criterion_id=str(criterion["id"]),
                criterion=str(criterion["name"]),
                max_marks=Decimal(str(criterion["max_marks"])),
                awarded_marks=Decimal(str(criterion["max_marks"])) if clean else Decimal("0"),
                reason=f"synthetic grader verdict: {reason}",
                evidence=found[0].text if found else None,
                confidence=self.CLEAN_CONFIDENCE if clean else self.LOW_CONFIDENCE,
            )
            for criterion in criteria
        ]
        score = sum((item.awarded_marks for item in breakdown), Decimal("0"))
        flags = ["synthetic_fake_provider", "teacher_review_required"]
        if not clean:
            flags.append(f"synthetic_evidence_{reason}")
        return self._complete(
            record,
            GradeSuggestionOutput(
                score=score,
                max_score=Decimal(str(rubric_json.get("total_marks", question_total_marks))),
                confidence=self.CLEAN_CONFIDENCE if clean else self.LOW_CONFIDENCE,
                needs_review=True,
                rubric_breakdown=breakdown,
                detected_answer_summary="SYN150 saw: "
                + (" ".join(t.text for t in found) or "nothing"),
                major_errors=[],
                feedback_to_student="Synthetic draft feedback.",
                review_flags=flags,
                model_provider=self.provider_name,
                model_name=self.model_name,
                prompt_version=prompt_version,
            ),
        )


# --------------------------------------------------------------------------- fault helpers

PageTransform = Callable[[VisualPageTranscriptOutput], VisualPageTranscriptOutput]


def drop_block(index: int = 0) -> PageTransform:
    """``Fault.transform``: the model silently omits one block (writing that is never read)."""

    def transform(output: VisualPageTranscriptOutput) -> VisualPageTranscriptOutput:
        blocks = list(output.blocks)
        del blocks[index]
        return output.model_copy(update={"blocks": blocks})

    return transform


def hallucinate_label(label: str = "Q99", index: int = 0) -> PageTransform:
    """``Fault.transform``: one block comes back labelled with a question that does not exist."""

    def transform(output: VisualPageTranscriptOutput) -> VisualPageTranscriptOutput:
        blocks = list(output.blocks)
        blocks[index] = blocks[index].model_copy(
            update={
                "question_label": label,
                "label_source": "heading",
                "continues_from_previous": False,
            }
        )
        return output.model_copy(update={"blocks": blocks})

    return transform


def empty_non_blank_page() -> PageTransform:
    """``Fault.transform``: the page is declared non-blank but no block was returned."""

    def transform(output: VisualPageTranscriptOutput) -> VisualPageTranscriptOutput:
        del output
        return VisualPageTranscriptOutput(blocks=[], is_blank_page=False)

    return transform


def reverse_blocks() -> PageTransform:
    """``Fault.transform``: the blocks come back bottom-to-top, not in the bbox order stored."""

    def transform(output: VisualPageTranscriptOutput) -> VisualPageTranscriptOutput:
        return output.model_copy(update={"blocks": list(reversed(output.blocks))})

    return transform


# --------------------------------------------------------------------------- preconditions


def precondition(condition: object, message: str = "") -> None:
    """Fail the test, as a real FAILURE, when a setup step did not happen the way it must.

    Use it (never a bare ``assert``) for everything in a ``GAP`` test that is NOT the
    desired-behaviour assertion: that the injected Fault fired, that the run reached the state
    the scenario needs, that a helper's own expectation held. A GAP test is
    ``xfail(strict=True, raises=AssertionError)``; a failed ``assert`` in its setup is ALSO an
    ``AssertionError``, so a Fault that was mis-targeted or never fired would still XFAIL and
    the test would "prove" a production defect it never reached.

    ``pytest.fail`` raises ``Failed``, which is not an ``AssertionError``, so ``xfail(raises=
    AssertionError)`` does not absorb it: a broken precondition is reported as FAILED.

    Call it from test code only. ``Failed`` is a ``BaseException``: raised from inside a
    provider callback or anything else that runs under ``run_next`` it would unwind mid-unit
    exactly like :class:`ProcessKilled`.
    """

    if not condition:
        pytest.fail(f"PRECONDITION BROKEN (the scenario never reached the gap): {message}")


def precondition_faults_fired(provider: FakeBulkBrainProvider) -> None:
    """:func:`precondition` that every Fault injected into ``provider`` has fired at least once.

    Call it right after the step that should have triggered the Fault, not at the end of the
    test: in a GAP test the end is never reached when the desired assertion fails.
    """

    silent = [fault for fault in provider.faults if not fault.fired]
    precondition(not silent, f"an injected Fault never fired: {silent!r}")


@contextmanager
def other_session(lock_timeout_ms: int = 2000) -> Iterator[Session]:
    """An independent session (another browser tab, another worker) that cannot hang the test.

    ``lock_timeout`` makes a statement that needs a row the in-flight unit still holds
    ``FOR UPDATE`` fail with an ``OperationalError`` after ``lock_timeout_ms`` instead of
    deadlocking a single-threaded test.

    The session lives on its OWN engine, never on the application's pooled ``engine``: it uses
    ``NullPool`` (every connection is closed when the session releases it, none is ever
    returned to a pool) and the timeout is a connection STARTUP option
    (``-c lock_timeout=...``), so every connection this session opens already carries it. The
    obvious alternative, ``SET lock_timeout`` on a ``SessionLocal()`` followed by ``RESET``,
    is WRONG: a ``Session`` does not pin one connection across ``commit()``. It releases its
    connection to the pool and checks out whichever is free for the next statement, so a
    ``SET`` and its ``RESET`` can land on two different pooled connections and strand
    ``lock_timeout`` on the first, where it hangs around for whichever test draws that
    connection next. Nothing here ever modifies a pooled connection.
    """

    own_engine = create_engine(
        engine.url,  # the URL object: ``str(engine.url)`` would mask a password
        poolclass=NullPool,
        connect_args={"options": f"-c lock_timeout={int(lock_timeout_ms)}"},
    )
    session = sessionmaker(bind=own_engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        try:
            session.rollback()
        finally:
            try:
                session.close()
            finally:
                own_engine.dispose()


class RecoverMidCall:
    """``Fault.callback``: another session presses Recover while a provider call is in flight.

    Ages the run's heartbeat (so it looks abandoned) and calls the real
    ``BulkEvaluationService.resume`` from an independent session, then lets the in-flight call
    carry on. ``resumed``/``refusal``/``error`` record what that second session saw.
    """

    def __init__(
        self, run_id: int, teacher_id: int, *, settings: Settings, age_heartbeat: bool = True
    ) -> None:
        self.run_id = run_id
        self.teacher_id = teacher_id
        self.settings = settings
        self.age_heartbeat = age_heartbeat
        self.invocations = 0
        self.resumed: bool | None = None
        self.refusal: str | None = None
        self.error: BaseException | None = None

    def __call__(self, record: CallRecord) -> None:
        del record
        self.invocations += 1
        storage = harness_storage(self.settings)
        try:
            with other_session() as db:
                if self.age_heartbeat:
                    run = db.get(BulkEvaluationRun, self.run_id)
                    if run is None:
                        raise HarnessError(f"RecoverMidCall: run {self.run_id} does not exist")
                    run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=100000)
                    db.commit()
                service = BulkEvaluationService(db, settings=self.settings, storage=storage)
                try:
                    service.resume(service.get_run(self.run_id), teacher_id=self.teacher_id)
                    self.resumed = True
                except BulkEvaluationError as exc:
                    db.rollback()
                    self.resumed, self.refusal = False, str(exc)
        except DBAPIError as exc:  # e.g. lock timeout: the in-flight unit still holds a row
            self.error = exc


def hard_kill_skips_lease_release(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make :class:`ProcessKilled` behave like ``kill -9`` for the managed-local lease.

    ``ProcessKilled`` unwinds gracefully, so ``LocalModelLeaseService.hold``'s ``finally``
    releases the lease (a database write a dead process would never make). With this patch a
    ``release`` reached while a ``ProcessKilled`` is propagating does nothing except drop the
    process-local call authorization (it dies with the process); the DATABASE row stays held by
    the dead worker. Every other release is the real one. Returns the list of holder ids whose
    release was skipped.
    """

    original = LocalModelLeaseService.release
    skipped: list[str] = []

    def release(self: LocalModelLeaseService, *, holder_id: str) -> None:
        if isinstance(sys.exc_info()[1], ProcessKilled):
            skipped.append(holder_id)
            clear_local_model_call_authorization(holder_id=holder_id)
            return
        original(self, holder_id=holder_id)

    monkeypatch.setattr(LocalModelLeaseService, "release", release)
    return skipped


def read_lease(db: Session) -> LocalModelLease | None:
    db.expire_all()
    return db.scalar(select(LocalModelLease).where(LocalModelLease.lease_key == LEASE_KEY))


def leave_lease_held(
    db: Session,
    *,
    phase: str = "Qwen38",
    holder_kind: str = "script_page_read",
    holder_id: str | None = None,
    seconds: int = 1800,
) -> str:
    """Make the database look like a HARD kill: a dead worker still holds the model lease.

    ``ProcessKilled`` unwinds gracefully and releases the lease, so after one the row is free.
    This writes the row a ``kill -9`` would have left behind (held, expiring in ``seconds``).
    Returns the dead holder's id.
    """

    holder = holder_id or f"{holder_kind}:dead-{uuid4().hex}"
    now = datetime.now(UTC)
    row = read_lease(db)
    if row is None:
        row = LocalModelLease(lease_key=LEASE_KEY)
        db.add(row)
    row.model_phase = phase
    row.holder_kind = holder_kind
    row.holder_id = holder
    row.acquired_at = now
    row.heartbeat_at = now
    row.expires_at = now + timedelta(seconds=seconds)
    db.commit()
    return holder


def expire_lease(db: Session, *, seconds_ago: int = 60) -> None:
    """Move the lease's expiry into the past, as 30 minutes without a heartbeat would."""

    row = read_lease(db)
    if row is None or row.holder_id is None:
        raise HarnessError("no held lease to expire")
    row.expires_at = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    db.commit()


# --------------------------------------------------------------------------- fixtures


def assert_disposable_database(
    database_name: str | None, environ: Mapping[str, str] | None = None
) -> None:
    """Refuse to wipe a database whose name does not end in ``_test``.

    Mirrors ``tests/conftest.py`` exactly: ``TA_ALLOW_DESTRUCTIVE_TEST_DATABASE=true`` and
    ``CI=true`` are the two overrides (GitHub Actions runs the suite against a throwaway
    service database named ``teacher_assistant``, see ``.github/workflows/ci.yml``). A
    developer shell does not set ``CI``, so a real database is still refused there.
    """

    env = os.environ if environ is None else environ
    if env.get("TA_ALLOW_DESTRUCTIVE_TEST_DATABASE", "").lower() == "true":
        return
    if env.get("CI", "").lower() == "true":
        return
    if not (database_name or "").endswith("_test"):
        raise HarnessError(
            f"refusing to migrate and wipe database {database_name!r}: its name does not end in "
            "'_test'. Point DATABASE_URL at a disposable test database."
        )


@pytest.fixture(name="db_session")
def bulk150_db_session() -> Iterator[Session]:
    """Clean tables before and after, like the sibling tests (import with ``noqa: F401``).

    Refuses to run (before the migration and before any ``DELETE``) unless the engine's
    database name ends in ``_test``; see :func:`assert_disposable_database`.
    """

    assert_disposable_database(engine.url.database)
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


def make_settings(storage_root: Path, **overrides: Any) -> Settings:
    """Settings that satisfy the REAL authorization checks, with storage inside ``storage_root``.

    ``COHORT_MODEL_GRADING_ENABLED`` is false and the local-AI phase switch is off (it would
    otherwise start and stop real model servers); neither is ever meant to be turned on here.
    """

    values: dict[str, Any] = {
        "LOCAL_STORAGE_ROOT": str(storage_root),
        "UPLOADS_DIR": str(storage_root / "uploads"),
        "ARTIFACTS_DIR": str(storage_root / "artifacts"),
        "BULK_SUPERVISED_ENABLED": True,
        "LOCAL_SCRIPT_PREPARATION_ENABLED": True,
        "LOCAL_SINGLE_ANSWER_GRADING_ENABLED": True,
        "COHORT_MODEL_GRADING_ENABLED": False,
        "LOCAL_AI_PHASE_SWITCH_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


# The same flags, as environment variables, so that ``get_settings()`` (which GradingService,
# the page-read service and the worker-job path read) agrees with ``make_settings()`` (which is
# handed to BulkEvaluationService and drain).
BULK_ENV_FLAGS = {
    "BULK_SUPERVISED_ENABLED": "true",
    "LOCAL_SCRIPT_PREPARATION_ENABLED": "true",
    "LOCAL_SINGLE_ANSWER_GRADING_ENABLED": "true",
    "COHORT_MODEL_GRADING_ENABLED": "false",
    "LOCAL_AI_PHASE_SWITCH_ENABLED": "false",
}
_AGREEING_FLAGS = (
    "bulk_supervised_enabled",
    "local_script_preparation_enabled",
    "local_single_answer_grading_enabled",
    "cohort_model_grading_enabled",
    "local_ai_phase_switch_enabled",
)
_STORAGE_FIELDS = ("local_storage_root", "uploads_dir", "artifacts_dir")

# Set by ``bulk150_env`` for the duration of a test; every storage helper checks it.
_ACTIVE_ENV: Settings | None = None


def _storage_roots(settings: Settings) -> tuple[Path, ...]:
    return tuple(Path(getattr(settings, name)).resolve() for name in _STORAGE_FIELDS)


def assert_settings_agree(harness: Settings, live: Settings) -> None:
    """The Settings handed to the services and ``get_settings()`` must say the same thing."""

    problems = [
        f"{name}: harness={getattr(harness, name)!r} get_settings()={getattr(live, name)!r}"
        for name in _AGREEING_FLAGS
        if getattr(harness, name) != getattr(live, name)
    ]
    if _storage_roots(harness) != _storage_roots(live):
        problems.append(
            f"storage roots: harness={_storage_roots(harness)} "
            f"get_settings()={_storage_roots(live)}"
        )
    if harness.cohort_model_grading_enabled or live.cohort_model_grading_enabled:
        problems.append("COHORT_MODEL_GRADING_ENABLED must stay false")
    if harness.local_ai_phase_switch_enabled or live.local_ai_phase_switch_enabled:
        problems.append("LOCAL_AI_PHASE_SWITCH_ENABLED must stay false (it drives real servers)")
    if problems:
        raise HarnessError("Settings sources disagree:\n  " + "\n  ".join(problems))


@contextmanager
def bulk_environment(root: Path) -> Iterator[Settings]:
    """Point every storage root at ``root`` and make ``get_settings()`` agree with the harness.

    The environment variables are set BEFORE ``get_settings.cache_clear()`` and restored
    BEFORE the final ``cache_clear()``, so neither the code under test nor the next test can be
    handed a cached Settings from the wrong environment. ``get_settings()`` (read by
    GradingService, the page-read service and the worker-job path) is asserted to agree with
    :func:`make_settings` (handed to BulkEvaluationService and drain) on every flag the
    harness depends on, so there is ONE Settings truth, not two.
    """

    global _ACTIVE_ENV
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LOCAL_STORAGE_ROOT", str(root))
        env.setenv("UPLOADS_DIR", str(root / "uploads"))
        env.setenv("ARTIFACTS_DIR", str(root / "artifacts"))
        for name, value in BULK_ENV_FLAGS.items():
            env.setenv(name, value)
        get_settings.cache_clear()
        previous = _ACTIVE_ENV
        try:
            settings = make_settings(root)
            assert_settings_agree(settings, get_settings())
            _ACTIVE_ENV = settings
            yield settings
        finally:
            _ACTIVE_ENV = previous
    get_settings.cache_clear()


@pytest.fixture(name="bulk_env")
def bulk150_env(tmp_path: Path) -> Iterator[Settings]:
    """Storage inside ``tmp_path``, matching Settings and env (see :func:`bulk_environment`)."""

    with bulk_environment(tmp_path / "storage") as settings:
        yield settings


class HarnessStorage(LocalStorage):
    """``LocalStorage`` rooted in an explicit Settings.

    ``LocalStorage()`` takes no arguments and always reads ``get_settings()``, i.e. whatever
    the process environment says, which outside ``bulk_env`` could be the real data directory.
    """

    def __init__(self, settings: Settings) -> None:
        self.root, self.uploads_dir, self.artifacts_dir = _storage_roots(settings)
        for directory in (self.root, self.uploads_dir, self.artifacts_dir):
            directory.mkdir(parents=True, exist_ok=True)


def harness_storage(settings: Settings | None = None) -> LocalStorage:
    """Storage for the harness helpers, built from the PASSED Settings.

    Refuses to run unless :func:`bulk150_env` is active, because any other root might be
    ``E:\\teacher-assistant\\data``. ``settings`` (default: the active env's) must name the
    same storage roots as the active env and as ``get_settings()``, since production code
    below the service builds its own ``LocalStorage()`` from ``get_settings()``.
    """

    active = _ACTIVE_ENV
    if active is None:
        raise HarnessError(
            "the bulk_env fixture is not active: refusing to build storage from the process "
            "environment (it could be the real data directory). Request bulk_env in the test."
        )
    chosen = active if settings is None else settings
    if _storage_roots(chosen) != _storage_roots(active):
        raise HarnessError(
            f"settings storage roots {_storage_roots(chosen)} differ from the active bulk_env "
            f"roots {_storage_roots(active)}; production code would write to the latter"
        )
    assert_settings_agree(active, get_settings())
    return HarnessStorage(chosen)


def require_active_storage(storage: LocalStorage, settings: Settings | None = None) -> LocalStorage:
    """Accept an EXPLICIT ``storage=`` only when it is exactly the active environment's storage.

    ``harness_storage`` guards the default path, but a caller who hands a storage object to
    :func:`import_zip` or :func:`register_stored_pages` would otherwise bypass every check: a
    bare ``LocalStorage()`` reads ``get_settings()``, i.e. whatever the process environment
    says, which outside ``bulk_env`` could be ``E:\\teacher-assistant\\data``. So an explicit
    storage must satisfy ALL of:

    * :func:`bulk150_env` is active;
    * ``root``, ``uploads_dir`` and ``artifacts_dir`` equal the active env's roots (which
      ``get_settings()`` is asserted to agree with, so production code below the service writes
      to the same place);
    * and, when ``settings`` is given, equal the PASSED settings' roots.

    Raises :class:`HarnessError` otherwise; returns ``storage`` unchanged when it is accepted.
    """

    active = _ACTIVE_ENV
    if active is None:
        raise HarnessError(
            "the bulk_env fixture is not active: refusing an explicit storage= (it could point at "
            "the real data directory). Request bulk_env in the test."
        )
    actual = tuple(
        Path(getattr(storage, name)).resolve() for name in ("root", "uploads_dir", "artifacts_dir")
    )
    if actual != _storage_roots(active):
        raise HarnessError(
            f"explicit storage roots {actual} differ from the active bulk_env roots "
            f"{_storage_roots(active)}; production code would write to the latter"
        )
    if settings is not None and actual != _storage_roots(settings):
        raise HarnessError(
            f"explicit storage roots {actual} differ from the passed settings' roots "
            f"{_storage_roots(settings)}"
        )
    assert_settings_agree(active, get_settings())
    return storage


# --------------------------------------------------------------------------- seeding


@dataclass
class Seeded:
    teacher: User
    course: Course
    assessment: Assessment
    grading_run: GradingRun
    labels: tuple[str, ...]
    questions: dict[str, Question]
    nodes: dict[str, QuestionNode]


def seed_assessment(
    db: Session,
    *,
    questions: int | Sequence[str] = 2,
    marks: str = "5.00",
) -> Seeded:
    """Teacher, assessment, finalized questions (solution + active rubric), confirmed nodes."""

    labels = (
        tuple(f"Q{index}" for index in range(1, questions + 1))
        if isinstance(questions, int)
        else tuple(questions)
    )
    teacher = User(
        name="Synthetic Teacher",
        email=f"bulk150-{uuid4().hex}@example.invalid",
        password_hash="synthetic-only",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code=f"B150{uuid4().hex[:6]}", title="Synthetic 150")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Synthetic bulk assessment",
        assessment_type="synthetic",
        total_marks=Decimal(marks) * len(labels),
        status="ready",
    )
    db.add(assessment)
    db.flush()
    grading_run = GradingRun(
        assessment_id=assessment.id,
        created_by_teacher_id=teacher.id,
        mode="bulk_supervised",
        status="grading_ready",
        marking_policy="general",
        questions_confirmed_at=datetime.now(UTC),
        rubrics_confirmed_at=datetime.now(UTC),
    )
    extraction = ExtractionRun(
        assessment_id=assessment.id,
        artifact_file_path="artifacts/synthetic-paper.pdf",
        original_filename="synthetic-paper.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="mock",
        status="succeeded",
        blockers=[],
    )
    db.add_all([grading_run, extraction])
    db.flush()
    question_rows: dict[str, Question] = {}
    node_rows: dict[str, QuestionNode] = {}
    for label in labels:
        question = Question(
            assessment_id=assessment.id,
            question_no=label,
            question_text=f"SYNQ|{label}| Synthetic question {label}",
            model_answer=f"Synthetic model answer for {label}",
            total_marks=Decimal(marks),
        )
        db.add(question)
        db.flush()
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                rubric_json={
                    "total_marks": marks,
                    "criteria": [
                        {
                            "id": "accuracy",
                            "name": "Accuracy",
                            "description": "Synthetic criterion",
                            "max_marks": marks,
                        }
                    ],
                },
                is_active=True,
            )
        )
        node = QuestionNode(
            assessment_id=assessment.id,
            extraction_run_id=extraction.id,
            question_number=label,
            label=label,
            text=f"Synthetic question {label}",
            node_type="question",
            teacher_confirmed=True,
        )
        db.add(node)
        question_rows[label] = question
        node_rows[label] = node
    db.commit()
    return Seeded(
        teacher=teacher,
        course=course,
        assessment=assessment,
        grading_run=grading_run,
        labels=labels,
        questions=question_rows,
        nodes=node_rows,
    )


def install_fake_brain(
    monkeypatch: pytest.MonkeyPatch,
    provider: FakeBulkBrainProvider,
    settings: Settings,
) -> BrainAdapter:
    """Inject the fake adapter through the single construction seam the service uses."""

    adapter = BrainAdapter(
        provider, image_input_enabled=False, storage_root=settings.local_storage_root
    )

    def _policy(settings_arg: Settings, profile_id: str, *, adapter_override: Any = None) -> Any:
        return brain_policy_from_settings(
            settings_arg,
            adapter_override=adapter_override or adapter,
            profile_id=profile_id.strip().lower(),
        )

    monkeypatch.setattr(bulk_module, "brain_policy_for_profile", _policy)
    return adapter


# --------------------------------------------------------------------------- intake


def register_stored_pages(
    db: Session,
    provider: FakeBulkBrainProvider,
    corpus: Corpus,
    assessment_id: int,
    storage: LocalStorage | None = None,
    *,
    strict_identity: bool = True,
    settings: Settings | None = None,
) -> int:
    """Register sha256(stored page image) -> expected page. Returns pages registered.

    ``create_from_zip`` re-encodes every image to PNG (PDFs are re-rendered), so the registry
    key is the hash of the STORED bytes, never of the source member.

    WHICH page a stored image is comes from its PIXELS, not from the database: the decoded
    pixels are matched against every corpus page (:meth:`Corpus.pixel_owners`) and the spec
    the pixels say is the one registered. If the database claims ``(student, page_no)`` but
    the pixels belong to somebody else, intake mis-assigned a page: that raises
    :class:`HarnessError` (``strict_identity=True``, the default), because the fake would
    otherwise answer from the DB's claim and the whole run would look healthy. With
    ``strict_identity=False`` the mismatch is recorded in ``provider.identity_mismatches`` and
    the registry follows the pixels, so the pipeline returns what the IMAGE shows and
    :func:`assert_no_cross_student_evidence` must catch the mis-assignment downstream.

    ``storage`` (default: the active env's) is verified against the active ``bulk_env`` roots,
    and against ``settings`` when given (:func:`require_active_storage`) BEFORE anything is
    read or queried.
    """

    storage = (
        harness_storage(settings) if storage is None else require_active_storage(storage, settings)
    )
    owners_by_pixels = corpus.pixel_owners()
    registered = 0
    submissions = db.scalars(
        select(Submission).where(Submission.assessment_id == assessment_id).order_by(Submission.id)
    ).all()
    for submission in submissions:
        student = submission.student_identifier
        if student not in corpus.students:
            continue
        pages = db.scalars(
            select(SubmissionPage)
            .where(SubmissionPage.submission_id == submission.id)
            .order_by(SubmissionPage.page_no)
        ).all()
        for page in pages:
            raw = storage.resolve_relative(page.image_path).read_bytes()
            with Image.open(BytesIO(raw)) as image:
                owners = owners_by_pixels.get(pixel_digest(image))
            if not owners:
                raise HarnessError(
                    f"stored page {student}/p{page.page_no} (SubmissionPage {page.id}) matches no "
                    "corpus page: intake changed the pixels, or the corpus options differ"
                )
            claimed = (student, page.page_no)
            owner = claimed
            if claimed not in owners:
                message = (
                    f"intake mis-assigned a page: the database says {claimed} "
                    f"(SubmissionPage {page.id}) but the pixels say {list(owners)}"
                )
                if strict_identity:
                    raise HarnessError(message)
                provider.identity_mismatches.append(message)
                owner = owners[0]
            provider.register(
                hashlib.sha256(raw).hexdigest(),
                corpus.pages[owner],
                student=owner[0],
                page_no=owner[1],
            )
            registered += 1
    return registered


def import_zip(
    db: Session,
    *,
    seeded: Seeded,
    corpus: Corpus,
    provider: FakeBulkBrainProvider,
    settings: Settings,
    maximum_provider_calls: int | None = None,
    marking_policy: str = "general",
    budget_slack: int = 2,
    storage: LocalStorage | None = None,
    archive_path: Path | None = None,
    register: bool = True,
) -> BulkEvaluationRun:
    """Real ``create_from_zip`` plus registration of the stored pages with the fake.

    The default authorization is the exact clean-run call count PLUS ``budget_slack``.
    A slack of zero is deliberately not the default: production pauses a run whose budget
    is consumed by its very last call before it can finish (see the xfail in the smoke
    tests), so an exact budget hides every later stage behind a ``paused`` status.

    An explicit ``storage`` must be exactly the active ``bulk_env`` storage and the passed
    settings' (:func:`require_active_storage`); it is checked before anything else happens.
    """

    storage = (
        harness_storage(settings) if storage is None else require_active_storage(storage, settings)
    )
    service = BulkEvaluationService(db, settings=settings, storage=storage)
    source = archive_path or corpus.archive_path
    upload = UploadFile(filename=source.name, file=BytesIO(source.read_bytes()))
    run = service.create_from_zip(
        assessment_id=seeded.assessment.id,
        grading_run=seeded.grading_run,
        teacher=seeded.teacher,
        upload=upload,
        expected_model=provider.model_name,
        marking_policy=marking_policy,
        maximum_provider_calls=(
            maximum_provider_calls
            if maximum_provider_calls is not None
            else max(corpus.call_budget() + budget_slack, 1)
        ),
        provider=provider.provider_name,
    )
    if register:
        register_stored_pages(
            db, provider, corpus, seeded.assessment.id, storage, settings=settings
        )
    return run


# --------------------------------------------------------------------------- driving


_SETTLED = {"completed", "completed_with_exceptions", "failed", "stopped", "paused", "review_ready"}


@dataclass
class DrainResult:
    units: int
    seconds: float
    status: str
    stage: str
    calls_used: int
    authorized_call_limit: int
    error: str | None
    provider_counts: dict[str, int]
    harness_errors: tuple[str, ...] = ()

    @property
    def settled(self) -> bool:
        return self.status in _SETTLED


def drain_unit_budget(run: BulkEvaluationRun) -> int:
    """Upper bound on ``run_next`` units for ``run``: items * 2 + submissions + 10.

    One unit reads (or assigns) a whole script and one grades an item, so a clean run needs
    about ``submissions + items``; the rest is headroom for retries and the finishing unit.
    """

    return run.total_items * 2 + run.total_submissions + 10


def drain(
    run_id: int,
    *,
    settings: Settings,
    provider: FakeBulkBrainProvider | None = None,
    max_units: int | None = None,
    fresh_session: bool = True,
    db: Session | None = None,
    strict_harness: bool = False,
) -> DrainResult:
    """Call ``run_next`` until it stops, like the RQ worker chain does (no Redis).

    Each unit opens a fresh ``SessionLocal`` by default, exactly as ``run_bulk_evaluation_next_job``
    does. Refuses to loop forever: raises :class:`HarnessError` after ``max_units``, which
    defaults to ``run.total_items * 2 + run.total_submissions + 10`` (one read or assignment
    unit per script plus one grading unit per item, with headroom), so it scales with a
    150-student run instead of a fixed constant.

    ``run_next`` turns ANY ``Exception`` into a ``paused`` run, so a harness mistake raised
    inside the fake (an unregistered page) looks exactly like a product failure.
    ``strict_harness=True`` raises :class:`HarnessError` instead when the provider recorded one
    (``provider.harness_errors``); ``DrainResult.harness_errors`` always carries them.
    """

    storage = harness_storage(settings)
    if max_units is None:
        sizing = SessionLocal()
        try:
            sized = sizing.get(BulkEvaluationRun, run_id)
            if sized is None:
                raise HarnessError(f"run {run_id} does not exist")
            max_units = drain_unit_budget(sized)
        finally:
            sizing.close()
    started = time.perf_counter()
    units = 0
    while True:
        if units >= max_units:
            raise HarnessError(f"run {run_id} did not settle within {max_units} units")
        session = SessionLocal() if (fresh_session or db is None) else db
        try:
            more = BulkEvaluationService(session, settings=settings, storage=storage).run_next(
                run_id
            )
        finally:
            if session is not db:
                session.close()
        units += 1
        if not more:
            break
    seconds = time.perf_counter() - started
    harness_errors = tuple(provider.harness_errors) if provider is not None else ()
    if strict_harness and harness_errors:
        raise HarnessError(f"run {run_id}: the fake provider hit harness errors: {harness_errors}")
    check = SessionLocal()
    try:
        run = check.get(BulkEvaluationRun, run_id)
        if run is None:
            raise HarnessError(f"run {run_id} vanished while it was being drained")
        return DrainResult(
            units=units,
            seconds=seconds,
            status=run.status,
            stage=run.stage,
            calls_used=run.calls_used,
            authorized_call_limit=run.authorized_call_limit,
            error=run.error,
            provider_counts=provider.counts if provider is not None else {},
            harness_errors=harness_errors,
        )
    finally:
        check.close()


@dataclass
class ReviewOutcome:
    confirmed: list[int] = field(default_factory=list)
    refused: dict[int, str] = field(default_factory=dict)
    ownership_confirmed: list[int] = field(default_factory=list)


def _run_submission_ids(db: Session, run_id: int) -> list[int]:
    return sorted(
        db.scalars(
            select(BulkEvaluationItem.submission_id)
            .where(BulkEvaluationItem.run_id == run_id)
            .distinct()
        ).all()
    )


def review_all_transcripts(
    db: Session,
    run_id: int,
    teacher: User,
    *,
    classify: Callable[[ScriptPageTranscript], str] | None = None,
    confirm_ownership: bool = True,
    only_submissions: Sequence[int] | None = None,
) -> ReviewOutcome:
    """Do what the teacher does in the UI, through the real route functions.

    Per submission: classify every page (blank -> ``non_answer``, otherwise
    ``answer_content``), press "confirm current ownership" when any question is
    ``ambiguous`` (inferred ownership), then confirm the transcript review. A refusal
    (HTTP 409) is recorded in ``refused`` rather than raised, so tests can assert on it.
    """

    db.expire_all()
    outcome = ReviewOutcome()
    submission_ids = list(only_submissions) if only_submissions else _run_submission_ids(db, run_id)
    for submission_id in submission_ids:
        transcript = db.scalars(
            select(ScriptTranscript)
            .where(
                ScriptTranscript.submission_id == submission_id,
                ScriptTranscript.status != "superseded",
            )
            .order_by(ScriptTranscript.id.desc())
        ).first()
        if transcript is None:
            outcome.refused[submission_id] = "no transcript"
            continue
        try:
            for page in sorted(transcript.pages, key=lambda item: item.page_order):
                if page.state != "succeeded":
                    continue
                label = (
                    classify(page)
                    if classify
                    else ("non_answer" if page.is_blank_page else "answer_content")
                )
                classify_script_transcript_page(
                    page.id,
                    ScriptTranscriptPageClassificationUpdate(classification=label),  # type: ignore[arg-type]
                    db,
                    teacher,
                )
            if confirm_ownership:
                states = {
                    item.state
                    for item in AnswerEvidenceAssignmentService(db).current_assignments(
                        transcript.id
                    )
                }
                if "ambiguous" in states:
                    confirm_current_answer_evidence_ownership(submission_id, db, teacher)
                    outcome.ownership_confirmed.append(submission_id)
            confirm_script_transcript_review(submission_id, db, teacher)
            outcome.confirmed.append(submission_id)
        except HTTPException as exc:
            db.rollback()
            outcome.refused[submission_id] = f"{exc.status_code}: {exc.detail}"
    return outcome


@dataclass
class ResumeOutcome:
    resumed: list[int] = field(default_factory=list)
    refused: dict[int, str] = field(default_factory=dict)


def resume_all_items(
    run_id: int,
    teacher: User,
    *,
    settings: Settings,
    codes: set[str] | None = None,
    only_stage: str | None = "read",
) -> ResumeOutcome:
    """``resume_item`` for every exception/uncertain item (optionally filtered by code)."""

    outcome = ResumeOutcome()
    storage = harness_storage(settings)
    db = SessionLocal()
    try:
        service = BulkEvaluationService(db, settings=settings, storage=storage)
        run = service.get_run(run_id)
        for item in list(run.items):
            if item.status not in {"exception", "uncertain"}:
                continue
            if only_stage is not None and item.stage != only_stage:
                continue
            if codes is not None and not (set(item.exception_codes or []) & codes):
                continue
            try:
                service.resume_item(run, item, teacher_id=teacher.id)
                outcome.resumed.append(item.id)
            except BulkEvaluationError as exc:
                db.rollback()
                outcome.refused[item.id] = str(exc)
                run = service.get_run(run_id)
    finally:
        db.close()
    return outcome


def reconcile_unknown_pages(
    db: Session,
    run_id: int,
    teacher: User,
    *,
    note: str = "synthetic reconcile",
    states: Sequence[str] = ("unknown_outcome",),
    refusals: dict[int, str] | None = None,
) -> list[int]:
    """Teacher settles page reads of the given states as failed (the real route function).

    ``states`` defaults to ``unknown_outcome``, the only state the route accepts. Pass
    ``("dispatched",)`` to try the page a killed worker leaves behind; the route's refusal
    (HTTP 409) is then recorded in ``refusals`` (page id -> detail) instead of raised.
    """

    db.expire_all()
    pages = db.scalars(
        select(ScriptPageTranscript)
        .join(ScriptTranscript, ScriptTranscript.id == ScriptPageTranscript.script_transcript_id)
        .join(
            BulkEvaluationItem, BulkEvaluationItem.submission_id == ScriptTranscript.submission_id
        )
        .where(
            BulkEvaluationItem.run_id == run_id,
            ScriptPageTranscript.state.in_(tuple(states)),
        )
        .distinct()
    ).all()
    fixed: list[int] = []
    for page in pages:
        try:
            reconcile_script_transcript_page(
                page.id,
                ScriptTranscriptReconcileRequest(resolution="failed", note=note),
                db,
                teacher,
            )
        except HTTPException as exc:
            db.rollback()
            if refusals is None:
                raise
            refusals[page.id] = f"{exc.status_code}: {exc.detail}"
            continue
        fixed.append(page.id)
    return fixed


def age_page_reservations(db: Session, run_id: int, *, seconds: int = 5 * 3600) -> int:
    """Make every ``dispatched`` page reservation of the run look long expired."""

    db.expire_all()
    pages = db.scalars(
        select(ScriptPageTranscript)
        .join(ScriptTranscript, ScriptTranscript.id == ScriptPageTranscript.script_transcript_id)
        .join(
            BulkEvaluationItem, BulkEvaluationItem.submission_id == ScriptTranscript.submission_id
        )
        .where(BulkEvaluationItem.run_id == run_id, ScriptPageTranscript.state == "dispatched")
        .distinct()
    ).all()
    for page in pages:
        page.reserved_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.commit()
    return len(pages)


def try_resume_run(run_id: int, teacher: User, *, settings: Settings) -> tuple[bool, str | None]:
    """Run-level ``resume`` through a fresh session. Returns ``(resumed, refusal_message)``."""

    storage = harness_storage(settings)
    db = SessionLocal()
    try:
        service = BulkEvaluationService(db, settings=settings, storage=storage)
        try:
            service.resume(service.get_run(run_id), teacher_id=teacher.id)
        except BulkEvaluationError as exc:
            db.rollback()
            return False, str(exc)
        return True, None
    finally:
        db.close()


def age_run_heartbeat(db: Session, run_id: int, *, seconds: int = 100000) -> None:
    """Make a run look abandoned, so the stale-worker recovery path in ``resume`` applies."""

    run = db.get(BulkEvaluationRun, run_id)
    if run is None:
        raise HarnessError(f"run {run_id} does not exist")
    run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.commit()


def age_grading_jobs(db: Session, *, seconds: int = 100000) -> int:
    """Make every queued/running GradingJob look long dead, as an hour+ of silence would.

    ``_process_grading`` closes an item's own earlier job only when it is provably not live: with
    no model lease to consult (``managed_local_phase=None``) that means the job is older than the
    bulk RQ job timeout (``max(3600, policy timeout)``), so a test that re-grades after a worker
    kill ages the stranded job first (``100000`` s is beyond any timeout, like
    :func:`age_run_heartbeat`). Returns the number of jobs aged. Direct update, test time travel.
    """

    db.expire_all()
    jobs = db.scalars(select(GradingJob).where(GradingJob.status.in_(("queued", "running")))).all()
    for job in jobs:
        job.created_at = datetime.now(UTC) - timedelta(seconds=seconds)
    db.commit()
    return len(jobs)


def set_authorised_limit(db: Session, run_id: int, limit: int) -> None:
    """Lower a just-imported run's stored call limit, as if the cohort had been under-authorised.

    Intake refuses an authorisation below ``pages + items`` (it could never finish), so the
    "authorisation spent mid-run" scenarios import at the corpus budget and call this BEFORE the
    first drain. Direct update, like :func:`age_run_heartbeat`; only valid while nothing has been
    spent (``calls_used`` is 0), so the table's CHECK constraints hold. The intake audit row still
    records the limit the cohort was imported with.
    """

    run = db.get(BulkEvaluationRun, run_id)
    if run is None:
        raise HarnessError(f"run {run_id} does not exist")
    if run.calls_used != 0 or limit < 1:
        raise HarnessError(f"cannot set limit {limit} on run {run_id} ({run.calls_used} used)")
    run.authorized_call_limit = limit
    db.commit()


# --------------------------------------------------------------------------- inspection


@dataclass
class ItemView:
    item_id: int
    student: str
    question: str
    status: str
    stage: str
    codes: tuple[str, ...]
    suggestion_id: int | None
    confidence: Decimal | None
    provider_calls: int


def item_views(db: Session, run_id: int) -> dict[tuple[str, str], ItemView]:
    """``(student_identifier, question_label) -> ItemView`` for every item of a run."""

    db.expire_all()
    rows = db.execute(
        select(BulkEvaluationItem, Submission.student_identifier, Question.question_no)
        .join(Submission, Submission.id == BulkEvaluationItem.submission_id)
        .join(Question, Question.id == BulkEvaluationItem.question_id)
        .where(BulkEvaluationItem.run_id == run_id)
    ).all()
    return {
        (student, question): ItemView(
            item_id=item.id,
            student=student,
            question=question,
            status=item.status,
            stage=item.stage,
            codes=tuple(item.exception_codes or ()),
            suggestion_id=item.grade_suggestion_id,
            confidence=item.grading_confidence,
            provider_calls=item.provider_call_count,
        )
        for item, student, question in rows
    }


def _allowed_owner(owner_field: str, student: str) -> bool:
    return student in owner_field.split("+")


def common_students(found: Sequence[Token]) -> set[str]:
    """Students that EVERY token could belong to (a shared page's token names several).

    Evidence is single-student when this set is non-empty: ``SYN150|S001+S002|Q1|p1`` plus
    ``SYN150|S001|Q1|p2`` is one student's answer (S001) even though the raw owner fields
    differ. Empty when there are no tokens or when two tokens share no student.
    """

    sets = [set(token_.students) for token_ in found]
    return set.intersection(*sets) if sets else set()


def assert_no_cross_student_evidence(
    db: Session,
    run_id: int,
    *,
    corpus: Corpus | None = None,
    provider: FakeBulkBrainProvider | None = None,
) -> int:
    """Fail loudly if any evidence for submission X contains another student's text.

    Checked surfaces, for every submission of the run:
      * the text of every span of every CURRENT assignment (token student == X, token
        question == the assignment's question, token page == span page);
      * STRUCTURAL OWNERSHIP of every span, current and suggestion-bound alike: span -> block
        -> page transcript -> transcript must be the transcript the assignment owns, belong to
        the assignment's submission, and read a submission page of that same submission. Text
        alone cannot see this: two byte-identical shared pages carry identical tokens;
      * the compatibility ``AnswerRegion.manual_answer_text`` the grading call reads;
      * every item's links: its evidence assignment, answer region and linked draft must all
        belong to the item's own submission and question, and the draft must be the draft OF
        THE ITEM'S REGION (swapped ``grade_suggestion_id`` values are flagged);
      * every GradeSuggestion of these submissions (current or superseded): its bound
        assignment must belong to the same submission and question, every span of that
        assignment is resolved and checked even when no longer current, and the tokens the
        grader reported seeing (``detected_answer_summary``, a load-bearing second detector,
        because the provider cannot attribute a grade call to a student) must belong to the
        same student and question;
      * with ``provider``: each recorded grading call is single-student (the tokens' student
        sets intersect, see :func:`common_students`) and single-question;
      * with ``corpus``: each assignment holds exactly the expected tokens, no more or less.
    Returns the number of evidence texts inspected. Raises ``AssertionError`` listing all
    violations.
    """

    db.expire_all()
    service = AnswerEvidenceAssignmentService(db)
    violations: list[str] = []
    inspected = 0

    submissions = {
        row.id: row
        for row in db.scalars(
            select(Submission).where(Submission.id.in_(_run_submission_ids(db, run_id)))
        ).all()
    }
    questions = {row.id: row for row in db.scalars(select(Question)).all()}

    def check_text(where: str, text: str, student: str, question: str | None) -> None:
        for found in parse_tokens(text):
            if not _allowed_owner(found.student, student):
                violations.append(
                    f"{where}: foreign student token {found.text} (expected {student})"
                )
            if question is not None and found.question != question:
                violations.append(
                    f"{where}: wrong question token {found.text} (expected {question})"
                )

    def check_span_ownership(
        where: str, span: AnswerEvidenceSpan, assignment: AnswerEvidenceAssignment
    ) -> None:
        block = span.block
        page_transcript = block.page_transcript if block is not None else None
        transcript = page_transcript.transcript if page_transcript is not None else None
        if block is None or page_transcript is None or transcript is None:
            violations.append(f"{where}: span {span.id} does not resolve to a block's transcript")
            return
        if transcript.id != assignment.script_transcript_id:
            violations.append(
                f"{where}: span {span.id}: block {block.id} belongs to transcript "
                f"{transcript.id} (submission {transcript.submission_id}), but assignment "
                f"{assignment.id} owns transcript {assignment.script_transcript_id} "
                f"(submission {assignment.submission_id})"
            )
        if transcript.submission_id != assignment.submission_id:
            violations.append(
                f"{where}: span {span.id}: block {block.id} sits in a transcript of submission "
                f"{transcript.submission_id}, assignment {assignment.id} is for submission "
                f"{assignment.submission_id}"
            )
        page = page_transcript.page
        if page is None or page.submission_id != assignment.submission_id:
            owner = None if page is None else page.submission_id
            violations.append(
                f"{where}: span {span.id}: page transcript {page_transcript.id} reads a "
                f"submission page of submission {owner}, assignment {assignment.id} is for "
                f"submission {assignment.submission_id}"
            )
        if page_transcript.page_no != span.page_no:
            violations.append(
                f"{where}: span {span.id} says page {span.page_no} but its block is on "
                f"page {page_transcript.page_no}"
            )

    assignments = db.scalars(
        select(AnswerEvidenceAssignment).where(
            AnswerEvidenceAssignment.submission_id.in_(list(submissions)),
            AnswerEvidenceAssignment.is_current.is_(True),
        )
    ).all()
    for assignment in assignments:
        student = submissions[assignment.submission_id].student_identifier
        label = questions[assignment.question_id].question_no
        gathered: list[str] = []
        for span in assignment.spans:
            text = service.resolve_span_text(span)
            inspected += 1
            gathered.extend(t.text for t in parse_tokens(text))
            where = f"assignment {assignment.id} span {span.order_index}"
            check_text(where, text, student, label)
            check_span_ownership(where, span, assignment)
            for found in parse_tokens(text):
                if found.page_no != span.page_no:
                    violations.append(
                        f"assignment {assignment.id}: token {found.text} "
                        f"on span page {span.page_no}"
                    )
        if corpus is not None and student in corpus.students:
            expected = sorted(corpus.expected_tokens(student, label))
            if sorted(gathered) != expected and assignment.state == "answer_present":
                violations.append(
                    f"assignment {assignment.id} ({student}/{label}): tokens {sorted(gathered)} "
                    f"!= expected {expected}"
                )

    items = db.scalars(select(BulkEvaluationItem).where(BulkEvaluationItem.run_id == run_id)).all()
    for item in items:
        student = submissions[item.submission_id].student_identifier
        label = questions[item.question_id].question_no
        if item.answer_evidence_assignment_id is not None:
            linked_assignment = db.get(AnswerEvidenceAssignment, item.answer_evidence_assignment_id)
            if (
                linked_assignment is None
                or linked_assignment.submission_id != item.submission_id
                or linked_assignment.question_id != item.question_id
            ):
                violations.append(f"item {item.id}: evidence assignment belongs to another item")
        if item.answer_region_id is not None:
            region = db.get(AnswerRegion, item.answer_region_id)
            if region is not None:
                if (
                    region.submission_id != item.submission_id
                    or region.question_id != item.question_id
                ):
                    violations.append(f"item {item.id}: answer region bound to another submission")
                inspected += 1
                check_text(
                    f"item {item.id} region text", region.manual_answer_text or "", student, label
                )
        if item.grade_suggestion_id is not None:
            linked = db.get(GradeSuggestion, item.grade_suggestion_id)
            if linked is None:
                violations.append(f"item {item.id}: linked grade suggestion does not exist")
            else:
                if linked.question_id != item.question_id:
                    violations.append(
                        f"item {item.id}: linked grade suggestion is for another question"
                    )
                # The results workbook and approve_clean key on item.grade_suggestion_id, so a
                # draft of ANOTHER student's region (same question) must not be reachable here.
                if linked.answer_region_id != item.answer_region_id:
                    violations.append(
                        f"item {item.id}: linked suggestion {linked.id} belongs to region "
                        f"{linked.answer_region_id}, item owns region {item.answer_region_id}"
                    )

    # Every grade suggestion of these submissions, current or superseded, and the evidence it
    # is bound to: a draft must never be bound to another student's or question's assignment.
    suggestions = db.scalars(
        select(GradeSuggestion)
        .join(AnswerRegion, AnswerRegion.id == GradeSuggestion.answer_region_id)
        .where(AnswerRegion.submission_id.in_(list(submissions)))
    ).all()
    for suggestion in suggestions:
        region = db.get(AnswerRegion, suggestion.answer_region_id)
        if region is None:
            raise HarnessError(f"suggestion {suggestion.id} has no answer region")
        student = submissions[region.submission_id].student_identifier
        label = questions[suggestion.question_id].question_no
        bound = (
            db.get(AnswerEvidenceAssignment, suggestion.answer_evidence_assignment_id)
            if suggestion.answer_evidence_assignment_id is not None
            else None
        )
        if bound is not None:
            if bound.submission_id != region.submission_id or bound.question_id != (
                suggestion.question_id
            ):
                violations.append(
                    f"suggestion {suggestion.id}: bound to another submission's/question's evidence"
                )
            for span in bound.spans:  # resolved even when the assignment is no longer current
                inspected += 1
                where = f"suggestion {suggestion.id} bound span {span.order_index}"
                check_text(where, service.resolve_span_text(span), student, label)
                check_span_ownership(where, span, bound)
        summary = str((suggestion.raw_response_json or {}).get("detected_answer_summary") or "")
        inspected += 1
        check_text(f"suggestion {suggestion.id} grade summary", summary, student, label)

    if provider is not None:
        for call in provider.calls_of("grade"):
            found_tokens = parse_tokens(call.evidence_text)
            if found_tokens and not common_students(found_tokens):
                named = sorted({s for t in found_tokens for s in t.students})
                violations.append(f"grade call #{call.index} saw several students: {named}")
            for found in found_tokens:
                if found.question != call.question:
                    violations.append(
                        f"grade call #{call.index} for {call.question} saw {found.text}"
                    )
    assert not violations, "cross-student/question evidence leakage:\n  " + "\n  ".join(violations)
    return inspected


def assert_no_final_grades(db: Session, run_id: int | None = None) -> None:
    """No FinalGrade exists, no item claims one, and every suggestion is still a draft."""

    db.expire_all()
    assert db.scalar(select(func.count(FinalGrade.id))) == 0, "a FinalGrade row exists"
    query = select(BulkEvaluationItem)
    if run_id is not None:
        query = query.where(BulkEvaluationItem.run_id == run_id)
    for item in db.scalars(query).all():
        assert item.final_grade_id is None, f"item {item.id} links a final grade"
        assert item.status != "approved", f"item {item.id} is approved"
    for suggestion in db.scalars(select(GradeSuggestion)).all():
        assert suggestion.needs_review is True, f"suggestion {suggestion.id} is not a draft"


_GRADED_STATUSES = frozenset({"graded", "approved"})


def assert_every_answered_question_graded(
    corpus: Corpus,
    views: Mapping[tuple[str, str], ItemView],
    *,
    allowed_exceptions: Iterable[tuple[str, str]] = (),
    strict: bool = True,
) -> dict[tuple[str, str], str]:
    """Every question the corpus says a student ANSWERED has a graded draft, and only those.

    ``assert_no_cross_student_evidence`` inspects the evidence that exists; it cannot see an
    answer production silently demoted to ``missing_answer`` (a dropped block, an unreadable
    page). With 150 students nobody asserts 450 statuses by hand, so this walks every
    ``(student, question)`` of the corpus against ``views`` (from :func:`item_views`):

    * answered (the corpus holds expected tokens) -> the item must be ``graded`` (or later
      ``approved``) with a draft and a confidence; anything else is an unexpected exception;
    * unanswered -> the item must NOT carry a draft (a grade for a blank page is a hallucination);
    * a missing item is reported too.

    ``allowed_exceptions`` lists ``(student, question)`` pairs a test EXPECTS to be exceptions
    (a blank page, an injected fault); they are exempt from the answered-must-be-graded rule.
    Returns ``{(student, question): reason}`` for every unexpected item. By default it also
    raises ``AssertionError`` when that mapping is not empty (``strict=False`` only returns it).
    """

    allowed = set(allowed_exceptions)
    unexpected: dict[tuple[str, str], str] = {}
    for student in corpus.students:
        answered = set(corpus.answered_questions(student))
        for label in corpus.labels:
            key = (student, label)
            view = views.get(key)
            if view is None:
                unexpected[key] = "no bulk item exists for it"
            elif label in answered:
                if key in allowed:
                    continue
                if view.status not in _GRADED_STATUSES:
                    unexpected[key] = (
                        f"answered but {view.status}/{view.stage} {list(view.codes)}, not graded"
                    )
                elif view.suggestion_id is None or view.confidence is None:
                    unexpected[key] = f"{view.status} without a draft/confidence"
            elif view.suggestion_id is not None or view.status in _GRADED_STATUSES:
                unexpected[key] = f"never answered but {view.status} with a draft"
    if strict:
        assert not unexpected, "answered questions that were not graded:\n  " + "\n  ".join(
            f"{student}/{label}: {reason}"
            for (student, label), reason in sorted(unexpected.items())
        )
    return unexpected


def assert_continuations_isolated(provider: FakeBulkBrainProvider) -> int:
    """No script starts with another script's open continuation.

    ``open_continuations`` is the only state production carries from one page read to the
    next, so a read of PAGE 1 must always see ``()``: a non-empty value means the previous
    script's trailing answer leaked into this student's first page. Returns the number of
    page-1 reads checked (a vacuous pass is a failure of the test, not of this helper).
    """

    checked = 0
    violations: list[str] = []
    for call in provider.calls_of("read_page"):
        entry = provider.registry.get(call.image_sha256 or "")
        # Byte-identical pages (blank pages, shared pages) may sit at different page numbers
        # in different scripts; only an image that is page 1 everywhere proves "first page".
        if entry is None or {page for _student, page in entry.pages} != {1}:
            continue
        checked += 1
        if call.open_continuations:
            violations.append(
                f"read #{call.index} of page 1 ({list(call.students)}) was handed open "
                f"continuations {list(call.open_continuations)}"
            )
    assert not violations, "continuation carried across scripts:\n  " + "\n  ".join(violations)
    return checked
