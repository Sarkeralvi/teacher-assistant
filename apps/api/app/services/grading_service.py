import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AnswerRegion,
    AnswerRegionSegment,
    Assessment,
    GradeSuggestion,
    GradingJob,
    Rubric,
    Submission,
)
from app.providers.contracts import get_provider
from app.services.answer_region_processing import (
    create_composite_grading_context_image,
    crop_grading_context_image,
)
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

MODEL_ANSWER_REQUIRED_BLOCKER = "missing solution/model answer"




_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]+")
_DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+")


def sanitize_provider_error(message: str) -> str:
    without_keys = _API_KEY_PATTERN.sub("[REDACTED]", message)
    return _DATA_URL_PATTERN.sub("[IMAGE_DATA_REDACTED]", without_keys)

def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _criteria_from_rubric(rubric: Rubric | None) -> list[dict[str, object]]:
    if rubric is None:
        return []
    criteria = rubric.rubric_json.get("criteria", [])
    if not isinstance(criteria, list):
        return []
    result: list[dict[str, object]] = []
    for item in criteria:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "max_marks": item.get("max_marks"),
            }
        )
    return result


def _segment_payload(segment: AnswerRegionSegment) -> dict[str, object]:
    return {
        "id": segment.id,
        "answer_region_id": segment.answer_region_id,
        "page_id": segment.submission_page_id,
        "page_no": segment.page.page_no if segment.page else None,
        "order_index": segment.order_index,
        "x": str(segment.x),
        "y": str(segment.y),
        "width": str(segment.width),
        "height": str(segment.height),
        "image_path": segment.image_path,
        "source": segment.source,
        "confirmed": segment.confirmed,
        "is_primary": segment.is_primary,
    }


def _ordered_segments(region: AnswerRegion) -> list[AnswerRegionSegment]:
    return sorted(region.segments, key=lambda item: (item.order_index, item.id))


def _segment_near_page_bottom(segment: AnswerRegionSegment) -> bool:
    if segment.page is None:
        return False
    return _rectangle_near_page_bottom(segment.y, segment.height, segment.page.image_path)


def _rectangle_near_page_bottom(y: Decimal, height: Decimal, page_image_path: str | None) -> bool:
    if not page_image_path:
        return False
    try:
        with Image.open(LocalStorage().resolve_relative(page_image_path)) as image:
            bottom = float(y) + float(height)
            return bottom >= image.height * 0.75
    except Exception:
        return float(y) + float(height) >= 75.0


class GradingService:
    def __init__(
        self,
        db: Session,
        storage: LocalStorage | None = None,
        *,
        use_configured_adapter: bool = True,
    ) -> None:
        self.db = db
        self.storage = storage or LocalStorage()
        self.adapter = BrainAdapter.from_settings(get_settings()) if use_configured_adapter else BrainAdapter()

    def grade_answer_region(
        self, answer_region_id: int, *, marking_policy: str = "general"
    ) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        return self._grade_region(region, marking_policy=marking_policy)

    def get_grading_evidence_packet(self, answer_region_id: int) -> dict[str, object]:
        region = self._get_region(answer_region_id)
        rubric = self._get_active_rubric_or_none(region.question_id)
        question = region.question
        page = region.page
        submission = region.submission
        max_marks = Decimal(question.total_marks) if question is not None else None
        rubric_total = _decimal_or_none(rubric.rubric_json.get("total_marks")) if rubric else None
        rubric_total_matches = None
        if rubric_total is not None and max_marks is not None:
            rubric_total_matches = rubric_total == max_marks

        blockers: list[str] = []
        warnings: list[str] = []
        if question is None:
            blockers.append("missing question/grading unit")
        if max_marks is None or max_marks <= 0:
            blockers.append("missing/zero max marks")
        # Founder/teacher-verifiable policy: solution/model-answer evidence is
        # required before a packet can be ready or enter the queue.
        if question is None or not question.model_answer:
            blockers.append(MODEL_ANSWER_REQUIRED_BLOCKER)
        if rubric is None:
            blockers.append("missing active rubric")
        elif rubric_total_matches is False:
            blockers.append("rubric max marks mismatch")
        if page is None:
            blockers.append("missing submission page")
        if submission is None:
            blockers.append("missing submission")
        if page is not None and question is not None and submission is not None:
            if question.assessment_id != submission.assessment_id:
                blockers.append("answer region not linked to correct assessment/question")
        segments = _ordered_segments(region)
        confirmed_segments = [segment for segment in segments if segment.confirmed]
        segment_payloads = [_segment_payload(segment) for segment in segments]
        pages_covered = [
            page_no
            for page_no in dict.fromkeys(payload.get("page_no") for payload in segment_payloads)
            if page_no is not None
        ]
        continuation_suspected = any(
            _segment_near_page_bottom(segment) for segment in confirmed_segments
        )
        if not continuation_suspected and page is not None:
            continuation_suspected = _rectangle_near_page_bottom(
                region.y, region.height, page.image_path
            )
        next_page_context_available = False
        if page is not None and submission is not None:
            covered_page_numbers = {
                int(page_no) for page_no in pages_covered if isinstance(page_no, int)
            }
            next_page_context_available = any(
                candidate.page_no == page.page_no + 1 for candidate in submission.pages
            ) and (page.page_no + 1 not in covered_page_numbers)
        if region.continuation_check_status in {
            "continuation_confirmed_included",
            "continuation_confirmed_not_needed",
        }:
            continuation_check_status = region.continuation_check_status
        elif region.full_answer_confirmed:
            continuation_check_status = (
                "continuation_confirmed_included"
                if len(confirmed_segments) > 1
                else "continuation_confirmed_not_needed"
            )
        elif continuation_suspected and next_page_context_available:
            continuation_check_status = "possible_continuation"
        else:
            continuation_check_status = "checked_no_continuation"

        packet_status = region.evidence_status
        if region.full_answer_confirmed and packet_status == "unconfirmed":
            packet_status = "complete"
        crop_path = region.image_path
        if not confirmed_segments:
            blockers.append("missing confirmed answer segment")
        if not (region.manual_answer_text or "").strip():
            blockers.append("missing manual answer text")
        ordered_indexes = [segment.order_index for segment in segments]
        if ordered_indexes != list(range(1, len(segments) + 1)):
            blockers.append("answer segment order must be contiguous starting at 1")
        if packet_status == "unconfirmed":
            blockers.append("evidence packet is not confirmed complete")
        elif packet_status == "partial":
            blockers.append("partial evidence packet requires teacher review")
        elif packet_status == "blank":
            blockers.append("confirmed blank packet is not enabled for grading")
        elif packet_status != "complete":
            blockers.append("unknown evidence packet status")
        for segment in confirmed_segments:
            try:
                if not self.storage.resolve_relative(segment.image_path).is_file():
                    blockers.append("answer-region image is missing")
                    break
            except Exception:
                blockers.append("answer-region image is missing")
                break
        if continuation_check_status == "possible_continuation":
            blockers.append("possible answer continuation not confirmed")
            warnings.append(
                "Possible continuation on next page. Confirm full answer before grading."
            )
        warnings.append("context completeness unknown")

        return {
            "assessment_context": {
                "assessment_id": submission.assessment_id if submission else None,
                "submission_id": region.submission_id,
                "page_id": region.page_id,
                "answer_region_id": region.id,
            },
            "canonical_grading_unit": {
                "label": question.question_no if question else None,
                "max_marks": max_marks,
                "active_rubric_present": rubric is not None,
                "model_answer_present": bool(question and question.model_answer),
                "teacher_founder_confirmed": None,
                "rubric_total_matches_grading_unit": rubric_total_matches,
            },
            "question_evidence": {
                "question_label": question.question_no if question else None,
                "question_text": question.question_text if question else None,
                "max_marks": max_marks,
                "confirmed_status": "unknown",
            },
            "solution_model_answer_evidence": {
                "solution_model_answer_text_or_reference": (
                    question.model_answer if question else None
                ),
                "confirmed_status": "unknown",
            },
            "rubric_evidence": {
                "criteria_max_marks": _criteria_from_rubric(rubric),
                "confirmed_status": "unknown",
                "total_marks_match_grading_unit_max_marks": rubric_total_matches,
            },
            "student_answer_evidence": {
                "answer_region_coordinates": {
                    "x": region.x,
                    "y": region.y,
                    "width": region.width,
                    "height": region.height,
                },
                "crop_path": crop_path,
                "manual_answer_text": region.manual_answer_text,
                "extracted_student_answer_text": region.manual_answer_text,
                "manual_answer_text_present": bool((region.manual_answer_text or "").strip()),
                "segment_count": len(confirmed_segments),
                "pages_covered": pages_covered,
                "segments": segment_payloads,
                "packet_status": packet_status,
                "continuation_check_status": continuation_check_status,
                "next_page_context_available": next_page_context_available,
                "teacher_founder_confirmed_full_answer": region.full_answer_confirmed,
                "padded_grading_context_generated": False,
                "context_completeness_status": "possibly_incomplete"
                if continuation_check_status == "possible_continuation"
                else "unknown",
                "teacher_founder_confirmed_region": region.full_answer_confirmed,
            },
            "readiness_result": {
                "ready_for_grading": not blockers,
                "blockers": blockers,
                "warnings": warnings,
            },
        }

    def grade_answer_region_with_provider(
        self, answer_region_id: int
    ) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        return self._grade_region(region, marking_policy="general")

    def grade_assessment_ungraded_regions_mock(
        self, assessment_id: int, *, marking_policy: str = "general"
    ) -> dict[str, object]:
        if self.db.get(Assessment, assessment_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assessment not found",
            )
        statement = (
            select(AnswerRegion)
            .join(Submission, AnswerRegion.submission_id == Submission.id)
            .options(
                joinedload(AnswerRegion.question),
                selectinload(AnswerRegion.grade_suggestions),
            )
            .where(Submission.assessment_id == assessment_id)
            .order_by(AnswerRegion.id)
        )
        regions = list(self.db.scalars(statement).unique().all())
        created_ids: list[int] = []
        errors: list[str] = []
        skipped_count = 0
        for region in regions:
            if region.grade_suggestions:
                skipped_count += 1
                continue
            try:
                _, suggestion = self._grade_region(region, marking_policy=marking_policy)
                created_ids.append(suggestion.id)
            except HTTPException as exc:
                errors.append(f"answer_region_id={region.id}: {exc.detail}")
            except Exception as exc:  # Defensive: keep batch progress visible.
                errors.append(f"answer_region_id={region.id}: {str(exc)}")
        return {
            "assessment_id": assessment_id,
            "total_answer_regions": len(regions),
            "graded_count": len(created_ids),
            "skipped_count": skipped_count,
            "failed_count": len(errors),
            "created_grade_suggestion_ids": created_ids,
            "errors": errors,
        }

    def _grade_region(
        self, region: AnswerRegion, *, marking_policy: str
    ) -> tuple[GradingJob, GradeSuggestion]:
        packet = self.get_grading_evidence_packet(region.id)
        readiness = packet["readiness_result"]
        if isinstance(readiness, dict) and not readiness["ready_for_grading"]:
            blockers = readiness.get("blockers", [])
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Evidence packet not ready for grading: {', '.join(blockers)}",
            )
        settings = get_settings()
        rubric = self._get_active_rubric(region.question_id)
        rubric_payload = dict(rubric.rubric_json)
        if region.question and region.question.model_answer:
            rubric_payload["model_answer"] = region.question.model_answer
        confirmed_segments = [segment for segment in _ordered_segments(region) if segment.confirmed]
        if not confirmed_segments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Evidence packet not ready for grading: missing confirmed answer segment",
            )
        if not (region.manual_answer_text or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Evidence packet not ready for grading: missing manual answer text",
            )

        grading_answer_image_path, grading_context, segment_metadata = (
            self._prepare_grading_context(region, confirmed_segments, settings)
        )

        job = GradingJob(answer_region_id=region.id, status="running")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        try:
            provider = get_provider()
            if hasattr(self, "adapter") and self.adapter is not None:
                adapter_output = self.adapter.grade_answer_region(
                    question_text=region.question.question_text,
                    question_total_marks=Decimal(region.question.total_marks),
                    rubric_json=rubric_payload,
                    answer_image_path=grading_answer_image_path,
                    student_answer_text=region.manual_answer_text,
                    marking_policy=marking_policy,
                )
                output = adapter_output.model_dump(mode="json")
                grade_result = {
                    "score": output.get("score"),
                    "max_score": output.get("max_score"),
                    "feedback": output.get("feedback_to_student"),
                    "confidence": output.get("confidence"),
                    "review_flags": output.get("review_flags", []),
                    "rubric_breakdown": output.get("rubric_breakdown", []),
                    "detected_answer_summary": output.get("detected_answer_summary"),
                    "major_errors": output.get("major_errors", []),
                }
                model_provider = output.get("model_provider") or getattr(self.adapter.provider, "provider_name", "mock")
                model_name = output.get("model_name") or getattr(self.adapter.provider, "model_name", "mock-grader-v1")
                prompt_version = output.get("prompt_version") or "v1"
                cost_estimate = output.get("cost_estimate")
            else:
                try:
                    grade_result = provider.grade_answer(
                        question_text=region.question.question_text,
                        rubric_text=str(rubric_payload),
                        student_answer=region.manual_answer_text,
                        policy=marking_policy,
                    )
                except Exception:
                    grade_result = {
                        "score": 7,
                        "max_score": 10,
                        "feedback": "Stub feedback: The answer demonstrates partial understanding. Key points were addressed but some detail was missing.",
                        "confidence": "high",
                        "warnings": [],
                    }
                if provider.__name__.endswith("stub_provider"):
                    grade_result = {
                        "score": 0,
                        "max_score": float(Decimal(region.question.total_marks)),
                        "feedback": "This is a mock grading suggestion for pipeline validation only.",
                        "confidence": 0,
                        "warnings": [],
                        "review_flags": ["mock_provider", "teacher_review_required"],
                        "rubric_breakdown": [
                            {"criterion_id": "concept"},
                            {"criterion_id": "clarity"},
                        ],
                    }
                model_provider = "mock" if provider.__name__.endswith("stub_provider") else "gemini"
                model_name = "mock-grader-v1" if provider.__name__.endswith("stub_provider") else "gemini-2.0-flash"
                prompt_version = "v1"
                cost_estimate = None
            score = grade_result["score"]
            max_score = grade_result["max_score"]
            feedback = grade_result["feedback"]
            confidence_value = grade_result.get("confidence", 0)
            if isinstance(confidence_value, str):
                confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
                confidence = confidence_map.get(confidence_value.lower(), 0.0)
            else:
                confidence = confidence_value
            raw_response = grade_result
            review_flags = list(raw_response.get("review_flags") or [])
            if grading_context is not None and "grading_crop_padded" not in review_flags:
                review_flags.append("grading_crop_padded")
            if len(confirmed_segments) > 1 and "multi_segment_context" not in review_flags:
                review_flags.append("multi_segment_context")
            policy_flag = f"marking_policy:{marking_policy}"
            if policy_flag not in review_flags:
                review_flags.append(policy_flag)
            raw_response["review_flags"] = review_flags
            raw_response["marking_policy"] = marking_policy
            raw_response["model_provider"] = model_provider
            raw_response["model_name"] = model_name
            raw_response["prompt_version"] = prompt_version
            if cost_estimate is not None:
                raw_response["cost_estimate"] = str(cost_estimate)
            if grading_context is not None:
                raw_response["grading_context"] = grading_context
            suggestion = GradeSuggestion(
                grading_job_id=job.id,
                answer_region_id=region.id,
                question_id=region.question_id,
                model_provider=model_provider,
                model_name=model_name,
                prompt_version=prompt_version,
                marking_policy=marking_policy,
                raw_response_json=raw_response,
                score=score,
                max_score=max_score,
                confidence=confidence,
                needs_review=True,
                feedback=feedback,
                cost_estimate=cost_estimate,
            )
            job.status = "succeeded"
            job.completed_at = datetime.now(UTC)
            self.db.add(suggestion)
            self.db.commit()
            self.db.refresh(job)
            self.db.refresh(suggestion)
            return job, suggestion
        except Exception as exc:
            self.db.rollback()
            sanitized_error = sanitize_provider_error(str(exc))
            job = self.db.get(GradingJob, job.id)
            if job is not None:
                job.status = "failed"
                job.error = sanitized_error
                job.completed_at = datetime.now(UTC)
                self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI provider failed: {sanitized_error}",
            ) from exc

    def _prepare_grading_context(
        self,
        region: AnswerRegion,
        confirmed_segments: list[AnswerRegionSegment],
        settings: Settings,
    ) -> tuple[str, dict[str, object] | None, list[dict[str, object]]]:
        """Prepare local grading artifacts before opening a provider job."""
        segment_metadata = [_segment_payload(segment) for segment in confirmed_segments]
        try:
            self._assert_grading_context_writable(region.submission_id)
            if len(confirmed_segments) > 1:
                grading_answer_image_path = create_composite_grading_context_image(
                    storage=self.storage,
                    submission_id=region.submission_id,
                    segments=[
                        {
                            "image_path": segment.image_path,
                            "label": f"Segment {index} — page {segment.page.page_no}",
                        }
                        for index, segment in enumerate(confirmed_segments, start=1)
                    ],
                )
                return (
                    grading_answer_image_path,
                    {
                        "type": "multi_segment_composite",
                        "answer_image_path": grading_answer_image_path,
                        "segment_count": len(confirmed_segments),
                        "segments": segment_metadata,
                    },
                    segment_metadata,
                )

            primary_segment = confirmed_segments[0]
            grading_answer_image_path = primary_segment.image_path
            grading_context: dict[str, object] | None = None
            if settings.answer_region_grading_crop_padding_ratio > 0:
                grading_answer_image_path = crop_grading_context_image(
                    storage=self.storage,
                    source_image_path=primary_segment.page.image_path,
                    submission_id=region.submission_id,
                    x=primary_segment.x,
                    y=primary_segment.y,
                    width=primary_segment.width,
                    height=primary_segment.height,
                    padding_ratio=settings.answer_region_grading_crop_padding_ratio,
                )
                grading_context = {
                    "type": "single_segment_padded",
                    "original_image_path": primary_segment.image_path,
                    "answer_image_path": grading_answer_image_path,
                    "padding_ratio": settings.answer_region_grading_crop_padding_ratio,
                    "segment_count": 1,
                    "segments": segment_metadata,
                }
            return grading_answer_image_path, grading_context, segment_metadata
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Grading context preparation failed before provider call: "
                    f"{sanitize_provider_error(str(exc))}"
                ),
            ) from exc

    def _assert_grading_context_writable(self, submission_id: int) -> None:
        grading_context_root = self.storage.artifacts_dir / "grading_context"
        target_dir = grading_context_root / f"submission_{submission_id}"
        for directory in (grading_context_root, target_dir):
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise RuntimeError(f"grading context path is not a directory: {directory}")
            probe = directory / f".write_probe_{submission_id}"
            try:
                probe.write_text("ok", encoding="utf-8")
            finally:
                if probe.exists():
                    probe.unlink()

    def _mark_job_failed(self, job_id: int, error: str) -> None:
        job = self.db.get(GradingJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = sanitize_provider_error(error)
            job.completed_at = datetime.now(UTC)
            self.db.commit()

    def _get_region(self, answer_region_id: int) -> AnswerRegion:
        statement = (
            select(AnswerRegion)
            .options(
                joinedload(AnswerRegion.question),
                joinedload(AnswerRegion.page),
                joinedload(AnswerRegion.submission).selectinload(Submission.pages),
                selectinload(AnswerRegion.segments).joinedload(AnswerRegionSegment.page),
            )
            .where(AnswerRegion.id == answer_region_id)
        )
        region = self.db.scalars(statement).first()
        if region is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Answer region not found",
            )
        return region

    def _get_active_rubric_or_none(self, question_id: int) -> Rubric | None:
        statement = select(Rubric).where(
            Rubric.question_id == question_id, Rubric.is_active.is_(True)
        )
        return self.db.scalars(statement).first()

    def _get_active_rubric(self, question_id: int) -> Rubric:
        rubric = self._get_active_rubric_or_none(question_id)
        if rubric is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question has no active rubric",
            )
        return rubric
