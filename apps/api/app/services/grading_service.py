from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import get_settings
from app.models import AnswerRegion, Assessment, GradeSuggestion, GradingJob, Rubric, Submission
from app.services.answer_region_processing import crop_grading_context_image
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter, sanitize_provider_error
from packages.brain.codex_cli_provider import CodexCliProvider


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
        self.adapter = (
            BrainAdapter.from_settings(get_settings()) if use_configured_adapter else BrainAdapter()
        )

    def grade_answer_region(
        self, answer_region_id: int, *, marking_policy: str = "general"
    ) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        return self._grade_region(region, self.adapter, marking_policy=marking_policy)

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
        crop_path = region.image_path
        if not crop_path:
            blockers.append("answer-region image is missing")
        else:
            try:
                if not self.storage.resolve_relative(crop_path).is_file():
                    blockers.append("answer-region image is missing")
            except Exception:
                blockers.append("answer-region image is missing")
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
                "padded_grading_context_generated": False,
                "context_completeness_status": "unknown",
                "teacher_founder_confirmed_region": None,
            },
            "readiness_result": {
                "ready_for_grading": not blockers,
                "blockers": blockers,
                "warnings": warnings,
            },
        }

    def grade_answer_region_with_codex_cli(
        self, answer_region_id: int
    ) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        settings = get_settings()
        codex_adapter = BrainAdapter(
            CodexCliProvider(
                command=settings.codex_cli_command,
                model_name=settings.codex_cli_model,
                timeout_seconds=settings.codex_cli_timeout_seconds,
                sandbox=settings.codex_cli_sandbox,
                use_json=settings.codex_cli_use_json,
                output_last_message=settings.codex_cli_output_last_message,
                image_input_enabled=settings.codex_cli_image_input_enabled,
                workdir=settings.codex_cli_workdir,
                skip_git_repo_check=settings.codex_cli_skip_git_repo_check,
            ),
            image_input_enabled=settings.codex_cli_image_input_enabled,
            storage_root=settings.local_storage_root,
        )
        return self._grade_region(region, codex_adapter, marking_policy="general")

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
        mock_adapter = BrainAdapter()
        created_ids: list[int] = []
        errors: list[str] = []
        skipped_count = 0
        for region in regions:
            if region.grade_suggestions:
                skipped_count += 1
                continue
            try:
                _, suggestion = self._grade_region(
                    region, mock_adapter, marking_policy=marking_policy
                )
                created_ids.append(suggestion.id)
            except HTTPException as exc:
                errors.append(f"answer_region_id={region.id}: {exc.detail}")
            except Exception as exc:  # Defensive: keep batch progress visible.
                errors.append(f"answer_region_id={region.id}: {sanitize_provider_error(str(exc))}")
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
        self, region: AnswerRegion, adapter: BrainAdapter, *, marking_policy: str
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
        image_path = self.storage.resolve_relative(region.image_path)

        job = GradingJob(answer_region_id=region.id, status="running")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        if not image_path.is_file():
            self._mark_job_failed(job.id, "Answer region image is missing")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Answer region image is missing",
            )

        try:
            grading_answer_image_path = region.image_path
            grading_context: dict[str, object] | None = None
            if settings.answer_region_grading_crop_padding_ratio > 0:
                grading_answer_image_path = crop_grading_context_image(
                    storage=self.storage,
                    source_image_path=region.page.image_path,
                    submission_id=region.submission_id,
                    x=region.x,
                    y=region.y,
                    width=region.width,
                    height=region.height,
                    padding_ratio=settings.answer_region_grading_crop_padding_ratio,
                )
                grading_context = {
                    "original_image_path": region.image_path,
                    "answer_image_path": grading_answer_image_path,
                    "padding_ratio": settings.answer_region_grading_crop_padding_ratio,
                }
            output = adapter.grade_answer_region(
                question_text=region.question.question_text,
                question_total_marks=Decimal(region.question.total_marks),
                rubric_json=rubric.rubric_json,
                answer_image_path=grading_answer_image_path,
                marking_policy=marking_policy,
            )
            raw_response = output.model_dump(mode="json")
            review_flags = list(raw_response.get("review_flags") or [])
            if grading_context is not None and "grading_crop_padded" not in review_flags:
                review_flags.append("grading_crop_padded")
            policy_flag = f"marking_policy:{marking_policy}"
            if policy_flag not in review_flags:
                review_flags.append(policy_flag)
            raw_response["review_flags"] = review_flags
            raw_response["marking_policy"] = marking_policy
            if grading_context is not None:
                raw_response["grading_context"] = grading_context
            suggestion = GradeSuggestion(
                grading_job_id=job.id,
                answer_region_id=region.id,
                question_id=region.question_id,
                model_provider=output.model_provider,
                model_name=output.model_name,
                prompt_version=output.prompt_version,
                marking_policy=marking_policy,
                raw_response_json=raw_response,
                score=output.score,
                max_score=output.max_score,
                confidence=output.confidence,
                needs_review=output.needs_review,
                feedback=output.feedback_to_student,
                cost_estimate=output.cost_estimate,
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
                detail=f"Brain provider failed: {sanitized_error}",
            ) from exc

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
                joinedload(AnswerRegion.submission),
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
