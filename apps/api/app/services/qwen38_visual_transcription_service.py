from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import AnswerRegion, AnswerRegionMapping, AnswerRegionOcrRun, AuditLog, User
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseService
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter, sanitize_provider_error


class VisualTranscriptionError(RuntimeError):
    pass


FINAL_INTENT_PROMPT_VERSION = "qwen38-final-intent-structured-v2"


def _sha256_joined(parts: list[str]) -> str:
    return hashlib.sha256("".join(parts).encode("ascii")).hexdigest()


class Qwen38VisualTranscriptionService:
    """One durable, no-retry final-intent transcription call per confirmed mapping."""

    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = LocalStorage()

    def create(
        self, region: AnswerRegion, *, teacher: User, expected_model: str
    ) -> AnswerRegionOcrRun:
        self._assert_enabled(expected_model)
        mapping = self._mapping_for_region(region.id)
        if mapping is None or not mapping.teacher_confirmed:
            raise VisualTranscriptionError(
                "Confirm the answer mapping before Qwen3.8 visual transcription"
            )
        if not region.segments:
            raise VisualTranscriptionError("Mapped answer has no image segments")
        active = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == "qwen38_verbatim_visual",
                AnswerRegionOcrRun.status.in_(["queued", "running"]),
            )
        )
        if active is not None:
            raise VisualTranscriptionError("A visual transcription run is already active")
        source_hash = self._source_hash(region)
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"qwen38-visual-{region.id}-{time.time_ns()}",
            status="queued",
            profile="qwen38_verbatim_visual",
            task_kind="visual_transcription",
            reasoning_mode="off",
            prompt_version=FINAL_INTENT_PROMPT_VERSION,
            source_image_sha256=source_hash,
            source_image_hashes=self._source_hashes(region),
            input_manifest_sha256=source_hash,
            model_asset_sha256=self.settings.local_qwen38_model_sha256 or None,
            mmproj_asset_sha256=self.settings.local_qwen38_mmproj_sha256 or None,
            queued_at=datetime.now(UTC),
            call_limit=1,
            calls_used=0,
            provider="llama_cpp_qwen38",
            model_name=self.settings.local_qwen38_model,
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
            self._assert_enabled(run.model_name)
            if run.source_image_sha256 != self._source_hash(region):
                raise VisualTranscriptionError(
                    "Answer image changed after transcription was authorized"
                )
            mapping = self._mapping_for_region(region.id)
            if mapping is None or not mapping.teacher_confirmed:
                raise VisualTranscriptionError("Answer mapping is no longer confirmed")
            lease_holder_id = f"visual_transcription:{run.id}:{uuid4().hex}"
            lease = LocalModelLeaseService(self.db)
            with lease.hold(
                model_phase="Qwen38",
                holder_kind="visual_transcription",
                holder_id=lease_holder_id,
            ):
                if self.settings.local_ai_phase_switch_enabled:
                    LocalAiPhaseManager(settings=self.settings, db=self.db).switch(
                        "Qwen38", lease_holder_id=lease_holder_id
                    )
                adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen38")
                adapter.verify_available_model()
                provider = adapter.provider
                images: list[tuple[bytes, str]] = []
                image_hashes: list[str] = []
                for segment in sorted(region.segments, key=lambda item: item.order_index):
                    path = self.storage.resolve_relative(segment.image_path)
                    image_bytes = path.read_bytes()
                    images.append((image_bytes, "image/png"))
                    image_hashes.append(hashlib.sha256(image_bytes).hexdigest())
                lease.heartbeat(holder_id=lease_holder_id)
                result = provider.transcribe_images(
                    images=images,
                    label=region.question.question_no,
                )
                lease.heartbeat(holder_id=lease_holder_id)
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
                "is_blank": result.is_blank,
                "is_irrelevant": result.is_irrelevant,
                "confidence": str(result.confidence),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
            run.warnings = [
                "teacher_review_required",
                "final_intent_transcription",
                *(
                    ["cancelled_work_excluded"]
                    if result.cancellation_detected
                    else []
                ),
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
                },
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run_id)
            if failed is not None:
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                failed.error = sanitize_provider_error(str(exc))[:500]
                self._audit(
                    failed,
                    "qwen38_visual_transcription_failed",
                    "worker",
                    None,
                    {
                        "answer_region_id": failed.answer_region_id,
                        "calls_used": failed.calls_used,
                    },
                )
                self.db.commit()

    def confirm(
        self, region: AnswerRegion, run: AnswerRegionOcrRun, *, teacher: User, draft_hash: str
    ) -> None:
        if run.answer_region_id != region.id or run.profile != "qwen38_verbatim_visual":
            raise VisualTranscriptionError(
                "Visual transcription run does not belong to this answer"
            )
        if run.prompt_version != FINAL_INTENT_PROMPT_VERSION:
            raise VisualTranscriptionError(
                "This transcript used retired include-crossed-out rules; run final-intent "
                "transcription before confirmation"
            )
        is_blank = bool((run.normalized_result or {}).get("is_blank"))
        if run.status != "succeeded" or (not run.draft_text and not is_blank):
            raise VisualTranscriptionError("Only a completed visual transcription can be confirmed")
        if hashlib.sha256(run.draft_text.encode("utf-8")).hexdigest() != draft_hash:
            raise VisualTranscriptionError(
                "Displayed visual transcription changed; refresh before confirming"
            )
        if run.source_image_sha256 != self._source_hash(region):
            raise VisualTranscriptionError("Answer image changed after transcription; run it again")
        mapping = self._mapping_for_region(region.id)
        if (
            mapping is None
            or not mapping.teacher_confirmed
            or region.grading_jobs
            or region.grade_suggestions
        ):
            raise VisualTranscriptionError("Visual evidence is no longer fresh for confirmation")
        run.status = "confirmed"
        run.confirmed_text = run.draft_text
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = datetime.now(UTC)
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
            },
        )
        self.db.commit()

    def reject(
        self, region: AnswerRegion, run: AnswerRegionOcrRun, *, teacher: User, reason: str
    ) -> None:
        if run.answer_region_id != region.id or run.profile != "qwen38_verbatim_visual":
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

    def _assert_enabled(self, expected_model: str) -> None:
        if not self.settings.brain_allow_real_providers:
            raise VisualTranscriptionError("Real local providers are disabled")
        if (
            not self.settings.local_qwen38_enabled
            or not self.settings.local_qwen38_transcription_enabled
        ):
            raise VisualTranscriptionError("Qwen3.8 visual transcription rescue is disabled")
        if expected_model != self.settings.local_qwen38_model:
            raise VisualTranscriptionError("Expected Qwen3.8 model alias does not match")

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
