from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import AnswerRegion, AnswerRegionMapping, AnswerRegionOcrRun, AuditLog, User
from app.services.brain_execution import hold_brain_execution
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainProviderConfigurationError, sanitize_provider_error
from packages.brain.capabilities import BrainCapability
from packages.brain.policy import (
    BrainPolicy,
    brain_policy_from_settings,
    configured_visual_provider,
)
from packages.brain.schemas_qwen38 import (
    FINAL_INTENT_PROMPT_VERSION,
    SUPPORTED_FINAL_INTENT_PROMPT_VERSIONS,
    THINKING_REPAIR_PROMPT_VERSION,
    VISUAL_PAGE_READ_PROMPT_VERSION,
)


class VisualTranscriptionError(RuntimeError):
    pass


def _mapping_is_verified(mapping: AnswerRegionMapping | None) -> bool:
    return bool(
        mapping is not None
        and (mapping.teacher_confirmed or mapping.bulk_policy_verified)
    )


def _sha256_joined(parts: list[str]) -> str:
    return hashlib.sha256("".join(parts).encode("ascii")).hexdigest()


def _repair_decision_hash(decisions: list[dict[str, Any]]) -> str:
    encoded = json.dumps(decisions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _thinking_repair_input_hash(
    *,
    source_hash: str,
    source_run_id: int,
    source_draft_hash: str,
    source_editing_hash: str = "",
    prompt_version: str = THINKING_REPAIR_PROMPT_VERSION,
) -> str:
    """Pin duplicate protection to the exact output contract version."""

    return hashlib.sha256(
        (
            f"{source_hash}:{source_run_id}:{source_draft_hash}:"
            f"{source_editing_hash}:{prompt_version}"
        ).encode("ascii")
    ).hexdigest()


def _source_run_has_repairable_output(run: AnswerRegionOcrRun) -> bool:
    """A model-blank result is repairable when visible writing may have been deleted."""

    return bool((run.draft_text or "").strip()) or bool(
        (run.normalized_result or {}).get("is_blank")
    )


def _repair_source_text(run: AnswerRegionOcrRun) -> str:
    return run.draft_text or "[source model returned blank despite visible student writing]"


def _repair_source_editing_marks(run: AnswerRegionOcrRun) -> list[dict[str, Any]]:
    analysis = (run.normalized_result or {}).get("editing_analysis") or {}
    raw_marks = analysis.get("editing_marks") if isinstance(analysis, dict) else None
    if not isinstance(raw_marks, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in raw_marks:
        if not isinstance(raw, dict):
            continue
        # Never copy baseline text or position hints into the repair prompt.
        # Only image coordinates and provisional status are useful location hints.
        result.append(
            {
                "page_index": raw.get("page_index"),
                "bbox": raw.get("bbox"),
                "status": raw.get("status"),
                "position_hint": "source visual edit location",
            }
        )
    return result


class Qwen38VisualTranscriptionService:
    """One durable, no-retry visual-evidence transcription per confirmed mapping."""

    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = LocalStorage()

    def create(
        self,
        region: AnswerRegion,
        *,
        teacher: User,
        expected_model: str,
        provider: str | None = None,
    ) -> AnswerRegionOcrRun:
        policy = (
            self._assert_enabled(expected_model)
            if provider is None
            else self._assert_enabled(expected_model, provider=provider)
        )
        mapping = self._mapping_for_region(region.id)
        if not _mapping_is_verified(mapping):
            raise VisualTranscriptionError(
                "Confirm the answer mapping before visual transcription"
            )
        if region.grading_jobs or region.grade_suggestions:
            raise VisualTranscriptionError(
                "Cannot replace answer evidence after grading has started"
            )
        if not region.segments:
            raise VisualTranscriptionError("Mapped answer has no image segments")
        active = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile.in_(
                    ["qwen38_verbatim_visual", "qwen38_thinking_repair"]
                ),
                AnswerRegionOcrRun.status.in_(["queued", "running"]),
            )
        )
        if active is not None:
            raise VisualTranscriptionError("A visual transcription run is already active")
        source_hash = self._source_hash(region)
        existing_repair = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == "qwen38_thinking_repair",
                AnswerRegionOcrRun.source_image_sha256 == source_hash,
            )
        )
        if existing_repair is not None:
            raise VisualTranscriptionError(
                "A thinking repair already exists for these images; upload clearer pages to restart"
            )
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"brain-visual-{region.id}-{time.time_ns()}",
            status="queued",
            profile="qwen38_verbatim_visual",
            task_kind="visual_transcription",
            reasoning_mode="off",
            prompt_version=FINAL_INTENT_PROMPT_VERSION,
            source_image_sha256=source_hash,
            source_image_hashes=self._source_hashes(region),
            input_manifest_sha256=source_hash,
            model_asset_sha256=policy.model_asset_sha256,
            mmproj_asset_sha256=policy.auxiliary_model_asset_sha256,
            queued_at=datetime.now(UTC),
            call_limit=1,
            calls_used=0,
            provider=policy.provider,
            model_name=policy.model,
            layout_model_name=None,
            warnings=[],
        )
        self.db.add(run)
        self.db.flush()
        self._audit(
            run,
            "qwen38_visual_transcription_requested",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "source_image_sha256": source_hash,
                "segment_count": len(region.segments),
                "call_limit": 1,
            },
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def create_thinking_repair(
        self,
        region: AnswerRegion,
        source_run: AnswerRegionOcrRun,
        *,
        teacher: User,
        expected_model: str,
        provider: str | None = None,
    ) -> AnswerRegionOcrRun:
        policy = (
            self._assert_thinking_repair_enabled(expected_model)
            if provider is None
            else self._assert_thinking_repair_enabled(
                expected_model,
                provider=provider,
            )
        )
        mapping = self._mapping_for_region(region.id)
        if not _mapping_is_verified(mapping):
            raise VisualTranscriptionError("Confirm the answer mapping before thinking repair")
        if region.grading_jobs or region.grade_suggestions:
            raise VisualTranscriptionError(
                "Cannot replace answer evidence after grading has started"
            )
        if not region.segments:
            raise VisualTranscriptionError("Mapped answer has no image segments")
        if (
            source_run.answer_region_id != region.id
            or source_run.profile != "qwen38_verbatim_visual"
            or source_run.prompt_version not in SUPPORTED_FINAL_INTENT_PROMPT_VERSIONS
            or source_run.status not in {"succeeded", "confirmed", "rejected"}
            or not _source_run_has_repairable_output(source_run)
        ):
            raise VisualTranscriptionError(
                "Thinking repair requires a completed visual-evidence transcript"
            )
        source_hash = self._source_hash(region)
        if source_run.source_image_sha256 != source_hash:
            raise VisualTranscriptionError("Answer images changed; run normal transcription again")
        source_draft_hash = hashlib.sha256(source_run.draft_text.encode("utf-8")).hexdigest()
        source_editing_marks = _repair_source_editing_marks(source_run)
        source_editing_hash = _repair_decision_hash(source_editing_marks)
        input_hash = _thinking_repair_input_hash(
            source_hash=source_hash,
            source_run_id=source_run.id,
            source_draft_hash=source_draft_hash,
            source_editing_hash=source_editing_hash,
        )
        existing = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == "qwen38_thinking_repair",
                AnswerRegionOcrRun.input_manifest_sha256 == input_hash,
            )
        )
        if existing is not None:
            raise VisualTranscriptionError(
                "This transcript already has a thinking repair; automatic or duplicate "
                "retries are disabled"
            )
        active = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile.in_(
                    ["qwen38_verbatim_visual", "qwen38_thinking_repair"]
                ),
                AnswerRegionOcrRun.status.in_(["queued", "running"]),
            )
        )
        if active is not None:
            raise VisualTranscriptionError("A visual transcription call is already active")
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"brain-thinking-repair-{region.id}-{time.time_ns()}",
            status="queued",
            profile="qwen38_thinking_repair",
            task_kind="visual_transcription_thinking_repair",
            reasoning_mode="thinking",
            prompt_version=THINKING_REPAIR_PROMPT_VERSION,
            source_image_sha256=source_hash,
            source_image_hashes=self._source_hashes(region),
            input_manifest_sha256=input_hash,
            model_asset_sha256=policy.model_asset_sha256,
            mmproj_asset_sha256=policy.auxiliary_model_asset_sha256,
            queued_at=datetime.now(UTC),
            call_limit=3,
            calls_used=0,
            provider=policy.provider,
            model_name=policy.model,
            warnings=["teacher_review_required", "thinking_repair_pending"],
            normalized_result={
                "task_kind": "visual_transcription_thinking_repair",
                "prompt_version": THINKING_REPAIR_PROMPT_VERSION,
                "source_run_id": source_run.id,
                "source_draft_sha256": source_draft_hash,
                "source_editing_sha256": source_editing_hash,
            },
        )
        self.db.add(run)
        self.db.flush()
        self._audit(
            run,
            "qwen38_thinking_repair_requested",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "source_run_id": source_run.id,
                "source_draft_sha256": source_draft_hash,
                "source_image_sha256": source_hash,
                "call_limit": 3,
            },
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_enqueue_failed(self, run_id: int, message: str) -> None:
        """Make a queue outage visible instead of leaving a run queued forever."""

        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = message
        self._audit(
            run,
            "qwen38_visual_transcription_enqueue_failed",
            "system",
            None,
            {"error": message},
        )
        self.db.commit()

    def run(self, run_id: int) -> None:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None or run.profile != "qwen38_verbatim_visual" or run.status != "queued":
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = run.started_at
        self.db.commit()
        try:
            region = self.db.scalar(
                select(AnswerRegion)
                .options(selectinload(AnswerRegion.segments))
                .where(AnswerRegion.id == run.answer_region_id)
            )
            if region is None:
                raise VisualTranscriptionError("Answer region no longer exists")
            policy = self._assert_enabled(run.model_name, provider=run.provider)
            if run.source_image_sha256 != self._source_hash(region):
                raise VisualTranscriptionError(
                    "Answer image changed after transcription was authorized"
                )
            mapping = self._mapping_for_region(region.id)
            if not _mapping_is_verified(mapping):
                raise VisualTranscriptionError("Answer mapping is no longer confirmed")
            lease_holder_id = f"visual_transcription:{run.id}:{uuid4().hex}"
            with hold_brain_execution(
                db=self.db,
                settings=self.settings,
                adapter=policy.adapter,
                holder_kind="visual_transcription",
                holder_id=lease_holder_id,
            ) as execution:
                images: list[tuple[bytes, str]] = []
                image_hashes: list[str] = []
                for segment in sorted(region.segments, key=lambda item: item.order_index):
                    path = self.storage.resolve_relative(segment.image_path)
                    image_bytes = path.read_bytes()
                    images.append((image_bytes, "image/png"))
                    image_hashes.append(hashlib.sha256(image_bytes).hexdigest())
                execution.heartbeat()
                # Count the provider attempt before the call. A timeout or
                # malformed response still consumed the one authorized call.
                run.calls_used = 1
                run.heartbeat_at = datetime.now(UTC)
                self.db.commit()
                result = policy.adapter.transcribe_images(
                    images=images,
                    label=region.question.question_no,
                )
                execution.heartbeat()
            draft_hash = hashlib.sha256(result.draft_text.encode("utf-8")).hexdigest()
            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            run.heartbeat_at = run.completed_at
            run.calls_used = 1
            run.draft_text = result.draft_text
            run.candidate_set_sha256 = draft_hash
            run.output_sha256 = draft_hash
            run.normalized_result = {
                "task_kind": "visual_transcription",
                "prompt_version": FINAL_INTENT_PROMPT_VERSION,
                "reasoning_mode": "off",
                "input_image_sha256": image_hashes,
                "draft_text_sha256": draft_hash,
                "uncertain_glyphs": [
                    item.model_dump(mode="json") for item in result.uncertain_glyphs
                ],
                "editing_analysis": {
                    "editing_marks": [
                        item.model_dump(mode="json") for item in result.editing_marks
                    ],
                    "cancellation_detected": result.cancellation_detected,
                    "replacement_detected": result.replacement_detected,
                    "uncertain_correction_detected": result.uncertain_correction_detected,
                },
                "requires_thinking_repair": result.requires_thinking_repair,
                "is_blank": result.is_blank,
                "is_irrelevant": result.is_irrelevant,
                "confidence": str(result.confidence),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "provider_calls_used": result.provider_calls_used,
            }
            run.warnings = [
                "teacher_review_required",
                "final_intent_transcription",
                *(["visible_edits_preserved"] if result.editing_marks else []),
                *(
                    ["student_replacement_detected"]
                    if result.replacement_detected
                    else []
                ),
                *(
                    ["uncertain_student_correction"]
                    if result.uncertain_correction_detected
                    else []
                ),
                *(["visual_transcription_uncertain"] if result.uncertain_glyphs else []),
                *(
                    ["thinking_repair_required"]
                    if result.requires_thinking_repair
                    else []
                ),
            ]
            run.latency_ms = result.latency_ms
            self._audit(
                run,
                "qwen38_visual_transcription_succeeded",
                "worker",
                None,
                {
                    "answer_region_id": region.id,
                    "source_image_sha256": run.source_image_sha256,
                    "draft_text_sha256": draft_hash,
                    "segment_count": len(images),
                    "calls_used": 1,
                    "latency_ms": run.latency_ms,
                    "cancellation_detected": result.cancellation_detected,
                    "replacement_detected": result.replacement_detected,
                    "uncertain_correction_detected": (
                        result.uncertain_correction_detected
                    ),
                    "requires_thinking_repair": result.requires_thinking_repair,
                },
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run_id)
            if failed is not None:
                failure_code = str(
                    getattr(exc, "failure_code", "visual_transcription_execution_failed")
                )[:100]
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                failed.error = sanitize_provider_error(str(exc))[:500]
                failed.normalized_result = {
                    **(failed.normalized_result or {}),
                    "prompt_version": failed.prompt_version,
                    "failure_code": failure_code,
                }
                failed.warnings = [
                    warning
                    for warning in (failed.warnings or [])
                    if warning != "visual_transcription_pending"
                ] + [failure_code]
                self._audit(
                    failed,
                    "qwen38_visual_transcription_failed",
                    "worker",
                    None,
                    {
                        "answer_region_id": failed.answer_region_id,
                        "calls_used": failed.calls_used,
                        "failure_code": failure_code,
                    },
                )
                self.db.commit()

    def confirm(
        self, region: AnswerRegion, run: AnswerRegionOcrRun, *, teacher: User, draft_hash: str
    ) -> None:
        # A page-read run (LocalScriptPageReadService, one call per page) carries
        # no structured editing_marks, so it is never routed into Thinking repair;
        # it is instead directly confirmable here, on the same terms as a current
        # final-intent run, gated by the same forbidden-marker scan below.
        if run.answer_region_id != region.id or run.profile not in {
            "qwen38_verbatim_visual",
            "qwen38_visual_page_read",
        }:
            raise VisualTranscriptionError(
                "Visual transcription run does not belong to this answer"
            )
        is_page_read = run.profile == "qwen38_visual_page_read"
        current_prompt_version = (
            VISUAL_PAGE_READ_PROMPT_VERSION if is_page_read else FINAL_INTENT_PROMPT_VERSION
        )
        if run.prompt_version != current_prompt_version:
            raise VisualTranscriptionError(
                "This transcript used the older combined transcription/cancellation policy; "
                "run the current evidence-preserving transcription before direct confirmation, "
                "or use the explicit Thinking repair"
            )
        is_blank = bool((run.normalized_result or {}).get("is_blank"))
        normalized = run.normalized_result or {}
        editing_analysis = normalized.get("editing_analysis") or {}
        forbidden_markers = (
            "[visibly crossed]",
            "[overwritten]",
            "[illegible crossed writing]",
            "[unclear correction]",
            "[illegible]",
            "[visible writing unresolved",
        )
        if (
            normalized.get("uncertain_glyphs")
            or (
                isinstance(editing_analysis, dict)
                and editing_analysis.get("uncertain_correction_detected")
            )
            or any(marker in (run.draft_text or "").casefold() for marker in forbidden_markers)
        ):
            raise VisualTranscriptionError(
                "This baseline still contains unresolved or explicitly preserved edited writing; "
                "use the Qwen3.8 Thinking comparison or upload a clearer complete page"
            )
        if run.status != "succeeded" or (not run.draft_text and not is_blank):
            raise VisualTranscriptionError("Only a completed visual transcription can be confirmed")
        if hashlib.sha256(run.draft_text.encode("utf-8")).hexdigest() != draft_hash:
            raise VisualTranscriptionError(
                "Displayed visual transcription changed; refresh before confirming"
            )
        if run.source_image_sha256 != self._source_hash(region):
            raise VisualTranscriptionError("Answer image changed after transcription; run it again")
        confirmed_repair_exists = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == "qwen38_thinking_repair",
                AnswerRegionOcrRun.status == "confirmed",
            )
        )
        if confirmed_repair_exists is not None:
            raise VisualTranscriptionError(
                "A Thinking alternative is already confirmed; it cannot be overwritten by the "
                "original transcript"
            )
        mapping = self._mapping_for_region(region.id)
        if (
            not _mapping_is_verified(mapping)
            or region.grading_jobs
            or region.grade_suggestions
        ):
            raise VisualTranscriptionError("Visual evidence is no longer fresh for confirmation")
        run.status = "confirmed"
        run.confirmed_text = run.draft_text
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = datetime.now(UTC)
        teacher_selected_flagged_baseline = bool(
            (run.normalized_result or {}).get("requires_thinking_repair")
        )
        existing_warnings = run.warnings or []
        if (
            teacher_selected_flagged_baseline
            and "teacher_selected_original_transcript" not in existing_warnings
        ):
            run.warnings = [*existing_warnings, "teacher_selected_original_transcript"]
        region.manual_answer_text = run.draft_text
        region.evidence_status = "partial"
        self._audit(
            run,
            "qwen38_visual_transcription_confirmed",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "draft_text_sha256": draft_hash,
                "character_count": len(run.draft_text),
                "teacher_selected_flagged_baseline": teacher_selected_flagged_baseline,
            },
        )
        self.db.commit()

    def run_thinking_repair(self, run_id: int) -> None:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if (
            run is None
            or run.profile != "qwen38_thinking_repair"
            or run.status != "queued"
        ):
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = run.started_at
        self.db.commit()
        try:
            region = self.db.scalar(
                select(AnswerRegion)
                .options(selectinload(AnswerRegion.segments))
                .where(AnswerRegion.id == run.answer_region_id)
            )
            if region is None:
                raise VisualTranscriptionError("Answer region no longer exists")
            if run.source_image_sha256 != self._source_hash(region):
                raise VisualTranscriptionError(
                    "Answer image changed after thinking repair was authorized"
                )
            mapping = self._mapping_for_region(region.id)
            if not _mapping_is_verified(mapping):
                raise VisualTranscriptionError("Answer mapping is no longer confirmed")
            source_run_id = (run.normalized_result or {}).get("source_run_id")
            source_run = self.db.get(AnswerRegionOcrRun, source_run_id)
            if (
                source_run is None
                or source_run.answer_region_id != region.id
                or not _source_run_has_repairable_output(source_run)
            ):
                raise VisualTranscriptionError("Source transcript is no longer available")
            source_draft_hash = hashlib.sha256(
                source_run.draft_text.encode("utf-8")
            ).hexdigest()
            if source_draft_hash != (run.normalized_result or {}).get(
                "source_draft_sha256"
            ):
                raise VisualTranscriptionError("Source transcript changed after authorization")
            source_editing_marks = _repair_source_editing_marks(source_run)
            source_editing_hash = _repair_decision_hash(source_editing_marks)
            if source_editing_hash != (run.normalized_result or {}).get(
                "source_editing_sha256"
            ):
                raise VisualTranscriptionError(
                    "Source visual edit locations changed after authorization"
                )

            policy = self._assert_thinking_repair_enabled(
                run.model_name,
                provider=run.provider,
            )

            lease_holder_id = f"visual_transcription_repair:{run.id}:{uuid4().hex}"
            with hold_brain_execution(
                db=self.db,
                settings=self.settings,
                adapter=policy.adapter,
                holder_kind="visual_transcription_repair",
                holder_id=lease_holder_id,
            ) as execution:
                images: list[tuple[bytes, str]] = []
                image_hashes: list[str] = []
                for segment in sorted(region.segments, key=lambda item: item.order_index):
                    image_bytes = self.storage.resolve_relative(segment.image_path).read_bytes()
                    images.append((image_bytes, "image/png"))
                    image_hashes.append(hashlib.sha256(image_bytes).hexdigest())
                execution.heartbeat()
                run.calls_used = 1
                run.heartbeat_at = datetime.now(UTC)
                self.db.commit()
                result = policy.adapter.repair_transcription_images(
                    images=images,
                    rejected_transcript=_repair_source_text(source_run),
                    source_editing_marks=source_editing_marks,
                )
                run.calls_used = result.provider_calls_used
                execution.heartbeat()

            draft_hash = hashlib.sha256(result.draft_text.encode("utf-8")).hexdigest()
            decisions = [item.model_dump(mode="json") for item in result.editing_marks]
            decision_hash = _repair_decision_hash(decisions)
            candidate_hash = hashlib.sha256(
                f"{draft_hash}:{decision_hash}".encode("ascii")
            ).hexdigest()
            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            run.heartbeat_at = run.completed_at
            run.draft_text = result.draft_text
            run.candidate_set_sha256 = candidate_hash
            run.output_sha256 = draft_hash
            run.normalized_result = {
                "task_kind": "visual_transcription_thinking_repair",
                "prompt_version": THINKING_REPAIR_PROMPT_VERSION,
                "reasoning_mode": "thinking",
                "source_run_id": source_run.id,
                "source_draft_sha256": source_draft_hash,
                "input_image_sha256": image_hashes,
                "draft_text_sha256": draft_hash,
                "decision_set_sha256": decision_hash,
                "editing_analysis": {
                    "editing_marks": decisions,
                    "cancellation_detected": result.cancellation_detected,
                    "replacement_detected": result.replacement_detected,
                    "uncertain_correction_detected": result.uncertain_correction_detected,
                },
                "is_blank": result.is_blank,
                "is_irrelevant": result.is_irrelevant,
                "confidence": str(result.confidence),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
            run.warnings = [
                "teacher_review_required",
                "thinking_enabled_edit_adjudication",
                "no_question_solution_or_rubric_context",
                "all_edit_decisions_require_confirmation",
                *(
                    ["bounded_visual_resolution_used"]
                    if result.provider_calls_used == 3
                    else []
                ),
                *(
                    ["uncertain_student_correction"]
                    if result.uncertain_correction_detected
                    else []
                ),
            ]
            run.latency_ms = result.latency_ms
            self._audit(
                run,
                "qwen38_thinking_repair_succeeded",
                "worker",
                None,
                {
                    "answer_region_id": region.id,
                    "source_run_id": source_run.id,
                    "source_draft_sha256": source_draft_hash,
                    "draft_text_sha256": draft_hash,
                    "decision_set_sha256": decision_hash,
                    "decision_count": len(decisions),
                    "calls_used": result.provider_calls_used,
                    "latency_ms": run.latency_ms,
                },
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run_id)
            if failed is not None:
                failed.calls_used = max(
                    failed.calls_used,
                    int(getattr(exc, "calls_used", failed.calls_used)),
                )
                failure_code = str(
                    getattr(exc, "failure_code", "thinking_repair_execution_failed")
                )[:100]
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                failed.error = sanitize_provider_error(str(exc))[:500]
                failed.normalized_result = {
                    **(failed.normalized_result or {}),
                    "prompt_version": failed.prompt_version,
                    "failure_code": failure_code,
                }
                failed.warnings = [
                    warning
                    for warning in (failed.warnings or [])
                    if warning != "thinking_repair_pending"
                ] + [failure_code]
                self._audit(
                    failed,
                    "qwen38_thinking_repair_failed",
                    "worker",
                    None,
                    {
                        "answer_region_id": failed.answer_region_id,
                        "calls_used": failed.calls_used,
                        "failure_code": failure_code,
                    },
                )
                self.db.commit()

    def confirm_thinking_repair(
        self,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        *,
        teacher: User,
        draft_hash: str,
        decision_set_hash: str,
        reviewed_decision_indexes: list[int],
    ) -> None:
        if run.answer_region_id != region.id or run.profile != "qwen38_thinking_repair":
            raise VisualTranscriptionError("Thinking repair run does not belong to this answer")
        if run.prompt_version != THINKING_REPAIR_PROMPT_VERSION:
            raise VisualTranscriptionError("Thinking repair prompt version is not current")
        if run.status != "succeeded" or not (run.draft_text or "").strip():
            raise VisualTranscriptionError("Only a completed thinking repair can be confirmed")
        if hashlib.sha256(run.draft_text.encode("utf-8")).hexdigest() != draft_hash:
            raise VisualTranscriptionError("Displayed repaired transcript changed; refresh first")
        normalized = run.normalized_result or {}
        decisions = (normalized.get("editing_analysis") or {}).get("editing_marks") or []
        if not isinstance(decisions, list):
            raise VisualTranscriptionError("Thinking repair editing decisions are invalid")
        if not decisions:
            raise VisualTranscriptionError(
                "Finalized surviving-work transcription requires image-grounded edit decisions"
            )
        if any(
            isinstance(decision, dict)
            and decision.get("status") == "uncertain_correction"
            for decision in decisions
        ):
            raise VisualTranscriptionError(
                "Unresolved correction cannot be confirmed for grading"
            )
        forbidden_markers = (
            "[visibly crossed]",
            "[overwritten]",
            "[illegible crossed writing]",
            "[unclear correction]",
            "[visible writing unresolved",
        )
        normalized_draft = (run.draft_text or "").casefold()
        if any(marker in normalized_draft for marker in forbidden_markers):
            raise VisualTranscriptionError(
                "Finalized surviving-work transcription still contains unresolved evidence markers"
            )
        expected_decision_hash = _repair_decision_hash(decisions)
        if (
            decision_set_hash != expected_decision_hash
            or decision_set_hash != normalized.get("decision_set_sha256")
        ):
            raise VisualTranscriptionError("Displayed editing decisions changed; refresh first")
        expected_indexes = list(range(len(decisions)))
        if sorted(reviewed_decision_indexes) != expected_indexes:
            raise VisualTranscriptionError(
                "Review and acknowledge every visual editing decision before confirmation"
            )
        if run.source_image_sha256 != self._source_hash(region):
            raise VisualTranscriptionError("Answer images changed after repair; start again")
        mapping = self._mapping_for_region(region.id)
        if (
            not _mapping_is_verified(mapping)
            or region.grading_jobs
            or region.grade_suggestions
        ):
            raise VisualTranscriptionError("Repaired visual evidence is no longer fresh")
        run.status = "confirmed"
        run.confirmed_text = run.draft_text
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = datetime.now(UTC)
        region.manual_answer_text = run.draft_text
        region.evidence_status = "partial"
        mapping.mapping_status = "teacher_confirmed"
        mapping.blocker_reason = None
        self._audit(
            run,
            "qwen38_thinking_repair_confirmed",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "draft_text_sha256": draft_hash,
                "decision_set_sha256": decision_set_hash,
                "reviewed_decision_count": len(reviewed_decision_indexes),
            },
        )
        self.db.commit()

    def reject_thinking_repair(
        self,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        *,
        teacher: User,
        reason: str,
    ) -> None:
        if run.answer_region_id != region.id or run.profile != "qwen38_thinking_repair":
            raise VisualTranscriptionError("Thinking repair run does not belong to this answer")
        if run.status not in {"succeeded", "uncertain", "failed"}:
            raise VisualTranscriptionError("Only an unconfirmed thinking repair can be rejected")
        run.status = "rejected"
        run.rejected_by_teacher_id = teacher.id
        run.rejected_at = datetime.now(UTC)
        run.rejection_reason_codes = [reason]
        self._audit(
            run,
            "qwen38_thinking_repair_rejected",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "reason": reason,
                "diagnostic_reference": f"thinking-repair:{run.id}:region:{region.id}",
            },
        )
        self.db.commit()

    def reject(
        self, region: AnswerRegion, run: AnswerRegionOcrRun, *, teacher: User, reason: str
    ) -> None:
        if run.answer_region_id != region.id or run.profile not in {
            "qwen38_verbatim_visual",
            "qwen38_visual_page_read",
        }:
            raise VisualTranscriptionError(
                "Visual transcription run does not belong to this answer"
            )
        if run.status not in {"succeeded", "uncertain", "failed"}:
            raise VisualTranscriptionError(
                "Only an unconfirmed visual transcription can be rejected"
            )
        run.status = "rejected"
        run.rejected_by_teacher_id = teacher.id
        run.rejected_at = datetime.now(UTC)
        run.rejection_reason_codes = [reason]
        mapping = self._mapping_for_region(region.id)
        if mapping is not None:
            mapping.mapping_status = "blocked"
            mapping.blocker_reason = "Visual transcription rejected; upload a clearer complete page"
        self._audit(
            run,
            "qwen38_visual_transcription_rejected",
            "teacher",
            teacher.id,
            {
                "answer_region_id": region.id,
                "reason": reason,
                "diagnostic_reference": f"visual-run:{run.id}:region:{region.id}",
            },
        )
        self.db.commit()

    def _assert_enabled(
        self,
        expected_model: str,
        *,
        provider: str | None = None,
    ) -> BrainPolicy:
        requested_provider = _resolve_visual_provider(self.settings, provider)
        try:
            policy = brain_policy_from_settings(
                self.settings,
                requested_provider=requested_provider,
            )
            policy.validate_request(
                requested_provider=provider or "active",
                expected_model=expected_model,
                capability=BrainCapability.VISUAL_TRANSCRIPTION,
                feature_enabled=policy.transcription_enabled,
            )
        except BrainProviderConfigurationError as exc:
            raise VisualTranscriptionError(str(exc)) from exc
        return policy

    def _assert_thinking_repair_enabled(
        self,
        expected_model: str,
        *,
        provider: str | None = None,
    ) -> BrainPolicy:
        requested_provider = _resolve_visual_provider(self.settings, provider)
        if (
            (provider or "").strip().lower() in {"", "brain", "active"}
            and self.settings.brain_thinking_repair_enabled is None
            and not self.settings.local_qwen38_thinking_repair_enabled
        ):
            raise VisualTranscriptionError("Brain thinking repair is disabled")
        try:
            policy = brain_policy_from_settings(
                self.settings,
                requested_provider=requested_provider,
            )
            if not (policy.transcription_enabled and policy.thinking_repair_enabled):
                raise VisualTranscriptionError("Brain thinking repair is disabled")
            policy.validate_request(
                requested_provider=provider or "active",
                expected_model=expected_model,
                capability=BrainCapability.TRANSCRIPTION_REPAIR,
                feature_enabled=(
                    policy.transcription_enabled and policy.thinking_repair_enabled
                ),
            )
        except BrainProviderConfigurationError as exc:
            raise VisualTranscriptionError(str(exc)) from exc
        return policy

    def _mapping_for_region(self, region_id: int) -> AnswerRegionMapping | None:
        return self.db.scalar(
            select(AnswerRegionMapping).where(AnswerRegionMapping.answer_region_id == region_id)
        )

    def _source_hash(self, region: AnswerRegion) -> str:
        return _sha256_joined(self._source_hashes(region))

    def _source_hashes(self, region: AnswerRegion) -> list[str]:
        return [
            hashlib.sha256(
                self.storage.resolve_relative(segment.image_path).read_bytes()
            ).hexdigest()
            for segment in sorted(region.segments, key=lambda item: item.order_index)
        ]

    def _audit(
        self,
        run: AnswerRegionOcrRun,
        event: str,
        actor_type: str,
        actor_id: int | None,
        payload: dict[str, Any],
    ) -> None:
        self.db.add(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=event,
                entity_type="answer_region_ocr_run",
                entity_id=run.id,
                payload_json=payload,
            )
        )


def _resolve_visual_provider(settings: Settings, provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"", "brain", "active"}:
        return configured_visual_provider(settings)
    return normalized
