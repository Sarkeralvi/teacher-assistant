from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageFilter, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionSegment,
    AuditLog,
    Question,
    QuestionNode,
    Rubric,
    Submission,
    User,
)
from app.services.answer_region_processing import crop_answer_region_image
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseError, LocalModelLeaseService
from app.services.local_ocr_client import LocalOcrClient
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter


class LocalScriptPreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedSegment:
    page_id: int
    page_no: int
    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal
    block_orders: list[int]


@dataclass(frozen=True)
class _ScriptPageReading:
    """One script page as tier-1 OCR saw it, plus whether detection can be trusted."""

    page: Any
    blocks: list[dict[str, Any]]
    reading: Any
    decision: Any

    @property
    def escalated(self) -> bool:
        return bool(self.decision.escalated)


@dataclass(frozen=True)
class _PaddleDecision:
    escalated: bool = False


class LocalScriptPreparationService:
    """Prepare draft answer regions from full script pages without manual cropping."""

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        storage: LocalStorage | None = None,
        qwen_adapter: BrainAdapter | None = None,
        phase_manager: LocalAiPhaseManager | None = None,
        ocr_engine: Any | None = None,
        text_adapter: BrainAdapter | None = None,
        paddle_client_factory: Any | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorage()
        self._qwen_adapter = qwen_adapter
        # Injected so the whole staged pipeline is testable without an engine
        # installed or a model resident. See TierOneOcrEngine in packages.ocr.types.
        self._ocr_engine = ocr_engine
        self._text_adapter = text_adapter
        self._paddle_client_factory = paddle_client_factory or (
            lambda: LocalOcrClient.from_settings(self.settings)
        )
        self.phase_manager = phase_manager or LocalAiPhaseManager(
            settings=self.settings, db=self.db
        )

    def prepare(
        self,
        *,
        submission: Submission,
        teacher: User,
        expected_model: str,
        replace_existing: bool,
        maximum_ocr_calls: int,
    ) -> list[AnswerRegionMapping]:
        """Create review-only Qwen3.8 visual mappings from complete script pages.

        This deliberately performs no transcription and no grading.  Mapping and
        verbatim evidence are independent teacher gates.
        """
        self._validate_authorization(expected_model)
        pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
        if not pages:
            raise LocalScriptPreparationError("The uploaded script has no rendered pages")
        if len(pages) > maximum_ocr_calls:
            raise LocalScriptPreparationError(
                "Script page count exceeds the explicitly authorized visual call limit"
            )
        questions, nodes, _references = self._load_finalized_references(submission)
        existing = self._load_existing(submission.id)
        if existing and not replace_existing:
            raise LocalScriptPreparationError(
                "Draft mappings already exist; explicitly replace them to prepare again"
            )
        self._assert_replace_is_safe(existing)

        labels = [question.question_no for question in questions]
        question_by_label = {question.question_no.casefold(): question for question in questions}
        segments_by_question: dict[int, list[PreparedSegment]] = {
            question.id: [] for question in questions
        }
        warning_by_question: dict[int, list[str]] = {question.id: [] for question in questions}
        confidence_by_question: dict[int, list[Decimal]] = {
            question.id: [] for question in questions
        }
        open_continuations: list[str] = []
        calls_used = 0
        lease_holder_id = f"script_preparation:{submission.id}:{uuid4().hex}"
        lease = LocalModelLeaseService(self.db)
        try:
            with lease.hold(
                model_phase="Qwen38",
                holder_kind="script_preparation",
                holder_id=lease_holder_id,
            ):
                if self.settings.local_ai_phase_switch_enabled:
                    self.phase_manager.switch("Qwen38", lease_holder_id=lease_holder_id)

                adapter = self._qwen_adapter or BrainAdapter.for_provider(
                    self.settings, "llama_cpp_qwen38"
                )
                adapter.verify_available_model()
                provider = adapter.provider
                if not hasattr(provider, "map_page_answer_regions"):
                    raise LocalScriptPreparationError(
                        "Configured local provider cannot map visual script pages"
                    )
                for page in pages:
                    image_path = self.storage.resolve_relative(page.image_path)
                    image_bytes = image_path.read_bytes()
                    try:
                        lease.heartbeat(holder_id=lease_holder_id)
                        result = provider.map_page_answer_regions(
                            image_bytes=image_bytes,
                            mime_type=_image_content_type(image_path),
                            question_labels=labels,
                            open_continuations=open_continuations,
                        )
                        lease.heartbeat(holder_id=lease_holder_id)
                    except Exception as exc:
                        raise LocalScriptPreparationError(
                            f"Qwen3.8 visual mapping failed safely: {exc}"
                        ) from exc
                    calls_used += 1
                    seen: set[str] = set()
                    next_continuations: list[str] = []
                    for region in result.regions:
                        label = region.question_label.casefold()
                        if label in seen:
                            raise LocalScriptPreparationError(
                                "Qwen3.8 split one answer into multiple page regions"
                            )
                        seen.add(label)
                        question = question_by_label.get(label)
                        if question is None:
                            raise LocalScriptPreparationError(
                                "Qwen3.8 returned an unknown finalized question"
                            )
                        x1, y1, x2, y2 = region.bbox
                        with Image.open(image_path) as image:
                            x, y, width, height = _normalized_box_to_page_box(
                                x1, y1, x2, y2, image.width, image.height
                            )
                        segments_by_question[question.id].append(
                            PreparedSegment(
                                page_id=page.id,
                                page_no=page.page_no,
                                x=x,
                                y=y,
                                width=width,
                                height=height,
                                block_orders=[],
                            )
                        )
                        confidence_by_question[question.id].append(region.confidence)
                        warning_by_question[question.id].extend(region.warnings)
                        if region.continues_to_next:
                            next_continuations.append(question.question_no)
                    open_continuations = next_continuations
        except LocalModelLeaseError as exc:
            raise LocalScriptPreparationError(str(exc)) from exc

        unassigned_pages = self._detect_unassigned_content(pages, segments_by_question)

        created: list[AnswerRegionMapping] = []
        for question in questions:
            segments = segments_by_question[question.id]
            draft = {
                "status": "mapped" if segments else "not_found",
                "confidence": str(min(confidence_by_question[question.id], default=Decimal("0"))),
                "warnings": list(dict.fromkeys(warning_by_question[question.id])),
            }
            node = nodes[question.id]
            # Attach the unassigned-content warning to questions the mapper did
            # NOT place. Those are the ones the missed ink might belong to, and
            # attaching it to every mapping would bury the signal.
            page_warnings: list[str] = []
            if not segments:
                for finding in unassigned_pages:
                    if finding["blank"]:
                        continue
                    page_warnings.append(
                        f"page {finding['page_no']} has handwriting that was not assigned "
                        "to any question; this answer may be there"
                    )
            mapping = self._create_mapping(
                submission=submission,
                question=question,
                node=node,
                draft=draft,
                segments=segments,
                draft_text="",
                ocr_warnings=[],
                qwen_warnings=page_warnings,
            )
            created.append(mapping)

        for mapping in existing:
            region = mapping.answer_region
            self.db.delete(mapping)
            if region is not None:
                self.db.delete(region)
        self.db.flush()
        for mapping in created:
            self.db.add(mapping)
        self.db.add(
            AuditLog(
                actor_type="teacher",
                actor_id=teacher.id,
                event_type="submission_script_draft_prepared",
                entity_type="submission",
                entity_id=submission.id,
                payload_json={
                    "assessment_id": submission.assessment_id,
                    "provider": "llama_cpp_qwen38",
                    "expected_qwen_model": expected_model,
                    "visual_mapping_call_count": calls_used,
                    "mapping_count": len(created),
                    "mapped_count": sum(1 for item in created if item.answer_region is not None),
                    "pages_with_unassigned_ink": [
                        item["page_no"] for item in unassigned_pages if not item["blank"]
                    ],
                    "blank_pages": [
                        item["page_no"] for item in unassigned_pages if item["blank"]
                    ],
                    "warning_count": sum(
                        len(item.source_reference.get("warnings", [])) for item in created
                    ),
                },
            )
        )
        self.db.commit()
        return self._load_existing(submission.id)

    def prepare_from_tier1_ocr(
        self,
        *,
        submission: Submission,
        teacher: User,
        expected_text_model: str,
        expected_vision_model: str,
        replace_existing: bool,
        maximum_visual_calls: int,
    ) -> list[AnswerRegionMapping]:
        """Map a script by reading it cheaply first and spending vision only where needed.

        Staged collect-then-execute, in this order:

        1. Tier-1 OCR every page on the CPU. No model resident, no VRAM.
        2. Pages whose DETECTION failed go to the Qwen3.8 vision mapper. Their
           blocks are absent or untrustworthy, so feeding them to a text mapper
           would be mapping noise.
        3. Qwen3.6 maps the blocks of the remaining pages in ONE text call.
        4. Merge. The two mappers work on disjoint page sets, so segments
           concatenate in page order and never need arbitration.

        Interleaving stages would cost a 60-90 s model reload per page, so the
        shape enforces the batching rather than a convention asking for it.

        Performs no transcription and no grading: mapping, verbatim evidence and
        full-answer coverage remain three separate teacher confirmations.
        """
        self._validate_tier1_authorization(
            expected_text_model=expected_text_model,
            expected_vision_model=expected_vision_model,
        )
        pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
        if not pages:
            raise LocalScriptPreparationError("The uploaded script has no rendered pages")
        questions, nodes, references = self._load_finalized_references(submission)
        existing = self._load_existing(submission.id)
        if existing and not replace_existing:
            raise LocalScriptPreparationError(
                "Draft mappings already exist; explicitly replace them to prepare again"
            )
        self._assert_replace_is_safe(existing)

        readings = self._ocr_pages(pages)
        escalated = [item for item in readings if item.escalated]
        budget = min(maximum_visual_calls, self.settings.local_script_max_escalations)
        if len(escalated) > budget:
            raise LocalScriptPreparationError(
                f"{len(escalated)} script page(s) could not be read by the first-pass reader "
                f"but only {budget} vision call(s) were authorized. Re-run with a higher "
                "budget, or supply clearer pages."
            )

        segments_by_question: dict[int, list[PreparedSegment]] = {q.id: [] for q in questions}
        warning_by_question: dict[int, list[str]] = {q.id: [] for q in questions}
        confidence_by_question: dict[int, list[Decimal]] = {q.id: [] for q in questions}
        draft_text_by_question: dict[int, str] = {}
        warnings: list[str] = []
        visual_calls = 0
        text_calls = 0

        lease = LocalModelLeaseService(self.db)
        holder = f"script_tier1_preparation:{submission.id}:{uuid4().hex}"
        try:
            if escalated:
                visual_calls = self._map_escalated_pages_with_vision(
                    escalated=escalated,
                    questions=questions,
                    segments_by_question=segments_by_question,
                    warning_by_question=warning_by_question,
                    confidence_by_question=confidence_by_question,
                    lease=lease,
                    holder=holder,
                )
                warnings.append(
                    f"{len(escalated)} page(s) were mapped by the vision model because the "
                    "first-pass reader could not locate their handwriting: "
                    + ", ".join(str(item.page.page_no) for item in escalated)
                )

            accepted = [item for item in readings if not item.escalated and item.blocks]
            if accepted:
                text_calls, _used_blocks = self._map_accepted_pages_with_text_model(
                    accepted=accepted,
                    questions=questions,
                    references=references,
                    segments_by_question=segments_by_question,
                    warning_by_question=warning_by_question,
                    confidence_by_question=confidence_by_question,
                    draft_text_by_question=draft_text_by_question,
                    lease=lease,
                    holder=holder,
                )
            elif not escalated:
                raise LocalScriptPreparationError(
                    "Tier-1 OCR found no text blocks on any page and no page was escalated; "
                    "there is nothing to map"
                )
        except LocalModelLeaseError as exc:
            raise LocalScriptPreparationError(str(exc)) from exc

        return self._persist_prepared_mappings(
            submission=submission,
            teacher=teacher,
            questions=questions,
            questions_to_persist=questions,
            nodes=nodes,
            pages=pages,
            existing=existing,
            preserved_existing=[],
            segments_by_question=segments_by_question,
            warning_by_question=warning_by_question,
            confidence_by_question=confidence_by_question,
            draft_text_by_question=draft_text_by_question,
            run_warnings=warnings,
            provider="llama_cpp_qwen",
            audit_payload={
                "expected_text_model": expected_text_model,
                "expected_vision_model": expected_vision_model,
                "tier1_engine": readings[0].reading.engine if readings else None,
                "tier1_page_count": len(readings),
                "visual_mapping_call_count": visual_calls,
                "text_mapping_call_count": text_calls,
                "escalated_pages": [item.page.page_no for item in escalated],
                "escalation_reasons": sorted(
                    {reason for item in escalated for reason in item.decision.reason_codes}
                ),
            },
        )

    def prepare_from_paddle_ocr(
        self,
        *,
        submission: Submission,
        teacher: User,
        expected_text_model: str,
        expected_ocr_model: str,
        expected_layout_model: str,
        replace_existing: bool,
        maximum_ocr_calls: int,
        repair_unconfirmed_only: bool = False,
        maximum_text_mapping_calls: int = 2,
    ) -> list[AnswerRegionMapping]:
        """Paddle locates ordered blocks; Qwen3.6 maps only their identifiers."""

        self._validate_paddle_authorization(
            expected_text_model=expected_text_model,
            expected_ocr_model=expected_ocr_model,
            expected_layout_model=expected_layout_model,
        )
        pages = sorted(submission.pages, key=lambda item: (item.page_no, item.id))
        if not pages:
            raise LocalScriptPreparationError("The uploaded script has no rendered pages")
        if len(pages) > min(maximum_ocr_calls, self.settings.local_script_max_ocr_calls):
            raise LocalScriptPreparationError("Script pages exceed the authorized OCR call limit")
        questions, nodes, references = self._load_finalized_references(submission)
        existing = self._load_existing(submission.id)
        if existing and not replace_existing and not repair_unconfirmed_only:
            raise LocalScriptPreparationError(
                "Draft mappings already exist; explicitly replace them to prepare again"
            )
        if repair_unconfirmed_only:
            preserved_existing, replaceable_existing = self._split_preserved_mappings(existing)
            preserved_question_ids = {
                mapping.question_id
                for mapping in preserved_existing
                if mapping.question_id is not None
            }
            questions_to_persist = [
                question for question in questions if question.id not in preserved_question_ids
            ]
            if not questions_to_persist:
                raise LocalScriptPreparationError(
                    "No unresolved mappings remain; confirmed or graded evidence is preserved"
                )
        else:
            self._assert_replace_is_safe(existing)
            preserved_existing = []
            replaceable_existing = existing
            questions_to_persist = questions
        if maximum_text_mapping_calls < 1 or maximum_text_mapping_calls > 2:
            raise LocalScriptPreparationError(
                "Text mapping calls must be authorized between 1 and 2"
            )

        readings: list[_ScriptPageReading] = []
        lease = LocalModelLeaseService(self.db)
        holder = f"script_paddle_preparation:{submission.id}:{uuid4().hex}"
        try:
            with lease.hold(
                model_phase="PaddleOcr",
                holder_kind="script_preparation",
                holder_id=holder,
            ):
                if self.settings.local_ai_phase_switch_enabled:
                    self.phase_manager.switch("PaddleOcr", lease_holder_id=holder)
                client = self._paddle_client_factory()
                client.health()
                for page in pages:
                    path = self.storage.resolve_relative(page.image_path)
                    lease.heartbeat(holder_id=holder)
                    result = client.ocr_image(
                        image_bytes=path.read_bytes(),
                        content_type=_image_content_type(path),
                        request_id=f"script-{submission.id}-page-{page.page_no}",
                        mode="document",
                    )
                    lease.heartbeat(holder_id=holder)
                    blocks = [
                        {
                            "order": block.order,
                            "text": block.text,
                            "bbox": block.bbox,
                            "confidence": None,
                        }
                        for block in result.blocks
                        if block.text.strip() and block.bbox is not None
                    ]
                    readings.append(
                        _ScriptPageReading(
                            page=page,
                            blocks=blocks,
                            reading=result,
                            decision=_PaddleDecision(),
                        )
                    )
        except LocalModelLeaseError as exc:
            raise LocalScriptPreparationError(str(exc)) from exc
        except Exception as exc:
            raise LocalScriptPreparationError(
                f"PaddleOCR script reading failed safely: {exc}"
            ) from exc

        accepted = [item for item in readings if item.blocks]
        if not accepted:
            raise LocalScriptPreparationError(
                "PaddleOCR found no locatable answer blocks; upload a clearer complete script"
            )
        segments_by_question: dict[int, list[PreparedSegment]] = {q.id: [] for q in questions}
        warning_by_question: dict[int, list[str]] = {q.id: [] for q in questions}
        confidence_by_question: dict[int, list[Decimal]] = {q.id: [] for q in questions}
        draft_text_by_question: dict[int, str] = {}
        try:
            text_calls, used_blocks = self._map_accepted_pages_with_text_model(
                accepted=accepted,
                questions=questions,
                references=references,
                segments_by_question=segments_by_question,
                warning_by_question=warning_by_question,
                confidence_by_question=confidence_by_question,
                draft_text_by_question=draft_text_by_question,
                lease=lease,
                holder=holder,
            )
            if repair_unconfirmed_only:
                self._discard_preserved_draft_assignments(
                    segments_by_question=segments_by_question,
                    used_blocks=used_blocks,
                    preserved_question_ids={
                        mapping.question_id
                        for mapping in preserved_existing
                        if mapping.question_id is not None
                    },
                )
            if maximum_text_mapping_calls == 2:
                text_calls += self._complete_unassigned_block_coverage(
                    accepted=accepted,
                    questions=questions,
                    references=references,
                    segments_by_question=segments_by_question,
                    warning_by_question=warning_by_question,
                    confidence_by_question=confidence_by_question,
                    draft_text_by_question=draft_text_by_question,
                    used_blocks=used_blocks,
                    excluded_question_ids={
                        mapping.question_id
                        for mapping in preserved_existing
                        if mapping.question_id is not None
                    },
                    lease=lease,
                    holder=holder,
                )
        except LocalModelLeaseError as exc:
            raise LocalScriptPreparationError(str(exc)) from exc

        return self._persist_prepared_mappings(
            submission=submission,
            teacher=teacher,
            questions=questions,
            questions_to_persist=questions_to_persist,
            nodes=nodes,
            pages=pages,
            existing=replaceable_existing,
            preserved_existing=preserved_existing,
            segments_by_question=segments_by_question,
            warning_by_question=warning_by_question,
            confidence_by_question=confidence_by_question,
            draft_text_by_question=draft_text_by_question,
            run_warnings=[
                "PaddleOCR located answer blocks; Qwen3.6 mapped block IDs only. "
                "Confirm every region before transcription."
            ],
            provider="local_paddle_qwen",
            audit_payload={
                "expected_text_model": expected_text_model,
                "expected_ocr_model": expected_ocr_model,
                "expected_layout_model": expected_layout_model,
                "paddle_ocr_call_count": len(readings),
                "text_mapping_call_count": text_calls,
                "text_mapping_call_limit": maximum_text_mapping_calls,
                "repair_unconfirmed_only": repair_unconfirmed_only,
                "qwen38_call_count": 0,
            },
        )

    def _discard_preserved_draft_assignments(
        self,
        *,
        segments_by_question: dict[int, list[PreparedSegment]],
        used_blocks: set[tuple[int, int]],
        preserved_question_ids: set[int],
    ) -> None:
        """Do not let a repair's fresh draft alter or hide immutable evidence."""
        for question_id in preserved_question_ids:
            for segment in segments_by_question.get(question_id, []):
                used_blocks.difference_update(
                    (segment.page_no, order) for order in segment.block_orders
                )
            segments_by_question[question_id] = []

    def _validate_paddle_authorization(
        self,
        *,
        expected_text_model: str,
        expected_ocr_model: str,
        expected_layout_model: str,
    ) -> None:
        if not self.settings.brain_allow_real_providers:
            raise LocalScriptPreparationError("Real local providers are disabled")
        if not self.settings.local_script_preparation_enabled:
            raise LocalScriptPreparationError("Local script preparation is disabled")
        if not self.settings.local_paddle_ocr_enabled:
            raise LocalScriptPreparationError("Local PaddleOCR must be enabled")
        if not self.settings.local_qwen_enabled:
            raise LocalScriptPreparationError("Local Qwen3.6 must be enabled")
        if expected_text_model != self.settings.local_qwen_model:
            raise LocalScriptPreparationError("Expected Qwen3.6 model alias does not match")
        if expected_ocr_model != self.settings.local_paddle_ocr_model:
            raise LocalScriptPreparationError("Expected PaddleOCR model alias does not match")
        if expected_layout_model != self.settings.local_paddle_ocr_layout_model:
            raise LocalScriptPreparationError("Expected Paddle layout model alias does not match")

    def _map_escalated_pages_with_vision(
        self,
        *,
        escalated: list[_ScriptPageReading],
        questions: list[Question],
        segments_by_question: dict[int, list[PreparedSegment]],
        warning_by_question: dict[int, list[str]],
        confidence_by_question: dict[int, list[Decimal]],
        lease: LocalModelLeaseService,
        holder: str,
    ) -> int:
        """Map the pages tier-1 could not read, using the vision model, once each."""
        labels = [question.question_no for question in questions]
        question_by_label = {q.question_no.casefold(): q for q in questions}
        calls = 0
        with lease.hold(model_phase="Qwen38", holder_kind="script_preparation", holder_id=holder):
            if self.settings.local_ai_phase_switch_enabled:
                self.phase_manager.switch("Qwen38", lease_holder_id=holder)
            adapter = self._qwen_adapter or BrainAdapter.for_provider(
                self.settings, "llama_cpp_qwen38"
            )
            adapter.verify_available_model()
            provider = adapter.provider
            if not hasattr(provider, "map_page_answer_regions"):
                raise LocalScriptPreparationError(
                    "Configured local provider cannot map visual script pages"
                )
            open_continuations: list[str] = []
            for item in escalated:
                image_path = self.storage.resolve_relative(item.page.image_path)
                try:
                    lease.heartbeat(holder_id=holder)
                    result = provider.map_page_answer_regions(
                        image_bytes=image_path.read_bytes(),
                        mime_type=_image_content_type(image_path),
                        question_labels=labels,
                        open_continuations=open_continuations,
                    )
                    lease.heartbeat(holder_id=holder)
                except Exception as exc:
                    raise LocalScriptPreparationError(
                        f"Qwen3.8 visual mapping failed safely: {exc}"
                    ) from exc
                calls += 1
                seen: set[str] = set()
                next_continuations: list[str] = []
                for region in result.regions:
                    label = region.question_label.casefold()
                    if label in seen:
                        raise LocalScriptPreparationError(
                            "Qwen3.8 split one answer into multiple page regions"
                        )
                    seen.add(label)
                    question = question_by_label.get(label)
                    if question is None:
                        raise LocalScriptPreparationError(
                            "Qwen3.8 returned an unknown finalized question"
                        )
                    x1, y1, x2, y2 = region.bbox
                    with Image.open(image_path) as image:
                        x, y, width, height = _normalized_box_to_page_box(
                            x1, y1, x2, y2, image.width, image.height
                        )
                    segments_by_question[question.id].append(
                        PreparedSegment(
                            page_id=item.page.id,
                            page_no=item.page.page_no,
                            x=x,
                            y=y,
                            width=width,
                            height=height,
                            block_orders=[],
                        )
                    )
                    confidence_by_question[question.id].append(region.confidence)
                    warning_by_question[question.id].extend(region.warnings)
                    warning_by_question[question.id].append(
                        f"page {item.page.page_no} was located by the vision model because the "
                        "first-pass reader could not; check this region most closely"
                    )
                    if region.continues_to_next:
                        next_continuations.append(question.question_no)
                open_continuations = next_continuations
        return calls

    def _map_accepted_pages_with_text_model(
        self,
        *,
        accepted: list[_ScriptPageReading],
        questions: list[Question],
        references: list[dict[str, Any]],
        segments_by_question: dict[int, list[PreparedSegment]],
        warning_by_question: dict[int, list[str]],
        confidence_by_question: dict[int, list[Decimal]],
        draft_text_by_question: dict[int, str],
        lease: LocalModelLeaseService,
        holder: str,
    ) -> tuple[int, set[tuple[int, int]]]:
        """Map tier-1 blocks to locked questions with Qwen3.6, in one text call.

        Qwen3.6 selects block identifiers; it never produces coordinates. The
        geometry comes from the boxes tier-1 detected, so a misread block still
        crops the right part of the page.
        """
        ocr_pages = [{"page": item.page.page_no, "blocks": item.blocks} for item in accepted]
        block_index = self._block_index(ocr_pages)
        with lease.hold(model_phase="Qwen", holder_kind="script_preparation", holder_id=holder):
            if self.settings.local_ai_phase_switch_enabled:
                self.phase_manager.switch("Qwen", lease_holder_id=holder)
            adapter = self._text_adapter or BrainAdapter.for_provider(
                self.settings, "llama_cpp_qwen"
            )
            adapter.verify_available_model()
            provider = adapter.provider
            if not hasattr(provider, "map_submission_answers_from_ocr_pages"):
                raise LocalScriptPreparationError(
                    "Configured local provider cannot map script answers from OCR text"
                )
            try:
                lease.heartbeat(holder_id=holder)
                result = provider.map_submission_answers_from_ocr_pages(
                    pages=ocr_pages, questions=references
                )
                lease.heartbeat(holder_id=holder)
            except Exception as exc:
                raise LocalScriptPreparationError(
                    f"Qwen3.6 answer mapping failed safely: {exc}"
                ) from exc

        drafts = self._with_duplicate_block_claims_withheld(
            list(result.get("mappings") or [])
        )
        self._validate_draft_set(drafts, questions)
        drafts = self._expand_contiguous_block_evidence(
            drafts=drafts,
            block_index=block_index,
            questions=questions,
        )
        pages_by_no = [item.page for item in accepted]
        used_blocks: set[tuple[int, int]] = set()
        for draft in drafts:
            question_id = int(draft["question_id"])
            # A question the vision pass already placed is not re-placed here:
            # the two mappers own disjoint pages, and letting both claim one
            # answer would produce two regions for it.
            if segments_by_question[question_id]:
                continue
            segments, draft_text = self._resolve_draft(
                draft=draft,
                pages=pages_by_no,
                block_index=block_index,
                used_blocks=used_blocks,
            )
            segments_by_question[question_id].extend(segments)
            warning_by_question[question_id].extend(list(draft.get("warnings") or []))
            if draft.get("status") == "uncertain":
                warning_by_question[question_id].append(
                    "Qwen3.6 marked this block mapping uncertain; teacher approval is required"
                )
            if draft_text:
                warning_by_question[question_id].append(
                    "first-pass OCR text is approximate and is used only to locate this answer; "
                    "the verbatim reading is a separate confirmation"
                )
                draft_text_by_question[question_id] = draft_text
            confidence = draft.get("confidence")
            if confidence is not None:
                confidence_by_question[question_id].append(Decimal(str(confidence)))
        return 1, used_blocks

    def _complete_unassigned_block_coverage(
        self,
        *,
        accepted: list[_ScriptPageReading],
        questions: list[Question],
        references: list[dict[str, Any]],
        segments_by_question: dict[int, list[PreparedSegment]],
        warning_by_question: dict[int, list[str]],
        confidence_by_question: dict[int, list[Decimal]],
        draft_text_by_question: dict[int, str],
        used_blocks: set[tuple[int, int]],
        excluded_question_ids: set[int],
        lease: LocalModelLeaseService,
        holder: str,
    ) -> int:
        """Run one bounded coverage pass over blocks omitted by the initial map.

        This is not a provider retry: it has a different, explicitly limited
        job.  It may attach a continuation to an already mapped answer or map
        a question left ``not_found``.  It can only select block IDs that the
        first pass left unassigned, so it cannot rewrite confirmed geometry.
        """
        all_blocks = self._block_index(
            [{"page": item.page.page_no, "blocks": item.blocks} for item in accepted]
        )
        unused_keys = set(all_blocks).difference(used_blocks)
        if not unused_keys:
            return 0

        page_by_no = {item.page.page_no: item.page for item in accepted}
        unresolved = [
            question
            for question in questions
            if question.id not in excluded_question_ids and not segments_by_question[question.id]
        ]
        continuations = [
            question
            for question in questions
            if question.id not in excluded_question_ids
            and segments_by_question[question.id]
            and self._last_segment_reaches_page_bottom(
                segments_by_question[question.id], page_by_no
            )
        ]
        targets = list(
            {question.id: question for question in [*unresolved, *continuations]}.values()
        )
        if not targets:
            return 0

        unused_pages: list[dict[str, Any]] = []
        for page_no in sorted(page_by_no):
            blocks = [
                block
                for key, block in all_blocks.items()
                if key[0] == page_no and key in unused_keys
            ]
            if blocks:
                unused_pages.append({"page": page_no, "blocks": blocks})
        if not unused_pages:
            return 0

        target_ids = {question.id for question in targets}
        coverage_references = [
            {**reference, "mapping_scope": "additional_unassigned_blocks_only"}
            for reference in references
            if int(reference["question_id"]) in target_ids
        ]
        with lease.hold(
            model_phase="Qwen", holder_kind="script_mapping_coverage", holder_id=holder
        ):
            if self.settings.local_ai_phase_switch_enabled:
                self.phase_manager.switch("Qwen", lease_holder_id=holder)
            adapter = self._text_adapter or BrainAdapter.for_provider(
                self.settings, "llama_cpp_qwen"
            )
            adapter.verify_available_model()
            provider = adapter.provider
            if not hasattr(provider, "map_submission_answers_from_ocr_pages"):
                raise LocalScriptPreparationError(
                    "Configured local provider cannot complete unassigned script blocks"
                )
            try:
                lease.heartbeat(holder_id=holder)
                result = provider.map_submission_answers_from_ocr_pages(
                    pages=unused_pages, questions=coverage_references
                )
                lease.heartbeat(holder_id=holder)
            except Exception as exc:
                raise LocalScriptPreparationError(
                    f"Qwen3.6 coverage mapping failed safely: {exc}"
                ) from exc

        drafts = self._with_duplicate_block_claims_withheld(
            list(result.get("mappings") or [])
        )
        self._validate_draft_set(drafts, targets)
        drafts = self._expand_contiguous_block_evidence(
            drafts=drafts,
            block_index=all_blocks,
            questions=questions,
        )
        for draft in drafts:
            question_id = int(draft["question_id"])
            segments, draft_text = self._resolve_draft(
                draft=draft,
                pages=[item.page for item in accepted],
                block_index=all_blocks,
                used_blocks=used_blocks,
            )
            if not segments:
                continue
            segments_by_question[question_id].extend(segments)
            warning_by_question[question_id].extend(
                [
                    "additional unassigned OCR blocks were mapped by the bounded coverage pass; "
                    "review every segment before transcription",
                    *list(draft.get("warnings") or []),
                ]
            )
            if draft.get("status") == "uncertain":
                warning_by_question[question_id].append(
                    "Qwen3.6 marked this block mapping uncertain; teacher approval is required"
                )
            if draft_text:
                # This pass can extend an already-mapped answer with a
                # continuation segment; append rather than overwrite so the
                # first pass's text is not silently dropped.
                existing_text = draft_text_by_question.get(question_id, "")
                draft_text_by_question[question_id] = (
                    f"{existing_text}\n{draft_text}" if existing_text else draft_text
                )
            confidence = draft.get("confidence")
            if confidence is not None:
                confidence_by_question[question_id].append(Decimal(str(confidence)))
        return 1

    def _last_segment_reaches_page_bottom(
        self, segments: list[PreparedSegment], page_by_no: dict[int, Any]
    ) -> bool:
        last = max(segments, key=lambda item: (item.page_no, item.y + item.height))
        page = page_by_no.get(last.page_no)
        if page is None:
            return False
        with Image.open(self.storage.resolve_relative(page.image_path)) as image:
            return float(last.y + last.height) >= image.height * 0.88

    def _persist_prepared_mappings(
        self,
        *,
        submission: Submission,
        teacher: User,
        questions: list[Question],
        questions_to_persist: list[Question],
        nodes: dict[int, QuestionNode],
        pages: list[Any],
        existing: list[AnswerRegionMapping],
        preserved_existing: list[AnswerRegionMapping],
        segments_by_question: dict[int, list[PreparedSegment]],
        warning_by_question: dict[int, list[str]],
        confidence_by_question: dict[int, list[Decimal]],
        draft_text_by_question: dict[int, str],
        run_warnings: list[str],
        provider: str,
        audit_payload: dict[str, Any],
    ) -> list[AnswerRegionMapping]:
        coverage_segments = {
            question_id: list(segments)
            for question_id, segments in segments_by_question.items()
        }
        for mapping in preserved_existing:
            region = mapping.answer_region
            if region is None or mapping.question_id is None:
                continue
            coverage_segments.setdefault(mapping.question_id, []).extend(
                PreparedSegment(
                    page_id=segment.submission_page_id,
                    page_no=segment.page.page_no,
                    x=segment.x,
                    y=segment.y,
                    width=segment.width,
                    height=segment.height,
                    block_orders=[],
                )
                for segment in region.segments
            )
        unassigned_pages = self._detect_unassigned_content(pages, coverage_segments)
        unassigned_page_numbers = {
            int(finding["page_no"])
            for finding in unassigned_pages
            if not finding["blank"]
        }
        page_by_no = {page.page_no: page for page in pages}

        created: list[AnswerRegionMapping] = []
        for question in questions_to_persist:
            segments = sorted(
                segments_by_question[question.id], key=lambda item: (item.page_no, item.y)
            )
            is_uncertain = any(
                warning.startswith("Qwen3.6 marked this block mapping uncertain")
                or warning.startswith("ambiguous OCR block claim was withheld")
                for warning in warning_by_question[question.id]
            )
            draft = {
                "status": (
                    "uncertain"
                    if segments and is_uncertain
                    else "mapped"
                    if segments
                    else "not_found"
                ),
                "confidence": str(min(confidence_by_question[question.id], default=Decimal("0"))),
                "warnings": list(dict.fromkeys(warning_by_question[question.id])),
            }
            possible_continuation = bool(
                segments
                and self._last_segment_reaches_page_bottom(segments, page_by_no)
                and max(segment.page_no for segment in segments) + 1 in unassigned_page_numbers
            )
            if possible_continuation:
                draft["status"] = "uncertain"
                draft["warnings"].append(
                    "answer reaches the page bottom and the next page contains unassigned "
                    "handwriting; continuation is required before full-answer confirmation"
                )
            page_warnings = list(run_warnings)
            # Attach the unassigned-content warning to questions that were NOT
            # placed. Those are the ones the missed ink might belong to, and
            # attaching it to every mapping would bury the signal.
            if not segments:
                for finding in unassigned_pages:
                    if finding["blank"]:
                        continue
                    page_warnings.append(
                        f"page {finding['page_no']} has handwriting that was not assigned "
                        "to any question; this answer may be there"
                    )
            created.append(
                self._create_mapping(
                    submission=submission,
                    question=question,
                    node=nodes[question.id],
                    draft=draft,
                    segments=segments,
                    draft_text=draft_text_by_question.get(question.id, ""),
                    ocr_warnings=[],
                    qwen_warnings=page_warnings,
                    provider=provider,
                    text_source="tier1_ocr_mapping_pending_transcription",
                    possible_continuation=possible_continuation,
                )
            )

        for mapping in existing:
            region = mapping.answer_region
            self.db.delete(mapping)
            if region is not None:
                self.db.delete(region)
        self.db.flush()
        for mapping in created:
            self.db.add(mapping)
        self.db.add(
            AuditLog(
                actor_type="teacher",
                actor_id=teacher.id,
                event_type="submission_script_draft_prepared",
                entity_type="submission",
                entity_id=submission.id,
                payload_json={
                    "assessment_id": submission.assessment_id,
                    "provider": provider,
                    "mapping_count": len(created),
                    "preserved_mapping_count": len(preserved_existing),
                    "mapped_count": sum(1 for item in created if item.answer_region is not None),
                    "pages_with_unassigned_ink": [
                        item["page_no"] for item in unassigned_pages if not item["blank"]
                    ],
                    "blank_pages": [item["page_no"] for item in unassigned_pages if item["blank"]],
                    "warning_count": sum(
                        len((item.source_reference or {}).get("warnings", [])) for item in created
                    ),
                    **audit_payload,
                },
            )
        )
        self.db.commit()
        return self._load_existing(submission.id)

    def _validate_tier1_authorization(
        self, *, expected_text_model: str, expected_vision_model: str
    ) -> None:
        if not self.settings.brain_allow_real_providers:
            raise LocalScriptPreparationError("Real local providers are disabled")
        if not self.settings.local_qwen_enabled:
            raise LocalScriptPreparationError("Qwen3.6 must be enabled to map script answers")
        if expected_text_model != self.settings.local_qwen_model:
            raise LocalScriptPreparationError("Expected Qwen3.6 model alias does not match")
        # The vision model is only the fallback here, but a page that needs it
        # must not discover mid-run that it is unavailable.
        if not self.settings.local_qwen38_visual_preparation_enabled:
            raise LocalScriptPreparationError("Qwen3.8 visual preparation is disabled")
        if not self.settings.local_qwen38_enabled:
            raise LocalScriptPreparationError("Qwen3.8 must be enabled")
        if expected_vision_model != self.settings.local_qwen38_model:
            raise LocalScriptPreparationError("Expected Qwen3.8 model alias does not match")

    def _detect_unassigned_content(
        self,
        pages: list[Any],
        segments_by_question: dict[int, list[PreparedSegment]],
    ) -> list[dict[str, Any]]:
        """Find pages carrying ink that no mapped answer accounts for.

        The safety net for an answer the mapper missed outright. Such an answer
        produces no region, so no per-region check can notice it; the only
        evidence is ink sitting outside every region that WAS placed.

        Geometry only, on the CPU, with no model involved. Detecting that ink
        exists is a far easier problem than reading it, so this stays reliable
        on handwriting where recognition is not.
        """
        from packages.ocr.coverage import measure_uncovered_ink

        boxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
        for segments in segments_by_question.values():
            for segment in segments:
                boxes_by_page.setdefault(segment.page_id, []).append(
                    (
                        float(segment.x),
                        float(segment.y),
                        float(segment.x) + float(segment.width),
                        float(segment.y) + float(segment.height),
                    )
                )

        findings: list[dict[str, Any]] = []
        threshold = self.settings.local_script_unassigned_ink_warn_above
        for page in pages:
            image_path = self.storage.resolve_relative(page.image_path)
            try:
                image_bytes = image_path.read_bytes()
            except OSError:
                continue
            coverage = measure_uncovered_ink(image_bytes, boxes_by_page.get(page.id, []))
            if coverage is None:
                continue
            # A page with no ink at all is blank, not unassigned. Saying
            # "unassigned content" about an empty page would train the teacher
            # to ignore the warning.
            if coverage.is_blank:
                findings.append({"page_no": page.page_no, "blank": True, "ratio": "0"})
                continue
            if coverage.ratio > threshold:
                findings.append(
                    {
                        "page_no": page.page_no,
                        "blank": False,
                        "ratio": str(coverage.ratio),
                    }
                )
        return findings

    def _validate_authorization(self, expected_model: str) -> None:
        if not self.settings.brain_allow_real_providers:
            raise LocalScriptPreparationError("Real local providers are disabled")
        if not self.settings.local_qwen38_visual_preparation_enabled:
            raise LocalScriptPreparationError("Qwen3.8 visual preparation is disabled")
        if not self.settings.local_qwen38_enabled:
            raise LocalScriptPreparationError("Qwen3.8 must be enabled")
        if expected_model != self.settings.local_qwen38_model:
            raise LocalScriptPreparationError("Expected local Qwen model alias does not match")

    def _load_finalized_references(
        self, submission: Submission
    ) -> tuple[list[Question], dict[int, QuestionNode], list[dict[str, Any]]]:
        questions = list(
            self.db.scalars(
                select(Question)
                .where(Question.assessment_id == submission.assessment_id)
                .order_by(Question.id)
            ).all()
        )
        if not questions:
            raise LocalScriptPreparationError("No finalized questions are available")
        nodes = list(
            self.db.scalars(
                select(QuestionNode)
                .where(QuestionNode.assessment_id == submission.assessment_id)
                .where(QuestionNode.teacher_confirmed.is_(True))
                .where(QuestionNode.node_type.in_(["question", "subquestion"]))
            ).all()
        )
        node_by_label: dict[str, QuestionNode] = {}
        for node in nodes:
            for value in (node.label, node.question_number):
                node_by_label.setdefault(value.strip().casefold(), node)
        node_by_question: dict[int, QuestionNode] = {}
        references: list[dict[str, Any]] = []
        for question in questions:
            node = node_by_label.get(question.question_no.strip().casefold())
            if node is None:
                raise LocalScriptPreparationError(
                    f"Finalized question {question.question_no} has no confirmed question node"
                )
            rubric = self.db.scalars(
                select(Rubric)
                .where(Rubric.question_id == question.id)
                .where(Rubric.is_active.is_(True))
                .order_by(Rubric.version.desc(), Rubric.id.desc())
            ).first()
            if not (question.model_answer or "").strip() or rubric is None:
                raise LocalScriptPreparationError(
                    f"Finalized question {question.question_no} is missing its solution or rubric"
                )
            node_by_question[question.id] = node
            references.append(
                {
                    "question_id": question.id,
                    "question_no": question.question_no,
                    "question_text": question.question_text,
                }
            )
        return questions, node_by_question, references

    def _ocr_pages(self, pages: list[Any]) -> list[_ScriptPageReading]:
        """Read every script page with the tier-1 engine, on the CPU.

        Supplies the geometry the mapper needs: one block per detected line,
        numbered in reading order, with its box in page pixels. The text is
        carried too and is deliberately treated as approximate - it exists so
        Qwen3.6 can tell one answer from the next, not so anyone can mark from
        it. Verbatim reading happens later, per confirmed region, on the vision
        model.

        Escalation here asks only whether DETECTION failed, via
        ``evaluate_page_detection_only``. A page whose ink was found is usable
        even when badly misread.
        """
        from packages.ocr.escalation import EscalationPolicy, evaluate_page_detection_only

        if not self.settings.local_ocr_enabled:
            raise LocalScriptPreparationError(
                "Tier-1 OCR is disabled; set LOCAL_OCR_ENABLED to prepare scripts from OCR"
            )
        engine = self._ocr_engine or self._default_ocr_engine()
        policy = EscalationPolicy(
            line_confidence_escalate_below=self.settings.local_ocr_confidence_escalate_below,
            uncovered_ink_escalate_above=self.settings.local_ocr_uncovered_ink_escalate_above,
        )

        results: list[_ScriptPageReading] = []
        for page in pages:
            image_path = self.storage.resolve_relative(page.image_path)
            image_bytes = image_path.read_bytes()
            with Image.open(image_path) as image:
                width, height = image.width, image.height
            try:
                reading = engine.read_page(
                    image_bytes,
                    render_dpi=self.settings.local_ocr_render_dpi,
                    page_width=width,
                    page_height=height,
                )
            except Exception as exc:
                raise LocalScriptPreparationError(f"Tier-1 OCR failed safely: {exc}") from exc

            blocks: list[dict[str, Any]] = []
            for line in reading.lines:
                text = line.text.strip()
                # A block with no text or no box cannot be mapped or cropped, so
                # it is dropped rather than given an order number the mapper
                # could select and the crop step could not honour.
                if not text or line.bbox is None:
                    continue
                blocks.append(
                    {
                        "order": len(blocks) + 1,
                        "text": text,
                        "bbox": [
                            float(line.bbox.x1),
                            float(line.bbox.y1),
                            float(line.bbox.x2),
                            float(line.bbox.y2),
                        ],
                        "confidence": (
                            str(line.confidence) if line.confidence is not None else None
                        ),
                    }
                )
            results.append(
                _ScriptPageReading(
                    page=page,
                    blocks=blocks,
                    reading=reading,
                    decision=evaluate_page_detection_only(reading, policy=policy),
                )
            )
        return results

    def _default_ocr_engine(self) -> Any:
        from packages.ocr.rapidocr_engine import OcrEngineUnavailableError, RapidOcrEngine

        try:
            return RapidOcrEngine()
        except OcrEngineUnavailableError as exc:
            raise LocalScriptPreparationError(str(exc)) from exc

    def _page_geometry(self, pages: list[Any]) -> dict[int, tuple[int, int, int]]:
        geometry: dict[int, tuple[int, int, int]] = {}
        for page in pages:
            with Image.open(self.storage.resolve_relative(page.image_path)) as image:
                geometry[int(page.page_no)] = (int(page.id), image.width, image.height)
        return geometry

    def _prepare_baseline_ocr_candidates(
        self,
        submission: Submission,
        segments: list[PreparedSegment],
        expected_model: str,
        questions: dict[int, Question],
    ) -> list[str]:
        del submission, segments, expected_model, questions
        raise LocalScriptPreparationError(
            "PaddleOCR has been removed. Visual script preparation will be provided by Qwen3.8."
        )

    def _block_index(self, pages: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
        index: dict[tuple[int, int], dict[str, Any]] = {}
        for page in pages:
            page_no = int(page["page"])
            for block in page["blocks"]:
                key = (page_no, int(block["order"]))
                if key in index:
                    raise LocalScriptPreparationError("OCR block identifiers are duplicated")
                index[key] = block
        return index

    @staticmethod
    def _with_duplicate_block_claims_withheld(
        drafts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve only the safe subset of duplicate OCR-block claims.

        Qwen3.6 maps block identifiers; it does not own their geometry. A
        duplicate claim is ambiguous evidence, not a reason to discard every
        other answer on the script. When exactly one claimant has no other
        visible block while the others already have evidence, provisionally
        give the disputed block to that otherwise-missing answer. This is the
        common page-continuation boundary case and remains uncertain for
        teacher review. In every other case, withhold it from all claimants.
        """
        claims: dict[tuple[int, int], set[int]] = {}
        keys_by_question: dict[int, set[tuple[int, int]]] = {}
        for draft in drafts:
            question_id = int(draft.get("question_id") or 0)
            for reference in draft.get("block_references") or []:
                page_no = int(reference.get("page_no") or 0)
                for order in reference.get("block_orders") or []:
                    key = (page_no, int(order))
                    claims.setdefault(key, set()).add(question_id)
                    keys_by_question.setdefault(question_id, set()).add(key)
        ambiguous = {key for key, question_ids in claims.items() if len(question_ids) > 1}
        if not ambiguous:
            return drafts

        unambiguous_by_question = {
            question_id: keys.difference(ambiguous)
            for question_id, keys in keys_by_question.items()
        }
        provisional_owner: dict[tuple[int, int], int] = {}
        for key in ambiguous:
            claimants = claims[key]
            otherwise_missing = [
                question_id
                for question_id in claimants
                if not unambiguous_by_question.get(question_id)
            ]
            already_located = [
                question_id
                for question_id in claimants
                if unambiguous_by_question.get(question_id)
            ]
            if len(otherwise_missing) == 1 and already_located:
                provisional_owner[key] = otherwise_missing[0]

        sanitized: list[dict[str, Any]] = []
        for draft in drafts:
            copy = dict(draft)
            question_id = int(copy.get("question_id") or 0)
            filtered_references: list[dict[str, Any]] = []
            withheld: list[tuple[int, int]] = []
            provisionally_owned: list[tuple[int, int]] = []
            for reference in copy.get("block_references") or []:
                page_no = int(reference.get("page_no") or 0)
                retained_orders: list[int] = []
                for order in reference.get("block_orders") or []:
                    key = (page_no, int(order))
                    owner = provisional_owner.get(key)
                    if key in ambiguous and owner != question_id:
                        withheld.append(key)
                    else:
                        retained_orders.append(int(order))
                        if owner == question_id:
                            provisionally_owned.append(key)
                if retained_orders:
                    filtered = dict(reference)
                    filtered["block_orders"] = retained_orders
                    filtered_references.append(filtered)
            if withheld or provisionally_owned:
                warnings = list(copy.get("warnings") or [])
                if withheld:
                    locations = ", ".join(
                        f"page {page_no}, block {order}"
                        for page_no, order in sorted(set(withheld))
                    )
                    warnings.append(
                        "ambiguous OCR block claim was withheld from this answer "
                        f"({locations}); teacher review is required"
                    )
                if provisionally_owned:
                    locations = ", ".join(
                        f"page {page_no}, block {order}"
                        for page_no, order in sorted(set(provisionally_owned))
                    )
                    warnings.append(
                        "ambiguous boundary block was assigned only to this otherwise-missing "
                        f"answer ({locations}); verify it against the full source page"
                    )
                copy["warnings"] = list(dict.fromkeys(warnings))
                copy["block_references"] = filtered_references
                if not filtered_references:
                    # Preserve the provider-schema invariant that a mapped or
                    # uncertain draft always has at least one block reference.
                    copy["status"] = "not_found"
                    copy["confidence"] = "0"
                else:
                    copy["status"] = "uncertain"
                    copy["confidence"] = str(
                        min(Decimal(str(copy.get("confidence") or 0)), Decimal("0.35"))
                    )
            sanitized.append(copy)
        return sanitized

    @staticmethod
    def _expand_contiguous_block_evidence(
        *,
        drafts: list[dict[str, Any]],
        block_index: dict[tuple[int, int], dict[str, Any]],
        questions: list[Question],
    ) -> list[dict[str, Any]]:
        """Turn sparse model anchors into complete, non-overlapping answer bands.

        The text model is useful for identifying question anchors, but it can
        select only formula lines and omit headings, setup, or incorrect work.
        Cropping directly around those sparse anchors truncated real answers in
        rehearsal. Geometry therefore follows deterministic reading order:

        * fill holes between a question's own first and last selected block;
        * include leading blocks before the first mapped answer on each page;
        * give gaps between adjacent canonical questions to the following
          question, where its heading and setup physically occur;
        * never bridge over an unresolved canonical question or steal a block
          explicitly selected by another answer.

        Any expansion remains uncertain until the teacher sees the full-page
        boundary preview and confirms it.
        """
        question_order = {question.id: index for index, question in enumerate(questions)}
        copies = [{**draft, "warnings": list(draft.get("warnings") or [])} for draft in drafts]
        by_question = {int(draft.get("question_id") or 0): draft for draft in copies}

        selected: dict[tuple[int, int], set[int]] = {}
        selected_owner: dict[tuple[int, int], int | None] = {}
        for draft in copies:
            question_id = int(draft.get("question_id") or 0)
            for reference in draft.get("block_references") or []:
                page_no = int(reference.get("page_no") or 0)
                for raw_order in reference.get("block_orders") or []:
                    order = int(raw_order)
                    key = (page_no, order)
                    selected.setdefault((question_id, page_no), set()).add(order)
                    previous_owner = selected_owner.get(key)
                    if previous_owner is None and key not in selected_owner:
                        selected_owner[key] = question_id
                    elif previous_owner != question_id:
                        selected_owner[key] = None

        expanded = {key: set(orders) for key, orders in selected.items()}
        page_orders: dict[int, list[int]] = {}
        for page_no, order in block_index:
            page_orders.setdefault(page_no, []).append(order)
        for orders in page_orders.values():
            orders.sort()

        additions: dict[int, set[tuple[int, int]]] = {}
        for page_no, available_orders in page_orders.items():
            owners: list[tuple[int, int, int]] = []
            for (question_id, selected_page), orders in selected.items():
                if selected_page == page_no and orders:
                    owners.append((question_id, min(orders), max(orders)))
            owners.sort(key=lambda item: (item[1], question_order.get(item[0], 10**9)))
            if not owners:
                continue

            def add_if_unclaimed(
                question_id: int, order: int, *, selected_page_no: int = page_no
            ) -> None:
                key = (selected_page_no, order)
                owner = selected_owner.get(key)
                if key not in block_index or owner not in {None, question_id}:
                    return
                # ``None`` can mean either unclaimed or conflicting. A key
                # present in selected_owner with value None is a conflict and
                # must not be expanded into a region.
                if key in selected_owner and owner is None:
                    return
                expanded.setdefault((question_id, selected_page_no), set()).add(order)
                if order not in selected.get((question_id, selected_page_no), set()):
                    additions.setdefault(question_id, set()).add(key)

            # Keep every detected line between this question's sparse anchors.
            for question_id, first_order, last_order in owners:
                for order in available_orders:
                    if first_order <= order <= last_order:
                        add_if_unclaimed(question_id, order)

            # The first mapped answer owns leading page content. This restores
            # omitted headings and setup without crossing another answer.
            first_question_id, first_order, _last_order = owners[0]
            for order in available_orders:
                if order < first_order:
                    add_if_unclaimed(first_question_id, order)

            # A gap between adjacent canonical questions belongs to the next
            # question. Do not bridge a missing question in the canonical list.
            for previous, current in zip(owners, owners[1:], strict=False):
                previous_question_id, _previous_first, previous_last = previous
                current_question_id, current_first, _current_last = current
                if question_order.get(current_question_id) != question_order.get(
                    previous_question_id, -2
                ) + 1:
                    continue
                for order in available_orders:
                    if previous_last < order < current_first:
                        add_if_unclaimed(current_question_id, order)

        for (question_id, page_no), orders in expanded.items():
            draft = by_question.get(question_id)
            if draft is None or not orders:
                continue
            references_by_page = {
                int(reference.get("page_no") or 0): dict(reference)
                for reference in draft.get("block_references") or []
            }
            reference = references_by_page.get(page_no, {"page_no": page_no})
            reference["block_orders"] = sorted(orders)
            references_by_page[page_no] = reference
            draft["block_references"] = [
                references_by_page[key] for key in sorted(references_by_page)
            ]

        for question_id, added in additions.items():
            if not added:
                continue
            draft = by_question[question_id]
            locations = ", ".join(
                f"page {page_no}, block {order}" for page_no, order in sorted(added)
            )
            draft["warnings"].append(
                "crop geometry was expanded from sparse Qwen anchors to include contiguous "
                f"PaddleOCR evidence ({locations}); verify the full-page boundary before approval"
            )
            draft["status"] = "uncertain"
            draft["confidence"] = str(
                min(Decimal(str(draft.get("confidence") or 0)), Decimal("0.5"))
            )
        return copies

    def _validate_draft_set(self, drafts: list[dict[str, Any]], questions: list[Question]) -> None:
        expected = {question.id for question in questions}
        actual = {int(draft.get("question_id") or 0) for draft in drafts}
        if actual != expected or len(drafts) != len(expected):
            raise LocalScriptPreparationError(
                "Local Qwen did not return exactly one draft per finalized question"
            )

    def _resolve_draft(
        self,
        *,
        draft: dict[str, Any],
        pages: list[Any],
        block_index: dict[tuple[int, int], dict[str, Any]],
        used_blocks: set[tuple[int, int]],
    ) -> tuple[list[PreparedSegment], str]:
        if draft.get("status") == "not_found":
            return [], ""
        selected: dict[int, list[dict[str, Any]]] = {}
        local_keys: set[tuple[int, int]] = set()
        for reference in draft.get("block_references") or []:
            page_no = int(reference["page_no"])
            for order in reference["block_orders"]:
                key = (page_no, int(order))
                block = block_index.get(key)
                if block is None:
                    raise LocalScriptPreparationError("Qwen selected an unknown OCR block")
                if key in local_keys:
                    raise LocalScriptPreparationError(
                        "Qwen repeated one OCR block inside the same answer"
                    )
                if key in used_blocks:
                    raise LocalScriptPreparationError(
                        "Qwen assigned one OCR block to multiple answers"
                    )
                bbox = block.get("bbox")
                if not _valid_bbox(bbox):
                    raise LocalScriptPreparationError(
                        "A selected OCR block has no usable bounding box"
                    )
                local_keys.add(key)
                selected.setdefault(page_no, []).append(block)
        used_blocks.update(local_keys)
        page_by_no = {page.page_no: page for page in pages}
        segments: list[PreparedSegment] = []
        text_parts: list[str] = []
        for page_no in sorted(selected):
            page = page_by_no.get(page_no)
            if page is None:
                raise LocalScriptPreparationError("Qwen selected an unknown script page")
            blocks = sorted(selected[page_no], key=lambda item: int(item["order"]))
            text_parts.extend(str(block["text"]).strip() for block in blocks)
            with Image.open(self.storage.resolve_relative(page.image_path)) as image:
                x, y, width, height = _union_box(blocks, image.width, image.height)
            segments.append(
                PreparedSegment(
                    page_id=page.id,
                    page_no=page_no,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    block_orders=[int(block["order"]) for block in blocks],
                )
            )
        if not segments:
            raise LocalScriptPreparationError("A mapped Qwen draft selected no OCR blocks")
        return segments, "\n".join(text_parts).strip()

    def _create_mapping(
        self,
        *,
        submission: Submission,
        question: Question,
        node: QuestionNode,
        draft: dict[str, Any],
        segments: list[PreparedSegment],
        draft_text: str,
        ocr_warnings: list[str],
        qwen_warnings: list[str],
        provider: str = "llama_cpp_qwen38",
        text_source: str = "qwen38_visual_mapping_pending_transcription",
        possible_continuation: bool = False,
    ) -> AnswerRegionMapping:
        status = "blocked" if not segments else str(draft["status"])
        if status == "not_found":
            status = "blocked"
        warnings = list(
            dict.fromkeys([*ocr_warnings, *qwen_warnings, *list(draft.get("warnings") or [])])
        )
        mapping = AnswerRegionMapping(
            assessment_id=submission.assessment_id,
            submission_id=submission.id,
            question_node_id=node.id,
            question_id=question.id,
            source_page=segments[0].page_no if segments else None,
            source_reference={
                "ocr_draft_text": draft_text,
                "ocr_draft_text_sha256": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
                "segments": [
                    {"page_no": item.page_no, "block_orders": item.block_orders}
                    for item in segments
                ],
                "warnings": warnings,
                "teacher_review_required": True,
                "text_source": text_source,
            },
            confidence=Decimal(str(draft["confidence"])),
            mapping_status=status,
            blocker_reason=(
                "No answer blocks were found for this question"
                if not segments
                else ("Qwen marked this mapping uncertain" if status == "uncertain" else None)
            ),
            provider=provider,
            teacher_confirmed=False,
        )
        if not segments:
            return mapping
        primary = segments[0]
        primary_page = next(page for page in submission.pages if page.id == primary.page_id)
        primary_crop = crop_answer_region_image(
            storage=self.storage,
            source_image_path=primary_page.image_path,
            submission_id=submission.id,
            x=primary.x,
            y=primary.y,
            width=primary.width,
            height=primary.height,
        )
        region = AnswerRegion(
            submission_id=submission.id,
            question_id=question.id,
            question_node_id=node.id,
            page_id=primary.page_id,
            x=primary.x,
            y=primary.y,
            width=primary.width,
            height=primary.height,
            image_path=primary_crop,
            manual_answer_text=None,
            full_answer_confirmed=False,
            evidence_status="unconfirmed",
            continuation_check_status=(
                "possible_continuation" if possible_continuation else "not_checked"
            ),
        )
        for index, segment in enumerate(segments, start=1):
            page = next(page for page in submission.pages if page.id == segment.page_id)
            image_path = (
                primary_crop
                if index == 1
                else crop_answer_region_image(
                    storage=self.storage,
                    source_image_path=page.image_path,
                    submission_id=submission.id,
                    x=segment.x,
                    y=segment.y,
                    width=segment.width,
                    height=segment.height,
                )
            )
            region.segments.append(
                AnswerRegionSegment(
                    submission_page_id=segment.page_id,
                    order_index=index,
                    x=segment.x,
                    y=segment.y,
                    width=segment.width,
                    height=segment.height,
                    image_path=image_path,
                    source="suggestion",
                    confirmed=False,
                    is_primary=index == 1,
                )
            )
        mapping.answer_region = region
        return mapping

    def _load_existing(self, submission_id: int) -> list[AnswerRegionMapping]:
        return list(
            self.db.scalars(
                select(AnswerRegionMapping)
                .options(
                    selectinload(AnswerRegionMapping.answer_region).selectinload(
                        AnswerRegion.segments
                    )
                )
                .where(AnswerRegionMapping.submission_id == submission_id)
                .order_by(AnswerRegionMapping.id)
            ).all()
        )

    def _split_preserved_mappings(
        self, mappings: list[AnswerRegionMapping]
    ) -> tuple[list[AnswerRegionMapping], list[AnswerRegionMapping]]:
        """Keep teacher-confirmed or grading-linked evidence immutable during repair."""
        preserved: list[AnswerRegionMapping] = []
        replaceable: list[AnswerRegionMapping] = []
        for mapping in mappings:
            region = mapping.answer_region
            protected = bool(
                mapping.teacher_confirmed
                or region is not None
                and (
                    bool((region.manual_answer_text or "").strip())
                    or region.grading_jobs
                    or region.grade_suggestions
                    or region.final_grades
                )
            )
            if protected:
                preserved.append(mapping)
            else:
                replaceable.append(mapping)
        return preserved, replaceable

    def _assert_replace_is_safe(self, mappings: list[AnswerRegionMapping]) -> None:
        for mapping in mappings:
            region = mapping.answer_region
            if region is None:
                continue
            if (
                mapping.teacher_confirmed
                or bool((region.manual_answer_text or "").strip())
                or region.grading_jobs
                or region.grade_suggestions
                or region.final_grades
            ):
                raise LocalScriptPreparationError(
                    "Confirmed or graded mappings cannot be replaced automatically"
                )


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    raise LocalScriptPreparationError("Stored script page is not PNG or JPEG")


def _normalized_box_to_page_box(
    x1: int, y1: int, x2: int, y2: int, page_width: int, page_height: int
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Convert a Qwen normalized union box to a conservatively padded crop."""
    pad_x = max(8, round(page_width * 0.015))
    pad_y = max(8, round(page_height * 0.015))
    left = max(0, round(page_width * x1 / 1000) - pad_x)
    top = max(0, round(page_height * y1 / 1000) - pad_y)
    right = min(page_width, round(page_width * x2 / 1000) + pad_x)
    bottom = min(page_height, round(page_height * y2 / 1000) + pad_y)
    if right <= left or bottom <= top:
        raise LocalScriptPreparationError("Qwen3.8 returned an invalid visual mapping box")
    return Decimal(left), Decimal(top), Decimal(right - left), Decimal(bottom - top)


def _apply_adjacent_continuation_boundary_fallback(
    prepared: list[tuple[dict[str, Any], list[PreparedSegment], str]],
    block_index: dict[tuple[int, int], dict[str, Any]],
    page_geometry: dict[int, tuple[int, int, int]],
) -> None:
    """Separate a likely next answer from an inferred continuation strip.

    Paddle layout can miss a sparse final line at the top of a continuation
    page and assign the next visible formula to the previous answer. If the
    immediately following finalized question was reported as not found, move
    that visible block to the following answer and preserve the preceding page
    area as a separate review-only continuation strip. Never duplicate one
    segment across two answers.
    """

    for index in range(1, len(prepared)):
        draft, segments, _draft_text = prepared[index]
        previous_draft, previous_segments, _previous_text = prepared[index - 1]
        if segments or draft.get("status") != "not_found":
            continue
        if len(previous_segments) < 2:
            continue
        shared = previous_segments[-1]
        if shared.page_no <= previous_segments[0].page_no:
            continue
        blocks = [block_index[(shared.page_no, order)] for order in shared.block_orders]
        shared_text = "\n".join(str(block.get("text") or "").strip() for block in blocks).strip()
        if not shared_text:
            continue
        warning = "continuation_boundary_inferred_requires_teacher_review"
        draft["status"] = "uncertain"
        draft["confidence"] = "0.35"
        draft["warnings"] = list(dict.fromkeys([*draft.get("warnings", []), warning]))
        previous_draft["status"] = "uncertain"
        previous_draft["warnings"] = list(
            dict.fromkeys([*previous_draft.get("warnings", []), warning])
        )
        previous_revised = previous_segments[:-1]
        geometry = page_geometry.get(shared.page_no)
        if geometry is not None and shared.y > Decimal("24"):
            page_id, page_width, page_height = geometry
            strip_bottom = min(Decimal(str(page_height)), shared.y)
            previous_revised.append(
                PreparedSegment(
                    page_id=page_id,
                    page_no=shared.page_no,
                    x=Decimal("0"),
                    y=Decimal("0"),
                    width=Decimal(str(page_width)),
                    height=strip_bottom,
                    block_orders=[],
                )
            )
        prepared[index - 1] = (previous_draft, previous_revised, _previous_text)
        prepared[index] = (draft, [shared], shared_text)


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
        and float(value[2]) > float(value[0])
        and float(value[3]) > float(value[1])
    )


def _append_ocr_candidate(
    *,
    candidates: list[dict[str, Any]],
    all_warnings: list[str],
    question: Question,
    segment_order: int,
    kind: str,
    result: Any,
) -> None:
    text = result.normalized_text.strip()
    warnings = list(result.warnings)
    all_warnings.extend(
        f"{question.question_no} segment {segment_order}: {warning}" for warning in warnings
    )
    if text:
        candidates.append(
            {
                "id": f"q{question.id}-segment-{segment_order}-{kind}",
                "kind": kind,
                "text": text,
                "warnings": warnings,
                "latency_ms": result.latency_ms,
            }
        )


def _union_box(
    blocks: list[dict[str, Any]], image_width: int, image_height: int
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    boxes = [block["bbox"] for block in blocks]
    left = max(0.0, min(float(box[0]) for box in boxes) - 96.0)
    top = max(0.0, min(float(box[1]) for box in boxes) - 32.0)
    raw_right = max(float(box[2]) for box in boxes)
    if float(image_width) - raw_right <= float(image_width) * 0.20:
        right = float(image_width)
    else:
        right = min(float(image_width), raw_right + 96.0)
    raw_bottom = max(float(box[3]) for box in boxes)
    if float(image_height) - raw_bottom <= float(image_height) * 0.15:
        bottom = float(image_height)
    else:
        bottom = min(float(image_height), raw_bottom + 96.0)
    if right <= left or bottom <= top:
        raise LocalScriptPreparationError("OCR blocks produced an invalid answer region")
    return tuple(Decimal(str(round(value, 2))) for value in (left, top, right - left, bottom - top))


def _cleaned_whole_image(path: Path) -> bytes:
    with Image.open(path) as source:
        # Teacher annotations are commonly red and can be mistaken for student
        # digits, operators, or trailing letters. Remove only strongly
        # red-dominant pixels before converting to monochrome; black/grey
        # handwriting and faint pencil work remain available to OCR.
        grayscale = _remove_red_annotations(source.convert("RGB")).convert("L")
        # Preserve one-pixel complement bars, fraction strokes, and faint
        # pencil marks. The previous hard threshold plus median filter erased
        # precisely the mathematical evidence that needs teacher review.
        cleaned = ImageOps.autocontrast(grayscale, cutoff=1)
        cleaned = cleaned.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
        cleaned = ImageOps.expand(cleaned, border=32, fill=255)
        target_width = min(2000, max(cleaned.width, 1400))
        if target_width != cleaned.width:
            target_height = max(1, round(cleaned.height * target_width / cleaned.width))
            cleaned = cleaned.resize((target_width, target_height), Image.Resampling.LANCZOS)
        return _png_bytes(cleaned)


def _remove_red_annotations(image: Image.Image) -> Image.Image:
    red, green, blue = image.split()
    red_over_green = ImageChops.subtract(red, green).point(lambda value: 255 if value >= 18 else 0)
    red_over_blue = ImageChops.subtract(red, blue).point(lambda value: 255 if value >= 18 else 0)
    annotation_mask = ImageChops.multiply(red_over_green, red_over_blue)
    # Include anti-aliased edges around a coloured pen stroke without
    # expanding far enough to erase neighbouring black handwriting.
    annotation_mask = annotation_mask.filter(ImageFilter.MaxFilter(3))
    return Image.composite(
        Image.new("RGB", image.size, "white"),
        image,
        annotation_mask,
    )


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
