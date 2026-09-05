"""Shared validation helpers for isolated agentic CLI provider transports."""

from __future__ import annotations

from typing import Any

from packages.brain.schemas import GradeSuggestionOutput


def finalize_cli_grade_output(
    payload: dict[str, Any],
    *,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    provider_flag: str,
) -> GradeSuggestionOutput:
    """Attach trusted metadata, enforce review flags, and validate model-authored JSON."""

    raw = dict(payload)
    raw.update(
        {
            "model_provider": provider_name,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "needs_review": True,
            "cost_estimate": raw.get("cost_estimate", 0),
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    )
    flags = list(raw.get("review_flags") or [])
    for flag in ("teacher_review_required", provider_flag, "image_input_used"):
        if flag not in flags:
            flags.append(flag)
    raw["review_flags"] = flags
    return GradeSuggestionOutput.model_validate(raw)
