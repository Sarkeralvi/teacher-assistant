from __future__ import annotations

import argparse
import hmac
import io
import json
import os
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

ALLOWED_CONTENT_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
ALLOWED_MODES = {"document", "answer_region"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OcrEngine(Protocol):
    model_name: str
    layout_model_name: str
    version: str
    device: str

    def predict(self, image_path: Path, mode: str, prompt_label: str = "ocr") -> list[Any]: ...


@dataclass(frozen=True)
class SidecarConfig:
    api_key: str
    vl_model_path: Path
    layout_model_path: Path
    host: str = "127.0.0.1"
    port: int = 8090
    max_image_bytes: int = 20 * 1024 * 1024
    device: str = "gpu:0"

    @classmethod
    def from_environment(cls) -> SidecarConfig:
        api_key = os.environ.get("LOCAL_PADDLE_OCR_API_KEY", "")
        vl_path = os.environ.get("LOCAL_PADDLE_OCR_VL_MODEL_PATH", "")
        layout_path = os.environ.get("LOCAL_PADDLE_OCR_LAYOUT_MODEL_PATH", "")
        if not api_key:
            raise RuntimeError("LOCAL_PADDLE_OCR_API_KEY is required")
        if not vl_path or not layout_path:
            raise RuntimeError("Local PaddleOCR model paths are required")
        host = os.environ.get("LOCAL_PADDLE_OCR_HOST", "127.0.0.1")
        if host not in LOOPBACK_HOSTS:
            raise RuntimeError("The OCR sidecar may bind only to a loopback host")
        device = os.environ.get("LOCAL_PADDLE_OCR_DEVICE", "gpu:0").strip().lower()
        if device not in {"cpu", "gpu:0"}:
            raise RuntimeError("LOCAL_PADDLE_OCR_DEVICE must be cpu or gpu:0")
        return cls(
            api_key=api_key,
            vl_model_path=Path(vl_path),
            layout_model_path=Path(layout_path),
            host=host,
            port=int(os.environ.get("LOCAL_PADDLE_OCR_PORT", "8090")),
            max_image_bytes=int(
                os.environ.get("LOCAL_PADDLE_OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024))
            ),
            device=device,
        )


class PaddleOcrVlEngine:
    model_name = "PaddleOCR-VL-1.6"
    layout_model_name = "PP-DocLayoutV3"
    version = "3.7.0"

    def __init__(self, *, vl_model_path: Path, layout_model_path: Path, device: str) -> None:
        self._assert_local_model(vl_model_path, "model.safetensors")
        self._assert_local_model(layout_model_path, "inference.pdiparams")
        self.device = device
        # Model loading is fail-closed and offline. An operator must prepare the
        # exact assets before this process starts; page loads cannot download.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

        import paddle
        from paddlex.utils import env as paddlex_environment

        paddle.set_device(device)
        if paddle.device.get_device() != device:
            raise RuntimeError("PaddleOCR initialized on an unexpected device")
        if device == "cpu":
            paddlex_environment.get_gpu_compute_capability = lambda: None
        else:
            # PaddleX 3.7.2 selects BF16 on Blackwell, but this host's validated
            # Paddle 3.2.1 build can emit invalid padded-vocabulary logits.
            # Float32 remains GPU accelerated and was the stable measured mode.
            from paddlex.inference.models.doc_vlm import predictor as doc_vlm_predictor

            doc_vlm_predictor.is_bfloat16_available = lambda _device: False

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
        predictor = self.pipeline.paddlex_pipeline.vl_rec_model
        self.precision = str(predictor.dtype)
        if self.precision != "float32":
            raise RuntimeError("Local PaddleOCR must use validated float32 precision")
        self.blocked_padding_token_count = _install_valid_token_logits_guard(
            self.pipeline, paddle_module=paddle
        )

    def predict(self, image_path: Path, mode: str, prompt_label: str = "ocr") -> list[Any]:
        return self.pipeline.predict(
            str(image_path),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=mode == "document",
            use_chart_recognition=False,
            use_seal_recognition=False,
            use_ocr_for_image_block=False,
            use_queues=False,
            prompt_label=prompt_label if mode == "answer_region" else None,
            temperature=0.0,
        )

    @staticmethod
    def _assert_local_model(directory: Path, required_file: str) -> None:
        if not directory.is_dir() or not (directory / required_file).is_file():
            raise RuntimeError(f"Configured local OCR model is incomplete: {directory.name}")


def _install_valid_token_logits_guard(pipeline: Any, *, paddle_module: Any) -> int:
    predictor = pipeline.paddlex_pipeline.vl_rec_model
    tokenizer = predictor.processor.tokenizer
    sentencepiece_size = int(tokenizer.sp_model.get_piece_size())
    added_ids = sorted(int(token_id) for token_id in tokenizer.added_tokens_decoder)
    added_ids = [token_id for token_id in added_ids if token_id >= sentencepiece_size]
    expected_ids = list(range(sentencepiece_size, sentencepiece_size + len(added_ids)))
    if added_ids != expected_ids:
        raise RuntimeError("Local OCR tokenizer has non-contiguous decodable token IDs")
    valid_id_limit = sentencepiece_size + len(added_ids)
    model = predictor.infer
    model_vocab_size = int(model.config.vocab_size)
    if model_vocab_size < valid_id_limit:
        raise RuntimeError("Local OCR vocabulary is smaller than its tokenizer")
    blocked_count = model_vocab_size - valid_id_limit
    if blocked_count <= 0:
        return 0
    original_forward = model.lm_head.forward

    def guarded_forward(*args: Any, **kwargs: Any) -> Any:
        logits = original_forward(*args, **kwargs)
        if int(logits.shape[-1]) != model_vocab_size:
            raise RuntimeError("Local OCR language-model head changed vocabulary size")
        return paddle_module.concat(
            (
                logits[..., :valid_id_limit],
                paddle_module.full_like(logits[..., valid_id_limit:], float("-inf")),
            ),
            axis=-1,
        )

    model.lm_head.forward = guarded_forward
    return blocked_count


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
            "precision": str(getattr(self.engine, "precision", "unknown")),
            "max_concurrency": 1,
            "offline": True,
            "blocked_padding_token_count": int(
                getattr(self.engine, "blocked_padding_token_count", 0)
            ),
        }

    def run(
        self,
        *,
        image_bytes: bytes,
        content_type: str,
        request_id: str,
        mode: str,
        prompt_label: str = "ocr",
    ) -> dict[str, Any]:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Only PNG and JPEG image bytes are accepted")
        if mode not in ALLOWED_MODES:
            raise ValueError("OCR mode must be document or answer_region")
        if prompt_label not in {"ocr", "formula"}:
            raise ValueError("OCR prompt label must be ocr or formula")
        if not request_id.strip() or len(request_id) > 128:
            raise ValueError("A request ID of at most 128 characters is required")
        if not image_bytes or len(image_bytes) > self.max_image_bytes:
            raise OverflowError("Image is empty or exceeds the configured size limit")
        _verify_image(image_bytes, content_type)
        if not self._slot.acquire(blocking=False):
            raise OcrBusyError("The OCR sidecar is busy")
        started = time.perf_counter()
        try:
            suffix = ALLOWED_CONTENT_TYPES[content_type]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                temporary.write(image_bytes)
                image_path = Path(temporary.name)
            try:
                normalized = normalize_paddle_results(
                    self.engine.predict(image_path, mode, prompt_label)
                )
            finally:
                image_path.unlink(missing_ok=True)
            return {
                "request_id": request_id,
                "mode": mode,
                **normalized,
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
        markdown = _markdown_text(_result_payload(result, "markdown"))
        if markdown and not _is_decoration_only_text(markdown):
            markdown_pages.append(markdown.strip())
        raw_blocks = payload.get("parsing_res_list", []) if isinstance(payload, dict) else []
        if not isinstance(raw_blocks, list):
            raw_blocks = []
            warnings.append(f"page {page_index}: OCR blocks were unavailable")
        for fallback_order, raw_block in enumerate(raw_blocks, start=1):
            if not isinstance(raw_block, dict):
                continue
            content = str(raw_block.get("block_content") or "").strip()
            if not content or _is_decoration_only_text(content):
                continue
            bbox = raw_block.get("block_bbox")
            valid_bbox = (
                isinstance(bbox, (list, tuple))
                and len(bbox) == 4
                and all(isinstance(value, (int, float)) for value in bbox)
            )
            blocks.append(
                {
                    "page": page_index,
                    "order": int(raw_block.get("block_order") or fallback_order),
                    "label": str(raw_block.get("block_label") or "text"),
                    "text": content,
                    "bbox": list(bbox) if valid_bbox else None,
                }
            )
    blocks.sort(key=lambda item: (item["page"], item["order"]))
    normalized_text = "\n".join(str(block["text"]) for block in blocks).strip()
    markdown = "\n\n".join(markdown_pages).strip()
    if not normalized_text:
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


def _is_decoration_only_text(value: str) -> bool:
    normalized = str(value or "").strip().translate(str.maketrans({"—": "-", "–": "-"}))
    compact = "".join(normalized.split())
    return bool(compact) and all(character in "-_=~|/\\.·•" for character in compact)


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
    class Handler(BaseHTTPRequestHandler):
        server_version = "TeacherAssistantLocalPaddleOCR/2.0"

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
            elif self._authorized():
                self._json(HTTPStatus.OK, service.health())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/ocr":
                self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found"})
                return
            if not self._authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
                if length <= 0:
                    raise ValueError("A non-empty image body is required")
                if length > service.max_image_bytes:
                    raise OverflowError("Image exceeds the configured size limit")
                result = service.run(
                    image_bytes=self.rfile.read(length),
                    content_type=self.headers.get("Content-Type", "").split(";", 1)[0].strip(),
                    request_id=self.headers.get("X-Request-ID", ""),
                    mode=self.headers.get("X-OCR-Mode", ""),
                    prompt_label=self.headers.get("X-OCR-Prompt-Label", "ocr"),
                )
            except OverflowError as exc:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": str(exc)})
            except OcrBusyError as exc:
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"detail": str(exc)})
            except (TypeError, ValueError) as exc:
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"detail": str(exc)})
            except Exception:
                traceback.print_exc()
                self._json(HTTPStatus.BAD_GATEWAY, {"detail": "Local OCR inference failed"})
            else:
                self._json(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _authorized(self) -> bool:
            if not hmac.compare_digest(
                self.headers.get("Authorization", ""), f"Bearer {api_key}"
            ):
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

    return Handler


def build_server(config: SidecarConfig, engine: OcrEngine | None = None) -> ThreadingHTTPServer:
    if config.host not in LOOPBACK_HOSTS:
        raise RuntimeError("The OCR sidecar may bind only to a loopback host")
    resolved_engine = engine or PaddleOcrVlEngine(
        vl_model_path=config.vl_model_path,
        layout_model_path=config.layout_model_path,
        device=config.device,
    )
    server = ThreadingHTTPServer(
        (config.host, config.port),
        make_handler(
            OcrService(resolved_engine, max_image_bytes=config.max_image_bytes),
            config.api_key,
        ),
    )
    server.daemon_threads = True
    return server


def main() -> None:
    argparse.ArgumentParser(description="Teacher Assistant local PaddleOCR sidecar").parse_args()
    server = build_server(SidecarConfig.from_environment())
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
