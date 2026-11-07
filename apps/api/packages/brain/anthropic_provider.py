"""Claude (Anthropic API) brain provider: the production model for Teacher Assistant v2.

Founder decision 2026-11-07 (``docs/decisions/2026-11-07-claude-api.md``): the
Anthropic API is the production model provider and full scanned pages are sent.
Everything this provider returns is draft evidence for teacher review. Nothing
here can create or imply a final mark.

Contract notes, all enforced below and covered by tests:

* Structured output uses ``output_config.format`` with a JSON schema derived from
  the same Pydantic models every other provider is validated against, so the
  workflow services never learn which transport ran.
* No sampling parameters are sent (the current API version rejects them) and
  thinking is left to the model's adaptive default; depth is controlled per
  task through ``output_config.effort``.
* A refusal, a ``max_tokens`` truncation, an unexpected stop reason or an
  unexpected serving model raises instead of returning a partial or substituted
  result. The only exception is grading, where the server-side refusal fallback
  may serve the request and the draft is then flagged for teacher review.
* Every call is reported to registered observers with tokens, cost, latency,
  request id and the model that actually served it. Observers never receive
  prompt or response text.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.brain.agentic_cli import normalize_cli_grade_payload
from packages.brain.capabilities import (
    BrainCapability,
    BrainExecutionLocation,
    BrainImageInputMode,
    BrainTransport,
)
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy
from packages.brain.transcript_assignment import (
    FullTranscriptAssignmentOutput,
    build_full_transcript_assignment_prompt,
    normalize_full_transcript_assignment,
    validate_full_transcript_assignment,
)
from packages.brain.universal_vision import (
    UniversalVisionCompletion,
    UniversalVisionProviderMixin,
    repair_page_read_geometry,
)

logger = logging.getLogger(__name__)

ANTHROPIC_PROVIDER_NAME = "anthropic"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Claude's documented high-resolution vision ceiling: 2576 px on the long edge and
# about 3.75 megapixels. Larger images are downscaled here, deterministically, so
# the evidence the teacher inspects and the evidence the model read stay aligned.
MAX_IMAGE_LONG_EDGE_PX = 2576
MAX_IMAGE_PIXELS = 3_750_000
MAX_IMAGE_BYTES = 3_750_000

_SUPPORTED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_SUPPORTED_STRING_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "uri",
        "ipv4",
        "ipv6",
        "uuid",
    }
)
# Constraints that Claude structured outputs do not accept. They are removed from
# the schema sent to the API and still enforced client-side by Pydantic.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "default",
        "examples",
        "title",
        "discriminator",
    }
)
_NAMED_SUBSCHEMA_KEYS = frozenset({"properties", "$defs", "definitions", "patternProperties"})

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

DEFAULT_TASK_EFFORT: dict[str, str] = {
    "visual_page_read": "medium",
    "visual_reference_bundle": "high",
    "transcript_assignment": "medium",
    "grading": "high",
    "visual_page_mapping": "medium",
    "visual_transcription": "medium",
    "visual_transcription_repair": "high",
    "question_pdf_extraction": "high",
    "rubric_pdf_extraction": "high",
}

_SYSTEM_PROMPT = (
    "You assist a teacher-controlled grading system for handwritten mathematics exams. "
    "Follow the task instructions exactly. Report only what is visible in the supplied "
    "images or text; never invent, solve, correct or complete student work unless the "
    "task explicitly asks you to grade it. Every result is a draft for teacher review. "
    "Return only the requested JSON."
)

_GRADE_OUTPUT_INSTRUCTION = "\nReturn only the grade-suggestion JSON object."

# Successful key+model checks: sha256(key), model -> monotonic time of the check.
MODEL_VERIFY_TTL_SECONDS = 600.0
_VERIFIED_MODELS: dict[tuple[str, str], float] = {}

# The worker job envelope (packages/brain/policy.py) adds 60 s and is capped at
# 3600 s, so one provider call, with every SDK retry, must fit in 3540 s.
MAX_PROVIDER_ENVELOPE_SECONDS = 3540.0
# Allowance per SDK retry for its backoff wait, including a server Retry-After.
RETRY_WAIT_ALLOWANCE_SECONDS = 60.0
# A served model may differ from the configured id only by a dated snapshot suffix.
_SNAPSHOT_SUFFIX = re.compile(r"-\d{8}$")


class AnthropicProviderError(RuntimeError):
    """Raised when a Claude call cannot satisfy the draft-evidence contract.

    Messages carry only metadata (task, status, request id, counts). Exceptions
    that may contain student text or request content are never chained.
    """


class SpendLimitReached(AnthropicProviderError):
    """A registered spend guard refused the next call before anything was sent."""


# ---------------------------------------------------------------------------
# Spend guards (checked before every call; nothing is sent when one refuses)
# ---------------------------------------------------------------------------

SpendGuard = Callable[[str], None]
_SPEND_GUARDS: list[SpendGuard] = []


def register_spend_guard(guard: SpendGuard) -> Callable[[], None]:
    """Run ``guard(task)`` before each call; it raises SpendLimitReached to refuse."""

    _SPEND_GUARDS.append(guard)

    def unregister() -> None:
        if guard in _SPEND_GUARDS:
            _SPEND_GUARDS.remove(guard)

    return unregister


# ---------------------------------------------------------------------------
# Call observation (tokens, cost, latency; never prompt or response text)
# ---------------------------------------------------------------------------

CallObserver = Callable[[dict[str, Any]], None]
_CALL_OBSERVERS: list[CallObserver] = []


def register_call_observer(observer: CallObserver) -> Callable[[], None]:
    """Receive one metadata record per Claude call. Returns an unregister function."""

    _CALL_OBSERVERS.append(observer)

    def unregister() -> None:
        if observer in _CALL_OBSERVERS:
            _CALL_OBSERVERS.remove(observer)

    return unregister


def _emit_call_record(record: dict[str, Any]) -> None:
    logger.info(
        "anthropic_call task=%s model=%s served=%s stop=%s in=%s out=%s "
        "cache_write=%s cache_read=%s cost_usd=%s latency_ms=%s request_id=%s",
        record.get("task"),
        record.get("model_requested"),
        record.get("model_served"),
        record.get("stop_reason"),
        record.get("input_tokens"),
        record.get("output_tokens"),
        record.get("cache_creation_input_tokens"),
        record.get("cache_read_input_tokens"),
        record.get("cost_usd"),
        record.get("latency_ms"),
        record.get("request_id"),
    )
    for observer in list(_CALL_OBSERVERS):
        try:
            observer(dict(record))
        except Exception:  # an observer must never break a model call
            logger.exception("anthropic call observer failed")


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnthropicPricing:
    """USD per million tokens. Defaults are Claude Opus 5.5 list prices."""

    input_per_mtok: Decimal = Decimal("4.00")
    output_per_mtok: Decimal = Decimal("20.00")
    cache_write_per_mtok: Decimal = Decimal("5.00")
    cache_read_per_mtok: Decimal = Decimal("0.20")

    def cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> Decimal:
        million = Decimal(1_000_000)
        total = (
            Decimal(input_tokens) * self.input_per_mtok
            + Decimal(output_tokens) * self.output_per_mtok
            + Decimal(cache_creation_input_tokens) * self.cache_write_per_mtok
            + Decimal(cache_read_input_tokens) * self.cache_read_per_mtok
        ) / million
        return total.quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------
# Schema and image preparation
# ---------------------------------------------------------------------------


def claude_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the model's JSON schema restricted to what Claude structured outputs accept.

    Unsupported constraints are removed (Pydantic still enforces them on the
    response) and every object is closed with ``additionalProperties: false``.
    A free-form object cannot be expressed, so it raises instead of silently
    forcing an empty object.
    """

    return _sanitize_schema_node(copy.deepcopy(model.model_json_schema()))


def _sanitize_schema_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_sanitize_schema_node(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "format" and value not in _SUPPORTED_STRING_FORMATS:
            continue
        if key in _NAMED_SUBSCHEMA_KEYS and isinstance(value, dict):
            cleaned[key] = {name: _sanitize_schema_node(sub) for name, sub in value.items()}
            continue
        cleaned[key] = _sanitize_schema_node(value)
    if cleaned.get("type") == "object" or "properties" in cleaned:
        additional = cleaned.get("additionalProperties", False)
        if additional is not False:
            raise ValueError(
                "Claude structured outputs require closed objects; "
                "a free-form object field cannot be expressed"
            )
        cleaned["additionalProperties"] = False
    return cleaned


def prepare_image_for_claude(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Fit an image inside Claude's vision limits without altering orientation.

    Images already inside the limits and in a supported format are passed
    through byte-for-byte. Larger ones are downscaled (never upscaled) and
    re-encoded as PNG, or JPEG when PNG would still be too large.
    """

    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            opened.load()
            image = opened.copy()
    except Exception as exc:  # corrupt or unsupported image bytes
        raise ValueError("Image bytes could not be decoded for Claude vision input") from exc
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Image has no pixels")
    scale = min(
        1.0,
        MAX_IMAGE_LONG_EDGE_PX / max(width, height),
        math.sqrt(MAX_IMAGE_PIXELS / (width * height)),
    )
    resized = scale < 1.0
    if resized:
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    if (
        not resized
        and mime_type in _SUPPORTED_IMAGE_MEDIA_TYPES
        and len(image_bytes) <= MAX_IMAGE_BYTES
    ):
        return image_bytes, mime_type
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    if buffer.tell() <= MAX_IMAGE_BYTES:
        return buffer.getvalue(), "image/png"
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    if buffer.tell() > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large for Claude vision input even after re-encoding")
    return buffer.getvalue(), "image/jpeg"


def _image_block(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    data, media_type = prepare_image_for_claude(image_bytes, mime_type)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


# ---------------------------------------------------------------------------
# Grade draft schema (model-authored fields only)
# ---------------------------------------------------------------------------


class _AnthropicRubricBreakdownDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    criterion_status: str = Field(min_length=1)
    max_marks: Decimal = Field(ge=Decimal("0"))
    awarded_marks: Decimal = Field(ge=Decimal("0"))
    reason: str = Field(min_length=1)
    evidence: str | None = None
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


class _AnthropicGradeSuggestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: bool = True
    rubric_breakdown: list[_AnthropicRubricBreakdownDraft] = Field(min_length=1)
    detected_answer_summary: str = Field(min_length=1)
    major_errors: list[str] = Field(default_factory=list)
    feedback_to_student: str = Field(
        default="Teacher review is required before feedback is released.",
        min_length=1,
    )
    review_flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


@dataclass
class _CallRecord:
    task: str
    model_requested: str
    model_served: str
    request_id: str | None
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    image_count: int = 0
    effort: str = ""
    fallback_served: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def as_observation(self) -> dict[str, Any]:
        return {
            "provider": ANTHROPIC_PROVIDER_NAME,
            "task": self.task,
            "model_requested": self.model_requested,
            "model_served": self.model_served,
            "request_id": self.request_id,
            "stop_reason": self.stop_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": str(self.cost_usd),
            "latency_ms": self.latency_ms,
            "image_count": self.image_count,
            "effort": self.effort,
            "fallback_served": self.fallback_served,
        }


class AnthropicApiProvider(UniversalVisionProviderMixin, BrainProvider):
    """Claude through the official Anthropic SDK, behind the provider-neutral contracts."""

    provider_name = ANTHROPIC_PROVIDER_NAME
    execution_location = BrainExecutionLocation.CLOUD
    transport = BrainTransport.HTTP
    # Grading is always text-only from saved, teacher-reviewable transcripts.
    # Visual tasks receive image bytes directly through their own contracts.
    image_input_mode = BrainImageInputMode.NONE
    capabilities = frozenset(
        {
            BrainCapability.GRADING,
            BrainCapability.OCR_ANSWER_MAPPING,
            BrainCapability.QUESTION_PDF_EXTRACTION,
            BrainCapability.RUBRIC_PDF_EXTRACTION,
            BrainCapability.VISUAL_REFERENCE_EXTRACTION,
            BrainCapability.VISUAL_MAPPING,
            BrainCapability.VISUAL_PAGE_READ,
            BrainCapability.VISUAL_TRANSCRIPTION,
            BrainCapability.TRANSCRIPTION_REPAIR,
        }
    )

    def __init__(
        self,
        *,
        api_key: str = "",
        model_name: str = DEFAULT_ANTHROPIC_MODEL,
        timeout_seconds: float = 120.0,
        call_deadline_seconds: float = 900.0,
        max_retries: int = 2,
        max_output_tokens: int = 32000,
        task_effort: dict[str, str] | None = None,
        refusal_fallback_enabled: bool = True,
        pricing: AnthropicPricing | None = None,
        client: Any | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("ANTHROPIC_API_KEY is required for the anthropic profile")
        if timeout_seconds <= 0 or call_deadline_seconds <= 0:
            raise ValueError("Anthropic timeouts must be positive")
        if max_retries < 0:
            raise ValueError("Anthropic max_retries cannot be negative")
        if max_output_tokens < 1024:
            raise ValueError("Anthropic max_output_tokens must be at least 1024")
        # Worst case for one call: every attempt waits the full silence timeout,
        # every retry waits its allowance, and the final stream runs to the
        # wall-clock deadline. The worker job must outlive all of it.
        envelope = (
            float(call_deadline_seconds)
            + float(timeout_seconds) * (int(max_retries) + 1)
            + RETRY_WAIT_ALLOWANCE_SECONDS * int(max_retries)
            + 30.0
        )
        if envelope > MAX_PROVIDER_ENVELOPE_SECONDS:
            raise ValueError(
                f"Claude call settings need up to {envelope:.0f} s per call, more than the "
                f"{MAX_PROVIDER_ENVELOPE_SECONDS:.0f} s a worker job allows; lower "
                "ANTHROPIC_CALL_DEADLINE_SECONDS, ANTHROPIC_TIMEOUT_SECONDS or "
                "ANTHROPIC_MAX_RETRIES"
            )
        efforts = dict(DEFAULT_TASK_EFFORT)
        for task, effort in (task_effort or {}).items():
            normalized = str(effort).strip().lower()
            if normalized not in VALID_EFFORTS:
                raise ValueError(f"Unsupported Claude effort for {task}: {effort}")
            efforts[task] = normalized
        self.api_key = api_key
        self.model_name = (model_name or DEFAULT_ANTHROPIC_MODEL).strip()
        self.request_timeout_seconds = float(timeout_seconds)
        self.call_deadline_seconds = float(call_deadline_seconds)
        self.max_retries = int(max_retries)
        # The worker job envelope (packages/brain/policy.py) is derived from this
        # attribute, so it covers every SDK attempt and the final stream.
        self.timeout_seconds = envelope
        self.max_output_tokens = int(max_output_tokens)
        self.task_effort = efforts
        self.refusal_fallback_enabled = bool(refusal_fallback_enabled)
        self.pricing = pricing or AnthropicPricing()
        self._client = client

    # -- SDK client -----------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=self.request_timeout_seconds,
                max_retries=self.max_retries,
            )
        return self._client

    def verify_available_model(self) -> None:
        """Check the key and model without running inference (no tokens billed).

        The workflow calls this before every execution hold. A success is cached per
        key and model for a few minutes, so a run fails fast on a bad key without
        adding a second request to every page read and grade.
        """

        cache_key = (hashlib.sha256(self.api_key.encode("utf-8")).hexdigest(), self.model_name)
        verified_at = _VERIFIED_MODELS.get(cache_key)
        if verified_at is not None and time.monotonic() - verified_at < MODEL_VERIFY_TTL_SECONDS:
            return
        try:
            info = self.client.models.retrieve(self.model_name)
        except Exception as exc:
            raise AnthropicProviderError(_describe_sdk_error(exc)) from None
        served = str(getattr(info, "id", "") or "")
        if served and not _model_matches(self.model_name, served):
            raise AnthropicProviderError(
                f"Configured Claude model {self.model_name} resolved to {served}"
            )
        _VERIFIED_MODELS[cache_key] = time.monotonic()

    # -- Universal vision transport ---------------------------------------------

    def _complete_structured_vision(
        self,
        *,
        prompt: str,
        images: list[tuple[bytes, str]],
        response_model: type[BaseModel] | None,
        schema_name: str,
        max_tokens: int | None = None,
    ) -> UniversalVisionCompletion:
        # ``max_tokens`` budgets were sized for non-thinking local models. Claude
        # thinks adaptively and thinking counts toward max_tokens, so a provider
        # ceiling is used instead and truncation still fails closed.
        del max_tokens
        content: list[dict[str, Any]] = [
            _image_block(image_bytes, mime_type) for image_bytes, mime_type in images
        ]
        content.append({"type": "text", "text": prompt})
        completion, _record = self._structured_call(
            task=schema_name,
            system=_SYSTEM_PROMPT,
            content=content,
            response_model=response_model,
            image_count=len(images),
        )
        return completion

    # -- Transcript assignment (text only) ----------------------------------------

    def map_submission_answers_from_ocr_pages(
        self,
        *,
        pages: list[dict[str, Any]],
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = build_full_transcript_assignment_prompt(pages=pages, questions=questions)
        completion, _record = self._structured_call(
            task="transcript_assignment",
            system=_SYSTEM_PROMPT,
            content=prompt,
            response_model=FullTranscriptAssignmentOutput,
        )
        payload = FullTranscriptAssignmentOutput.model_validate(completion.payload)
        payload = normalize_full_transcript_assignment(payload, pages=pages)
        validate_full_transcript_assignment(payload, pages=pages, questions=questions)
        return payload.model_dump(mode="json")

    # -- Grading (text only) -------------------------------------------------------

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: ModelPolicy = ModelPolicy.REAL_GRADING,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del question_text, question_total_marks, rubric_json, answer_image_path
        del student_answer_text, task_name, model_policy, marking_policy
        if image_data_url:
            raise ValueError("Claude grading is text-only; image input must stay disabled")
        if not messages:
            raise ValueError("Claude grading requires the adapter-built grading prompt")
        system = "\n\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "system"
        ).strip()
        user = "\n\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") != "system"
        ).strip()
        if not user:
            raise ValueError("Claude grading prompt has no user content")
        completion, record = self._structured_call(
            task="grading",
            system=system or _SYSTEM_PROMPT,
            content=user + _GRADE_OUTPUT_INSTRUCTION,
            response_model=_AnthropicGradeSuggestionDraft,
            allow_fallback=True,
        )
        payload, not_met_removed = _zero_not_met_criteria(completion.payload)
        raw = normalize_cli_grade_payload(payload)
        raw.update(
            {
                "model_provider": self.provider_name,
                "model_name": record.model_served or self.model_name,
                "prompt_version": prompt_version,
                "needs_review": True,
                "cost_estimate": record.cost_usd,
                "latency_ms": record.latency_ms,
                "prompt_tokens": record.total_input_tokens,
                "completion_tokens": record.output_tokens,
                "total_tokens": record.total_input_tokens + record.output_tokens,
            }
        )
        flags = [str(flag) for flag in (raw.get("review_flags") or [])]
        required_flags = ["teacher_review_required", "anthropic_api_provider"]
        if not_met_removed:
            required_flags.append("not_met_criterion_credit_removed")
        if record.fallback_served:
            required_flags.append(f"served_by_fallback_model:{record.model_served}")
        for flag in required_flags:
            if flag not in flags:
                flags.append(flag)
        raw["review_flags"] = list(dict.fromkeys(flags))
        if record.fallback_served:
            raw["confidence"] = min(Decimal(str(raw.get("confidence", 0))), Decimal("0.5"))
        try:
            return GradeSuggestionOutput.model_validate(raw)
        except ValidationError as exc:
            # Pydantic messages echo input values (quoted student text): never chain them.
            raise AnthropicProviderError(
                "Claude grading response did not satisfy the grade contract: "
                f"{exc.error_count()} validation error(s)"
            ) from None

    # -- Core call ---------------------------------------------------------------

    def _structured_call(
        self,
        *,
        task: str,
        system: str,
        content: str | list[dict[str, Any]],
        response_model: type[BaseModel] | None,
        image_count: int = 0,
        allow_fallback: bool = False,
    ) -> tuple[UniversalVisionCompletion, _CallRecord]:
        effort = self.task_effort.get(task, "medium")
        output_config: dict[str, Any] = {"effort": effort}
        if response_model is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": claude_json_schema(response_model),
            }
        params: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": output_config,
        }
        use_fallback = allow_fallback and self.refusal_fallback_enabled
        for guard in list(_SPEND_GUARDS):
            guard(task)
        started = time.perf_counter()
        try:
            message, request_id = self._send(params, use_fallback=use_fallback)
        except AnthropicProviderError:
            raise
        except Exception as exc:
            # The SDK exception (and anything it chains) stays out of tracebacks;
            # its status, request id and API error text are kept in the message.
            raise AnthropicProviderError(_describe_sdk_error(exc)) from None
        latency_ms = int((time.perf_counter() - started) * 1000)

        record = self._record(
            message,
            task=task,
            latency_ms=latency_ms,
            image_count=image_count,
            effort=effort,
            request_id=request_id,
        )
        model_ok = _model_matches(self.model_name, record.model_served)
        if not model_ok and use_fallback:
            record.fallback_served = True
        _emit_call_record(record.as_observation())

        stop_reason = record.stop_reason
        if stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise AnthropicProviderError(
                f"Claude declined the {task} request (refusal category: {category}); "
                "the item needs teacher handling"
            )
        if stop_reason == "max_tokens":
            raise AnthropicProviderError(
                f"Claude output for {task} reached max_tokens={self.max_output_tokens}; "
                "the truncated result was discarded"
            )
        if stop_reason not in {"end_turn", "stop_sequence"}:
            raise AnthropicProviderError(
                f"Claude {task} call ended with unexpected stop_reason={stop_reason}"
            )
        if not model_ok and not record.fallback_served:
            raise AnthropicProviderError(
                f"Claude {task} call was served by {record.model_served}, "
                f"not the configured {self.model_name}"
            )

        text = _response_text(message)
        payload = _parse_json_payload(text, structured=response_model is not None, task=task)
        if response_model is not None:
            payload = _validate_payload(payload, response_model, task=task)
        completion = UniversalVisionCompletion(
            payload=payload,
            latency_ms=latency_ms,
            prompt_tokens=record.total_input_tokens,
            completion_tokens=record.output_tokens,
        )
        return completion, record

    def _send(self, params: dict[str, Any], *, use_fallback: bool) -> tuple[Any, str | None]:
        """Stream one request under a wall-clock deadline.

        Streaming keeps long thinking plus long JSON inside the SDK's read
        timeout, but that timeout only bounds silence between events. The
        deadline bounds the whole call so the worker job can never be killed
        mid-stream; leaving the ``with`` block closes the connection.
        """

        started = time.monotonic()
        context = (
            self.client.beta.messages.stream(
                **params,
                betas=[REFUSAL_FALLBACK_BETA],
                fallbacks="default",
            )
            if use_fallback
            else self.client.messages.stream(**params)
        )
        with context as stream:
            for _event in stream:
                if time.monotonic() - started > self.call_deadline_seconds:
                    raise AnthropicProviderError(
                        f"Claude call exceeded its {self.call_deadline_seconds:.0f} s deadline; "
                        "the partial response was discarded"
                    )
            return stream.get_final_message(), getattr(stream, "request_id", None)

    def _record(
        self,
        message: Any,
        *,
        task: str,
        latency_ms: int,
        image_count: int,
        effort: str,
        request_id: str | None = None,
    ) -> _CallRecord:
        usage = getattr(message, "usage", None)
        input_tokens = _int_attr(usage, "input_tokens")
        output_tokens = _int_attr(usage, "output_tokens")
        cache_write = _int_attr(usage, "cache_creation_input_tokens")
        cache_read = _int_attr(usage, "cache_read_input_tokens")
        return _CallRecord(
            task=task,
            model_requested=self.model_name,
            model_served=str(getattr(message, "model", "") or ""),
            request_id=request_id or getattr(message, "_request_id", None),
            stop_reason=getattr(message, "stop_reason", None),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
            cost_usd=self.pricing.cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_write,
                cache_read_input_tokens=cache_read,
            ),
            latency_ms=latency_ms,
            image_count=image_count,
            effort=effort,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_matches(requested: str, served: str) -> bool:
    """Exact id, or that id plus a dated snapshot suffix; anything else is a substitution."""

    requested = (requested or "").strip()
    served = (served or "").strip()
    if not served or not requested:
        return False
    if served == requested:
        return True
    return served.startswith(requested) and bool(
        _SNAPSHOT_SUFFIX.fullmatch(served[len(requested):])
    )


def _validate_payload(
    payload: dict[str, Any], response_model: type[BaseModel], *, task: str
) -> dict[str, Any]:
    """Validate against the app contract without chaining Pydantic's input echoes."""

    try:
        return response_model.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        repaired = repair_page_read_geometry(payload, response_model, exc)
        error_count = exc.error_count()
    if repaired is not None:
        try:
            return response_model.model_validate(repaired).model_dump(mode="json")
        except ValidationError as exc:
            error_count = exc.error_count()
    raise AnthropicProviderError(
        f"Claude {task} response did not satisfy its contract: "
        f"{error_count} validation error(s)"
    )


def _int_attr(source: Any, name: str) -> int:
    value = getattr(source, name, None) if source is not None else None
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _response_text(message: Any) -> str:
    """Join every text block in order, skipping thinking and ``fallback`` markers.

    When a streamed request is declined mid-output, the declined model's partial
    text stays in ``content``, a ``fallback`` block marks the switch, and the
    fallback model continues that same text. The answer is the concatenation.
    """

    parts = [
        str(getattr(block, "text", "") or "")
        for block in getattr(message, "content", None) or []
        if getattr(block, "type", None) == "text"
    ]
    if not parts:
        raise AnthropicProviderError("Claude response contained no text block")
    return "".join(parts)


def _parse_json_payload(text: str, *, structured: bool, task: str) -> dict[str, Any]:
    candidate = text.strip()
    if not structured and candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # The decode error carries the whole response text; do not chain it.
        raise AnthropicProviderError(f"Claude {task} response was not valid JSON") from None
    if not isinstance(parsed, dict):
        raise AnthropicProviderError(f"Claude {task} response must be a JSON object")
    return parsed


def _zero_not_met_criteria(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """A criterion the model itself marks not_met can never carry marks."""

    raw = dict(payload)
    items = raw.get("rubric_breakdown")
    if not isinstance(items, list):
        return raw, False
    changed = False
    updated: list[Any] = []
    for item in items:
        if (
            isinstance(item, dict)
            and str(item.get("criterion_status", "")).strip().lower() == "not_met"
            and Decimal(str(item.get("awarded_marks", 0))) > 0
        ):
            item = {**item, "awarded_marks": "0", "evidence": None}
            changed = True
        updated.append(item)
    if changed:
        raw["rubric_breakdown"] = updated
        raw["score"] = str(
            sum(
                (
                    Decimal(str(item.get("awarded_marks", 0)))
                    for item in updated
                    if isinstance(item, dict)
                ),
                Decimal("0"),
            )
        )
        raw["confidence"] = str(min(Decimal(str(raw.get("confidence", 0))), Decimal("0.75")))
    return raw, changed


def _describe_sdk_error(exc: Exception) -> str:
    """Name the failure for operators without echoing request content or credentials."""

    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    if request_id is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            try:
                request_id = headers.get("request-id")
            except Exception:
                request_id = None
    detail = str(getattr(exc, "message", "") or exc)[:500]
    parts = [f"Claude API call failed: {name}"]
    if status is not None:
        parts.append(f"status={status}")
    if request_id:
        parts.append(f"request_id={request_id}")
    if detail:
        parts.append(detail)
    return " ".join(parts)
