from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrBand,
    AnswerRegionOcrCandidate,
    AnswerRegionOcrRun,
    AuditLog,
    GradingJob,
    User,
)
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_ocr_client import LocalOcrClient, LocalOcrResult
from app.services.storage import LocalStorage

PROFILE = "math_handwriting_rescue"
VL_MODEL = "PaddleOCR-VL-1.6"
LAYOUT_MODEL = "PP-DocLayoutV3"
DET_MODEL = "PP-OCRv6_medium_det"
REC_MODEL = "PP-OCRv6_medium_rec"
MATH_PATTERN = re.compile(
    r"[=+*/×÷^√∩∪<>]|\\frac|\bp\s*\(|\d\s*[:/]\s*\d",
    re.IGNORECASE,
)


class OcrRescueService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        storage: LocalStorage | None = None,
        client: LocalOcrClient | None = None,
        phase_manager: LocalAiPhaseManager | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = storage or LocalStorage()
        self.client = client
        self.phase_manager = phase_manager or LocalAiPhaseManager(settings=self.settings)

    def create_run(
        self, *, region: AnswerRegion, teacher: User, max_calls: int
    ) -> AnswerRegionOcrRun:
        if not self.settings.local_ocr_rescue_enabled:
            raise HTTPException(status_code=403, detail="Enhanced local OCR is disabled")
        if not self.settings.brain_allow_real_providers or not self.settings.local_ocr_enabled:
            raise HTTPException(status_code=403, detail="Local OCR provider is disabled")
        if max_calls > min(8, self.settings.local_ocr_rescue_max_calls):
            raise HTTPException(
                status_code=422, detail="OCR rescue call limit exceeds server policy"
            )
        mapping = self._mapping_for_region(region.id)
        if mapping is None:
            raise HTTPException(status_code=409, detail="Answer-region mapping is unavailable")
        if self.db.scalar(
            select(GradingJob.id).where(
                GradingJob.answer_region_id == region.id,
                GradingJob.status.in_(("queued", "running")),
            )
        ):
            raise HTTPException(status_code=409, detail="Grading is already active for this answer")
        source_bytes = self._source_image_bytes(region)
        source_hash = _sha256(source_bytes)
        rejected = self.db.scalar(
            select(AnswerRegionOcrRun.id).where(
                AnswerRegionOcrRun.answer_region_id == region.id,
                AnswerRegionOcrRun.profile == PROFILE,
                AnswerRegionOcrRun.source_image_sha256 == source_hash,
                AnswerRegionOcrRun.status == "rejected",
                AnswerRegionOcrRun.model_name == VL_MODEL,
                AnswerRegionOcrRun.layout_model_name == LAYOUT_MODEL,
            )
        )
        if rejected:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This rejected image/model rescue is immutable; upload a clearer complete page"
                ),
            )
        now = datetime.now(UTC)
        run = AnswerRegionOcrRun(
            answer_region_id=region.id,
            requested_by_teacher_id=teacher.id,
            request_id=f"ocr-rescue-{region.id}-{uuid4().hex}",
            status="queued",
            profile=PROFILE,
            source_image_sha256=source_hash,
            queued_at=now,
            call_limit=max_calls,
            calls_used=0,
            provider="local_paddle_qwen",
            model_name=VL_MODEL,
            layout_model_name=LAYOUT_MODEL,
            warnings=[],
            normalized_result={
                "expected_models": [VL_MODEL, LAYOUT_MODEL, DET_MODEL, REC_MODEL],
                "mapping_id": mapping.id,
                "draft_only": True,
                "qwen_transcription_disabled": True,
            },
        )
        self.db.add(run)
        self.db.flush()
        self._audit(
            teacher.id,
            run,
            "answer_region_ocr_rescue_requested",
            {"mapping_id": mapping.id, "call_limit": max_calls, "source_image_sha256": source_hash},
        )
        self.db.commit()
        return self.get_run(run.id)

    def run_queued(self, run_id: int) -> None:
        run = self.get_run(run_id)
        if run.status != "queued":
            return
        try:
            self._execute(run)
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(AnswerRegionOcrRun, run_id)
            if failed and failed.status in {"queued", "running"}:
                failed.status = "failed"
                failed.error = self._safe_error(exc)
                failed.completed_at = datetime.now(UTC)
                self._audit(
                    failed.requested_by_teacher_id,
                    failed,
                    "answer_region_ocr_rescue_failed",
                    {"calls_used": failed.calls_used},
                )
                self.db.commit()

    def _execute(self, run: AnswerRegionOcrRun) -> None:
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.heartbeat_at = run.started_at
        self.db.commit()
        region = self._load_region(run.answer_region_id)
        if _sha256(self._source_image_bytes(region)) != run.source_image_sha256:
            raise RuntimeError("OCR source image changed before execution")
        self.phase_manager.switch("OcrGpu")
        client = self.client or LocalOcrClient.from_settings(self.settings)
        health = client.health()
        self._verify_health(health)

        source = self._preprocess(self._source_image_bytes(region), alternate=False)
        pp_result = self._call(
            run,
            client,
            source,
            engine="ppocr_v6",
            prompt_label="ocr",
            suffix="detect",
            profile=PROFILE,
        )
        answer_blocks = [
            block
            for block in pp_result.blocks
            if block.bbox and not _looks_like_answer_header(block.text)
        ]
        band_boxes = group_ocr_blocks_into_bands(
            [block.model_dump() for block in answer_blocks],
            max_bands=min(self.settings.local_ocr_max_bands, max(1, run.call_limit - 1)),
        )
        if not band_boxes:
            raise RuntimeError("PP-OCRv6 found no reviewable answer bands")

        with Image.open(io.BytesIO(source)) as source_image:
            source_image = source_image.convert("RGB")
            lowest_math: tuple[float, AnswerRegionOcrBand, bytes] | None = None
            for order, box in enumerate(band_boxes, start=1):
                box = [
                    max(0.0, box[0]),
                    max(0.0, box[1]),
                    min(float(source_image.width), box[2]),
                    min(float(source_image.height), box[3]),
                ]
                crop = source_image.crop(tuple(int(round(value)) for value in box))
                crop_bytes = self._prepare_band(crop, alternate=False)
                selected_blocks = [
                    block
                    for block in answer_blocks
                    if block.bbox and _box_center_inside(block.bbox, box)
                ]
                pp_text = _pp_geometry_candidate(selected_blocks)
                compact_numeric = bool(re.search(r"\d", pp_text)) and len(pp_text.split()) <= 5
                classification = (
                    "formula" if MATH_PATTERN.search(pp_text) or compact_numeric else "text"
                )
                stored = self.storage.ocr_rescue_band_image_path(run.id, order)
                stored.absolute_path.write_bytes(crop_bytes)
                band = AnswerRegionOcrBand(
                    ocr_run_id=run.id,
                    order_index=order,
                    x=Decimal(str(box[0])),
                    y=Decimal(str(box[1])),
                    width=Decimal(str(box[2] - box[0])),
                    height=Decimal(str(box[3] - box[1])),
                    image_path=stored.relative_path,
                    image_sha256=_sha256(crop_bytes),
                    classification=classification,
                )
                self.db.add(band)
                self.db.flush()
                scores = [
                    block.confidence
                    for block in selected_blocks
                    if block.bbox
                    and block.confidence is not None
                    and _box_center_inside(block.bbox, box)
                ]
                pp_confidence = sum(scores) / len(scores) if scores else None
                self._candidate(
                    band,
                    engine="ppocr_v6",
                    model=REC_MODEL,
                    prompt="ocr",
                    preprocessing=PROFILE,
                    text=pp_text,
                    confidence=pp_confidence,
                    warnings=pp_result.warnings,
                    latency=pp_result.latency_ms,
                )
                vl_result = self._call(
                    run,
                    client,
                    crop_bytes,
                    engine="paddleocr_vl",
                    prompt_label="formula" if classification == "formula" else "ocr",
                    suffix=f"band-{order}",
                    profile=PROFILE,
                )
                self._candidate(
                    band,
                    engine="paddleocr_vl",
                    model=VL_MODEL,
                    prompt="formula" if classification == "formula" else "ocr",
                    preprocessing=PROFILE,
                    text=vl_result.normalized_text,
                    confidence=None,
                    warnings=vl_result.warnings,
                    latency=vl_result.latency_ms,
                )
                confidence_key = pp_confidence if pp_confidence is not None else 0.0
                if classification == "formula" and (
                    lowest_math is None or confidence_key < lowest_math[0]
                ):
                    lowest_math = (confidence_key, band, crop_bytes)
                self.db.commit()

        if lowest_math is not None and run.calls_used < run.call_limit:
            _score, band, original_crop = lowest_math
            with Image.open(io.BytesIO(original_crop)) as crop_image:
                alternate = self._prepare_band(crop_image, alternate=True)
            alternate_result = self._call(
                run,
                client,
                alternate,
                engine="paddleocr_vl",
                prompt_label="formula",
                suffix=f"band-{band.order_index}-alternate",
                profile="rescue_alternate",
            )
            self._candidate(
                band,
                engine="paddleocr_vl",
                model=VL_MODEL,
                prompt="formula",
                preprocessing="rescue_alternate",
                text=alternate_result.normalized_text,
                confidence=None,
                warnings=alternate_result.warnings,
                latency=alternate_result.latency_ms,
            )

        self.db.flush()
        hashes = [
            candidate.text_sha256
            for band in self.get_run(run.id).bands
            for candidate in band.candidates
        ]
        run.candidate_set_sha256 = _sha256("\n".join(hashes).encode())
        run.status = "succeeded"
        run.completed_at = datetime.now(UTC)
        run.heartbeat_at = run.completed_at
        run.error = None
        self._audit(
            run.requested_by_teacher_id,
            run,
            "answer_region_ocr_rescue_completed",
            {
                "band_count": len(run.bands),
                "candidate_count": len(hashes),
                "calls_used": run.calls_used,
            },
        )
        self.db.commit()

    def confirm_candidates(
        self,
        *,
        region: AnswerRegion,
        run: AnswerRegionOcrRun,
        teacher: User,
        candidate_ids: list[int],
    ) -> AnswerRegionOcrRun:
        run = self.get_run(run.id)
        if run.answer_region_id != region.id or run.requested_by_teacher_id != teacher.id:
            raise HTTPException(status_code=404, detail="OCR rescue run not found")
        if run.profile != PROFILE or run.status != "succeeded":
            raise HTTPException(
                status_code=409, detail="OCR candidates are not ready for confirmation"
            )
        if len(candidate_ids) != len(set(candidate_ids)) or len(candidate_ids) != len(run.bands):
            raise HTTPException(
                status_code=422, detail="Select exactly one candidate from every band"
            )
        selected: dict[int, AnswerRegionOcrCandidate] = {}
        candidates = list(
            self.db.scalars(
                select(AnswerRegionOcrCandidate)
                .where(AnswerRegionOcrCandidate.id.in_(candidate_ids))
                .options(selectinload(AnswerRegionOcrCandidate.band))
            ).all()
        )
        for candidate in candidates:
            if candidate.band.ocr_run_id != run.id or candidate.band_id in selected:
                raise HTTPException(status_code=422, detail="OCR candidate selection is invalid")
            if _sha256(candidate.text.encode()) != candidate.text_sha256:
                raise HTTPException(status_code=409, detail="OCR candidate integrity check failed")
            selected[candidate.band_id] = candidate
        if len(selected) != len(run.bands):
            raise HTTPException(
                status_code=422, detail="Select exactly one candidate from every band"
            )
        if _sha256(self._source_image_bytes(region)) != run.source_image_sha256:
            raise HTTPException(status_code=409, detail="Answer image changed after OCR rescue")
        mapping = self._mapping_for_region(region.id)
        if mapping is None or mapping.id != (run.normalized_result or {}).get("mapping_id"):
            raise HTTPException(status_code=409, detail="Answer mapping changed after OCR rescue")
        if self.db.scalar(select(GradingJob.id).where(GradingJob.answer_region_id == region.id)):
            raise HTTPException(status_code=409, detail="Grading already exists for this answer")
        ordered = [selected[band.id].text.strip() for band in run.bands]
        transcript = "\n".join(text for text in ordered if text)
        now = datetime.now(UTC)
        region.manual_answer_text = transcript
        region.full_answer_confirmed = False
        region.evidence_status = "unconfirmed"
        mapping.teacher_confirmed = True
        mapping.mapping_status = "teacher_confirmed"
        mapping.blocker_reason = None
        for segment in region.segments:
            segment.confirmed = True
        run.confirmed_text = transcript
        run.confirmed_by_teacher_id = teacher.id
        run.confirmed_at = now
        run.status = "confirmed"
        self._audit(
            teacher.id,
            run,
            "answer_region_ocr_candidates_confirmed",
            {
                "mapping_id": mapping.id,
                "candidate_ids": candidate_ids,
                "confirmed_text_sha256": _sha256(transcript.encode()),
                "full_answer_confirmed": False,
            },
        )
        self.db.commit()
        return self.get_run(run.id)

    def reject(
        self, *, region: AnswerRegion, run: AnswerRegionOcrRun, teacher: User, reasons: list[str]
    ) -> tuple[AnswerRegionOcrRun, int, str]:
        if run.answer_region_id != region.id or run.requested_by_teacher_id != teacher.id:
            raise HTTPException(status_code=404, detail="OCR rescue run not found")
        if run.profile != PROFILE or run.status not in {"succeeded", "uncertain"}:
            raise HTTPException(status_code=409, detail="OCR rescue run cannot be rejected")
        mapping = self._mapping_for_region(region.id)
        if mapping is None:
            raise HTTPException(status_code=409, detail="Answer mapping is unavailable")
        run.status = "rejected"
        run.rejected_by_teacher_id = teacher.id
        run.rejection_reason_codes = list(dict.fromkeys(reasons))
        run.rejected_at = datetime.now(UTC)
        mapping.mapping_status = "blocked"
        mapping.teacher_confirmed = False
        mapping.blocker_reason = "Enhanced OCR candidates were rejected"
        reference = f"OCR-RUN-{run.id}-MAP-{mapping.id}-SRC-{(run.source_image_sha256 or '')[:12]}"
        self._audit(
            teacher.id,
            run,
            "answer_region_ocr_rescue_rejected",
            {
                "mapping_id": mapping.id,
                "reason_codes": run.rejection_reason_codes,
                "diagnostic_reference": reference,
            },
        )
        self.db.commit()
        return self.get_run(run.id), mapping.id, reference

    def get_run(self, run_id: int) -> AnswerRegionOcrRun:
        run = self.db.scalar(
            select(AnswerRegionOcrRun)
            .where(AnswerRegionOcrRun.id == run_id)
            .options(
                selectinload(AnswerRegionOcrRun.bands).selectinload(AnswerRegionOcrBand.candidates)
            )
        )
        if run is None:
            raise HTTPException(status_code=404, detail="Answer region OCR run not found")
        if (
            run.profile == PROFILE
            and run.status == "running"
            and run.heartbeat_at
            and run.heartbeat_at < datetime.now(UTC) - timedelta(minutes=10)
        ):
            run.status = "uncertain"
            run.completed_at = datetime.now(UTC)
            run.error = "OCR worker heartbeat expired; this run will not be retried automatically"
            self.db.commit()
        return run

    def _call(
        self,
        run: AnswerRegionOcrRun,
        client: LocalOcrClient,
        image_bytes: bytes,
        *,
        engine: str,
        prompt_label: str,
        suffix: str,
        profile: str,
    ) -> LocalOcrResult:
        if run.calls_used >= run.call_limit:
            raise RuntimeError("OCR rescue call limit reached")
        run.calls_used += 1
        run.heartbeat_at = datetime.now(UTC)
        self.db.commit()
        return client.ocr_image(
            image_bytes=image_bytes,
            content_type="image/png",
            request_id=f"{run.request_id}-{suffix}",
            mode="answer_region",
            prompt_label=prompt_label,
            engine=engine,
            preprocessing_profile=profile,
        )

    def _candidate(
        self,
        band: AnswerRegionOcrBand,
        *,
        engine: str,
        model: str,
        prompt: str,
        preprocessing: str,
        text: str,
        confidence: float | None,
        warnings: list[str],
        latency: int,
    ) -> None:
        normalized = text.strip()
        self.db.add(
            AnswerRegionOcrCandidate(
                band_id=band.id,
                engine=engine,
                model_name=model,
                prompt_label=prompt,
                preprocessing_profile=preprocessing,
                text=normalized,
                text_sha256=_sha256(normalized.encode()),
                confidence=Decimal(str(confidence)) if confidence is not None else None,
                warnings=warnings,
                latency_ms=latency,
            )
        )

    def _load_region(self, region_id: int) -> AnswerRegion:
        region = self.db.scalar(
            select(AnswerRegion)
            .where(AnswerRegion.id == region_id)
            .options(selectinload(AnswerRegion.segments))
        )
        if region is None:
            raise RuntimeError("Answer region no longer exists")
        return region

    def _mapping_for_region(self, region_id: int) -> AnswerRegionMapping | None:
        return self.db.scalar(
            select(AnswerRegionMapping).where(AnswerRegionMapping.answer_region_id == region_id)
        )

    def _source_image_bytes(self, region: AnswerRegion) -> bytes:
        paths = [
            segment.image_path
            for segment in sorted(region.segments, key=lambda item: item.order_index)
        ]
        if not paths:
            paths = [region.image_path]
        images: list[Image.Image] = []
        try:
            for relative in paths:
                path = self.storage.resolve_relative(relative)
                images.append(Image.open(path).convert("RGB"))
            if len(images) == 1:
                output = io.BytesIO()
                images[0].save(output, format="PNG")
                return output.getvalue()
            width = max(image.width for image in images)
            height = sum(image.height for image in images) + 8 * (len(images) - 1)
            combined = Image.new("RGB", (width, height), "white")
            y = 0
            for image in images:
                combined.paste(image, (0, y))
                y += image.height + 8
            output = io.BytesIO()
            combined.save(output, format="PNG")
            return output.getvalue()
        finally:
            for image in images:
                image.close()

    def _preprocess(self, image_bytes: bytes, *, alternate: bool) -> bytes:
        with Image.open(io.BytesIO(image_bytes)) as image:
            rgb = image.convert("RGB")
            red, green, blue = rgb.split()
            red_over_green = ImageChops.subtract(red, green).point(
                lambda value: 255 if value >= 35 else 0
            )
            red_over_blue = ImageChops.subtract(red, blue).point(
                lambda value: 255 if value >= 35 else 0
            )
            red_mask = ImageChops.multiply(red_over_green, red_over_blue).filter(
                ImageFilter.MaxFilter(3)
            )
            cleaned = Image.composite(Image.new("RGB", rgb.size, "white"), rgb, red_mask)
            gray = ImageOps.grayscale(cleaned)
            gray = ImageOps.autocontrast(gray, cutoff=1 if alternate else 0)
            gray = ImageEnhance.Contrast(gray).enhance(1.35 if alternate else 1.12)
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1.0, percent=125, threshold=2))
            if gray.width < 1600:
                scale = 1600 / gray.width
                gray = gray.resize(
                    (1600, max(1, int(gray.height * scale))), Image.Resampling.LANCZOS
                )
            output = io.BytesIO()
            gray.save(output, format="PNG")
            return output.getvalue()

    def _prepare_band(self, image: Image.Image, *, alternate: bool) -> bytes:
        output = io.BytesIO()
        base = ImageOps.grayscale(image)
        base = ImageOps.autocontrast(base, cutoff=1 if alternate else 0)
        base = ImageEnhance.Contrast(base).enhance(1.35 if alternate else 1.12)
        base = base.filter(ImageFilter.UnsharpMask(radius=0.8, percent=110, threshold=1))
        if base.width < 1400:
            scale = 1400 / base.width
            base = base.resize((1400, max(1, int(base.height * scale))), Image.Resampling.LANCZOS)
        base.save(output, format="PNG")
        return output.getvalue()

    def _verify_health(self, health: dict[str, Any]) -> None:
        models = health.get("models")
        expected = {
            "paddleocr_vl": {"model": VL_MODEL, "layout_model": LAYOUT_MODEL},
            "ppocr_v6": {"model": REC_MODEL, "layout_model": DET_MODEL},
        }
        if health.get("device") != "gpu:0" or models != expected:
            raise RuntimeError(
                "Local OCR service model/device identity does not match rescue policy"
            )

    def _audit(
        self, actor_id: int, run: AnswerRegionOcrRun, event: str, payload: dict[str, Any]
    ) -> None:
        self.db.add(
            AuditLog(
                actor_type="teacher"
                if event.endswith(("requested", "confirmed", "rejected"))
                else "worker",
                actor_id=actor_id,
                event_type=event,
                entity_type="answer_region_ocr_run",
                entity_id=run.id,
                payload_json=payload,
            )
        )

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc) or "Local OCR rescue failed"
        for root in (
            str(self.storage.root),
            str(self.storage.artifacts_dir),
            str(self.storage.uploads_dir),
        ):
            message = message.replace(root, "[LOCAL_PATH_REDACTED]")
        return message[:1000]


def group_ocr_blocks_into_bands(
    blocks: list[dict[str, Any]], *, max_bands: int = 6
) -> list[list[float]]:
    boxes = [
        [float(value) for value in block["bbox"]]
        for block in blocks
        if isinstance(block.get("bbox"), list) and len(block["bbox"]) == 4
    ]
    boxes.sort(key=lambda box: (box[1], box[0], box[3], box[2]))
    groups: list[list[list[float]]] = []
    for box in boxes:
        height = max(1.0, box[3] - box[1])
        matched: list[list[float]] | None = None
        for group in groups:
            top = min(item[1] for item in group)
            bottom = max(item[3] for item in group)
            group_height = max(1.0, bottom - top)
            overlap = max(0.0, min(bottom, box[3]) - max(top, box[1]))
            vertical_gap = max(0.0, max(top, box[1]) - min(bottom, box[3]))
            group_left = min(item[0] for item in group)
            group_right = max(item[2] for item in group)
            group_width = max(1.0, group_right - group_left)
            box_width = max(1.0, box[2] - box[0])
            horizontal_overlap = max(
                0.0,
                min(group_right, box[2]) - max(group_left, box[0]),
            )
            aligned_overlap = horizontal_overlap / min(group_width, box_width)
            contains_thin_bar = any(
                (item[3] - item[1]) <= max(5.0, (item[2] - item[0]) * 0.12) for item in group
            ) or height <= max(5.0, box_width * 0.12)
            compact_components = group_width / group_height <= 4.0 and box_width / height <= 4.0
            centers_aligned = (
                abs((group_left + group_right) / 2 - (box[0] + box[2]) / 2)
                <= max(group_width, box_width) * 0.35
            )
            fraction_like = (
                aligned_overlap >= 0.5
                and centers_aligned
                and vertical_gap <= max(group_height, height) * 0.55
                and (contains_thin_bar or compact_components)
            )
            same_line = overlap >= min(group_height, height) * 0.25
            if same_line or fraction_like:
                matched = group
                break
        if matched is None:
            groups.append([box])
        else:
            matched.append(box)
    groups.sort(key=lambda group: (min(box[1] for box in group), min(box[0] for box in group)))
    while len(groups) > max_bands:
        gaps = [
            min(box[1] for box in groups[index + 1]) - max(box[3] for box in groups[index])
            for index in range(len(groups) - 1)
        ]
        merge_at = min(range(len(gaps)), key=lambda index: (gaps[index], index))
        groups[merge_at] = groups[merge_at] + groups.pop(merge_at + 1)
    raw_extents = [
        [
            min(box[0] for box in group),
            min(box[1] for box in group),
            max(box[2] for box in group),
            max(box[3] for box in group),
        ]
        for group in groups
    ]
    result: list[list[float]] = []
    for index, (raw_left, raw_top, raw_right, raw_bottom) in enumerate(raw_extents):
        group_width = max(1.0, raw_right - raw_left)
        group_height = max(1.0, raw_bottom - raw_top)
        # Detection boxes often omit a faint fraction numerator, complement
        # bar, or enclosing circle. Geometry-derived padding keeps those
        # source pixels available without inventing any textual candidate.
        horizontal_padding = max(30.0, group_width * 0.12)
        vertical_padding = max(20.0, group_height * 0.40)
        left = max(0.0, raw_left - horizontal_padding)
        top = max(0.0, raw_top - vertical_padding)
        right = raw_right + horizontal_padding
        bottom = raw_bottom + vertical_padding
        if index > 0:
            previous_bottom = raw_extents[index - 1][3]
            top = max(top, (previous_bottom + raw_top) / 2)
        if index + 1 < len(raw_extents):
            next_top = raw_extents[index + 1][1]
            bottom = min(bottom, (raw_bottom + next_top) / 2)
        result.append([left, top, right, bottom])
    return result


def _box_center_inside(box: list[float], band: list[float]) -> bool:
    center_x = (box[0] + box[2]) / 2
    center_y = (box[1] + box[3]) / 2
    return band[0] <= center_x <= band[2] and band[1] <= center_y <= band[3]


def _looks_like_answer_header(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "").lower()
    if re.match(r"^(answer|amwer|anw)[a-z]*(:|no|number)", compact):
        return True
    if re.fullmatch(r"0?\d{1,2}[\[(]?[a-z@][\])]?[.:_-]*", compact):
        return True
    return len(compact) <= 8 and bool(re.fullmatch(r"0?\d{1,2}[\[(][^=+/]{1,3}[\])]", compact))


def _pp_geometry_candidate(blocks: list[Any]) -> str:
    ordered = sorted(
        (block for block in blocks if block.bbox),
        key=lambda block: (block.bbox[1], block.bbox[0]),
    )
    if len(ordered) == 2:
        top, bottom = ordered
        top_box = top.bbox
        bottom_box = bottom.bbox
        top_width = max(1.0, top_box[2] - top_box[0])
        bottom_width = max(1.0, bottom_box[2] - bottom_box[0])
        overlap = max(0.0, min(top_box[2], bottom_box[2]) - max(top_box[0], bottom_box[0]))
        centers_close = (
            abs((top_box[0] + top_box[2]) / 2 - (bottom_box[0] + bottom_box[2]) / 2)
            <= max(top_width, bottom_width) * 0.35
        )
        top_center_y = (top_box[1] + top_box[3]) / 2
        bottom_center_y = (bottom_box[1] + bottom_box[3]) / 2
        vertically_stacked = (
            bottom_center_y - top_center_y
            >= min(top_box[3] - top_box[1], bottom_box[3] - bottom_box[1]) * 0.25
        )
        short_glyphs = all(len(block.text.strip()) <= 4 for block in ordered)
        if (
            overlap / min(top_width, bottom_width) >= 0.35
            and centers_close
            and vertically_stacked
            and short_glyphs
        ):
            return rf"$\frac{{{top.text.strip()}}}{{{bottom.text.strip()}}}$"
    return " ".join(block.text.strip() for block in ordered if block.text.strip()).strip()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
