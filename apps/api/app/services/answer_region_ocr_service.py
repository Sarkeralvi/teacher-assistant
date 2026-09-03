from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import AnswerRegion, AnswerRegionMapping, AnswerRegionOcrRun, AuditLog, User
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseService
from app.services.local_ocr_client import LocalOcrClient, LocalOcrResult
from app.services.storage import LocalStorage


class AnswerRegionOcrError(RuntimeError):
    pass


class AnswerRegionOcrService:
    """Create and confirm direct PaddleOCR evidence without model correction."""

    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        storage: LocalStorage | None = None,
        client: LocalOcrClient | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorage()
        self.client = client

    def create_draft(
        self,
        region: AnswerRegion,
        teacher: User,
        *,
        expected_model: str,
        expected_layout_model: str,
    ) -> AnswerRegionOcrRun:
        self._assert_enabled(expected_model, expected_layout_model)
        mapping = self._mapping_for_region(region.id)
        if mapping is None or not mapping.teacher_confirmed:
            raise AnswerRegionOcrError("Confirm the answer mapping before transcription")
        if region.grading_jobs or region.grade_suggestions:
            raise AnswerRegionOcrError("Answer evidence cannot change after grading starts")
        active = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == "paddle_direct_baseline_v1",
                AnswerRegionOcrRun.status.in_(["queued", "running"]),
            )
        )
        if active is not None:
            raise AnswerRegionOcrError("A PaddleOCR transcription is already active")
        sources = self._ordered_sources(region)
        source_hashes = [self._file_hash(path) for _, _, path in sources]
        source_hash = hashlib.sha256("".join(source_hashes).encode("ascii")).hexdigest()
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"paddle-baseline-{region.id}-{uuid4().hex}",
            status="queued",
            profile="paddle_direct_baseline_v1",
            task_kind="paddle_baseline_transcription",
            reasoning_mode="not_applicable",
            prompt_version="paddle-direct-v1",
            source_image_sha256=source_hash,
            source_image_hashes=source_hashes,
            input_manifest_sha256=source_hash,
            queued_at=datetime.now(UTC),
            call_limit=len(sources),
            calls_used=0,
            provider="local_paddle_qwen",
            model_name=expected_model,
            layout_model_name=expected_layout_model,
            warnings=["teacher_review_required", "direct_ocr_not_corrected"],
        )
        self.db.add(run)
        self.db.flush()
        self._audit(
            run,
            "paddle_ocr_baseline_requested",
            teacher.id,
            {"answer_region_id": region.id, "segment_count": len(sources)},
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def mark_enqueue_failed(self, run_id: int) -> None:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = "Local PaddleOCR transcription could not be queued"
        self.db.commit()

    def run(self, run_id: int) -> None:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None or run.status != "queued":
            return
        region = self.load_region(run.answer_region_id)
        if region is None:
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error = "Answer region is no longer available"
            self.db.commit()
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = run.started_at
        self.db.commit()
        sources = self._ordered_sources(region)
        if (
            len(sources) != run.call_limit
            or self._current_source_hash(region) != run.source_image_sha256
        ):
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            run.error = "Answer image changed before PaddleOCR started"
            self.db.commit()
            return

        holder = f"paddle_transcription:{run.id}:{uuid4().hex}"
        lease = LocalModelLeaseService(self.db)
        try:
            with lease.hold(
                model_phase="PaddleOcr",
                holder_kind="visual_transcription",
                holder_id=holder,
            ):
                if self.settings.local_ai_phase_switch_enabled:
                    LocalAiPhaseManager(settings=self.settings, db=self.db).switch(
                        "PaddleOcr", lease_holder_id=holder
                    )
                client = self.client or LocalOcrClient.from_settings(self.settings)
                client.health()
                results: list[tuple[int | None, int, LocalOcrResult]] = []
                for index, (segment_id, page_id, path) in enumerate(sources, start=1):
                    lease.heartbeat(holder_id=holder)
                    absolute = self.storage.resolve_relative(path)
                    results.append(
                        (
                            segment_id,
                            page_id,
                            client.ocr_image(
                                image_bytes=absolute.read_bytes(),
                                content_type=self._content_type(absolute),
                                request_id=f"{run.request_id}-segment-{index}",
                                mode="answer_region",
                            ),
                        )
                    )
                    run.calls_used = index
                    run.heartbeat_at = datetime.now(UTC)
                    self.db.commit()
                self._apply_results(run, results)
            self._audit(
                run,
                "paddle_ocr_baseline_succeeded",
                None,
                {
                    "answer_region_id": region.id,
                    "calls_used": run.calls_used,
                    "output_sha256": run.output_sha256,
                },
                actor_type="worker",
            )
            self.db.commit()
            self.db.refresh(run)
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run.id)
            if failed is not None:
                failed.status = "failed"
                failed.completed_at = datetime.now(UTC)
                failed.error = self._safe_error(exc)
                self._audit(
                    failed,
                    "paddle_ocr_baseline_failed",
                    None,
                    {"answer_region_id": region.id, "calls_used": failed.calls_used},
                    actor_type="worker",
                )
                self.db.commit()
            # RQ receives the failure so its job state matches the persistent
            # OCR run. retry=None on enqueue guarantees no automatic retry.
            raise AnswerRegionOcrError("Local PaddleOCR transcription failed") from exc

    def confirm(
        self,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        *,
        teacher: User,
        draft_hash: str,
    ) -> AnswerRegionOcrRun:
        self._assert_run_belongs(region, run)
        if run.status != "succeeded" or run.draft_text is None:
            raise AnswerRegionOcrError("Only a completed PaddleOCR draft can be confirmed")
        actual_hash = hashlib.sha256(run.draft_text.encode("utf-8")).hexdigest()
        if actual_hash != draft_hash or run.output_sha256 != draft_hash:
            raise AnswerRegionOcrError(
                "Displayed PaddleOCR text changed; refresh before confirming"
            )
        if run.source_image_sha256 != self._current_source_hash(region):
            raise AnswerRegionOcrError("Answer image changed after OCR; create a fresh draft")
        mapping = self._mapping_for_region(region.id)
        if mapping is None or not mapping.teacher_confirmed:
            raise AnswerRegionOcrError("Answer mapping is no longer confirmed")
        if region.grading_jobs or region.grade_suggestions:
            raise AnswerRegionOcrError("Answer evidence cannot change after grading starts")
        run.status = "confirmed"
        run.confirmed_text = run.draft_text
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = datetime.now(UTC)
        region.manual_answer_text = run.draft_text
        region.evidence_status = "partial"
        self._audit(
            run,
            "paddle_ocr_baseline_confirmed",
            teacher.id,
            {
                "answer_region_id": region.id,
                "confirmed_text_sha256": draft_hash,
                "character_count": len(run.draft_text),
            },
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def reject(
        self,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        *,
        teacher: User,
        reason: str,
    ) -> AnswerRegionOcrRun:
        self._assert_run_belongs(region, run)
        if run.status not in {"succeeded", "failed", "uncertain"}:
            raise AnswerRegionOcrError("Only an unconfirmed PaddleOCR draft can be rejected")
        run.status = "rejected"
        run.rejected_by_teacher_id = teacher.id
        run.rejected_at = datetime.now(UTC)
        run.rejection_reason_codes = [reason]
        self._audit(
            run,
            "paddle_ocr_baseline_rejected",
            teacher.id,
            {
                "answer_region_id": region.id,
                "reason": reason,
                "diagnostic_reference": f"paddle-run:{run.id}:region:{region.id}",
            },
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def list_runs(self, answer_region_id: int) -> list[AnswerRegionOcrRun]:
        return list(
            self.db.scalars(
                select(AnswerRegionOcrRun)
                .where(
                    AnswerRegionOcrRun.answer_region_id == answer_region_id,
                    AnswerRegionOcrRun.task_kind.in_(
                        [
                            "paddle_baseline_transcription",
                            "visual_transcription",
                            "visual_transcription_thinking_repair",
                            # LocalScriptPageReadService's one-call-per-page runs;
                            # without this the Custom Controlled review panel
                            # never sees the transcript page-read already produced.
                            "visual_page_read",
                        ]
                    ),
                )
                .order_by(AnswerRegionOcrRun.id.desc())
            ).all()
        )

    def get_run(self, run_id: int) -> AnswerRegionOcrRun:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None or run.profile != "paddle_direct_baseline_v1":
            raise AnswerRegionOcrError("PaddleOCR run not found")
        return run

    def load_region(self, answer_region_id: int) -> AnswerRegion | None:
        return self.db.scalar(
            select(AnswerRegion)
            .options(selectinload(AnswerRegion.segments))
            .where(AnswerRegion.id == answer_region_id)
        )

    def _apply_results(
        self, run: AnswerRegionOcrRun, results: list[tuple[int | None, int, LocalOcrResult]]
    ) -> None:
        text_parts: list[str] = []
        markdown_parts: list[str] = []
        warnings = list(run.warnings)
        segments: list[dict[str, object]] = []
        total_latency = 0
        for order, (segment_id, page_id, result) in enumerate(results, start=1):
            text = result.normalized_text.strip()
            text_parts.append(text)
            markdown_parts.append(result.markdown.strip())
            warnings.extend(result.warnings)
            total_latency += result.latency_ms
            segments.append(
                {
                    "segment_id": segment_id,
                    "page_id": page_id,
                    "order": order,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "blocks": [block.model_dump(mode="json") for block in result.blocks],
                    "warnings": result.warnings,
                }
            )
        combined_text = "\n\n".join(text_parts).strip()
        output_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
        run.status = "succeeded"
        run.completed_at = datetime.now(UTC)
        run.heartbeat_at = run.completed_at
        run.draft_text = combined_text
        run.output_sha256 = output_hash
        run.candidate_set_sha256 = output_hash
        run.normalized_result = {
            "normalized_text": combined_text,
            "markdown": "\n\n".join(markdown_parts).strip(),
            "segments": segments,
        }
        run.warnings = list(dict.fromkeys(warnings))
        run.latency_ms = total_latency
        run.error = None

    def _assert_enabled(self, expected_model: str, expected_layout_model: str) -> None:
        if not self.settings.brain_allow_real_providers:
            raise AnswerRegionOcrError("Real local providers are disabled")
        if not self.settings.local_paddle_ocr_enabled:
            raise AnswerRegionOcrError("Local PaddleOCR is disabled")
        if (
            expected_model != self.settings.local_paddle_ocr_model
            or expected_layout_model != self.settings.local_paddle_ocr_layout_model
        ):
            raise AnswerRegionOcrError("Expected PaddleOCR model identity does not match")

    def _ordered_sources(self, region: AnswerRegion) -> list[tuple[int | None, int, str]]:
        segments = sorted(region.segments, key=lambda item: (item.order_index, item.id))
        if segments:
            return [
                (segment.id, segment.submission_page_id, segment.image_path)
                for segment in segments
            ]
        return [(None, region.page_id, region.image_path)]

    def _current_source_hash(self, region: AnswerRegion) -> str:
        hashes = [self._file_hash(path) for _, _, path in self._ordered_sources(region)]
        return hashlib.sha256("".join(hashes).encode("ascii")).hexdigest()

    def _file_hash(self, path: str) -> str:
        return hashlib.sha256(self.storage.resolve_relative(path).read_bytes()).hexdigest()

    def _mapping_for_region(self, region_id: int) -> AnswerRegionMapping | None:
        return self.db.scalar(
            select(AnswerRegionMapping).where(AnswerRegionMapping.answer_region_id == region_id)
        )

    @staticmethod
    def _content_type(path: Path) -> Literal["image/png", "image/jpeg"]:
        suffix = path.suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        raise AnswerRegionOcrError("OCR evidence image must be PNG or JPEG")

    @staticmethod
    def _assert_run_belongs(region: AnswerRegion, run: AnswerRegionOcrRun) -> None:
        if run.answer_region_id != region.id or run.profile != "paddle_direct_baseline_v1":
            raise AnswerRegionOcrError("PaddleOCR run does not belong to this answer")

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc) or "Local PaddleOCR request failed"
        for root in (self.storage.root, self.storage.uploads_dir, self.storage.artifacts_dir):
            message = message.replace(str(root), "[LOCAL_PATH_REDACTED]")
        return message[:500]

    def _audit(
        self,
        run: AnswerRegionOcrRun,
        event: str,
        actor_id: int | None,
        payload: dict[str, object],
        *,
        actor_type: str = "teacher",
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
