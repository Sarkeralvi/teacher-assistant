from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import get_settings
from app.models import AnswerRegion, Assessment, GradeSuggestion, GradingJob, Rubric, Submission
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter, sanitize_provider_error
from packages.brain.codex_cli_provider import CodexCliProvider


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

    def grade_answer_region(self, answer_region_id: int) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        return self._grade_region(region, self.adapter, marking_policy="general")

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
            output = adapter.grade_answer_region(
                question_text=region.question.question_text,
                question_total_marks=Decimal(region.question.total_marks),
                rubric_json=rubric.rubric_json,
                answer_image_path=region.image_path,
            )
            raw_response = output.model_dump(mode="json")
            review_flags = list(raw_response.get("review_flags") or [])
            policy_flag = f"marking_policy:{marking_policy}"
            if policy_flag not in review_flags:
                review_flags.append(policy_flag)
            raw_response["review_flags"] = review_flags
            raw_response["marking_policy"] = marking_policy
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
            .options(joinedload(AnswerRegion.question))
            .where(AnswerRegion.id == answer_region_id)
        )
        region = self.db.scalars(statement).first()
        if region is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Answer region not found",
            )
        return region

    def _get_active_rubric(self, question_id: int) -> Rubric:
        statement = select(Rubric).where(
            Rubric.question_id == question_id, Rubric.is_active.is_(True)
        )
        rubric = self.db.scalars(statement).first()
        if rubric is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Question has no active rubric",
            )
        return rubric
