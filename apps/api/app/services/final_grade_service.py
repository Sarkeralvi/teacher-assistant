
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import AnswerRegion, Assessment, FinalGrade, GradeSuggestion, User
from app.schemas import (
    FinalGradeCreate,
    ReviewQueueItem,
    ReviewQueueQuestion,
    ReviewQueueSubmission,
)


class FinalGradeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def finalize_suggestion(
        self, suggestion_id: int, payload: FinalGradeCreate
    ) -> tuple[FinalGrade, bool]:
        suggestion = self.db.get(GradeSuggestion, suggestion_id)
        if suggestion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Grade suggestion not found"
            )
        region = self.db.get(AnswerRegion, suggestion.answer_region_id)
        if region is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found"
            )
        if suggestion.question_id != region.question_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Grade suggestion does not match answer region question",
            )
        teacher = self.db.get(User, payload.teacher_id)
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
        if payload.final_score > suggestion.max_score:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="final_score cannot exceed suggestion max_score",
            )

        existing = self.db.scalars(
            select(FinalGrade).where(FinalGrade.answer_region_id == region.id)
        ).first()
        created = existing is None
        final_grade = existing or FinalGrade(answer_region_id=region.id)
        final_grade.teacher_id = payload.teacher_id
        final_grade.suggestion_id = suggestion.id
        final_grade.final_score = payload.final_score
        final_grade.teacher_comment = payload.teacher_comment
        final_grade.approval_status = payload.approval_status
        self.db.add(final_grade)
        self.db.commit()
        self.db.refresh(final_grade)
        return final_grade, created

    def get_final_grade_for_region(self, answer_region_id: int) -> FinalGrade:
        region = self.db.get(AnswerRegion, answer_region_id)
        if region is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found"
            )
        final_grade = self.db.scalars(
            select(FinalGrade)
            .where(FinalGrade.answer_region_id == answer_region_id)
            .order_by(FinalGrade.id.desc())
        ).first()
        if final_grade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Final grade not found"
            )
        return final_grade

    def get_review_queue(self, assessment_id: int) -> list[ReviewQueueItem]:
        assessment = self.db.get(Assessment, assessment_id)
        if assessment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found"
            )
        regions = self.db.scalars(
            select(AnswerRegion)
            .join(AnswerRegion.submission)
            .where(AnswerRegion.submission.has(assessment_id=assessment_id))
            .options(
                joinedload(AnswerRegion.submission),
                joinedload(AnswerRegion.question),
            )
            .order_by(AnswerRegion.id)
        ).all()
        items: list[ReviewQueueItem] = []
        for region in regions:
            latest_suggestion = self.db.scalars(
                select(GradeSuggestion)
                .where(GradeSuggestion.answer_region_id == region.id)
                .order_by(GradeSuggestion.id.desc())
            ).first()
            final_grade = self.db.scalars(
                select(FinalGrade)
                .where(FinalGrade.answer_region_id == region.id)
                .order_by(FinalGrade.id.desc())
            ).first()
            review_status = self._review_status(latest_suggestion, final_grade)
            items.append(
                ReviewQueueItem(
                    answer_region=region,
                    submission=ReviewQueueSubmission(
                        id=region.submission.id,
                        student_identifier=region.submission.student_identifier,
                        student_name=region.submission.student_name,
                    ),
                    question=ReviewQueueQuestion(
                        id=region.question.id,
                        question_no=region.question.question_no,
                        question_text=region.question.question_text,
                        total_marks=region.question.total_marks,
                    ),
                    latest_grade_suggestion=latest_suggestion,
                    final_grade=final_grade,
                    review_status=review_status,
                )
            )
        return items

    @staticmethod
    def _review_status(
        latest_suggestion: GradeSuggestion | None, final_grade: FinalGrade | None
    ) -> str:
        if final_grade is not None:
            return "finalized"
        if latest_suggestion is not None:
            return "suggested"
        return "ungraded"
