"""Tier-1 OCR via RapidOCR (PP-OCRv6 ONNX, CPU).

CPU-only and deliberately so. It needs no VRAM, so it runs while a model is
resident and costs no phase switch; and it avoids the CUDA path entirely, which
is where the previous PaddleOCR integration hit Blackwell-specific numerical
bugs on this exact card.

Imported lazily: the package is optional, and a missing install must surface as
a clear configuration error rather than breaking application startup.
"""

from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from typing import Any

from packages.ocr.coverage import measure_uncovered_ink
from packages.ocr.types import BoundingBox, OcrLine, OcrPageReading

ENGINE_NAME = "rapidocr"


class OcrEngineUnavailableError(RuntimeError):
    """The tier-1 engine is not installed or cannot start."""


def _sequence_or_empty(value: Any) -> list[Any]:
    """Coerce an optional result field to a list.

    Not ``value or []``: RapidOCR returns numpy arrays, whose truthiness raises
    rather than being falsy when empty.
    """
    if value is None:
        return []
    return list(value)


def _bbox_from_points(points: Any) -> BoundingBox | None:
    try:
        coordinates = [(float(point[0]), float(point[1])) for point in points]
    except (TypeError, ValueError, IndexError):
        return None
    if not coordinates:
        return None
    xs = [item[0] for item in coordinates]
    ys = [item[1] for item in coordinates]
    return BoundingBox(x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys))


def uncovered_ink_ratio(image_bytes: bytes, boxes: list[BoundingBox]) -> Decimal | None:
    """Fraction of dark pixels lying outside every detected box."""
    coverage = measure_uncovered_ink(image_bytes, [box.as_tuple() for box in boxes])
    return None if coverage is None else coverage.ratio


class RapidOcrEngine:
    """Reads a rendered page and reports per-line text, geometry and confidence."""

    def __init__(self, *, compute_uncovered_ink: bool = True) -> None:
        self._engine: Any | None = None
        self.compute_uncovered_ink = compute_uncovered_ink

    def _instance(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr import RapidOCR  # noqa: PLC0415
            except ImportError as exc:
                raise OcrEngineUnavailableError(
                    "The tier-1 OCR engine is not installed. Install 'rapidocr' and "
                    "'onnxruntime' in the application environment, or disable local OCR."
                ) from exc
            try:
                self._engine = RapidOCR()
            except Exception as exc:
                raise OcrEngineUnavailableError(
                    f"The tier-1 OCR engine could not start: {exc}"
                ) from exc
        return self._engine

    def read_page(
        self,
        image_bytes: bytes,
        *,
        render_dpi: int,
        page_width: int,
        page_height: int,
    ) -> OcrPageReading:
        engine = self._instance()
        start = time.perf_counter()
        try:
            # RapidOCR takes raw bytes; a PIL Image raises.
            result = engine(image_bytes)
        except Exception as exc:
            raise OcrEngineUnavailableError(f"Tier-1 OCR failed to read a page: {exc}") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        texts = _sequence_or_empty(getattr(result, "txts", None))
        scores = _sequence_or_empty(getattr(result, "scores", None))
        boxes = _sequence_or_empty(getattr(result, "boxes", None))

        lines: list[OcrLine] = []
        for index, text in enumerate(texts):
            score = scores[index] if index < len(scores) else None
            box = boxes[index] if index < len(boxes) else None
            lines.append(
                OcrLine(
                    text=str(text),
                    confidence=(
                        Decimal(str(round(float(score), 6))) if score is not None else None
                    ),
                    bbox=_bbox_from_points(box) if box is not None else None,
                )
            )

        ink_ratio = None
        if self.compute_uncovered_ink:
            ink_ratio = uncovered_ink_ratio(
                image_bytes, [line.bbox for line in lines if line.bbox is not None]
            )

        return OcrPageReading(
            engine=ENGINE_NAME,
            lines=lines,
            render_dpi=render_dpi,
            page_image_sha256=hashlib.sha256(image_bytes).hexdigest(),
            page_width=page_width,
            page_height=page_height,
            engine_version=_engine_version(),
            latency_ms=latency_ms,
            uncovered_ink_ratio=ink_ratio,
        )


def _engine_version() -> str | None:
    try:
        from importlib.metadata import version  # noqa: PLC0415

        return version("rapidocr")
    except Exception:
        return None
