from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz

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
            pages.append(
                {
                    "page": page_no,
                    "text": result.normalized_text,
                    "markdown": result.markdown,
                    "blocks": [block.model_dump(mode="json") for block in result.blocks],
                    "device": result.device,
                    "model": result.model,
                    "layout_model": result.layout_model,
                    "latency_ms": result.latency_ms,
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
