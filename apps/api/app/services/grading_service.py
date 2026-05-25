from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import AnswerRegion, GradeSuggestion, GradingJob, Rubric
from app.services.storage import LocalStorage
from packages.brain.adapter import BrainAdapter


class GradingService:
    def __init__(self, db: Session, storage: LocalStorage | None = None) -> None:
        self.db = db
        self.storage = storage or LocalStorage()
        self.adapter = BrainAdapter()

    def grade_answer_region(self, answer_region_id: int) -> tuple[GradingJob, GradeSuggestion]:
        region = self._get_region(answer_region_id)
        rubric = self._get_active_rubric(region.question_id)
        image_path = self.storage.resolve_relative(region.image_path)
        if not image_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Answer region image is missing",
            )

        job = GradingJob(answer_region_id=region.id, status="running")
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        try:
            output = self.adapter.grade_answer_region(
                question_text=region.question.question_text,
                question_total_marks=Decimal(region.question.total_marks),
                rubric_json=rubric.rubric_json,
                answer_image_path=region.image_path,
            )
            raw_response = output.model_dump(mode="json")
            suggestion = GradeSuggestion(
                grading_job_id=job.id,
                answer_region_id=region.id,
                question_id=region.question_id,
                model_provider=output.model_provider,
                model_name=output.model_name,
                prompt_version=output.prompt_version,
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
            job = self.db.get(GradingJob, job.id)
            if job is not None:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = datetime.now(UTC)
                self.db.commit()
            raise

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
