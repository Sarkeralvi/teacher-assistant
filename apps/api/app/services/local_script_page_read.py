"""Transcript-first source reading and deterministic question assembly.

This service deliberately lives beside, rather than inside,
local_script_preparation. The established mapping then transcription path
remains the default; this class is an explicitly enabled alternative that
returns both artifacts from a single full-page provider read.

The source read is now durable and reusable. Each page's transcript is
committed by ``ScriptTranscriptStore`` the moment the provider returns it, and a
page whose source image and transcription settings are unchanged is served from
that record without a provider request. Assembly and mapping are pure functions
of the stored transcript, so a remap or a rubric change costs no vision work.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    AnswerRegionMapping,
    AnswerRegionOcrRun,
    AuditLog,
    Question,
    Submission,
    User,
)
from app.services.answer_evidence_assignment import (
    EXPLICIT_LABEL,
    AnswerEvidenceAssignmentService,
    CanonicalQuestion,
    OwnershipInput,
    assignment_summary,
    resolve_block_ownership,
)
from app.services.brain_execution import hold_brain_execution
from app.services.evidence_invalidation import EvidenceInvalidationService
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseError
from app.services.local_script_preparation import (
    LocalScriptPreparationError,
    LocalScriptPreparationService,
    PreparedSegment,
    _image_content_type,
    _stabilize_visual_page_regions,
)
from app.services.script_transcript_store import (
    UNKNOWN_OUTCOME,
    ScriptTranscriptError,
    ScriptTranscriptStore,
    classify_dispatch_failure,
)
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.capabilities import BrainCapability
from packages.brain.policy import (
    BrainPolicy,
    brain_policy_from_settings,
    configured_visual_provider,
)
from packages.brain.schemas_qwen38 import (
    VISUAL_PAGE_READ_PROMPT_VERSION,
    VisualPageBlock,
    VisualPageRegion,
    VisualPageTranscriptOutput,
)
from packages.brain.transcript_assignment import (
    FULL_TRANSCRIPT_ASSIGNMENT_PROMPT_VERSION,
    FullTranscriptAssignmentOutput,
    validate_full_transcript_assignment,
)


class LocalScriptPageReadError(LocalScriptPreparationError):
    """A page-read contract or deterministic assembly failed safely."""


def _page_no(page: Any) -> int:
    return int(page.page_no)


@dataclass(frozen=True)
class _AssignedPageBlock:
    page: Any
    block: VisualPageBlock
    question_id: int
    source_index: int


@dataclass(frozen=True)
class PageReadAssembly:
    """Pure-Python output after blocks have been attached to canonical labels."""

    segments_by_question: dict[int, list[PreparedSegment]]
    text_by_question: dict[int, str]
    confidence_by_question: dict[int, list[Decimal]]
    warnings_by_question: dict[int, list[str]]
    blockers_by_question: dict[int, list[str]]
    continuation_by_question: dict[int, bool]
    label_sources_by_question: dict[int, set[str]]
    page_ids_by_question: dict[int, set[int]]
    unassigned_pages: list[dict[str, Any]]


@dataclass(frozen=True)
class PageReadPreparationResult:
    """Persisted mapping/transcription artifacts from a one-page-per-call pass."""

    mappings: list[AnswerRegionMapping]
    transcription_runs_by_question: dict[int, AnswerRegionOcrRun]
    calls_used: int
    unassigned_pages: list[dict[str, Any]]
    # Pages served from the durable transcript without a provider request.
    # Reported rather than inferred so a reuse claim is auditable.
    reused_page_count: int = 0
    script_transcript_id: int | None = None
    # Counts per distinct evidence state, which ``mapping_status`` cannot carry.
    evidence_states: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _SourceRead:
    """The complete source transcript backing one preparation pass."""

    outputs: list[VisualPageTranscriptOutput]
    page_hashes: dict[int, str]
    calls_used: int
    reused_page_count: int
    transcript_id: int
    assignment_result: dict[str, Any] | None = None


class LocalScriptPageReadService:
    """Read every source page once and assemble canonical answer evidence locally."""

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        storage: LocalStorage | None = None,
        qwen_adapter: BrainAdapter | None = None,
        phase_manager: LocalAiPhaseManager | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorage()
        self._qwen_adapter = qwen_adapter
        self.phase_manager = phase_manager or LocalAiPhaseManager(
            settings=self.settings,
            db=self.db,
        )
        # Reuse the established persistence, finalized-reference, and
        # CPU-coverage implementation. This service adds no alternate crop or
        # model-lease behavior.
        self._mapping_service = LocalScriptPreparationService(
            self.db,
            settings=self.settings,
            storage=self.storage,
            qwen_adapter=self._qwen_adapter,
            phase_manager=self.phase_manager,
        )

    def prepare(
        self,
        *,
        submission: Submission,
        teacher: User,
        expected_model: str,
        replace_existing: bool,
        maximum_page_read_calls: int,
        provider: str | None = None,
        persist_legacy_artifacts: bool = True,
    ) -> PageReadPreparationResult:
        """Create review-only mappings and transcripts from one read per page."""

        policy = self._validate_authorization(expected_model, provider=provider)
        pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
        if not pages:
            raise LocalScriptPageReadError("The uploaded script has no rendered pages")
        questions, nodes, references = self._mapping_service._load_finalized_references(
            submission
        )
        existing = self._mapping_service._load_existing(submission.id)
        if persist_legacy_artifacts and existing and not replace_existing:
            raise LocalScriptPageReadError(
                "Draft mappings already exist; explicitly replace them to prepare again"
            )
        if persist_legacy_artifacts:
            self._mapping_service._assert_replace_is_safe(existing)

        source = self._read_pages(
            submission=submission,
            pages=pages,
            questions=questions,
            references=references,
            policy=policy,
            maximum_page_read_calls=maximum_page_read_calls,
        )
        page_hashes = source.page_hashes
        calls_used = source.calls_used
        # Page transcription and document understanding are separate. The
        # provider reads each page once, then one text-only pass assigns the
        # complete saved transcript to the finalized questions.
        assignment_service = AnswerEvidenceAssignmentService(self.db)
        transcript = assignment_service.load_transcript(source.transcript_id)
        canonical_questions = [
            CanonicalQuestion(
                question_id=question.id,
                question_node_id=nodes[question.id].id,
                question_no=question.question_no,
            )
            for question in questions
        ]
        assignments = (
            assignment_service.assign_from_full_transcript_mapping(
                submission_id=submission.id,
                transcript=transcript,
                questions=canonical_questions,
                mapping_result=source.assignment_result,
            )
            if source.assignment_result is not None
            else assignment_service.assign(
                submission_id=submission.id,
                transcript=transcript,
                questions=canonical_questions,
            )
        )
        assignment_by_question = {item.question_id: item for item in assignments}

        # A re-derived assignment is new evidence. Mark any draft grade that was
        # produced against the previous version, so a reviewer sees it is out of
        # date. Nothing is deleted and nothing is re-graded automatically;
        # _assert_replace_is_safe already refuses to touch a graded mapping.
        EvidenceInvalidationService(self.db).supersede_stale_suggestions(
            submission_id=submission.id,
            reason="the source transcript or the question assignment was re-derived",
        )

        if not persist_legacy_artifacts:
            states = assignment_summary(assignments)["states"]
            self.db.add(
                AuditLog(
                    actor_type="teacher",
                    actor_id=teacher.id,
                    event_type="submission_script_transcript_prepared",
                    entity_type="submission",
                    entity_id=submission.id,
                    payload_json={
                        "assessment_id": submission.assessment_id,
                        "provider": policy.provider,
                        "expected_model": expected_model,
                        "visual_page_read_call_count": calls_used,
                        "script_transcript_id": source.transcript_id,
                        "reused_page_transcript_count": source.reused_page_count,
                        "evidence_states": states,
                        "legacy_mapping_count": 0,
                        "legacy_transcription_artifact_count": 0,
                        "teacher_review_required": True,
                    },
                )
            )
            self.db.commit()
            return PageReadPreparationResult(
                mappings=[],
                transcription_runs_by_question={},
                calls_used=calls_used,
                unassigned_pages=[],
                reused_page_count=source.reused_page_count,
                script_transcript_id=source.transcript_id,
                evidence_states=states,
            )

        assembly = self.assemble(
            pages=pages,
            page_outputs=source.outputs,
            questions=questions,
        )

        # Delete replaceable draft evidence only after all provider calls and
        # deterministic assembly succeeded, so a failed read cannot erase an
        # existing teacher-reviewable draft.
        for mapping in existing:
            region = mapping.answer_region
            self.db.delete(mapping)
            if region is not None:
                self.db.delete(region)
        self.db.flush()

        created: list[AnswerRegionMapping] = []
        for question in questions:
            question_id = question.id
            segments = assembly.segments_by_question[question_id]
            blockers = list(dict.fromkeys(assembly.blockers_by_question[question_id]))
            warnings = list(dict.fromkeys(assembly.warnings_by_question[question_id]))
            draft = {
                "status": "blocked" if blockers else ("uncertain" if segments else "not_found"),
                "confidence": str(
                    min(assembly.confidence_by_question[question_id], default=Decimal("0"))
                ),
                "warnings": warnings,
                "mapping_blockers": blockers,
                "blocker_reason": blockers[0] if blockers else None,
            }
            mapping = self._mapping_service._create_mapping(
                submission=submission,
                question=question,
                node=nodes[question_id],
                draft=draft,
                segments=segments,
                draft_text=assembly.text_by_question[question_id],
                ocr_warnings=[],
                qwen_warnings=[],
                provider=policy.provider,
                text_source="brain_visual_page_read",
                possible_continuation=(
                    assembly.continuation_by_question[question_id] or len(segments) > 1
                ),
            )
            assignment = assignment_by_question[question_id]
            source_reference = dict(mapping.source_reference or {})
            source_reference["page_read"] = {
                "input_page_numbers": sorted(
                    {
                        segment.page_no
                        for segment in assembly.segments_by_question[question_id]
                    }
                ),
                "label_sources": sorted(assembly.label_sources_by_question[question_id]),
                "hard_blocker_count": len(blockers),
                "teacher_review_required": True,
                "script_transcript_id": source.transcript_id,
                # The distinct evidence state. ``mapping_status`` still carries
                # only the four legacy values, so an unanswered question and a
                # failed read remain indistinguishable *there*; they are told
                # apart here and in ``answer_evidence_assignments``. Narrowing
                # the legacy status to match would change what a teacher sees
                # on the existing workflow and is deliberately left as a
                # separate, founder-visible decision.
                "evidence_state": assignment.state,
                "evidence_state_reason": assignment.state_reason,
                "evidence_assignment_version": assignment.assignment_version,
                "source_coverage_complete": assignment.coverage_complete,
                "unassigned_block_count": assignment.unassigned_block_count,
            }
            mapping.source_reference = source_reference
            created.append(mapping)

        self.db.add_all(created)
        self.db.flush()

        transcription_runs: dict[int, AnswerRegionOcrRun] = {}
        for mapping in created:
            if mapping.question_id is None or mapping.answer_region is None:
                continue
            question_id = mapping.question_id
            run = self._create_transcription_artifact(
                mapping=mapping,
                teacher=teacher,
                policy=policy,
                text=assembly.text_by_question[question_id],
                confidence=min(
                    assembly.confidence_by_question[question_id],
                    default=Decimal("0"),
                ),
                page_hashes=page_hashes,
                label_sources=assembly.label_sources_by_question[question_id],
                blockers=assembly.blockers_by_question[question_id],
                warnings=assembly.warnings_by_question[question_id],
            )
            self.db.add(run)
            transcription_runs[question_id] = run

        self.db.flush()
        self.db.add(
            AuditLog(
                actor_type="teacher",
                actor_id=teacher.id,
                event_type="submission_script_page_read_prepared",
                entity_type="submission",
                entity_id=submission.id,
                payload_json={
                    "assessment_id": submission.assessment_id,
                    "provider": policy.provider,
                    "expected_model": expected_model,
                    "visual_page_read_call_count": calls_used,
                    "script_transcript_id": source.transcript_id,
                    "reused_page_transcript_count": source.reused_page_count,
                    "evidence_states": assignment_summary(assignments)["states"],
                    "mapping_count": len(created),
                    "transcription_artifact_count": len(transcription_runs),
                    "pages_with_unassigned_ink": [
                        item["page_no"]
                        for item in assembly.unassigned_pages
                        if not item["blank"]
                    ],
                    "blank_pages": [
                        item["page_no"] for item in assembly.unassigned_pages if item["blank"]
                    ],
                    "hard_blocked_mapping_count": sum(
                        bool(assembly.blockers_by_question[question.id])
                        for question in questions
                    ),
                    "teacher_review_required": True,
                },
            )
        )
        self.db.commit()
        return PageReadPreparationResult(
            mappings=created,
            transcription_runs_by_question=transcription_runs,
            calls_used=calls_used,
            unassigned_pages=assembly.unassigned_pages,
            reused_page_count=source.reused_page_count,
            script_transcript_id=source.transcript_id,
            evidence_states=assignment_summary(assignments)["states"],
        )

    def assemble(
        self,
        *,
        pages: list[Any],
        page_outputs: list[VisualPageTranscriptOutput],
        questions: list[Question],
    ) -> PageReadAssembly:
        """Attach provider blocks using only page order and canonical labels.

        This is intentionally model-free. A null block follows the nearest
        labelled block physically above it, even across page breaks; the next
        explicit label ends that ownership. Grouping then occurs by canonical
        label, not answer sequence, so students may answer questions in any
        order and return to a question later.
        """

        ordered_pages = sorted(pages, key=lambda item: (item.page_no, item.id))
        if len(ordered_pages) != len(page_outputs):
            raise LocalScriptPageReadError(
                "Page-read output count does not match the rendered script page count"
            )
        question_by_label = {
            question.question_no.strip().casefold(): question for question in questions
        }
        if len(question_by_label) != len(questions):
            raise LocalScriptPageReadError("Finalized question labels must be unique")
        question_by_id = {question.id: question for question in questions}
        segments_by_question = {question.id: [] for question in questions}
        text_parts_by_question = {question.id: [] for question in questions}
        confidence_by_question = {question.id: [] for question in questions}
        warnings_by_question = {question.id: [] for question in questions}
        blockers_by_question = {question.id: [] for question in questions}
        continuation_by_question = {question.id: False for question in questions}
        label_sources_by_question = {question.id: set() for question in questions}
        page_ids_by_question = {question.id: set() for question in questions}
        assignments_by_page: dict[int, list[_AssignedPageBlock]] = defaultdict(list)
        all_assignments: list[_AssignedPageBlock] = []
        global_blockers: list[str] = []

        # Ownership is decided once, by the same rule the evidence-assignment
        # layer uses. This walk used to decide it a second time and could
        # therefore build a crop for a block the assignment layer treats as
        # unplaced. The node id is mirrored from the question id here because
        # assembly works in question ids; the rule itself depends only on
        # labels, page order and the continuation claim, never on either id or
        # on geometry.
        canonical = [
            CanonicalQuestion(
                question_id=question.id,
                question_node_id=question.id,
                question_no=question.question_no,
            )
            for question in questions
        ]
        blocks_by_key: dict[tuple[int, int], tuple[Any, VisualPageBlock, int]] = {}
        ownership_inputs: list[OwnershipInput] = []
        for page, output in zip(ordered_pages, page_outputs, strict=True):
            if output.is_blank_page and output.blocks:
                raise LocalScriptPageReadError(
                    f"Page {page.page_no} was marked blank but also returned visual blocks"
                )
            ordered_blocks = sorted(
                enumerate(output.blocks),
                key=lambda item: (
                    int(item[1].bbox[1]),
                    int(item[1].bbox[3]),
                    int(item[1].bbox[0]),
                    item[0],
                ),
            )
            for block_index, (source_index, block) in enumerate(ordered_blocks):
                key = (int(page.page_no), block_index)
                blocks_by_key[key] = (page, block, source_index)
                ownership_inputs.append(
                    OwnershipInput(
                        key=key,
                        page_no=int(page.page_no),
                        question_label_raw=block.question_label,
                        label_source=block.label_source,
                        continues_from_previous=block.continues_from_previous,
                    )
                )

        ownership = resolve_block_ownership(blocks=ownership_inputs, questions=canonical)

        for owned in ownership.owned:
            page, block, source_index = blocks_by_key[owned.source.key]
            question_id = owned.question.question_id
            assignment = _AssignedPageBlock(
                page=page,
                block=block,
                question_id=question_id,
                source_index=source_index,
            )
            assignments_by_page[int(page.id)].append(assignment)
            all_assignments.append(assignment)
            page_ids_by_question[question_id].add(int(page.id))
            label_sources_by_question[question_id].add(block.label_source)
            if block.label_source == "inferred":
                warnings_by_question[question_id].append(
                    "inferred_question_label_requires_teacher_review"
                )
            if owned.basis != EXPLICIT_LABEL:
                warnings_by_question[question_id].append(
                    f"block_attached_by_{owned.basis}_requires_teacher_review"
                )
            if block.continues_from_previous:
                continuation_by_question[question_id] = True
            if not block.text.strip():
                blockers_by_question[question_id].append(
                    f"page {page.page_no} has a visible block with no faithful transcript; "
                    "page-read evidence is hard blocked"
                )

        for unplaced in ownership.unplaced:
            page, block, _source_index = blocks_by_key[unplaced.source.key]
            if not block.text.strip():
                continue
            # Writing that nobody could place is never silently dropped and
            # never attached to whichever question happened to come last.
            global_blockers.append(
                f"page {page.page_no} has writing that could not be placed "
                f"({unplaced.reason}); page-read evidence is hard blocked"
            )

        for page in ordered_pages:
            grouped: dict[int, list[_AssignedPageBlock]] = defaultdict(list)
            for assignment in assignments_by_page.get(int(page.id), []):
                grouped[assignment.question_id].append(assignment)
            if not grouped:
                continue
            image_path = self.storage.resolve_relative(page.image_path)
            with Image.open(image_path) as image:
                regions: list[VisualPageRegion] = []
                for question_id, assignments in grouped.items():
                    boxes = [assignment.block.bbox for assignment in assignments]
                    question = question_by_id[question_id]
                    regions.append(
                        VisualPageRegion(
                            question_label=question.question_no,
                            bbox=[
                                min(int(box[0]) for box in boxes),
                                min(int(box[1]) for box in boxes),
                                max(int(box[2]) for box in boxes),
                                max(int(box[3]) for box in boxes),
                            ],
                            continues_from_previous=any(
                                assignment.block.continues_from_previous
                                for assignment in assignments
                            ),
                            continues_to_next=False,
                            confidence=min(
                                assignment.block.confidence for assignment in assignments
                            ),
                            warnings=[],
                        )
                    )
                stabilized = _stabilize_visual_page_regions(
                    regions=regions,
                    image_path=image_path,
                    page_id=page.id,
                    page_no=page.page_no,
                    page_width=image.width,
                    page_height=image.height,
                )
            for stable in stabilized:
                question = question_by_label[
                    stable.model_region.question_label.strip().casefold()
                ]
                segments_by_question[question.id].append(stable.segment)
                confidence_by_question[question.id].append(stable.model_region.confidence)
                warnings_by_question[question.id].extend(stable.warnings)

        for assignment in sorted(
            all_assignments,
            key=lambda item: (
                int(item.page.page_no),
                int(item.block.bbox[1]),
                int(item.block.bbox[0]),
                item.source_index,
            ),
        ):
            text_parts_by_question[assignment.question_id].append(assignment.block.text)

        for question in questions:
            question_id = question.id
            segments_by_question[question_id].sort(
                key=lambda item: (item.page_no, item.y, item.x, item.height)
            )

        # This is the model-independent compensating control for merging the
        # mapping and transcription calls. Any detected ink outside every
        # deterministic band blocks the full submission's page-read evidence;
        # it is never downgraded to a warning on this path.
        unassigned_pages = self._mapping_service._detect_unassigned_content(
            ordered_pages,
            segments_by_question,
        )
        for finding in unassigned_pages:
            if finding["blank"]:
                continue
            global_blockers.append(
                f"page {finding['page_no']} has uncovered ink outside every page-read answer "
                "band; merged page-read evidence is hard blocked until a teacher resolves it"
            )

        for question in questions:
            question_id = question.id
            blockers_by_question[question_id].extend(global_blockers)
            warnings_by_question[question_id] = list(
                dict.fromkeys(warnings_by_question[question_id])
            )
            blockers_by_question[question_id] = list(
                dict.fromkeys(blockers_by_question[question_id])
            )

        return PageReadAssembly(
            segments_by_question=segments_by_question,
            text_by_question={
                question.id: "\n".join(text_parts_by_question[question.id])
                for question in questions
            },
            confidence_by_question=confidence_by_question,
            warnings_by_question=warnings_by_question,
            blockers_by_question=blockers_by_question,
            continuation_by_question=continuation_by_question,
            label_sources_by_question=label_sources_by_question,
            page_ids_by_question=page_ids_by_question,
            unassigned_pages=unassigned_pages,
        )

    def _read_pages(
        self,
        *,
        submission: Submission,
        pages: list[Any],
        questions: list[Question],
        references: list[dict[str, Any]],
        policy: BrainPolicy,
        maximum_page_read_calls: int,
    ) -> _SourceRead:
        """Produce the complete source transcript, reading only what is missing.

        Every page's bytes are hashed before anything is dispatched, so the
        reuse decision and the call-budget check both happen at the dispatch
        boundary rather than after a provider has been paid. A page that is
        already stored under the same source image and the same transcription
        settings is served from the record and costs no request.

        Nothing here deletes an existing draft mapping. That still happens in
        ``prepare`` only after the whole source read and assembly succeeded, so
        a failed read cannot erase reviewable teacher evidence.
        """

        adapter = self._qwen_adapter or policy.adapter
        labels = [question.question_no for question in questions]
        canonical_labels = {label.casefold(): label for label in labels}
        store = ScriptTranscriptStore(self.db)

        page_hashes: dict[int, str] = {}
        page_bytes: dict[int, bytes] = {}
        ordered_hashes: list[str] = []
        for page in pages:
            image_path = self.storage.resolve_relative(page.image_path)
            image_bytes = image_path.read_bytes()
            digest = hashlib.sha256(image_bytes).hexdigest()
            page_hashes[int(page.id)] = digest
            page_bytes[int(page.id)] = image_bytes
            ordered_hashes.append(digest)

        transcript = store.get_or_create(
            submission_id=submission.id,
            provider=policy.provider,
            model_name=policy.model,
            prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
            ordered_page_hashes=ordered_hashes,
        )
        # A different ordered source manifest means these pages are a different
        # script version. Older transcripts stay readable but stop being
        # eligible evidence.
        store.supersede_stale(
            submission_id=submission.id,
            keep_transcript_id=transcript.id,
        )

        reuse_by_page = {
            int(page.id): store.reuse_decision(
                transcript=transcript,
                submission_page_id=int(page.id),
                source_image_sha256=page_hashes[int(page.id)],
            )
            for page in pages
        }
        # A page whose previous outcome nobody could determine is never silently
        # read again: the provider may already have produced and billed it.
        unresolved = store.unresolved_pages(transcript)
        if unresolved:
            raise LocalScriptPageReadError(
                "Source pages "
                + ", ".join(str(item.page_no) for item in sorted(unresolved, key=_page_no))
                + " have an unresolved provider outcome. Reconcile them explicitly "
                "before preparing again; they are not retried automatically."
            )

        pages_needing_read = [page for page in pages if not reuse_by_page[int(page.id)].reusable]
        if len(pages_needing_read) > maximum_page_read_calls:
            raise LocalScriptPageReadError(
                "Pages still needing a source read exceed the explicitly authorized "
                "page-read call limit"
            )

        outputs: list[VisualPageTranscriptOutput] = []
        open_continuations: list[str] = []
        calls_used = 0
        reused_page_count = 0
        reading_order = 0
        holder_id = f"script_page_read:{uuid4().hex}"
        assignment_result: dict[str, Any] | None = None
        assignment_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "prompt_version": FULL_TRANSCRIPT_ASSIGNMENT_PROMPT_VERSION,
                    "source_manifest_sha256": transcript.source_manifest_sha256,
                    "questions": references,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        try:
            with hold_brain_execution(
                db=self.db,
                settings=self.settings,
                adapter=adapter,
                holder_kind="script_page_read",
                holder_id=holder_id,
                phase_manager=self.phase_manager,
            ) as execution:
                for page_order, page in enumerate(pages):
                    page_id = int(page.id)
                    reuse = reuse_by_page[page_id]
                    if reuse.reusable and reuse.page_transcript is not None:
                        result = store.load_page_output(reuse.page_transcript)
                        reused_page_count += 1
                    else:
                        image_path = self.storage.resolve_relative(page.image_path)
                        # Claim the page and commit the claim before spending
                        # anything. A concurrent worker, a double-clicked
                        # button or a restarted job now sees the claim instead
                        # of paying for the same page a second time.
                        try:
                            store.reserve_page(
                                transcript=transcript,
                                submission_page_id=page_id,
                                page_no=int(page.page_no),
                                page_order=page_order,
                                source_image_sha256=page_hashes[page_id],
                                holder_id=holder_id,
                            )
                        except ScriptTranscriptError as exc:
                            raise LocalScriptPageReadError(str(exc)) from exc
                        try:
                            execution.heartbeat()
                            result = adapter.read_page(
                                image_bytes=page_bytes[page_id],
                                mime_type=_image_content_type(image_path),
                                question_labels=labels,
                                question_references=references,
                                open_continuations=open_continuations,
                            )
                            execution.heartbeat()
                        except Exception as exc:
                            calls_used += 1
                            # A rejected request is a known failure and may be
                            # read again. A timeout or a dropped connection is
                            # not: the provider may have produced and billed
                            # output nobody saw, so that page keeps
                            # 'unknown_outcome' and is never retried on its own.
                            outcome = classify_dispatch_failure(exc)
                            store.record_page_failure(
                                transcript=transcript,
                                submission_page_id=page_id,
                                page_no=int(page.page_no),
                                page_order=page_order,
                                source_image_sha256=page_hashes[page_id],
                                state=outcome,
                                error=f"Brain visual page read failed safely: {exc}",
                            )
                            store.mark_failed(transcript)
                            detail = (
                                "Brain visual page read outcome is unknown and needs "
                                f"reconciliation: {exc}"
                                if outcome == UNKNOWN_OUTCOME
                                else f"Brain visual page read failed safely: {exc}"
                            )
                            raise LocalScriptPageReadError(detail) from exc
                        if not isinstance(result, VisualPageTranscriptOutput):
                            result = VisualPageTranscriptOutput.model_validate(result)
                        calls_used += 1
                        # Committed here, one page at a time, so an interrupted
                        # run never repeats a page it has already paid for.
                        store.record_page_success(
                            transcript=transcript,
                            submission_page_id=page_id,
                            page_no=int(page.page_no),
                            page_order=page_order,
                            source_image_sha256=page_hashes[page_id],
                            output=result,
                            reading_order_start=reading_order,
                        )
                    outputs.append(result)
                    reading_order += len(result.blocks)
                    open_continuations = self._next_open_continuations(
                        output=result,
                        canonical_labels=canonical_labels,
                        previous=open_continuations,
                    )
                transcript_pages = [
                    {
                        "page_no": int(page.page_no),
                        "blocks": [
                            {"order": index + 1, "text": block.text}
                            for index, block in enumerate(output.blocks)
                            if block.text.strip()
                        ],
                    }
                    for page, output in zip(pages, outputs, strict=True)
                ]
                has_writing = any(page["blocks"] for page in transcript_pages)
                needs_global_assignment = any(
                    block.question_label is None or block.label_source == "inferred"
                    for output in outputs
                    for block in output.blocks
                    if block.text.strip()
                )
                if has_writing and needs_global_assignment:
                    if (
                        transcript.assignment_status == "complete"
                        and transcript.assignment_fingerprint == assignment_fingerprint
                        and transcript.assignment_result_json is not None
                    ):
                        assignment_result = dict(transcript.assignment_result_json)
                    else:
                        if (
                            transcript.assignment_fingerprint == assignment_fingerprint
                            and transcript.assignment_status in {"in_progress", "unknown_outcome"}
                        ):
                            if transcript.assignment_status == "in_progress":
                                transcript.assignment_status = "unknown_outcome"
                                transcript.assignment_error = (
                                    "The complete-script assignment was dispatched but its "
                                    "outcome was never recorded"
                                )
                                self.db.commit()
                            raise LocalScriptPageReadError(
                                "The complete-script assignment has an unresolved provider "
                                "outcome and will not be repeated automatically"
                            )
                        if calls_used >= maximum_page_read_calls:
                            raise LocalScriptPageReadError(
                                "The complete-script assignment exceeds the explicitly "
                                "authorized provider-call limit"
                            )
                        transcript.assignment_status = "in_progress"
                        transcript.assignment_fingerprint = assignment_fingerprint
                        transcript.assignment_result_json = None
                        transcript.assignment_error = None
                        self.db.commit()
                        try:
                            execution.heartbeat()
                            raw_assignment = adapter.map_submission_answers_from_ocr_pages(
                                pages=transcript_pages,
                                questions=references,
                            )
                            execution.heartbeat()
                            assignment = FullTranscriptAssignmentOutput.model_validate(
                                raw_assignment
                            )
                            validate_full_transcript_assignment(
                                assignment,
                                pages=transcript_pages,
                                questions=references,
                            )
                        except Exception as exc:
                            calls_used += 1
                            transcript.assignment_provider_request_count += 1
                            transcript.assignment_status = classify_dispatch_failure(exc)
                            transcript.assignment_error = (
                                f"Complete-script assignment failed safely: {exc}"
                            )
                            self.db.commit()
                            raise LocalScriptPageReadError(transcript.assignment_error) from exc
                        calls_used += 1
                        transcript.assignment_provider_request_count += 1
                        transcript.assignment_status = "complete"
                        transcript.assignment_result_json = assignment.model_dump(mode="json")
                        transcript.assignment_error = None
                        self.db.commit()
                        assignment_result = dict(transcript.assignment_result_json)
        except LocalModelLeaseError as exc:
            raise LocalScriptPageReadError(str(exc)) from exc

        store.mark_complete(transcript)
        # The persisted transcript is the authority, not the provider objects
        # that happen to still be in memory. Reloading every page through the
        # store means assembly and assignment read exactly what was stored, so
        # anything lossy in persistence fails here instead of silently
        # diverging from what a teacher will later be shown.
        outputs = [
            store.load_page_output(
                store.reuse_decision(
                    transcript=transcript,
                    submission_page_id=int(page.id),
                    source_image_sha256=page_hashes[int(page.id)],
                ).page_transcript
            )
            for page in pages
        ]
        return _SourceRead(
            outputs=outputs,
            page_hashes=page_hashes,
            calls_used=calls_used,
            reused_page_count=reused_page_count,
            transcript_id=transcript.id,
            assignment_result=assignment_result,
        )

    @staticmethod
    def _next_open_continuations(
        *,
        output: VisualPageTranscriptOutput,
        canonical_labels: dict[str, str],
        previous: list[str],
    ) -> list[str]:
        """Carry only the physical last owner into the next page's prompt."""

        last = previous[-1] if previous else None
        for block in sorted(
            output.blocks,
            key=lambda item: (int(item.bbox[1]), int(item.bbox[3]), int(item.bbox[0])),
        ):
            if block.question_label is None:
                continue
            canonical = canonical_labels.get(block.question_label.strip().casefold())
            if canonical is None:
                raise LocalScriptPageReadError(
                    "The brain provider returned an unknown finalized question"
                )
            last = canonical
        return [last] if last else []

    def _validate_authorization(
        self,
        expected_model: str,
        *,
        provider: str | None = None,
    ) -> BrainPolicy:
        try:
            policy = brain_policy_from_settings(
                self.settings,
                requested_provider=provider or configured_visual_provider(self.settings),
                adapter_override=self._qwen_adapter,
            )
            policy.validate_request(
                requested_provider=provider or "active",
                expected_model=expected_model,
                capability=BrainCapability.VISUAL_PAGE_READ,
                feature_enabled=(
                    policy.script_preparation_enabled and policy.page_read_enabled
                ),
            )
        except BrainProviderConfigurationError as exc:
            raise LocalScriptPageReadError(str(exc)) from exc
        return policy

    def _create_transcription_artifact(
        self,
        *,
        mapping: AnswerRegionMapping,
        teacher: User,
        policy: BrainPolicy,
        text: str,
        confidence: Decimal,
        page_hashes: dict[int, str],
        label_sources: set[str],
        blockers: list[str],
        warnings: list[str],
    ) -> AnswerRegionOcrRun:
        region = mapping.answer_region
        if region is None:
            raise LocalScriptPageReadError("Cannot create a transcript without answer geometry")
        segments = sorted(region.segments, key=lambda item: item.order_index)
        segment_hashes = [
            hashlib.sha256(
                self.storage.resolve_relative(segment.image_path).read_bytes()
            ).hexdigest()
            for segment in segments
        ]
        input_hashes: list[str] = []
        for segment in segments:
            page_hash = page_hashes.get(int(segment.submission_page_id))
            if page_hash is None:
                raise LocalScriptPageReadError(
                    "Page-read provenance is missing a source-page image hash"
                )
            input_hashes.append(page_hash)
        source_hash = hashlib.sha256("".join(segment_hashes).encode("ascii")).hexdigest()
        input_manifest_hash = hashlib.sha256("".join(input_hashes).encode("ascii")).hexdigest()
        draft_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        normalized_text = text.casefold()
        requires_edit_review = any(
            marker in normalized_text
            for marker in (
                "[visibly crossed]",
                "[overwritten]",
                "[illegible crossed writing]",
                "[unclear correction]",
                "[visible writing unresolved",
            )
        )
        artifact_warnings = ["teacher_review_required", "visual_page_read"]
        if "inferred" in label_sources:
            artifact_warnings.append("inferred_question_label_requires_teacher_review")
        if blockers:
            artifact_warnings.append("uncovered_ink_hard_blocker")
        if requires_edit_review:
            artifact_warnings.append("visual_page_read_requires_edit_review")
        if any("no faithful transcript" in warning for warning in blockers):
            artifact_warnings.append("visual_page_read_empty_block_text")
        return AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"brain-page-read-{region.id}-{uuid4().hex}",
            status="succeeded",
            profile="qwen38_visual_page_read",
            task_kind="visual_page_read",
            reasoning_mode="off",
            prompt_version=VISUAL_PAGE_READ_PROMPT_VERSION,
            source_image_sha256=source_hash,
            source_image_hashes=segment_hashes,
            input_manifest_sha256=input_manifest_hash,
            output_sha256=draft_hash,
            model_asset_sha256=policy.model_asset_sha256,
            mmproj_asset_sha256=policy.auxiliary_model_asset_sha256,
            queued_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            heartbeat_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            # This record is derived from a shared full-page call. The run
            # ledger records that one call per page; duplicating it once per
            # question here would make the artifact ledger overstate provider
            # usage.
            call_limit=0,
            calls_used=0,
            candidate_set_sha256=draft_hash,
            provider=policy.provider,
            model_name=policy.model,
            layout_model_name=None,
            draft_text=text,
            normalized_result={
                "task_kind": "visual_page_read",
                "prompt_version": VISUAL_PAGE_READ_PROMPT_VERSION,
                "reasoning_mode": "off",
                "shared_page_read": True,
                "shared_page_input_sha256": input_hashes,
                "shared_page_read_call_count": len(input_hashes),
                "draft_text_sha256": draft_hash,
                "confidence": str(confidence),
                "is_blank": not bool(text.strip()),
                "is_irrelevant": False,
                "uncertain_glyphs": [],
                "editing_analysis": {
                    "editing_marks": [],
                    "cancellation_detected": False,
                    "replacement_detected": False,
                    "uncertain_correction_detected": False,
                },
                "requires_thinking_repair": requires_edit_review,
                "label_sources": sorted(label_sources),
                "mapping_hard_blocked": bool(blockers),
            },
            warnings=list(dict.fromkeys([*artifact_warnings, *warnings])),
            latency_ms=None,
        )
