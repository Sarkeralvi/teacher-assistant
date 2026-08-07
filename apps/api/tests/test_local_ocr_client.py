from typing import Any

import pytest

from app.core.config import Settings
from app.services.local_ocr_client import (
    LocalOcrClient,
    LocalOcrConfigurationError,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, kwargs))
        return FakeResponse(self.payload)


def valid_payload() -> dict[str, Any]:
    return {
        "request_id": "region-1",
        "mode": "answer_region",
        "text": "answer",
        "normalized_text": "answer",
        "markdown": "answer",
        "blocks": [
            {"page": 1, "order": 1, "label": "text", "text": "answer", "bbox": None}
        ],
        "warnings": [],
        "provider": "local_paddle_qwen",
        "model": "PaddleOCR-VL-1.6",
        "layout_model": "PP-DocLayoutV3",
        "version": "3.7.0",
        "device": "cpu",
        "latency_ms": 5,
    }


def test_local_ocr_client_posts_only_bytes_with_auth_and_metadata() -> None:
    fake = FakeClient(valid_payload())
    client = LocalOcrClient(
        base_url="http://127.0.0.1:8090",
        api_key="local-secret",
        timeout_seconds=5,
        max_image_bytes=100,
        client=fake,
    )

    result = client.ocr_image(
        image_bytes=b"image-bytes",
        content_type="image/png",
        request_id="region-1",
        mode="answer_region",
    )

    assert result.normalized_text == "answer"
    path, kwargs = fake.calls[0]
    assert path == "v1/ocr"
    assert kwargs["content"] == b"image-bytes"
    assert kwargs["headers"]["Authorization"] == "Bearer local-secret"
    assert "url" not in kwargs


def test_local_ocr_client_requires_kill_switch_flag_key_and_loopback() -> None:
    with pytest.raises(LocalOcrConfigurationError, match="BRAIN_ALLOW_REAL_PROVIDERS"):
        LocalOcrClient.from_settings(
            Settings(
                BRAIN_ALLOW_REAL_PROVIDERS=False,
                LOCAL_OCR_ENABLED=True,
                LOCAL_OCR_API_KEY="local-secret",
            )
        )
    with pytest.raises(LocalOcrConfigurationError, match="LOCAL_OCR_ENABLED"):
        LocalOcrClient.from_settings(
            Settings(BRAIN_ALLOW_REAL_PROVIDERS=True, LOCAL_OCR_ENABLED=False)
        )
    with pytest.raises(LocalOcrConfigurationError, match="loopback"):
        LocalOcrClient(
            base_url="https://remote.example.test",
            api_key="local-secret",
            timeout_seconds=5,
            max_image_bytes=100,
        )
