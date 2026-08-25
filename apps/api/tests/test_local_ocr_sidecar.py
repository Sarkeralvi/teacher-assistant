from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from packages.local_ocr_sidecar.server import OcrBusyError, OcrService, normalize_paddle_results


class FakeResult:
    def __init__(self, payload: dict[str, Any], markdown: str) -> None:
        self.json = {"res": payload}
        self.markdown = {"res": {"markdown_texts": markdown}}


class FakeEngine:
    model_name = "PaddleOCR-VL-1.6"
    layout_model_name = "PP-DocLayoutV3"
    version = "3.7.0"
    device = "gpu:0"
    precision = "float32"
    blocked_padding_token_count = 48

    def __init__(self) -> None:
        self.calls: list[tuple[Path, str, str]] = []

    def predict(self, image_path: Path, mode: str, prompt_label: str = "ocr") -> list[Any]:
        self.calls.append((image_path, mode, prompt_label))
        return [
            FakeResult(
                {
                    "parsing_res_list": [
                        {
                            "block_order": 2,
                            "block_label": "formula",
                            "block_content": "7/12",
                            "block_bbox": [20, 50, 100, 90],
                        },
                        {
                            "block_order": 1,
                            "block_label": "text",
                            "block_content": "P(X)=",
                            "block_bbox": [5, 10, 90, 40],
                        },
                    ]
                },
                "$P(X)=7/12$",
            )
        ]


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (32, 16), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_normalization_preserves_order_boxes_and_markdown() -> None:
    normalized = normalize_paddle_results(FakeEngine().predict(Path("unused"), "document"))

    assert normalized["normalized_text"] == "P(X)=\n7/12"
    assert normalized["markdown"] == "$P(X)=7/12$"
    assert [block["order"] for block in normalized["blocks"]] == [1, 2]
    assert normalized["blocks"][1]["bbox"] == [20, 50, 100, 90]


def test_sidecar_accepts_only_matching_png_or_jpeg_bytes() -> None:
    service = OcrService(FakeEngine(), max_image_bytes=1024 * 1024)

    with pytest.raises(OverflowError, match="empty"):
        service.run(
            image_bytes=b"",
            content_type="image/png",
            request_id="request-1",
            mode="document",
        )
    with pytest.raises(ValueError, match="Only PNG and JPEG"):
        service.run(
            image_bytes=_png_bytes(),
            content_type="text/plain",
            request_id="request-1",
            mode="document",
        )
    with pytest.raises(ValueError, match="do not match"):
        service.run(
            image_bytes=_png_bytes(),
            content_type="image/jpeg",
            request_id="request-1",
            mode="document",
        )
    with pytest.raises(OverflowError, match="exceeds"):
        OcrService(FakeEngine(), max_image_bytes=2).run(
            image_bytes=_png_bytes(),
            content_type="image/png",
            request_id="request-1",
            mode="document",
        )


def test_sidecar_runs_one_local_image_and_reports_identity() -> None:
    engine = FakeEngine()
    service = OcrService(engine, max_image_bytes=1024 * 1024)

    result = service.run(
        image_bytes=_png_bytes(),
        content_type="image/png",
        request_id="request-1",
        mode="answer_region",
        prompt_label="formula",
    )

    assert result["provider"] == "local_paddle_qwen"
    assert result["model"] == "PaddleOCR-VL-1.6"
    assert result["layout_model"] == "PP-DocLayoutV3"
    assert result["device"] == "gpu:0"
    assert engine.calls[0][1:] == ("answer_region", "formula")
    assert not engine.calls[0][0].exists()


def test_concurrency_guard_fails_without_waiting() -> None:
    service = OcrService(FakeEngine(), max_image_bytes=1024 * 1024)
    assert service._slot.acquire(blocking=False) is True
    try:
        with pytest.raises(OcrBusyError, match="busy"):
            service.run(
                image_bytes=_png_bytes(),
                content_type="image/png",
                request_id="request-1",
                mode="document",
            )
    finally:
        service._slot.release()


def test_health_proves_offline_single_slot_and_precision() -> None:
    health = OcrService(FakeEngine(), max_image_bytes=100).health()

    assert health["offline"] is True
    assert health["max_concurrency"] == 1
    assert health["precision"] == "float32"
    assert health["blocked_padding_token_count"] == 48
