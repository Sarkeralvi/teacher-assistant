from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageOps

from app.core.config import Settings, get_settings
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

LOCAL_PADDLE_QWEN_PROVIDER = "llama_cpp_qwen38"
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}


class LocalReferenceExtractionError(RuntimeError):
    pass


class LocalReferenceExtractor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        qwen_adapter: BrainAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        try:
            self._qwen_adapter = qwen_adapter
        except (BrainProviderConfigurationError, RuntimeError, ValueError) as exc:
            raise LocalReferenceExtractionError(str(exc)) from exc

    @property
    def qwen_adapter(self) -> BrainAdapter:
        if self._qwen_adapter is None:
            try:
                self._qwen_adapter = BrainAdapter.for_provider(self.settings, "llama_cpp_qwen38")
            except (BrainProviderConfigurationError, RuntimeError, ValueError) as exc:
                raise LocalReferenceExtractionError(str(exc)) from exc
        if self._qwen_adapter.provider.provider_name != "llama_cpp_qwen38":
            raise LocalReferenceExtractionError("Local Qwen3.8 provider is unavailable")
        return self._qwen_adapter

    def extract_questions(self, file_path: Path, content_type: str) -> dict[str, Any]:
        pages, ocr_warnings = self.ocr_pages(file_path, content_type)
        result = self.qwen_adapter.extract_questions_from_ocr_pages(pages)
        result["warnings"] = list(dict.fromkeys([*ocr_warnings, *list(result.get("warnings", []))]))
        return result

    def extract_rubric(self, file_path: Path, content_type: str) -> dict[str, Any]:
        pages, ocr_warnings = self.ocr_pages(file_path, content_type)
        result = self.qwen_adapter.extract_rubric_from_ocr_pages(pages)
        result["warnings"] = list(dict.fromkeys([*ocr_warnings, *list(result.get("warnings", []))]))
        return result

    def extract_reference_bundle(
        self, documents: dict[str, list[tuple[bytes, str, int]]]
    ) -> dict[str, Any]:
        try:
            provider = self.qwen_adapter.provider
            return provider.extract_reference_bundle_from_images(documents=documents)
        except (RuntimeError, ValueError, NotImplementedError) as exc:
            raise LocalReferenceExtractionError(str(exc)) from exc

    def ocr_pages(self, *args, **kwargs):
        raise LocalReferenceExtractionError(
            "PaddleOCR has been removed. Visual transcription will be provided by Qwen3.8."
        )

    def render_pages(self, file_path: Path, content_type: str) -> list[tuple[int, bytes, str]]:
        if content_type == "application/pdf":
            try:
                with fitz.open(file_path) as document:
                    return [
                        (
                            page_index,
                            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png"),
                            "image/png",
                        )
                        for page_index, page in enumerate(document, start=1)
                    ]
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


def _prepare_rubric_focus_png(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
    except Exception as exc:
        raise LocalReferenceExtractionError(
            "Rubric page could not be prepared for handwriting OCR"
        ) from exc
    # This is a supplemental view: the uncropped full-page OCR remains in the
    # Qwen context.  Most handwritten mark tables place labels and allocations
    # in the left two-thirds, while this crop removes unrelated reverse-side
    # writing that otherwise collapses rows into a single OCR line.
    image = image.crop((0, 0, max(1, int(image.width * 0.62)), image.height))
    contrasted = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
    thresholded = contrasted.point(lambda value: 0 if value < 185 else 255).convert("RGB")
    output = io.BytesIO()
    thresholded.save(output, format="PNG")
    return output.getvalue()
