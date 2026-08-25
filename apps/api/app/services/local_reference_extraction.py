from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from app.core.config import Settings, get_settings

# The provider recorded on reference extraction runs. Named for its role rather
# than an engine: it previously read "PADDLE_QWEN" while holding the Qwen3.8
# value, which invites picking the wrong provider when more than one exists.
LOCAL_REFERENCE_PROVIDER = "llama_cpp_qwen38"
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}

# 300 DPI clears the 146-320 DPI range of the reference scans seen in practice,
# so rendering no longer discards detail the source actually carries.
DEFAULT_RENDER_DPI = 300
# Bounds memory on unusually large pages; 4000px still exceeds A4 at 300 DPI.
MAX_RENDER_SIDE_PX = 4000


class LocalReferenceExtractionError(RuntimeError):
    pass


class LocalReferenceExtractor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()

    def extract_questions(self, file_path: Path, content_type: str) -> dict[str, Any]:
        del file_path, content_type
        raise LocalReferenceExtractionError(
            "Legacy single-document extraction is disabled; use the supervised hybrid bundle"
        )

    def extract_rubric(self, file_path: Path, content_type: str) -> dict[str, Any]:
        del file_path, content_type
        raise LocalReferenceExtractionError(
            "Legacy single-document extraction is disabled; use the supervised hybrid bundle"
        )

    def extract_reference_bundle(
        self, documents: dict[str, list[tuple[bytes, str, int]]]
    ) -> dict[str, Any]:
        del documents
        raise LocalReferenceExtractionError(
            "Direct Qwen3.8 reference extraction is retired; use PaddleOCR then Qwen3.6"
        )

    def ocr_pages(self, *args, **kwargs):
        raise LocalReferenceExtractionError(
            "Direct legacy OCR is disabled; use the leased PaddleOCR reference workflow"
        )

    def render_pages(
        self,
        file_path: Path,
        content_type: str,
        *,
        target_dpi: int = DEFAULT_RENDER_DPI,
        max_side_px: int = MAX_RENDER_SIDE_PX,
    ) -> list[tuple[int, bytes, str]]:
        """Render each page, preserving the source scan's detail.

        The previous fixed ``fitz.Matrix(2, 2)`` renders at 144 DPI regardless
        of the source. Measured against the real reference bundle that
        *downsamples* the scans it is given: the handwritten rubric loses ~47%
        of its linear resolution and the typeset solution ~55%, which is
        exactly the material that is hardest to read.

        It matters more for classical OCR than for a vision model, whose page
        input is capped at a fixed token count either way: PP-OCR normalizes
        every line crop to a fixed height, so halving the line height doubles
        the upsampling blur, degrading both the text and the confidence score
        the escalation gate depends on.
        """
        if target_dpi <= 0:
            raise LocalReferenceExtractionError("Reference render DPI must be positive")
        if content_type == "application/pdf":
            try:
                with fitz.open(file_path) as document:
                    rendered: list[tuple[int, bytes, str]] = []
                    for page_index, page in enumerate(document, start=1):
                        zoom = target_dpi / 72.0
                        longest_side = max(page.rect.width, page.rect.height) * zoom
                        if longest_side > max_side_px:
                            # Bound memory on unusually large pages rather than
                            # rendering something that cannot be held.
                            zoom *= max_side_px / longest_side
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                        rendered.append((page_index, pixmap.tobytes("png"), "image/png"))
                    return rendered
            except LocalReferenceExtractionError:
                raise
            except Exception as exc:
                raise LocalReferenceExtractionError(
                    "Reference PDF could not be rendered locally"
                ) from exc
        if content_type in _IMAGE_CONTENT_TYPES:
            try:
                return [(1, file_path.read_bytes(), content_type)]
            except OSError as exc:
                raise LocalReferenceExtractionError(
                    "Reference image could not be read locally"
                ) from exc
        raise LocalReferenceExtractionError(
            "local Qwen3.8 supports PDF, PNG, and JPEG reference files"
        )
