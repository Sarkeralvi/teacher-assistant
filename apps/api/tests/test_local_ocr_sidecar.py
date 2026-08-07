from __future__ import annotations

import io
import json
import os
import threading
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from packages.local_ocr_sidecar.server import (
    OcrBusyError,
    OcrService,
    SidecarConfig,
    _configure_cpu_only_environment,
    build_server,
    normalize_paddle_results,
)


class FakePaddleResult:
    def __init__(self) -> None:
        self.json = {
            "res": {
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": " First line ",
                        "block_bbox": [1, 2, 30, 40],
                        "block_order": 1,
                    },
                    {
                        "block_label": "formula",
                        "block_content": "x^2",
                        "block_bbox": None,
                        "block_order": 2,
                    },
                ]
            }
        }
        self.markdown = {"res": {"markdown_texts": "First line\n\n$x^2$"}}


class FakeEngine:
    model_name = "PaddleOCR-VL-1.6"
    layout_model_name = "PP-DocLayoutV3"
    version = "3.7.0"
    device = "cpu"

    def predict(self, image_path: Path, mode: str) -> list[Any]:
        assert image_path.is_file()
        assert mode in {"document", "answer_region"}
        return [FakePaddleResult()]


class BlockingEngine(FakeEngine):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def predict(self, image_path: Path, mode: str) -> list[Any]:
        del image_path, mode
        self.entered.set()
        self.release.wait(timeout=3)
        return [FakePaddleResult()]


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (16, 12), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_sidecar_normalizes_text_markdown_blocks_and_boxes() -> None:
    result = normalize_paddle_results([FakePaddleResult()])

    assert result["normalized_text"] == "First line\nx^2"
    assert result["markdown"] == "First line\n\n$x^2$"
    assert result["blocks"][0] == {
        "page": 1,
        "order": 1,
        "label": "text",
        "text": "First line",
        "bbox": [1, 2, 30, 40],
    }


def test_sidecar_service_is_image_only_size_limited_and_cpu() -> None:
    service = OcrService(FakeEngine(), max_image_bytes=1024)

    result = service.run(
        image_bytes=png_bytes(),
        content_type="image/png",
        request_id="request-1",
        mode="answer_region",
    )

    assert result["device"] == "cpu"
    assert result["provider"] == "local_paddle_qwen"
    assert result["request_id"] == "request-1"
    with pytest.raises(ValueError, match="Only PNG and JPEG"):
        service.run(
            image_bytes=b'{"url":"https://example.test/image.png"}',
            content_type="application/json",
            request_id="request-2",
            mode="document",
        )
    with pytest.raises(OverflowError, match="size limit"):
        service.run(
            image_bytes=b"x" * 1025,
            content_type="image/png",
            request_id="request-3",
            mode="document",
        )


def test_sidecar_hides_cuda_before_paddle_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    _configure_cpu_only_environment()

    assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"


def test_sidecar_config_accepts_explicit_gpu_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCAL_OCR_API_KEY", "local-secret")
    monkeypatch.setenv("LOCAL_OCR_VL_MODEL_PATH", str(tmp_path / "vl"))
    monkeypatch.setenv("LOCAL_OCR_LAYOUT_MODEL_PATH", str(tmp_path / "layout"))
    monkeypatch.setenv("LOCAL_OCR_DEVICE", "gpu:0")

    assert SidecarConfig.from_environment().device == "gpu:0"


def test_sidecar_enforces_single_concurrent_inference() -> None:
    engine = BlockingEngine()
    service = OcrService(engine, max_image_bytes=4096)
    thread = threading.Thread(
        target=lambda: service.run(
            image_bytes=png_bytes(),
            content_type="image/png",
            request_id="first",
            mode="answer_region",
        )
    )
    thread.start()
    assert engine.entered.wait(timeout=1)
    try:
        with pytest.raises(OcrBusyError, match="busy"):
            service.run(
                image_bytes=png_bytes(),
                content_type="image/png",
                request_id="second",
                mode="answer_region",
            )
    finally:
        engine.release.set()
        thread.join(timeout=2)


def test_sidecar_http_requires_auth_and_rejects_url_payload(tmp_path: Path) -> None:
    config = SidecarConfig(
        api_key="local-secret",
        vl_model_path=tmp_path / "vl",
        layout_model_path=tmp_path / "layout",
        port=0,
    )
    server = build_server(config, engine=FakeEngine())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        connection = HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/health")
        unauthorized = connection.getresponse()
        assert unauthorized.status == 401
        unauthorized.read()

        connection.request(
            "GET",
            "/health",
            headers={"Authorization": "Bearer local-secret"},
        )
        health = connection.getresponse()
        assert health.status == 200
        assert json.loads(health.read())["offline"] is True

        url_payload = b'{"url":"https://example.test/image.png"}'
        connection.request(
            "POST",
            "/v1/ocr",
            body=url_payload,
            headers={
                "Authorization": "Bearer local-secret",
                "Content-Type": "application/json",
                "Content-Length": str(len(url_payload)),
                "X-Request-ID": "url-request",
                "X-OCR-Mode": "document",
            },
        )
        assert connection.getresponse().status == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
