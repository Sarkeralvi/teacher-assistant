"""Bounded synthetic smoke for the rescued Paddle -> Qwen3.6 workflow.

This script creates no assessment, grade suggestion, or final grade. It uses
the production lease/phase/provider code and prints only model identities,
counts, hashes, and draft metadata. The PowerShell launcher supplies explicit
per-provider authorization flags and stops every model in a finally block.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import traceback
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.local_ai_phase_manager import LocalAiPhaseManager
from app.services.local_model_lease_service import LocalModelLeaseService
from app.services.local_ocr_client import LocalOcrClient
from packages.brain.adapter import BrainAdapter


def persist_result(path: Path | None, result: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def synthetic_image() -> bytes:
    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"
    heading = ImageFont.truetype(str(font_path), 52)
    answer = ImageFont.truetype(str(font_path), 72)
    final = ImageFont.truetype(str(font_path), 58)
    draw.text((70, 80), "Question 1", fill="black", font=heading)
    draw.text((70, 190), "12 + 8 = 20", fill="black", font=answer)
    draw.text((70, 310), "Final answer: 20", fill="black", font=final)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-paddle", action="store_true")
    parser.add_argument("--allow-qwen36", action="store_true")
    parser.add_argument("--allow-qwen38-rescue", action="store_true")
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    if not args.allow_paddle or not args.allow_qwen36:
        raise SystemExit("The bounded Paddle and Qwen3.6 calls require explicit flags")

    settings = get_settings()
    if settings.cohort_model_grading_enabled:
        raise SystemExit("Cohort model grading must remain disabled during the smoke")
    image_bytes = synthetic_image()
    result: dict[str, object] = {
        "synthetic_image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "provider_calls": {"paddle": 0, "qwen36": 0, "qwen38_rescue": 0},
        "final_grade_created": False,
        "stage": "prepared",
        "success": False,
    }
    persist_result(args.result_path, result)
    db = SessionLocal()
    lease = LocalModelLeaseService(db)
    phase_manager = LocalAiPhaseManager(settings=settings, db=db)
    try:
        paddle_holder = f"hybrid_smoke:paddle:{uuid4().hex}"
        with lease.hold(
            model_phase="PaddleOcr",
            holder_kind="host_smoke",
            holder_id=paddle_holder,
        ):
            phase_manager.switch("PaddleOcr", lease_holder_id=paddle_holder)
            ocr = LocalOcrClient.from_settings(settings)
            health = ocr.health()
            paddle_result = ocr.ocr_image(
                image_bytes=image_bytes,
                content_type="image/png",
                request_id=f"hybrid-smoke-{uuid4().hex}",
                mode="answer_region",
            )
            result["paddle"] = {
                "model": health["model"],
                "layout_model": health["layout_model"],
                "device": health["device"],
                "nonblank": bool(paddle_result.normalized_text.strip()),
                "text_sha256": hashlib.sha256(
                    paddle_result.normalized_text.encode("utf-8")
                ).hexdigest(),
                "latency_ms": paddle_result.latency_ms,
            }
            result["provider_calls"]["paddle"] = 1  # type: ignore[index]
            result["stage"] = "paddle_completed"
            persist_result(args.result_path, result)

        qwen_holder = f"hybrid_smoke:qwen36:{uuid4().hex}"
        with lease.hold(
            model_phase="Qwen",
            holder_kind="host_smoke",
            holder_id=qwen_holder,
        ):
            phase_manager.switch("Qwen", lease_holder_id=qwen_holder)
            adapter = BrainAdapter.for_provider(settings, "llama_cpp_qwen")
            reference_bundle = adapter.extract_reference_bundle_from_ocr_documents(
                {
                    "question_paper": [
                        {
                            "page": 1,
                            "text": (
                                "Question 1. Calculate 12 + 8 and state the final "
                                "answer. [5 marks]"
                            ),
                        }
                    ],
                    "solution": [
                        {"page": 1, "text": "Question 1. 12 + 8 = 20. Final answer: 20."}
                    ],
                    "rubric": [
                        {
                            "page": 1,
                            "text": (
                                "Question 1: correct calculation and final answer "
                                "20 - 5 marks."
                            ),
                        }
                    ],
                }
            )
            result["provider_calls"]["qwen36"] = 1  # type: ignore[index]
            reference_questions = reference_bundle.get("questions", [])
            result["qwen36_reference_probe"] = {
                "reference_count": len(reference_questions),
                "needs_review": bool(
                    len(reference_questions) == 1
                    and reference_questions[0].get("needs_review")
                ),
                "has_model_answer": bool(
                    len(reference_questions) == 1
                    and reference_questions[0].get("model_answer")
                ),
                "criterion_count": (
                    len(reference_questions[0].get("criteria", []))
                    if len(reference_questions) == 1
                    else 0
                ),
                "blocker_count": (
                    len(reference_questions[0].get("blockers", []))
                    if len(reference_questions) == 1
                    else 0
                ),
            }
            result["stage"] = "qwen36_reference_returned"
            persist_result(args.result_path, result)
            if len(reference_questions) != 1:
                raise ValueError("Synthetic reference correlation did not return one question")
            reference = reference_questions[0]
            if not reference.get("needs_review"):
                raise ValueError("Synthetic reference correlation bypassed teacher review")
            if not reference.get("model_answer"):
                raise ValueError("Synthetic reference correlation did not link the model answer")
            result["stage"] = "qwen36_reference_completed"
            persist_result(args.result_path, result)

            mapping = adapter.map_submission_answers_from_ocr_pages(
                pages=[
                    {
                        "page": 1,
                        "blocks": [
                            {"order": 1, "text": "Question 1"},
                            {"order": 2, "text": "12 + 8 = 20. Final answer: 20."},
                        ],
                    }
                ],
                questions=[
                    {
                        "question_id": 1,
                        "question_no": str(reference["question_number"]),
                        "question_text": str(reference["question_text"]),
                    }
                ],
            )
            mappings = mapping.get("mappings", [])
            if (
                len(mappings) != 1
                or mappings[0].get("status") not in {"mapped", "uncertain"}
                or not mappings[0].get("needs_review")
            ):
                raise ValueError("Synthetic answer mapping was not review-required and mapped")
            result["provider_calls"]["qwen36"] = 2  # type: ignore[index]
            result["stage"] = "qwen36_mapping_completed"
            persist_result(args.result_path, result)

            draft = adapter.grade_answer_region(
                question_text="Calculate 12 + 8 and state the final answer.",
                question_total_marks=Decimal("5"),
                rubric_json={
                    "total_marks": "5",
                    "criteria": [
                        {
                            "id": "calculation",
                            "name": "Correct calculation",
                            "description": "Adds 12 and 8 and states 20.",
                            "max_marks": "5",
                        }
                    ],
                },
                answer_image_path="[synthetic-image-disabled]",
                student_answer_text="12 + 8 = 20. Final answer: 20.",
                marking_policy="general",
            )
            result["qwen36"] = {
                "model": draft.model_name,
                "provider": draft.model_provider,
                "score": str(draft.score),
                "max_score": str(draft.max_score),
                "needs_review": draft.needs_review,
                "image_input_disabled": True,
                "latency_ms": draft.latency_ms,
                "reference_count": len(reference_questions),
                "reference_needs_review": bool(reference.get("needs_review")),
                "mapped_count": len(mappings),
                "mapping_needs_review": bool(mappings[0].get("needs_review")),
            }
            result["provider_calls"]["qwen36"] = 3  # type: ignore[index]
            result["stage"] = "qwen36_completed"
            persist_result(args.result_path, result)

        if args.allow_qwen38_rescue:
            if not settings.local_qwen38_transcription_enabled:
                raise SystemExit("Qwen3.8 transcription rescue is disabled")
            rescue_holder = f"hybrid_smoke:qwen38:{uuid4().hex}"
            with lease.hold(
                model_phase="Qwen38",
                holder_kind="host_smoke",
                holder_id=rescue_holder,
            ):
                phase_manager.switch("Qwen38", lease_holder_id=rescue_holder)
                rescue_adapter = BrainAdapter.for_provider(settings, "llama_cpp_qwen38")
                rescue = rescue_adapter.provider.transcribe_image(
                    image_bytes=image_bytes,
                    mime_type="image/png",
                    label="synthetic answer",
                )
                result["qwen38_rescue"] = {
                    "model": rescue.model_name,
                    "provider": rescue.model_provider,
                    "nonblank": not rescue.is_blank,
                    "draft_sha256": hashlib.sha256(
                        rescue.draft_text.encode("utf-8")
                    ).hexdigest(),
                    "needs_review": rescue.needs_review,
                    "reasoning_mode": "off",
                    "latency_ms": rescue.latency_ms,
                }
                result["provider_calls"]["qwen38_rescue"] = 1  # type: ignore[index]
                result["stage"] = "qwen38_rescue_completed"
                persist_result(args.result_path, result)
        result["stage"] = "completed"
        result["success"] = True
        persist_result(args.result_path, result)
    except Exception as exc:
        result["stage"] = "failed"
        result["error_type"] = type(exc).__name__
        result["error_fingerprint"] = hashlib.sha256(
            "".join(traceback.format_exception_only(type(exc), exc)).encode("utf-8")
        ).hexdigest()
        persist_result(args.result_path, result)
        raise
    finally:
        db.close()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
