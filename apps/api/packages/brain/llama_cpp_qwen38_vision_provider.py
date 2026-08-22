"""LlamaCppQwen38VisionProvider — Qwen3.8-27B multimodal local provider.

Architecture
------------
This provider wraps the llama.cpp OpenAI-compatible server running the
Qwen3.8-27B-Q4_K_M GGUF (alias ``qwen3.8-27b-q4km``) on port 8085.

Two operations are exposed:

1. ``transcribe_image()``
   Accepts application-owned PNG/JPEG bytes (never URLs), encodes them as a
   base64 data URL, and returns a ``VisualTranscriptionOutput`` draft.
   This operation cannot grade or confirm its own output.

2. ``grade()`` (implements BrainProvider.grade)
   Starts in a fresh context with no image.  Receives only teacher-confirmed
   transcription text, the question, rubric, and marking policy.
   Always returns ``needs_review=True``.

Safety invariants
-----------------
* Zero retries — one call, one result, explicit failure on any HTTP error.
* No fallback to any other provider.
* Sanitized errors: API key and raw student text are stripped from all
  raised messages before they propagate.
* Raw student image bytes are never stored in logs; the SHA256 is recorded
  in the response for audit.
* ``verify_available_model()`` asserts the exact alias; raises on mismatch.
* Disabled by default; protected by ``BRAIN_ALLOW_REAL_PROVIDERS``.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
from copy import deepcopy
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.brain.llama_cpp_qwen_provider import QwenReferenceBundlePayload
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, ModelPolicy, RubricBreakdownItem
from packages.brain.schemas_qwen38 import (
    UncertainGlyph,
    VisualPageMappingOutput,
    VisualTranscriptionOutput,
)

# ── Constants ──────────────────────────────────────────────────────────────
PROVIDER_NAME = "llama_cpp_qwen38"
EXPECTED_ALIAS = "qwen3.8-27b-q4km"

_TRANSCRIBE_MAX_TOKENS = 2048
_GRADE_MAX_TOKENS = 1500

# Reference-bundle completion budget is sized per request, not a flat
# constant: a real multi-question, multi-criterion bundle needs more room to
# describe in schema-constrained JSON as page count grows, but the prompt
# also grows with page count (each rendered page costs up to
# _IMAGE_MAX_TOKENS_PER_PAGE tokens), so the two must be balanced against the
# server's actual context window rather than guessed independently. Schema-
# constrained decoding stops at the JSON's natural end regardless of the
# requested ceiling, so a generous budget costs nothing on small bundles and
# only matters as a truncation guard on larger ones.
_REFERENCE_BUNDLE_BASE_TOKENS = 1500
_REFERENCE_BUNDLE_TOKENS_PER_PAGE = 1000
_REFERENCE_BUNDLE_MIN_TOKENS = 1500
_REFERENCE_BUNDLE_MAX_TOKENS_CEILING = 6500
# Must match --image-max-tokens on the running llama-server (Start-LocalAi.ps1).
_IMAGE_MAX_TOKENS_PER_PAGE = 1280
_REFERENCE_BUNDLE_PROMPT_OVERHEAD_TOKENS = 300
_CONTEXT_SAFETY_MARGIN_TOKENS = 500

# Patterns used for error sanitization
_API_KEY_PATTERN = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_DATA_URL_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


# ── Internal Pydantic schemas for structured grading ──────────────────────


class _Qwen38RubricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    criterion_status: Literal["met", "partially_met", "not_met"]
    max_marks: Decimal = Field(ge=Decimal("0"))
    awarded_marks: Decimal = Field(ge=Decimal("0"))
    reason: str = Field(min_length=1)
    evidence: str | None = None
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def awarded_not_above_max(self) -> _Qwen38RubricItem:
        if self.awarded_marks > self.max_marks:
            raise ValueError("awarded_marks cannot exceed max_marks")
        return self


class _Qwen38GradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=Decimal("0"))
    max_score: Decimal = Field(gt=Decimal("0"))
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]
    rubric_breakdown: list[_Qwen38RubricItem] = Field(min_length=1)
    detected_answer_summary: str = Field(min_length=1)
    major_errors: list[str]
    feedback_to_student: str = Field(min_length=1)
    review_flags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reconcile(self) -> _Qwen38GradePayload:
        if self.score > self.max_score:
            raise ValueError("score cannot exceed max_score")
        # Reconcile not_met items that still claim marks
        for item in self.rubric_breakdown:
            if item.criterion_status == "not_met" and item.awarded_marks != 0:
                item.awarded_marks = Decimal("0")
                item.confidence = min(item.confidence, Decimal("0.75"))
                if "criterion_status_reconciled" not in self.review_flags:
                    self.review_flags.append("criterion_status_reconciled")
        total = sum((i.awarded_marks for i in self.rubric_breakdown), Decimal("0"))
        if total != self.score:
            self.score = total
            self.confidence = min(self.confidence, Decimal("0.75"))
            if "score_reconciled_from_breakdown" not in self.review_flags:
                self.review_flags.append("score_reconciled_from_breakdown")
        return self


class _Qwen38TranscriptionPayload(BaseModel):
    """Structured output the model returns for visual transcription."""

    model_config = ConfigDict(extra="forbid")

    draft_text: str
    uncertain_glyphs: list[dict[str, Any]] = Field(default_factory=list)
    is_blank: bool
    is_irrelevant: bool
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    needs_review: Literal[True]


# ── JSON-schema helpers ───────────────────────────────────────────────────


def _prefer_json_numbers(value: Any) -> Any:
    """Remove Pydantic regex-string Decimal alternatives (llama.cpp grammar compat)."""
    if isinstance(value, list):
        return [_prefer_json_numbers(v) for v in value]
    if not isinstance(value, dict):
        return value
    normalized = {k: _prefer_json_numbers(v) for k, v in value.items()}
    alternatives = normalized.get("anyOf")
    if not isinstance(alternatives, list):
        return normalized
    has_number = any(isinstance(o, dict) and o.get("type") == "number" for o in alternatives)
    if not has_number:
        return normalized
    filtered = [
        o
        for o in alternatives
        if not (isinstance(o, dict) and o.get("type") == "string" and "pattern" in o)
    ]
    if len(filtered) == len(alternatives):
        return normalized
    if len(filtered) == 1:
        excluded = {"anyOf", "type", "minimum", "maximum"}
        meta = {k: v for k, v in normalized.items() if k not in excluded}
        return {**filtered[0], **meta}
    normalized["anyOf"] = filtered
    return normalized


def _llama_cpp_json_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    return _prefer_json_numbers(deepcopy(response_model.model_json_schema()))


# ── Main provider class ───────────────────────────────────────────────────


class LlamaCppQwen38VisionProvider(BrainProvider):
    """Qwen3.8-27B multimodal provider backed by a local llama.cpp server.

    Parameters
    ----------
    api_key:
        Bearer token for the llama.cpp server (``LLAMA_API_KEY``).
    model_name:
        Expected model alias.  Must be ``qwen3.8-27b-q4km``.
    base_url:
        Base URL of the llama.cpp server, e.g. ``http://127.0.0.1:8085/v1``.
    timeout_seconds:
        Request timeout in seconds.  Default 900.
    context_tokens:
        The running llama-server's context window (its ``-c`` value). Used to
        keep reference-bundle completion budgets from exceeding what the
        server can actually hold. Default 12288.
    """

    provider_name = PROVIDER_NAME
    model_name = EXPECTED_ALIAS

    # ── Construction ──────────────────────────────────────────────────────

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = EXPECTED_ALIAS,
        base_url: str = "http://127.0.0.1:8085/v1",
        timeout_seconds: float = 900.0,
        grading_reasoning_mode: str = "off",
        context_tokens: int = 12288,
        require_model_lease: bool = True,
    ) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        hostname = parsed.hostname or ""
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"LOCAL_QWEN38_BASE_URL must be a loopback address; got '{base_url}'")
        if not api_key:
            raise ValueError("LOCAL_QWEN38_API_KEY must be set")
        if model_name != EXPECTED_ALIAS:
            raise ValueError(f"LOCAL_QWEN38_MODEL must be '{EXPECTED_ALIAS}'; got '{model_name}'")
        if context_tokens < 12288:
            raise ValueError("LOCAL_QWEN38_CONTEXT_TOKENS must be at least 12288")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.context_tokens = context_tokens
        normalized_reasoning = grading_reasoning_mode.strip().lower()
        if normalized_reasoning not in {"off", "low"}:
            raise ValueError("LOCAL_QWEN38_GRADING_REASONING_MODE must be 'off' or 'low'")
        self.grading_reasoning_mode = normalized_reasoning
        self.require_model_lease = require_model_lease
        self.client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client(
                base_url=self.base_url + "/",
                timeout=self.timeout,
                trust_env=False,
                follow_redirects=False,
            )
        return self.client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _sanitize(self, message: str) -> str:
        """Strip API key and raw image data from error messages."""
        msg = message.replace(self.api_key, "[REDACTED]")
        msg = _API_KEY_PATTERN.sub("[REDACTED]", msg)
        return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", msg)

    # ── Model verification ─────────────────────────────────────────────────

    def verify_available_model(self) -> None:
        """Assert that the server is serving exactly EXPECTED_ALIAS.

        Raises RuntimeError if the alias is absent or the server is unreachable.
        """
        try:
            resp = self._http().get(
                "/models",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"llama_cpp_qwen38_vision: /v1/models request failed — {self._sanitize(str(exc))}"
            ) from exc

        model_ids = [entry.get("id") for entry in data.get("data", [])]
        if EXPECTED_ALIAS not in model_ids:
            raise RuntimeError(
                f"llama_cpp_qwen38_vision: model alias '{EXPECTED_ALIAS}' not found in "
                f"/v1/models. Available: {model_ids}"
            )

    # ── Structured completion helper ───────────────────────────────────────

    def _structured_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        schema_name: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        enable_thinking: bool = False,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Call /v1/chat/completions with JSON grammar and parse the result.

        Returns the validated Pydantic model and the usage dict.
        Raises ValueError for schema violations, RuntimeError for HTTP errors.
        Zero retries — callers handle failure explicitly.
        """
        if self.require_model_lease:
            from app.services.local_model_call_guard import (
                assert_local_model_call_authorized,
            )

            assert_local_model_call_authorized(model_phase="Qwen38")
        schema = _llama_cpp_json_schema(response_model)
        body: dict[str, Any] = {
            "model": EXPECTED_ALIAS,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": enable_thinking,
                "preserve_thinking": False,
            },
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
        }
        try:
            resp = self._http().post(
                "/chat/completions",
                json=body,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"llama_cpp_qwen38_vision: completion request failed — {self._sanitize(str(exc))}"
            ) from exc

        usage = data.get("usage") or {}
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"llama_cpp_qwen38_vision: empty choices in response ({usage})")
        finish_reason = choices[0].get("finish_reason")
        content = (choices[0].get("message") or {}).get("content") or ""
        # Included on every failure below so a truncated/malformed response is
        # diagnosable from the stored error message alone, without needing to
        # re-run the call or inspect server logs for token counts.
        diagnostics = (
            f"finish_reason={finish_reason} prompt_tokens={usage.get('prompt_tokens')} "
            f"completion_tokens={usage.get('completion_tokens')} "
            f"requested_max_tokens={max_tokens}"
        )
        if not content.strip():
            raise ValueError(f"llama_cpp_qwen38_vision: empty content in response ({diagnostics})")

        try:
            import json as _json

            parsed = _json.loads(content)
        except Exception as exc:
            if finish_reason == "length":
                raise ValueError(
                    "llama_cpp_qwen38_vision: response was cut off before finishing — the "
                    f"model needs a larger token budget for this input ({diagnostics})"
                ) from exc
            raise ValueError(
                "llama_cpp_qwen38_vision: response is not valid JSON — "
                f"{self._sanitize(str(exc))} ({diagnostics})"
            ) from exc

        try:
            validated = response_model.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError(
                "llama_cpp_qwen38_vision: response schema mismatch — "
                f"{self._sanitize(str(exc))} ({diagnostics})"
            ) from exc

        return validated, usage

    @staticmethod
    def _image_part(image_bytes: bytes, mime_type: str) -> tuple[dict[str, Any], str]:
        if mime_type not in {"image/png", "image/jpeg"}:
            raise ValueError("Visual Qwen accepts only PNG or JPEG images")
        if not image_bytes:
            raise ValueError("Visual Qwen image bytes must not be empty")
        if mime_type == "image/png" and image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("image bytes claim PNG but magic bytes are invalid")
        if mime_type == "image/jpeg" and image_bytes[:2] != b"\xff\xd8":
            raise ValueError("image bytes claim JPEG but magic bytes are invalid")
        digest = hashlib.sha256(image_bytes).hexdigest()
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        return {"type": "image_url", "image_url": {"url": data_url}}, digest

    # ── Visual transcription ───────────────────────────────────────────────

    def transcribe_image(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        label: str = "answer",
    ) -> VisualTranscriptionOutput:
        """Verbatim transcription of a handwritten student answer image.

        Parameters
        ----------
        image_bytes:
            Raw PNG or JPEG bytes owned by the application.  Never a URL.
        mime_type:
            ``"image/png"`` or ``"image/jpeg"``.
        label:
            Human-readable label used in the prompt (e.g. ``"1(a)(i)"``).

        Returns
        -------
        VisualTranscriptionOutput
            Draft transcription.  ``needs_review`` is always ``True``.
            Cannot grade or confirm itself.

        Raises
        ------
        ValueError
            If image_bytes is not a real PNG/JPEG, or model output is invalid.
        RuntimeError
            If the HTTP call fails.
        """
        return self.transcribe_images(images=[(image_bytes, mime_type)], label=label)

    def transcribe_images(
        self,
        *,
        images: list[tuple[bytes, str]],
        label: str = "answer",
    ) -> VisualTranscriptionOutput:
        """Transcribe ordered answer segments in one fresh, non-thinking visual call."""
        if not images:
            raise ValueError("At least one answer image is required")
        image_parts: list[dict[str, Any]] = []
        image_hashes: list[str] = []
        for image_bytes, mime_type in images:
            part, digest = self._image_part(image_bytes, mime_type)
            image_parts.append(part)
            image_hashes.append(digest)

        _TRANSCRIPTION_PROMPT = (
            f"Perform strict verbatim transcription of the ordered answer images for {label}.\n"
            "Do not solve, correct, complete, simplify, summarize, or reinterpret anything.\n"
            "Preserve every written mistake, line order, numeral, decimal point, fraction,\n"
            "conditional bar, complement bar, intersection, unit and crossed-out item.\n"
            "Use LaTeX for mathematics. If a glyph is ambiguous, return bounded alternatives\n"
            "marked uncertain. Never infer a character from arithmetic consistency.\n\n"
            "If the answer region is genuinely blank, set is_blank=true and draft_text to an "
            "empty string. Do not use a placeholder such as [blank].\n\n"
            "Return your answer as JSON matching the required schema."
        )

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _TRANSCRIPTION_PROMPT},
                    *image_parts,
                ],
            }
        ]

        start = time.perf_counter()
        payload, usage = self._structured_completion(
            messages=messages,
            response_model=_Qwen38TranscriptionPayload,
            schema_name="visual_transcription",
            max_tokens=_TRANSCRIBE_MAX_TOKENS,
            temperature=0.0,
            enable_thinking=False,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        assert isinstance(payload, _Qwen38TranscriptionPayload)

        # Build uncertain_glyphs from raw dicts
        uncertain_glyphs: list[UncertainGlyph] = []
        for raw in payload.uncertain_glyphs:
            try:
                uncertain_glyphs.append(UncertainGlyph.model_validate(raw))
            except Exception:
                pass  # malformed uncertain glyph — skip, lower confidence

        return VisualTranscriptionOutput(
            draft_text=payload.draft_text,
            uncertain_glyphs=uncertain_glyphs,
            is_blank=payload.is_blank,
            is_irrelevant=payload.is_irrelevant,
            confidence=payload.confidence,
            needs_review=True,
            model_provider=self.provider_name,
            model_name=self.model_name,
            image_sha256=hashlib.sha256("".join(image_hashes).encode("ascii")).hexdigest(),
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    def map_page_answer_regions(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        question_labels: list[str],
        open_continuations: list[str] | None = None,
    ) -> VisualPageMappingOutput:
        """Locate one union box per visible finalized answer label on a page.

        The caller supplies canonical labels so handwritten headers are never used as identity.
        """
        if not question_labels:
            raise ValueError("Finalized question labels are required for visual mapping")
        image_part, _digest = self._image_part(image_bytes, mime_type)
        labels = ", ".join(question_labels)
        continuation_hint = ", ".join(open_continuations or []) or "none"
        prompt = (
            "This is a complete exam-script page. Map only visible student answer segments to "
            "the supplied FINALIZED labels. Return at most one union bounding box per label on "
            "this page, never one box per line. Boxes use normalized [x1,y1,x2,y2] coordinates "
            "from 0 to 1000 and must include all handwriting for the visible segment. Exclude "
            "blank margins, borders, bleed-through, and colored teacher marks. Do not transcribe, "
            "solve, grade, or use a handwritten header as the identity. Mark continuation flags "
            "when the answer visibly continues between pages. Every result needs review.\n\n"
            f"FINALIZED LABELS: {labels}\n"
            f"OPEN CONTINUATIONS FROM PREVIOUS PAGE: {continuation_hint}"
        )
        payload, _usage = self._structured_completion(
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}, image_part],
                }
            ],
            response_model=VisualPageMappingOutput,
            schema_name="visual_page_mapping",
            max_tokens=900,
            temperature=0.0,
            enable_thinking=False,
        )
        assert isinstance(payload, VisualPageMappingOutput)
        known = {label.casefold() for label in question_labels}
        if any(region.question_label.casefold() not in known for region in payload.regions):
            raise ValueError("Visual mapping returned an unknown finalized question label")
        return payload

    def _reference_bundle_token_budget(self, total_pages: int) -> int:
        """Size the completion budget to the input, bounded by real context room.

        More pages need more room to describe in JSON, but also leave less
        context room for that JSON (each page costs prompt tokens too). Both
        sides of that trade-off are computed here instead of guessing one
        fixed ceiling that is wrong for both small and large bundles.
        """
        content_need = (
            _REFERENCE_BUNDLE_BASE_TOKENS + _REFERENCE_BUNDLE_TOKENS_PER_PAGE * total_pages
        )
        prompt_estimate = (
            total_pages * _IMAGE_MAX_TOKENS_PER_PAGE + _REFERENCE_BUNDLE_PROMPT_OVERHEAD_TOKENS
        )
        context_room = self.context_tokens - prompt_estimate - _CONTEXT_SAFETY_MARGIN_TOKENS
        budget = min(content_need, context_room, _REFERENCE_BUNDLE_MAX_TOKENS_CEILING)
        if budget < _REFERENCE_BUNDLE_MIN_TOKENS:
            raise ValueError(
                f"llama_cpp_qwen38_vision: {total_pages} reference pages leave only "
                f"~{max(context_room, 0)} completion tokens in a {self.context_tokens}-token "
                "context — too little room to extract safely in one call. Upload fewer pages, "
                "or raise LOCAL_QWEN38_CONTEXT_TOKENS if VRAM allows it."
            )
        return budget

    def extract_reference_bundle_from_images(
        self, *, documents: dict[str, list[tuple[bytes, str, int]]]
    ) -> dict[str, Any]:
        """Extract draft references directly from rendered local document pages."""
        if set(documents) != {"QUESTION", "SOLUTION", "RUBRIC"}:
            raise ValueError("Question, solution, and rubric page images are all required")
        total_pages = sum(len(pages) for pages in documents.values())
        max_tokens = self._reference_bundle_token_budget(total_pages)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Read the following local exam materials. QUESTION pages define "
                    "question labels "
                    "and wording; SOLUTION pages define worked model answers; RUBRIC pages define "
                    "criteria and marks. Extract one editable draft per gradable leaf question. "
                    "Never solve or invent missing text, marks, or criteria. Preserve mathematics. "
                    "Every output needs teacher review. Return strict JSON only."
                ),
            }
        ]
        for document_name in ("QUESTION", "SOLUTION", "RUBRIC"):
            for image_bytes, mime_type, page_number in documents[document_name]:
                image_part, _digest = self._image_part(image_bytes, mime_type)
                content.append({"type": "text", "text": f"{document_name} PAGE {page_number}"})
                content.append(image_part)
        payload, usage = self._structured_completion(
            messages=[{"role": "user", "content": content}],
            response_model=QwenReferenceBundlePayload,
            schema_name="qwen38_visual_reference_bundle",
            max_tokens=max_tokens,
            temperature=0.0,
            enable_thinking=False,
        )
        assert isinstance(payload, QwenReferenceBundlePayload)
        result = payload.model_dump(mode="json")
        result["usage"] = usage
        return result

    # ── Grading ───────────────────────────────────────────────────────────

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
        """Grade a student answer from teacher-confirmed transcription text.

        The model receives NO image.  It receives:
        - teacher-confirmed transcription text (``student_answer_text``)
        - question text
        - rubric JSON
        - marking policy

        A pending draft suggestion is created; ``needs_review`` is always ``True``.
        Never creates a final grade.
        """
        del answer_image_path, task_name, model_policy, image_data_url

        if not (student_answer_text or "").strip():
            raise ValueError(
                "llama_cpp_qwen38_vision: teacher-confirmed transcription "
                "text is required for grading"
            )
        if not messages:
            raise ValueError("llama_cpp_qwen38: a fresh grading prompt is required")

        payload, usage = self._structured_completion(
            messages=messages or [],
            response_model=_Qwen38GradePayload,
            schema_name="grade_suggestion",
            max_tokens=_GRADE_MAX_TOKENS,
            enable_thinking=self.grading_reasoning_mode == "low",
        )
        assert isinstance(payload, _Qwen38GradePayload)
        self._validate_grade_contract(payload, question_total_marks, rubric_json)

        flags = list(payload.review_flags)
        for required_flag in ("teacher_review_required", "image_input_disabled", "local_provider"):
            if required_flag not in flags:
                flags.append(required_flag)

        return GradeSuggestionOutput(
            score=payload.score,
            max_score=payload.max_score,
            confidence=payload.confidence,
            needs_review=True,
            rubric_breakdown=[
                RubricBreakdownItem.model_validate(i.model_dump(exclude={"criterion_status"}))
                for i in payload.rubric_breakdown
            ],
            detected_answer_summary=payload.detected_answer_summary,
            major_errors=payload.major_errors,
            feedback_to_student=payload.feedback_to_student,
            review_flags=flags,
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=Decimal("0"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )

    @staticmethod
    def _validate_grade_contract(
        payload: _Qwen38GradePayload,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
    ) -> None:
        if payload.max_score != question_total_marks:
            raise ValueError("Qwen3.8 changed the question maximum score")
        if payload.score > question_total_marks:
            raise ValueError("Qwen3.8 awarded more than the question maximum")
        criteria = rubric_json.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("Active rubric criteria are required for Qwen3.8 grading")
        expected = {
            str(item.get("id")): Decimal(str(item.get("max_marks")))
            for item in criteria
            if isinstance(item, dict)
            and item.get("id") is not None
            and item.get("max_marks") is not None
        }
        actual = {item.criterion_id: item for item in payload.rubric_breakdown}
        if set(actual) != set(expected):
            raise ValueError("Qwen3.8 rubric breakdown does not match the pinned rubric")
        for criterion_id, maximum in expected.items():
            if actual[criterion_id].max_marks != maximum:
                raise ValueError("Qwen3.8 changed a pinned rubric criterion maximum")
        awarded_total = sum(
            (item.awarded_marks for item in payload.rubric_breakdown), Decimal("0")
        )
        if awarded_total != payload.score:
            raise ValueError("Qwen3.8 score does not equal its rubric breakdown")
