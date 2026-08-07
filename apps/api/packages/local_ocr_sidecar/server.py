from __future__ import annotations

import argparse
import hmac
import io
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
ALLOWED_MODES = {"document", "answer_region"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _configure_cpu_only_environment() -> None:
    # The installed Paddle wheel includes CUDA support. Hiding CUDA before the
    # first Paddle import prevents a nominal ``device=cpu`` pipeline from still
    # creating a CUDA context and competing with llama.cpp for VRAM.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"


class OcrEngine(Protocol):
    model_name: str
    layout_model_name: str
    version: str
    device: str

    def predict(self, image_path: Path, mode: str) -> list[Any]: ...


@dataclass(frozen=True)
class SidecarConfig:
    api_key: str
    vl_model_path: Path
    layout_model_path: Path
    host: str = "127.0.0.1"
    port: int = 8090
    max_image_bytes: int = 20 * 1024 * 1024
    device: str = "cpu"

    @classmethod
    def from_environment(cls) -> SidecarConfig:
        api_key = os.environ.get("LOCAL_OCR_API_KEY", "")
        vl_path = os.environ.get("LOCAL_OCR_VL_MODEL_PATH", "")
        layout_path = os.environ.get("LOCAL_OCR_LAYOUT_MODEL_PATH", "")
        if not api_key:
            raise RuntimeError("LOCAL_OCR_API_KEY is required")
        if not vl_path or not layout_path:
            raise RuntimeError(
                "LOCAL_OCR_VL_MODEL_PATH and LOCAL_OCR_LAYOUT_MODEL_PATH are required"
            )
        host = os.environ.get("LOCAL_OCR_HOST", "127.0.0.1")
        if host not in LOOPBACK_HOSTS:
            raise RuntimeError("The OCR sidecar may bind only to a loopback host")
        device = os.environ.get("LOCAL_OCR_DEVICE", "cpu").strip().lower()
        if device not in {"cpu", "gpu:0"}:
            raise RuntimeError("LOCAL_OCR_DEVICE must be cpu or gpu:0")
        return cls(
            api_key=api_key,
            vl_model_path=Path(vl_path),
            layout_model_path=Path(layout_path),
            host=host,
            port=int(os.environ.get("LOCAL_OCR_PORT", "8090")),
            max_image_bytes=int(
                os.environ.get("LOCAL_OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024))
            ),
            device=device,
        )


class PaddleOcrVlEngine:
    model_name = "PaddleOCR-VL-1.6"
    layout_model_name = "PP-DocLayoutV3"
    version = "3.7.0"
    def __init__(
        self, *, vl_model_path: Path, layout_model_path: Path, device: str = "cpu"
    ) -> None:
        self._assert_local_model(vl_model_path, "model.safetensors")
        self._assert_local_model(layout_model_path, "inference.pdiparams")
        if device not in {"cpu", "gpu:0"}:
            raise RuntimeError("OCR device must be cpu or gpu:0")
        self.device = device
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        if device == "cpu":
            _configure_cpu_only_environment()
        import paddle
        from paddlex.utils import env as paddlex_environment

        paddle.set_device(device)
        if paddle.device.get_device() != device:
            raise RuntimeError(f"PaddleOCR failed to initialize on {device}")

        if device == "cpu":
            def cpu_compute_capability() -> None:
                return None

            # PaddleX 3.7.2 checks whether the wheel was compiled with CUDA instead
            # of whether this pipeline selected CUDA, then probes a hidden device.
            # Returning no capability disables only its optional GPU SDPA path.
            paddlex_environment.get_gpu_compute_capability = cpu_compute_capability
        from paddleocr import PaddleOCRVL

        self.pipeline = PaddleOCRVL(
            pipeline_version="v1.6",
            vl_rec_model_dir=str(vl_model_path.resolve()),
            layout_detection_model_dir=str(layout_model_path.resolve()),
            device=device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=True,
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
            use_queues=False,
        )

    def predict(self, image_path: Path, mode: str) -> list[Any]:
        return self.pipeline.predict(
            str(image_path),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=mode == "document",
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
            use_queues=False,
            temperature=0.0,
        )

    def _assert_local_model(self, directory: Path, required_file: str) -> None:
        if not directory.is_dir() or not (directory / required_file).is_file():
            raise RuntimeError(f"Configured local OCR model is incomplete: {directory.name}")


class OcrBusyError(RuntimeError):
    pass


class OcrService:
    def __init__(self, engine: OcrEngine, *, max_image_bytes: int) -> None:
        self.engine = engine
        self.max_image_bytes = max_image_bytes
        self._slot = threading.BoundedSemaphore(value=1)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "provider": "local_paddle_qwen",
            "model": self.engine.model_name,
            "layout_model": self.engine.layout_model_name,
            "version": self.engine.version,
            "device": self.engine.device,
            "max_concurrency": 1,
            "offline": True,
        }

    def run(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        request_id: str,
        mode: str,
    ) -> dict[str, Any]:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Only PNG and JPEG image bytes are accepted")
        if mode not in ALLOWED_MODES:
            raise ValueError("OCR mode must be document or answer_region")
        if not request_id.strip() or len(request_id) > 128:
            raise ValueError("A request ID of at most 128 characters is required")
        if not image_bytes:
            raise ValueError("Image body is empty")
        if len(image_bytes) > self.max_image_bytes:
            raise OverflowError("Image exceeds the configured size limit")
        _verify_image(image_bytes, content_type)
        if not self._slot.acquire(blocking=False):
            raise OcrBusyError("The OCR sidecar is busy")
        started = time.perf_counter()
        suffix = ALLOWED_CONTENT_TYPES[content_type]
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(image_bytes)
                image_path = Path(temporary.name)
            try:
                raw_results = self.engine.predict(image_path, mode)
            finally:
                image_path.unlink(missing_ok=True)
            normalized = normalize_paddle_results(raw_results)
            return {
                "request_id": request_id,
                "mode": mode,
                **normalized,
                "warnings": normalized.get("warnings", []),
                "provider": "local_paddle_qwen",
                "model": self.engine.model_name,
                "layout_model": self.engine.layout_model_name,
                "version": self.engine.version,
                "device": self.engine.device,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        finally:
            self._slot.release()


def normalize_paddle_results(results: list[Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    markdown_pages: list[str] = []
    warnings: list[str] = []
    for page_index, result in enumerate(results, start=1):
        payload = _result_payload(result, "json")
        markdown_payload = _result_payload(result, "markdown")
        markdown = _markdown_text(markdown_payload)
        if markdown:
            markdown_pages.append(markdown.strip())
        page_blocks = payload.get("parsing_res_list", []) if isinstance(payload, dict) else []
        if not isinstance(page_blocks, list):
            page_blocks = []
            warnings.append(f"page {page_index}: OCR blocks were unavailable")
        for fallback_order, raw_block in enumerate(page_blocks, start=1):
            if not isinstance(raw_block, dict):
                continue
            content = str(raw_block.get("block_content") or "").strip()
            if not content:
                continue
            bbox = raw_block.get("block_bbox")
            if not (
                isinstance(bbox, (list, tuple))
                and len(bbox) == 4
                and all(isinstance(value, (int, float)) for value in bbox)
            ):
                bbox = None
            blocks.append(
                {
                    "page": page_index,
                    "order": raw_block.get("block_order") or fallback_order,
                    "label": str(raw_block.get("block_label") or "text"),
                    "text": content,
                    "bbox": list(bbox) if bbox is not None else None,
                }
            )
    blocks.sort(key=lambda item: (int(item["page"]), int(item["order"])))
    normalized_text = "\n".join(str(block["text"]) for block in blocks).strip()
    markdown = "\n\n".join(markdown_pages).strip()
    if not normalized_text and markdown:
        normalized_text = markdown
    if not normalized_text:
        warnings.append("OCR returned no recognized text")
    return {
        "text": normalized_text,
        "normalized_text": normalized_text,
        "markdown": markdown or normalized_text,
        "blocks": blocks,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _result_payload(result: Any, attribute: str) -> dict[str, Any]:
    value = getattr(result, attribute, None)
    if callable(value):
        value = value()
    if isinstance(value, dict) and isinstance(value.get("res"), dict):
        return value["res"]
    return value if isinstance(value, dict) else {}


def _markdown_text(payload: dict[str, Any]) -> str:
    for key in ("markdown_texts", "markdown_text", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _verify_image(image_bytes: bytes, content_type: str) -> None:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
            detected = (image.format or "").upper()
    except Exception as exc:
        raise ValueError("Image body is not a valid PNG or JPEG") from exc
    expected = "PNG" if content_type == "image/png" else "JPEG"
    if detected != expected:
        raise ValueError("Image bytes do not match Content-Type")


def make_handler(service: OcrService, api_key: str) -> type[BaseHTTPRequestHandler]:
    class OcrRequestHandler(BaseHTTPRequestHandler):
        server_version = "TeacherAssistantLocalOCR/1.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            if not self._authorized():
                return
            self._json(HTTPStatus.OK, service.health())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/ocr":
                self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            if not self._authorized():
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
            length_header = self.headers.get("Content-Length", "")
            try:
                length = int(length_header)
            except ValueError:
                self._json(HTTPStatus.LENGTH_REQUIRED, {"detail": "Content-Length required"})
                return
            if length < 0:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"detail": "Content-Length must be non-negative"},
                )
                return
            if length > service.max_image_bytes:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": "Image too large"})
                return
            body = self.rfile.read(length)
            try:
                result = service.run(
                    image_bytes=body,
                    content_type=content_type,
                    request_id=self.headers.get("X-Request-ID", ""),
                    mode=self.headers.get("X-OCR-Mode", ""),
                )
            except OverflowError as exc:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": str(exc)})
            except OcrBusyError as exc:
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"detail": str(exc)})
            except ValueError as exc:
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"detail": str(exc)})
            except Exception:
                self._json(HTTPStatus.BAD_GATEWAY, {"detail": "Local OCR inference failed"})
            else:
                self._json(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _authorized(self) -> bool:
            expected = f"Bearer {api_key}"
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, expected):
                self._json(HTTPStatus.UNAUTHORIZED, {"detail": "Unauthorized"})
                return False
            return True

        def _json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return OcrRequestHandler


def build_server(config: SidecarConfig, engine: OcrEngine | None = None) -> ThreadingHTTPServer:
    if config.host not in LOOPBACK_HOSTS:
        raise RuntimeError("The OCR sidecar may bind only to a loopback host")
    resolved_engine = engine or PaddleOcrVlEngine(
        vl_model_path=config.vl_model_path,
        layout_model_path=config.layout_model_path,
        device=config.device,
    )
    service = OcrService(resolved_engine, max_image_bytes=config.max_image_bytes)
    server = ThreadingHTTPServer((config.host, config.port), make_handler(service, config.api_key))
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Teacher Assistant local PaddleOCR sidecar")
    parser.parse_args()
    config = SidecarConfig.from_environment()
    server = build_server(config)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
