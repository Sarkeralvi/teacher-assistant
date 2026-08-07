from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz
from PIL import Image, ImageOps

from app.core.config import Settings, get_settings
from app.services.local_ocr_client import LocalOcrClient
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

LOCAL_PADDLE_QWEN_PROVIDER = "local_paddle_qwen"
_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg"}


class LocalReferenceExtractionError(RuntimeError):
    pass


class LocalReferenceExtractor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        ocr_client: LocalOcrClient | None = None,
        qwen_adapter: BrainAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        try:
            self.ocr_client = ocr_client or LocalOcrClient.from_settings(self.settings)
            self._qwen_adapter = qwen_adapter
        except (BrainProviderConfigurationError, RuntimeError, ValueError) as exc:
            raise LocalReferenceExtractionError(str(exc)) from exc

    @property
    def qwen_adapter(self) -> BrainAdapter:
        if self._qwen_adapter is None:
            try:
                self._qwen_adapter = BrainAdapter.for_provider(
                    self.settings, "llama_cpp_qwen"
                )
            except (BrainProviderConfigurationError, RuntimeError, ValueError) as exc:
                raise LocalReferenceExtractionError(str(exc)) from exc
        if self._qwen_adapter.provider.provider_name != "llama_cpp_qwen":
            raise LocalReferenceExtractionError("Local Qwen provider is unavailable")
        return self._qwen_adapter

    def extract_questions(self, file_path: Path, content_type: str) -> dict[str, Any]:
        pages, ocr_warnings = self.ocr_pages(file_path, content_type)
        result = self.qwen_adapter.extract_questions_from_ocr_pages(pages)
        result["warnings"] = list(
            dict.fromkeys([*ocr_warnings, *list(result.get("warnings", []))])
        )
        return result

    def extract_rubric(self, file_path: Path, content_type: str) -> dict[str, Any]:
        pages, ocr_warnings = self.ocr_pages(file_path, content_type)
        result = self.qwen_adapter.extract_rubric_from_ocr_pages(pages)
        result["warnings"] = list(
            dict.fromkeys([*ocr_warnings, *list(result.get("warnings", []))])
        )
        return result

    def extract_reference_bundle(
        self, documents: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        try:
            return self.qwen_adapter.extract_reference_bundle_from_ocr_documents(documents)
        except (RuntimeError, ValueError, NotImplementedError) as exc:
            raise LocalReferenceExtractionError(str(exc)) from exc

    def ocr_pages(
        self,
        file_path: Path,
        content_type: str,
        *,
        on_call_started: Callable[[int], None] | None = None,
        supplemental_rubric_focus: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        rendered = self.render_pages(file_path, content_type)
        pages: list[dict[str, Any]] = []
        warnings: list[str] = []
        request_prefix = f"reference-{uuid4().hex}"
        for page_no, image_bytes, image_content_type in rendered:
            if on_call_started is not None:
                on_call_started(page_no)
            result = self.ocr_client.ocr_image(
                image_bytes=image_bytes,
                content_type=image_content_type,
                request_id=f"{request_prefix}-page-{page_no}",
                mode="document",
            )
            warnings.extend(f"page {page_no}: {warning}" for warning in result.warnings)
            normalized_text = result.normalized_text
            markdown = result.markdown
            blocks = [block.model_dump(mode="json") for block in result.blocks]
            latency_ms = result.latency_ms
            if supplemental_rubric_focus:
                # Handwritten rubrics are commonly sparse and affected by
                # reverse-side bleed-through.  Keep the full-page document OCR,
                # then add a high-contrast left-page reading that preserves the
                # row labels/marks for the text-only Qwen linker.
                focused_bytes = _prepare_rubric_focus_png(image_bytes)
                if on_call_started is not None:
                    on_call_started(page_no)
                focused = self.ocr_client.ocr_image(
                    image_bytes=focused_bytes,
                    content_type="image/png",
                    request_id=f"{request_prefix}-page-{page_no}-rubric-focus",
                    mode="answer_region",
                )
                warnings.extend(
                    f"page {page_no} rubric focus: {warning}"
                    for warning in focused.warnings
                )
                focused_text = focused.normalized_text.strip()
                if focused_text:
                    normalized_text = (
                        f"{normalized_text.strip()}\n\n"
                        "[RUBRIC HANDWRITING FOCUS]\n"
                        f"{focused_text}"
                    ).strip()
                    markdown = (
                        f"{markdown.strip()}\n\n"
                        "## Rubric handwriting focus\n\n"
                        f"{focused.markdown.strip()}"
                    ).strip()
                order_offset = max(
                    (int(block.get("order") or 0) for block in blocks), default=0
                )
                blocks.extend(
                    {
                        **block.model_dump(mode="json"),
                        "order": order_offset + index,
                        "label": f"rubric_focus_{block.label}",
                    }
                    for index, block in enumerate(focused.blocks, start=1)
                )
                latency_ms += focused.latency_ms
            pages.append(
                {
                    "page": page_no,
                    "text": normalized_text,
                    "markdown": markdown,
                    "blocks": blocks,
                    "device": result.device,
                    "model": result.model,
                    "layout_model": result.layout_model,
                    "latency_ms": latency_ms,
                }
            )
        if not any(str(page["text"]).strip() for page in pages):
            raise LocalReferenceExtractionError("Local OCR returned no reference text")
        return pages, list(dict.fromkeys(warnings))

    def render_pages(
        self, file_path: Path, content_type: str
    ) -> list[tuple[int, bytes, str]]:
        if content_type == "application/pdf":
            try:
                with fitz.open(file_path) as document:
                    return [
                        (
                            page_index,
                            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes(
                                "png"
                            ),
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
            "local_paddle_qwen supports PDF, PNG, and JPEG reference files"
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
    thresholded = contrasted.point(lambda value: 0 if value < 185 else 255).convert(
        "RGB"
    )
    output = io.BytesIO()
    thresholded.save(output, format="PNG")
    return output.getvalue()
