from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnswerRegion,
    AnswerRegionOcrRun,
    AuditLog,
    User,
)
from app.services.local_ocr_client import LocalOcrClient, LocalOcrResult
from app.services.storage import LocalStorage


class AnswerRegionOcrService:
    def __init__(
        self,
        db: Session,
        *,
        storage: LocalStorage | None = None,
        client: LocalOcrClient | None = None,
    ) -> None:
        self.db = db
        self.storage = storage or LocalStorage()
        self.client = client

    def create_draft(self, region: AnswerRegion, teacher: User) -> AnswerRegionOcrRun:
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"answer-region-{region.id}-{uuid4().hex}",
            status="running",
            provider="local_paddle_qwen",
            model_name="PaddleOCR-VL-1.6",
            layout_model_name="PP-DocLayoutV3",
            warnings=[],
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        try:
            client = self.client or LocalOcrClient.from_settings()
            sources = self._ordered_sources(region)
            results: list[tuple[int | None, int, LocalOcrResult]] = []
            for index, (segment_id, page_id, image_path) in enumerate(sources, start=1):
                absolute_path = self.storage.resolve_relative(image_path)
                image_bytes = self._read_image(absolute_path)
                content_type = self._content_type(absolute_path)
                result = client.ocr_image(
                    image_bytes=image_bytes,
                    content_type=content_type,
                    request_id=f"{run.request_id}-segment-{index}",
                    mode="answer_region",
                )
                results.append((segment_id, page_id, result))
            self._apply_results(run, results)
            self.db.add(
                AuditLog(
                    actor_type="teacher",
                    actor_id=teacher.id,
                    event_type="answer_region_ocr_draft_created",
                    entity_type="answer_region_ocr_run",
                    entity_id=run.id,
                    payload_json={
                        "answer_region_id": region.id,
                        "provider": run.provider,
                        "model": run.model_name,
                        "segment_count": len(results),
                        "warning_count": len(run.warnings),
                        "draft_character_count": len(run.draft_text or ""),
                    },
                )
            )
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run.id)
            if failed is not None:
                failed.status = "failed"
                failed.error = self._safe_error(exc)
                self.db.add(
                    AuditLog(
                        actor_type="teacher",
                        actor_id=teacher.id,
                        event_type="answer_region_ocr_draft_failed",
                        entity_type="answer_region_ocr_run",
                        entity_id=failed.id,
                        payload_json={"answer_region_id": region.id},
                    )
                )
                self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Local OCR failed; the failed OCR run was recorded",
            ) from exc

    def list_runs(self, answer_region_id: int) -> list[AnswerRegionOcrRun]:
        return list(
            self.db.scalars(
                select(AnswerRegionOcrRun)
                .where(AnswerRegionOcrRun.answer_region_id == answer_region_id)
                .order_by(AnswerRegionOcrRun.id.desc())
            ).all()
        )

    def get_run(self, run_id: int) -> AnswerRegionOcrRun:
        run = self.db.get(AnswerRegionOcrRun, run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Answer region OCR run not found",
            )
        return run

    def confirm(
        self,
        *,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        teacher: User,
        confirmed_text: str,
    ) -> AnswerRegionOcrRun:
        if run.answer_region_id != region.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Answer region OCR run not found",
            )
        if run.status not in {"succeeded", "confirmed"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a successful OCR draft can be confirmed",
            )
        now = datetime.now(UTC)
        region.manual_answer_text = confirmed_text
        run.confirmed_text = confirmed_text
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = now
        run.status = "confirmed"
        text_hash = hashlib.sha256(confirmed_text.encode("utf-8")).hexdigest()
        self.db.add(
            AuditLog(
                actor_type="teacher",
                actor_id=teacher.id,
                event_type="answer_region_ocr_text_confirmed",
                entity_type="answer_region_ocr_run",
                entity_id=run.id,
                payload_json={
                    "answer_region_id": region.id,
                    "confirmed_text_sha256": text_hash,
                    "confirmed_character_count": len(confirmed_text),
                    "full_answer_confirmed": region.full_answer_confirmed,
                    "evidence_status": region.evidence_status,
                },
            )
        )
        self.db.commit()
        self.db.refresh(run)
        return run

    def load_region(self, answer_region_id: int) -> AnswerRegion | None:
        return self.db.scalars(
            select(AnswerRegion)
            .options(selectinload(AnswerRegion.segments))
            .where(AnswerRegion.id == answer_region_id)
        ).first()

    def _ordered_sources(self, region: AnswerRegion) -> list[tuple[int | None, int, str]]:
        segments = sorted(region.segments, key=lambda item: (item.order_index, item.id))
        if segments:
            return [
                (segment.id, segment.submission_page_id, segment.image_path)
                for segment in segments
            ]
        return [(None, region.page_id, region.image_path)]

    def _apply_results(
        self,
        run: AnswerRegionOcrRun,
        results: list[tuple[int | None, int, LocalOcrResult]],
    ) -> None:
        text_parts: list[str] = []
        markdown_parts: list[str] = []
        warnings: list[str] = []
        normalized_segments: list[dict[str, object]] = []
        total_latency = 0
        for order, (segment_id, page_id, result) in enumerate(results, start=1):
            if (
                result.provider != "local_paddle_qwen"
                or result.model != "PaddleOCR-VL-1.6"
                or result.layout_model != "PP-DocLayoutV3"
                or result.version != "3.7.0"
                or result.device != "cpu"
            ):
                raise RuntimeError("Local OCR provider metadata does not match the baseline")
            text = result.normalized_text.strip()
            if text:
                text_parts.append(text)
            if result.markdown.strip():
                markdown_parts.append(result.markdown.strip())
            warnings.extend(result.warnings)
            total_latency += result.latency_ms
            normalized_segments.append(
                {
                    "segment_id": segment_id,
                    "page_id": page_id,
                    "order": order,
                    "text": text,
                    "markdown": result.markdown,
                    "blocks": [block.model_dump(mode="json") for block in result.blocks],
                    "warnings": result.warnings,
                    "request_id": result.request_id,
                }
            )
        combined_text = "\n\n".join(text_parts).strip()
        run.status = "succeeded"
        run.draft_text = combined_text
        run.normalized_result = {
            "normalized_text": combined_text,
            "markdown": "\n\n".join(markdown_parts).strip(),
            "segments": normalized_segments,
        }
        run.warnings = list(dict.fromkeys(warnings))
        run.latency_ms = total_latency
        run.error = None

    def _read_image(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RuntimeError("OCR evidence image is unavailable") from exc

    def _content_type(self, path: Path) -> Literal["image/png", "image/jpeg"]:
        try:
            with Image.open(path) as image:
                image_format = (image.format or "").upper()
        except Exception as exc:
            raise RuntimeError("OCR evidence image is invalid") from exc
        if image_format == "PNG":
            return "image/png"
        if image_format == "JPEG":
            return "image/jpeg"
        raise RuntimeError("OCR evidence image must be PNG or JPEG")

    def _safe_error(self, exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            return "Local OCR request failed"
        message = str(exc)
        if not message:
            return "Local OCR request failed"
        storage_roots = (
            str(self.storage.root),
            str(self.storage.uploads_dir),
            str(self.storage.artifacts_dir),
        )
        for root in storage_roots:
            message = message.replace(root, "[LOCAL_PATH_REDACTED]")
        return message[:1000]
