"""One-call-per-page visual evidence reading and deterministic assembly.

This service deliberately lives beside, rather than inside,
local_script_preparation. The established mapping then transcription path
remains the default; this class is an explicitly enabled alternative that
returns both artifacts from a single full-page provider read.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AnswerRegionMapping, AnswerRegionOcrRun, AuditLog, Question, Submission, User
from app.services.brain_execution import hold_brain_execution
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseError
from app.services.local_script_preparation import (
    LocalScriptPreparationError,
    LocalScriptPreparationService,
    PreparedSegment,
    _image_content_type,
    _stabilize_visual_page_regions,
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


class LocalScriptPageReadError(LocalScriptPreparationError):
    """A page-read contract or deterministic assembly failed safely."""


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
    ) -> PageReadPreparationResult:
        """Create review-only mappings and transcripts from one read per page."""

        policy = self._validate_authorization(expected_model, provider=provider)
        pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
        if not pages:
            raise LocalScriptPageReadError("The uploaded script has no rendered pages")
        if len(pages) > maximum_page_read_calls:
            raise LocalScriptPageReadError(
                "Script page count exceeds the explicitly authorized page-read call limit"
            )
        questions, nodes, references = self._mapping_service._load_finalized_references(
            submission
        )
        existing = self._mapping_service._load_existing(submission.id)
        if existing and not replace_existing:
            raise LocalScriptPageReadError(
                "Draft mappings already exist; explicitly replace them to prepare again"
            )
        self._mapping_service._assert_replace_is_safe(existing)

        outputs, page_hashes, calls_used = self._read_pages(
            pages=pages,
            questions=questions,
            references=references,
            policy=policy,
        )
        assembly = self.assemble(
            pages=pages,
            page_outputs=outputs,
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
        last_question: Question | None = None

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
            for source_index, block in ordered_blocks:
                question: Question | None
                if block.question_label is None:
                    if block.label_source != "continuation":
                        raise LocalScriptPageReadError(
                            "An unlabeled page block must declare continuation source"
                        )
                    question = last_question
                    if question is None:
                        global_blockers.append(
                            f"page {page.page_no} begins with an unlabeled block that has no "
                            "preceding canonical question; page-read evidence is hard blocked"
                        )
                        continue
                else:
                    if block.label_source == "continuation":
                        raise LocalScriptPageReadError(
                            "A labelled page block cannot declare continuation source"
                        )
                    question = question_by_label.get(block.question_label.strip().casefold())
                    if question is None:
                        raise LocalScriptPageReadError(
                            "The brain provider returned an unknown finalized question"
                        )
                    last_question = question

                assert question is not None
                assignment = _AssignedPageBlock(
                    page=page,
                    block=block,
                    question_id=question.id,
                    source_index=source_index,
                )
                assignments_by_page[int(page.id)].append(assignment)
                all_assignments.append(assignment)
                page_ids_by_question[question.id].add(int(page.id))
                label_sources_by_question[question.id].add(block.label_source)
                if block.label_source == "inferred":
                    warnings_by_question[question.id].append(
                        "inferred_question_label_requires_teacher_review"
                    )
                if block.continues_from_previous:
                    continuation_by_question[question.id] = True
                if not block.text.strip():
                    blockers_by_question[question.id].append(
                        f"page {page.page_no} has a visible block with no faithful transcript; "
                        "page-read evidence is hard blocked"
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
        pages: list[Any],
        questions: list[Question],
        references: list[dict[str, Any]],
        policy: BrainPolicy,
    ) -> tuple[list[VisualPageTranscriptOutput], dict[int, str], int]:
        adapter = self._qwen_adapter or policy.adapter
        labels = [question.question_no for question in questions]
        canonical_labels = {label.casefold(): label for label in labels}
        outputs: list[VisualPageTranscriptOutput] = []
        page_hashes: dict[int, str] = {}
        open_continuations: list[str] = []
        calls_used = 0
        holder_id = f"script_page_read:{uuid4().hex}"

        try:
            with hold_brain_execution(
                db=self.db,
                settings=self.settings,
                adapter=adapter,
                holder_kind="script_page_read",
                holder_id=holder_id,
                phase_manager=self.phase_manager,
            ) as execution:
                for page in pages:
                    image_path = self.storage.resolve_relative(page.image_path)
                    image_bytes = image_path.read_bytes()
                    page_hashes[int(page.id)] = hashlib.sha256(image_bytes).hexdigest()
                    try:
                        execution.heartbeat()
                        result = adapter.read_page(
                            image_bytes=image_bytes,
                            mime_type=_image_content_type(image_path),
                            question_labels=labels,
                            question_references=references,
                            open_continuations=open_continuations,
                        )
                        execution.heartbeat()
                    except Exception as exc:
                        raise LocalScriptPageReadError(
                            f"Brain visual page read failed safely: {exc}"
                        ) from exc
                    if not isinstance(result, VisualPageTranscriptOutput):
                        result = VisualPageTranscriptOutput.model_validate(result)
                    outputs.append(result)
                    calls_used += 1
                    open_continuations = self._next_open_continuations(
                        output=result,
                        canonical_labels=canonical_labels,
                        previous=open_continuations,
                    )
        except LocalModelLeaseError as exc:
            raise LocalScriptPageReadError(str(exc)) from exc
        return outputs, page_hashes, calls_used

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
