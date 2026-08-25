from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.config import Settings
from app.services.local_model_call_guard import (
    LocalModelCallGuardError,
    activate_local_model_call_authorization,
    clear_local_model_call_authorization_for_shutdown,
)
from app.services.local_ocr_client import LocalOcrClient, LocalOcrConfigurationError


class FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, *, health: dict[str, Any] | None = None) -> None:
        self.health_payload = health or _health_payload()
        self.get_calls: list[tuple[object, object]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(self, path: str, *, headers: dict[str, str]) -> FakeResponse:
        self.get_calls.append((path, headers))
        return FakeResponse(self.health_payload)

    def post(self, path: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"path": path, **kwargs})
        return FakeResponse(_ocr_payload())


def _health_payload() -> dict[str, Any]:
    return {
        "status": "ready",
        "model": "PaddleOCR-VL-1.6",
        "layout_model": "PP-DocLayoutV3",
        "offline": True,
        "max_concurrency": 1,
    }


def _ocr_payload() -> dict[str, Any]:
    return {
        "request_id": "request-1",
        "mode": "answer_region",
        "text": "P(X)=7/12",
        "normalized_text": "P(X)=7/12",
        "markdown": "$P(X)=7/12$",
        "blocks": [
            {
                "page": 1,
                "order": 1,
                "label": "formula",
                "text": "P(X)=7/12",
                "bbox": [1, 2, 100, 40],
            }
        ],
        "warnings": [],
        "provider": "local_paddle_qwen",
        "model": "PaddleOCR-VL-1.6",
        "layout_model": "PP-DocLayoutV3",
        "version": "3.7.0",
        "device": "gpu:0",
        "latency_ms": 125,
    }


def _client(fake: FakeClient) -> LocalOcrClient:
    return LocalOcrClient(
        base_url="http://127.0.0.1:8090",
        api_key="test-secret",
        timeout_seconds=5,
        max_image_bytes=1024,
        client=fake,
    )


@pytest.fixture(autouse=True)
def clear_guard() -> None:
    clear_local_model_call_authorization_for_shutdown()
    yield
    clear_local_model_call_authorization_for_shutdown()


def test_client_refuses_non_loopback_and_missing_kill_switches() -> None:
    with pytest.raises(LocalOcrConfigurationError, match="loopback"):
        LocalOcrClient(
            base_url="https://example.com",
            api_key="secret",
            timeout_seconds=5,
            max_image_bytes=1024,
        )

    with pytest.raises(LocalOcrConfigurationError, match="BRAIN_ALLOW_REAL_PROVIDERS"):
        LocalOcrClient.from_settings(Settings(LOCAL_PADDLE_OCR_ENABLED=True))

    with pytest.raises(LocalOcrConfigurationError, match="LOCAL_PADDLE_OCR_ENABLED"):
        LocalOcrClient.from_settings(Settings(BRAIN_ALLOW_REAL_PROVIDERS=True))


def test_health_requires_exact_offline_single_slot_identity() -> None:
    bad = _health_payload()
    bad["model"] = "unexpected-model"
    fake = FakeClient(health=bad)

    with pytest.raises(RuntimeError, match="model identity"):
        _client(fake).health()


def test_unleased_ocr_fails_before_any_http_request() -> None:
    fake = FakeClient()

    with pytest.raises(LocalModelCallGuardError, match="lease is required"):
        _client(fake).ocr_image(
            image_bytes=b"png",
            content_type="image/png",
            request_id="request-1",
            mode="answer_region",
        )

    assert fake.post_calls == []


def test_wrong_phase_lease_fails_before_any_http_request() -> None:
    fake = FakeClient()
    activate_local_model_call_authorization(
        model_phase="Qwen",
        holder_id="wrong-phase",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    with pytest.raises(LocalModelCallGuardError, match="phase does not match"):
        _client(fake).ocr_image(
            image_bytes=b"png",
            content_type="image/png",
            request_id="request-1",
            mode="answer_region",
        )

    assert fake.post_calls == []


def test_matching_paddle_lease_allows_one_authenticated_image_request() -> None:
    fake = FakeClient()
    activate_local_model_call_authorization(
        model_phase="PaddleOcr",
        holder_id="paddle-job",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    result = _client(fake).ocr_image(
        image_bytes=b"png",
        content_type="image/png",
        request_id="request-1",
        mode="answer_region",
    )

    assert result.normalized_text == "P(X)=7/12"
    assert len(fake.post_calls) == 1
    assert fake.post_calls[0]["headers"]["Authorization"] == "Bearer test-secret"
    assert fake.post_calls[0]["content"] == b"png"


def test_response_schema_and_model_mismatch_fail_closed() -> None:
    class WrongModelClient(FakeClient):
        def post(self, path: str, **kwargs: Any) -> FakeResponse:
            payload = _ocr_payload()
            payload["model"] = "other"
            return FakeResponse(payload)

    activate_local_model_call_authorization(
        model_phase="PaddleOcr",
        holder_id="paddle-job",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        _client(WrongModelClient()).ocr_image(
            image_bytes=b"png",
            content_type="image/png",
            request_id="request-1",
            mode="answer_region",
        )

