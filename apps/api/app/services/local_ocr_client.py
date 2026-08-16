from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DATA_URL_PATTERN = re.compile(
    r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", re.IGNORECASE
)


class LocalOcrConfigurationError(RuntimeError):
    pass


class OcrBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    order: int = Field(ge=1)
    label: str
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None


class LocalOcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    mode: Literal["document", "answer_region"]
    text: str
    normalized_text: str
    markdown: str
    blocks: list[OcrBlock]
    warnings: list[str]
    provider: Literal["local_paddle_qwen"]
    model: str
    layout_model: str
    version: str
    device: Literal["cpu", "gpu:0"]
    latency_ms: int = Field(ge=0)
    engine: Literal["paddleocr_vl", "ppocr_v6"] = "paddleocr_vl"
    preprocessing_profile: str = "default"


class LocalOcrClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_image_bytes: int,
        client: Any | None = None,
    ) -> None:
        _assert_loopback_url(base_url)
        if not api_key:
            raise LocalOcrConfigurationError("LOCAL_OCR_API_KEY is required")
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.max_image_bytes = max_image_bytes
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> LocalOcrClient:
        resolved = settings or get_settings()
        if not resolved.brain_allow_real_providers:
            raise LocalOcrConfigurationError(
                "BRAIN_ALLOW_REAL_PROVIDERS must be true before local OCR can initialize"
            )
        if not resolved.local_ocr_enabled:
            raise LocalOcrConfigurationError("LOCAL_OCR_ENABLED must be true")
        return cls(
            base_url=resolved.local_ocr_base_url,
            api_key=resolved.local_ocr_api_key,
            timeout_seconds=resolved.local_ocr_timeout_seconds,
            max_image_bytes=resolved.local_ocr_max_image_bytes,
        )

    def health(self) -> dict[str, Any]:
        try:
            response = self.client.get("health", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(self._sanitize(str(exc))) from exc
        if not isinstance(payload, dict) or payload.get("status") != "ready":
            raise RuntimeError("Local OCR health response is invalid")
        return payload

    def ocr_image(
        self,
        *,
        image_bytes: bytes,
        content_type: Literal["image/png", "image/jpeg"],
        request_id: str,
        mode: Literal["document", "answer_region"],
        prompt_label: Literal["ocr", "formula"] = "ocr",
        engine: Literal["paddleocr_vl", "ppocr_v6"] = "paddleocr_vl",
        preprocessing_profile: str = "default",
    ) -> LocalOcrResult:
        if not image_bytes:
            raise ValueError("OCR image is empty")
        if len(image_bytes) > self.max_image_bytes:
            raise ValueError("OCR image exceeds the configured size limit")
        try:
            response = self.client.post(
                "v1/ocr",
                headers={
                    **self._headers(),
                    "Content-Type": content_type,
                    "X-Request-ID": request_id,
                    "X-OCR-Mode": mode,
                    "X-OCR-Prompt-Label": prompt_label,
                    "X-OCR-Engine": engine,
                    "X-OCR-Preprocessing-Profile": preprocessing_profile,
                },
                content=image_bytes,
            )
            response.raise_for_status()
            return LocalOcrResult.model_validate(response.json())
        except ValidationError:
            raise RuntimeError("Local OCR returned an invalid response schema") from None
        except Exception as exc:
            raise RuntimeError(self._sanitize(str(exc))) from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _sanitize(self, message: str) -> str:
        sanitized = message.replace(self.api_key, "[REDACTED]")
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", sanitized)


def _assert_loopback_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise LocalOcrConfigurationError(
            "Local OCR base URL must use HTTP on a loopback host"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LocalOcrConfigurationError("Local OCR base URL contains unsupported components")
