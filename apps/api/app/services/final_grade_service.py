from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO

from fastapi import HTTPException, status
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    AnswerRegion,
    Assessment,
    AuditLog,
    FinalGrade,
    GradeSuggestion,
    Submission,
    User,
)
from app.schemas import (
    AssessmentSummaryRead,
    BatchFinalGradeApproveResponse,
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
        return self._save_final_grade(
            suggestion_id=suggestion_id,
            teacher_id=payload.teacher_id,
            final_score=payload.final_score,
            approval_status=payload.approval_status,
            teacher_comment=payload.teacher_comment,
        )

    def approve_suggestion(
        self, suggestion_id: int, teacher_id: int, teacher_comment: str | None = None
    ) -> tuple[FinalGrade, bool]:
        suggestion = self._get_suggestion(suggestion_id)
        if suggestion.score is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Cannot approve a suggestion without a score",
            )
        return self._save_final_grade(
            suggestion_id=suggestion_id,
            teacher_id=teacher_id,
            final_score=suggestion.score,
            approval_status="approved",
            teacher_comment=teacher_comment,
            suggestion=suggestion,
        )

    def edit_suggestion(
        self,
        suggestion_id: int,
        teacher_id: int,
        final_score,
        teacher_comment: str | None = None,
    ) -> tuple[FinalGrade, bool]:
        return self._save_final_grade(
            suggestion_id=suggestion_id,
            teacher_id=teacher_id,
            final_score=final_score,
            approval_status="edited",
            teacher_comment=teacher_comment,
        )

    def reject_suggestion(
        self, suggestion_id: int, teacher_id: int, teacher_comment: str | None = None
    ) -> tuple[FinalGrade, bool]:
        return self._save_final_grade(
            suggestion_id=suggestion_id,
            teacher_id=teacher_id,
            final_score=0,
            approval_status="rejected",
            teacher_comment=teacher_comment,
        )

    def approve_selected_suggestions(
        self, *, assessment_id: int, suggestion_ids: list[int], teacher_id: int
    ) -> BatchFinalGradeApproveResponse:
        self._get_assessment(assessment_id)
        teacher = self.db.get(User, teacher_id)
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")

        final_grade_ids: list[int] = []
        errors: list[str] = []
        approved_count = 0
        skipped_count = 0
        failed_count = 0

        for suggestion_id in suggestion_ids:
            suggestion = self.db.get(GradeSuggestion, suggestion_id)
            if suggestion is None:
                skipped_count += 1
                errors.append(f"Grade suggestion {suggestion_id} not found")
                continue
            region = self.db.scalars(
                select(AnswerRegion)
                .join(AnswerRegion.submission)
                .where(AnswerRegion.id == suggestion.answer_region_id)
                .where(Submission.assessment_id == assessment_id)
            ).first()
            if region is None:
                skipped_count += 1
                errors.append(
                    f"Grade suggestion {suggestion_id} does not belong to "
                    f"assessment {assessment_id}"
                )
                continue
            if suggestion.score is None:
                failed_count += 1
                errors.append(f"Grade suggestion {suggestion_id} failed: missing score")
                continue
            try:
                final_grade, _created = self._save_final_grade(
                    suggestion_id=suggestion.id,
                    teacher_id=teacher_id,
                    final_score=suggestion.score,
                    approval_status="approved",
                    teacher_comment=None,
                    suggestion=suggestion,
                )
            except HTTPException as exc:
                failed_count += 1
                errors.append(f"Grade suggestion {suggestion_id} failed: {exc.detail}")
                continue
            approved_count += 1
            final_grade_ids.append(final_grade.id)

        return BatchFinalGradeApproveResponse(
            requested_count=len(suggestion_ids),
            approved_count=approved_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            final_grade_ids=final_grade_ids,
            errors=errors,
        )

    def _get_suggestion(self, suggestion_id: int) -> GradeSuggestion:
        suggestion = self.db.get(GradeSuggestion, suggestion_id)
        if suggestion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Grade suggestion not found"
            )
        return suggestion

    def _save_final_grade(
        self,
        *,
        suggestion_id: int,
        teacher_id: int,
        final_score,
        approval_status: str,
        teacher_comment: str | None,
        suggestion: GradeSuggestion | None = None,
    ) -> tuple[FinalGrade, bool]:
        suggestion = suggestion or self._get_suggestion(suggestion_id)
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
        teacher = self.db.get(User, teacher_id)
        if teacher is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
        if final_score > suggestion.max_score:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="final_score cannot exceed suggestion max_score",
            )

        existing = self.db.scalars(
            select(FinalGrade).where(FinalGrade.answer_region_id == region.id)
        ).first()
        created = existing is None
        final_grade = existing or FinalGrade(answer_region_id=region.id)
        final_grade.teacher_id = teacher_id
        final_grade.suggestion_id = suggestion.id
        final_grade.final_score = final_score
        final_grade.teacher_comment = teacher_comment
        final_grade.approval_status = approval_status
        self.db.add(final_grade)
        self.db.flush()
        self.db.add(
            AuditLog(
                actor_type="teacher",
                actor_id=teacher_id,
                event_type=f"final_grade.{approval_status}",
                entity_type="final_grade",
                entity_id=final_grade.id,
                payload_json={
                    "answer_region_id": region.id,
                    "suggestion_id": suggestion.id,
                    "final_score": str(final_grade.final_score),
                    "approval_status": approval_status,
                    "upsert_created": created,
                },
            )
        )
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

    def get_assessment_summary(self, assessment_id: int) -> AssessmentSummaryRead:
        assessment = self._get_assessment(assessment_id)
        items = self.get_review_queue(assessment_id)
        final_grades = [item.final_grade for item in items if item.final_grade is not None]
        final_scores = [final_grade.final_score for final_grade in final_grades]
        total_submissions = len(
            self.db.scalars(
                select(Submission.id).where(Submission.assessment_id == assessment_id)
            ).all()
        )
        total_grade_suggestions = len(
            self.db.scalars(
                select(GradeSuggestion.id)
                .join(AnswerRegion, GradeSuggestion.answer_region_id == AnswerRegion.id)
                .join(Submission, AnswerRegion.submission_id == Submission.id)
                .where(Submission.assessment_id == assessment_id)
            ).all()
        )
        average_final_score = None
        if final_scores:
            average_final_score = (sum(final_scores, Decimal("0")) / len(final_scores)).quantize(
                Decimal("0.01")
            )
        max_possible_score = None
        if items:
            max_possible_score = sum(
                (item.question.total_marks for item in items), Decimal("0")
            ).quantize(Decimal("0.01"))

        return AssessmentSummaryRead(
            assessment_id=assessment.id,
            course_id=assessment.course_id,
            total_submissions=total_submissions,
            total_answer_regions=len(items),
            total_grade_suggestions=total_grade_suggestions,
            total_final_grades=len(final_grades),
            approved_count=sum(
                1 for final_grade in final_grades if final_grade.approval_status == "approved"
            ),
            edited_count=sum(
                1 for final_grade in final_grades if final_grade.approval_status == "edited"
            ),
            rejected_count=sum(
                1 for final_grade in final_grades if final_grade.approval_status == "rejected"
            ),
            pending_review_count=sum(1 for item in items if item.final_grade is None),
            average_final_score=average_final_score,
            max_possible_score=max_possible_score,
            generated_at=datetime.now(UTC),
        )

    def build_final_grades_workbook(self, assessment_id: int) -> bytes:
        assessment = self._get_assessment(assessment_id)
        items = self.get_review_queue(assessment_id)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Final Grades"
        headers = [
            "assessment_id",
            "course_id",
            "submission_id",
            "student_identifier",
            "student_name",
            "question_id",
            "question_no",
            "grading_unit_label",
            "grading_unit_max_marks",
            "answer_region_id",
            "grade_suggestion_id",
            "final_grade_id",
            "ai_score",
            "ai_max_score",
            "ai_confidence",
            "ai_needs_review",
            "marking_policy",
            "final_score",
            "approval_status",
            "teacher_comment",
            "reviewed_at",
            "feedback_to_student",
        ]
        sheet.append(headers)
        for item in items:
            suggestion = item.latest_grade_suggestion
            final_grade = item.final_grade
            if final_grade is None or final_grade.approval_status != "approved":
                continue
            sheet.append(
                [
                    assessment.id,
                    assessment.course_id,
                    item.submission.id,
                    item.submission.student_identifier,
                    item.submission.student_name,
                    item.question.id,
                    item.question.question_no,
                    item.question.question_no,
                    item.question.total_marks,
                    item.answer_region.id,
                    suggestion.id if suggestion else None,
                    final_grade.id if final_grade else None,
                    suggestion.score if suggestion else None,
                    suggestion.max_score if suggestion else None,
                    suggestion.confidence if suggestion else None,
                    suggestion.needs_review if suggestion else None,
                    suggestion.marking_policy if suggestion else None,
                    final_grade.final_score if final_grade else None,
                    final_grade.approval_status if final_grade else None,
                    final_grade.teacher_comment if final_grade else None,
                    final_grade.updated_at.isoformat() if final_grade else None,
                    suggestion.feedback if suggestion else None,
                ]
            )
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _get_assessment(self, assessment_id: int) -> Assessment:
        assessment = self.db.get(Assessment, assessment_id)
        if assessment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found"
            )
        return assessment

    @staticmethod
    def _review_status(
        latest_suggestion: GradeSuggestion | None, final_grade: FinalGrade | None
    ) -> str:
        if final_grade is not None:
            return "finalized"
        if latest_suggestion is not None:
            return "suggested"
        return "ungraded"
