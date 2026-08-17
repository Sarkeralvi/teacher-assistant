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
ALLOWED_ENGINES = {"paddleocr_vl", "ppocr_v6"}
ALLOWED_PREPROCESSING_PROFILES = {
    "default",
    "math_handwriting_rescue",
    "math_handwriting_rescue_v2",
    "math_handwriting_rescue_v3",
    "rescue_alternate",
}
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

    def predict(self, image_path: Path, mode: str, prompt_label: str = "ocr") -> list[Any]: ...


@dataclass(frozen=True)
class SidecarConfig:
    api_key: str
    vl_model_path: Path
    layout_model_path: Path
    text_det_model_path: Path | None = None
    text_rec_model_path: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8090
    max_image_bytes: int = 20 * 1024 * 1024
    device: str = "cpu"

    @classmethod
    def from_environment(cls) -> SidecarConfig:
        api_key = os.environ.get("LOCAL_OCR_API_KEY", "")
        vl_path = os.environ.get("LOCAL_OCR_VL_MODEL_PATH", "")
        layout_path = os.environ.get("LOCAL_OCR_LAYOUT_MODEL_PATH", "")
        det_path = os.environ.get("LOCAL_OCR_TEXT_DET_MODEL_PATH", "")
        rec_path = os.environ.get("LOCAL_OCR_TEXT_REC_MODEL_PATH", "")
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
        rescue_enabled = os.environ.get("LOCAL_OCR_RESCUE_ENABLED", "false").lower() == "true"
        if rescue_enabled and (not det_path or not rec_path):
            raise RuntimeError(
                "LOCAL_OCR_TEXT_DET_MODEL_PATH and LOCAL_OCR_TEXT_REC_MODEL_PATH are required"
            )
        return cls(
            api_key=api_key,
            vl_model_path=Path(vl_path),
            layout_model_path=Path(layout_path),
            text_det_model_path=Path(det_path) if det_path else None,
            text_rec_model_path=Path(rec_path) if rec_path else None,
            host=host,
            port=int(os.environ.get("LOCAL_OCR_PORT", "8090")),
            max_image_bytes=int(os.environ.get("LOCAL_OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024))),
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
        else:
            # PaddleX 3.7.2 selects bfloat16 for this Blackwell GPU.  In this
            # installed Paddle 3.2.1 build, the generated OCR logits can become
            # numerically invalid and select one of the padded vocabulary rows.
            # Float32 remains GPU-accelerated and is the stable host mode for
            # this exact local runtime.
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
        vl_predictor = self.pipeline.paddlex_pipeline.vl_rec_model
        self.precision = str(vl_predictor.dtype)
        if self.precision != "float32":
            raise RuntimeError("Local OCR must use the validated float32 precision")
        # PaddleOCR-VL-1.6 has a padded 103,424-row language-model head, while
        # the bundled SentencePiece vocabulary plus registered added tokens
        # contains only 101,314 decodable IDs.  The local GPU kernel can select
        # one of those padding rows, which then crashes SentencePiece with an
        # out-of-range ID.  Mask only the non-token padding rows at the logits
        # boundary; valid token scores and model assets remain unchanged.
        self.blocked_padding_token_count = _install_valid_token_logits_guard(
            self.pipeline,
            paddle_module=paddle,
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

    def _assert_local_model(self, directory: Path, required_file: str) -> None:
        if not directory.is_dir() or not (directory / required_file).is_file():
            raise RuntimeError(f"Configured local OCR model is incomplete: {directory.name}")


class PpOcrV6Engine:
    model_name = "PP-OCRv6_medium_rec"
    layout_model_name = "PP-OCRv6_medium_det"
    version = "3.7.0"

    def __init__(
        self, *, text_det_model_path: Path, text_rec_model_path: Path, device: str
    ) -> None:
        for directory in (text_det_model_path, text_rec_model_path):
            if not directory.is_dir() or not (directory / "inference.pdiparams").is_file():
                raise RuntimeError(f"Configured local OCR model is incomplete: {directory.name}")
        if device not in {"cpu", "gpu:0"}:
            raise RuntimeError("OCR device must be cpu or gpu:0")
        self.device = device
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        self.pipeline = PaddleOCR(
            text_detection_model_dir=str(text_det_model_path.resolve()),
            text_recognition_model_dir=str(text_rec_model_path.resolve()),
            device=device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        self.precision = "float32"

    def predict(self, image_path: Path, mode: str, prompt_label: str = "ocr") -> list[Any]:
        del mode
        if prompt_label != "ocr":
            raise ValueError("PP-OCRv6 supports only the ocr prompt")
        return list(self.pipeline.predict(str(image_path)))


def _tokenizer_valid_id_limit(tokenizer: Any) -> int:
    sp_model = getattr(tokenizer, "sp_model", None)
    get_piece_size = getattr(sp_model, "get_piece_size", None)
    if not callable(get_piece_size):
        raise RuntimeError("Local OCR tokenizer does not expose its SentencePiece size")
    sentencepiece_size = int(get_piece_size())
    if sentencepiece_size <= 0:
        raise RuntimeError("Local OCR tokenizer SentencePiece vocabulary is empty")
    added_decoder = getattr(tokenizer, "added_tokens_decoder", None)
    if not isinstance(added_decoder, dict):
        raise RuntimeError("Local OCR tokenizer does not expose its added-token IDs")
    added_ids = sorted(
        int(token_id) for token_id in added_decoder if int(token_id) >= sentencepiece_size
    )
    expected_added_ids = list(range(sentencepiece_size, sentencepiece_size + len(added_ids)))
    if added_ids != expected_added_ids:
        raise RuntimeError("Local OCR tokenizer has non-contiguous decodable token IDs")
    return sentencepiece_size + len(added_ids)


def _install_valid_token_logits_guard(
    pipeline: Any,
    *,
    paddle_module: Any,
) -> int:
    paddlex_pipeline = getattr(pipeline, "paddlex_pipeline", None)
    predictor = getattr(paddlex_pipeline, "vl_rec_model", None)
    processor = getattr(predictor, "processor", None)
    tokenizer = getattr(processor, "tokenizer", None)
    model = getattr(predictor, "infer", None)
    model_config = getattr(model, "config", None)
    lm_head = getattr(model, "lm_head", None)
    original_forward = getattr(lm_head, "forward", None)
    if tokenizer is None or model_config is None or not callable(original_forward):
        raise RuntimeError("Local OCR predictor internals do not support vocabulary guarding")

    valid_id_limit = _tokenizer_valid_id_limit(tokenizer)
    model_vocab_size = int(getattr(model_config, "vocab_size", 0))
    if model_vocab_size < valid_id_limit:
        raise RuntimeError("Local OCR model vocabulary is smaller than its tokenizer")
    blocked_count = model_vocab_size - valid_id_limit
    if blocked_count == 0:
        return 0

    def guarded_forward(*args: Any, **kwargs: Any) -> Any:
        logits = original_forward(*args, **kwargs)
        if int(logits.shape[-1]) != model_vocab_size:
            raise RuntimeError("Local OCR language-model head changed vocabulary size")
        valid_logits = logits[..., :valid_id_limit]
        invalid_logits = paddle_module.full_like(
            logits[..., valid_id_limit:],
            float("-inf"),
        )
        return paddle_module.concat((valid_logits, invalid_logits), axis=-1)

    # ``forward`` is stored on this layer instance so repository code owns the
    # compatibility guard without modifying the downloaded model or site-packages.
    lm_head.forward = guarded_forward
    return blocked_count


class OcrBusyError(RuntimeError):
    pass


class OcrService:
    def __init__(
        self,
        engine: OcrEngine | None = None,
        *,
        engines: dict[str, OcrEngine] | None = None,
        max_image_bytes: int,
    ) -> None:
        resolved = engines or ({"paddleocr_vl": engine} if engine is not None else {})
        if "paddleocr_vl" not in resolved:
            raise RuntimeError("PaddleOCR-VL engine is required")
        self.engines = resolved
        self.max_image_bytes = max_image_bytes
        self._slot = threading.BoundedSemaphore(value=1)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "provider": "local_paddle_qwen",
            "model": self.engines["paddleocr_vl"].model_name,
            "layout_model": self.engines["paddleocr_vl"].layout_model_name,
            "models": {
                name: {
                    "model": engine.model_name,
                    "layout_model": engine.layout_model_name,
                }
                for name, engine in self.engines.items()
            },
            "version": self.engines["paddleocr_vl"].version,
            "device": self.engines["paddleocr_vl"].device,
            "precision": str(getattr(self.engines["paddleocr_vl"], "precision", "unknown")),
            "max_concurrency": 1,
            "offline": True,
            "blocked_padding_token_count": int(
                getattr(self.engines["paddleocr_vl"], "blocked_padding_token_count", 0)
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
        engine_name: str = "paddleocr_vl",
        preprocessing_profile: str = "default",
    ) -> dict[str, Any]:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Only PNG and JPEG image bytes are accepted")
        if mode not in ALLOWED_MODES:
            raise ValueError("OCR mode must be document or answer_region")
        if prompt_label not in {"ocr", "formula"}:
            raise ValueError("OCR prompt label must be ocr or formula")
        if engine_name not in ALLOWED_ENGINES or engine_name not in self.engines:
            raise ValueError("Requested OCR engine is unavailable")
        if preprocessing_profile not in ALLOWED_PREPROCESSING_PROFILES:
            raise ValueError("Unsupported OCR preprocessing profile")
        if engine_name == "ppocr_v6" and prompt_label != "ocr":
            raise ValueError("PP-OCRv6 supports only the ocr prompt")
        if mode == "document" and prompt_label != "ocr":
            raise ValueError("Formula prompting is supported only for answer regions")
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
                selected_engine = self.engines[engine_name]
                raw_results = selected_engine.predict(image_path, mode, prompt_label)
            finally:
                image_path.unlink(missing_ok=True)
            normalized = (
                normalize_ppocr_results(raw_results)
                if engine_name == "ppocr_v6"
                else normalize_paddle_results(raw_results)
            )
            return {
                "request_id": request_id,
                "mode": mode,
                **normalized,
                "warnings": normalized.get("warnings", []),
                "provider": "local_paddle_qwen",
                "model": selected_engine.model_name,
                "layout_model": selected_engine.layout_model_name,
                "version": selected_engine.version,
                "device": selected_engine.device,
                "engine": engine_name,
                "preprocessing_profile": preprocessing_profile,
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
        if markdown and not _is_decoration_only_text(markdown):
            markdown_pages.append(markdown.strip())
        elif markdown:
            warnings.append(f"page {page_index}: page-line decoration was treated as blank")
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
            if _is_decoration_only_text(content):
                warnings.append(f"page {page_index}: page-line decoration was treated as blank")
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
                    "confidence": None,
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


def normalize_ppocr_results(results: list[Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    warnings: list[str] = []
    order = 0
    for page_index, result in enumerate(results, start=1):
        payload = _result_payload(result, "json")
        texts = payload.get("rec_texts", []) if isinstance(payload, dict) else []
        scores = payload.get("rec_scores", []) if isinstance(payload, dict) else []
        boxes = payload.get("rec_boxes", []) if isinstance(payload, dict) else []
        polygons = payload.get("dt_polys", []) if isinstance(payload, dict) else []
        for index, raw_text in enumerate(texts if isinstance(texts, list) else []):
            content = str(raw_text or "").strip()
            if not content or _is_decoration_only_text(content):
                continue
            raw_box = boxes[index] if isinstance(boxes, list) and index < len(boxes) else None
            if not (isinstance(raw_box, (list, tuple)) and len(raw_box) == 4):
                polygon = (
                    polygons[index]
                    if isinstance(polygons, list) and index < len(polygons)
                    else None
                )
                raw_box = _polygon_bbox(polygon)
            bbox = (
                [float(value) for value in raw_box]
                if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4
                else None
            )
            score = scores[index] if isinstance(scores, list) and index < len(scores) else None
            order += 1
            blocks.append(
                {
                    "page": page_index,
                    "order": order,
                    "label": "text",
                    "text": content,
                    "bbox": bbox,
                    "confidence": float(score) if isinstance(score, (int, float)) else None,
                }
            )
    blocks.sort(
        key=lambda item: (
            int(item["page"]),
            item["bbox"][1] if item["bbox"] else float("inf"),
            item["bbox"][0] if item["bbox"] else int(item["order"]),
        )
    )
    for index, block in enumerate(blocks, start=1):
        block["order"] = index
    text = "\n".join(str(block["text"]) for block in blocks).strip()
    if not text:
        warnings.append("OCR returned no recognized text")
    return {
        "text": text,
        "normalized_text": text,
        "markdown": text,
        "blocks": blocks,
        "warnings": warnings,
    }


def _polygon_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    points = [point for point in value if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _is_decoration_only_text(value: str) -> bool:
    normalized = str(value or "").strip()
    for mojibake_dash in ("â€”", "â€“", "âˆ’"):
        normalized = normalized.replace(mojibake_dash, "-")
    normalized = normalized.translate(str.maketrans({"—": "-", "–": "-", "−": "-", "‑": "-"}))
    compact = "".join(normalized.split())
    return bool(compact) and all(character in "-_=~|/\\.·•" for character in compact)


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
                    prompt_label=self.headers.get("X-OCR-Prompt-Label", "ocr"),
                    engine_name=self.headers.get("X-OCR-Engine", "paddleocr_vl"),
                    preprocessing_profile=self.headers.get(
                        "X-OCR-Preprocessing-Profile", "default"
                    ),
                )
            except OverflowError as exc:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": str(exc)})
            except OcrBusyError as exc:
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"detail": str(exc)})
            except ValueError as exc:
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"detail": str(exc)})
            except Exception:
                # The HTTP response remains sanitized, while the ignored
                # operator log retains the local traceback needed to diagnose
                # driver/model synchronization failures.
                traceback.print_exc()
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
    engines: dict[str, OcrEngine] = {"paddleocr_vl": resolved_engine}
    if engine is None and config.text_det_model_path and config.text_rec_model_path:
        engines["ppocr_v6"] = PpOcrV6Engine(
            text_det_model_path=config.text_det_model_path,
            text_rec_model_path=config.text_rec_model_path,
            device=config.device,
        )
    service = OcrService(engines=engines, max_image_bytes=config.max_image_bytes)
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
