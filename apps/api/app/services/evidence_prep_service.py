from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AnswerRegion, Assessment, Question, Submission, SubmissionPage
from app.services.grading_service import GradingService


class EvidencePrepService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.grading_service = GradingService(db, use_configured_adapter=False)

    def summarize_assessment(self, assessment_id: int) -> dict[str, Any]:
        assessment = self.db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError("Assessment not found")
        submissions = list(
            self.db.scalars(
                select(Submission)
                .options(selectinload(Submission.pages))
                .where(Submission.assessment_id == assessment_id)
                .order_by(Submission.id)
            ).all()
        )
        questions = list(
            self.db.scalars(
                select(Question)
                .where(Question.assessment_id == assessment_id)
                .order_by(Question.id)
            ).all()
        )
        regions = list(
            self.db.scalars(
                select(AnswerRegion)
                .options(
                    selectinload(AnswerRegion.segments),
                    selectinload(AnswerRegion.question).selectinload(Question.rubrics),
                )
                .join(Submission, AnswerRegion.submission_id == Submission.id)
                .where(Submission.assessment_id == assessment_id)
                .order_by(AnswerRegion.id)
            )
            .unique()
            .all()
        )
        region_by_submission_question = {
            (region.submission_id, region.question_id): region for region in regions
        }
        packets: list[dict[str, Any]] = []
        for submission in submissions:
            page_order_blocker = self._page_order_blocker(submission.pages)
            for question in questions:
                region = region_by_submission_question.get((submission.id, question.id))
                if region is None:
                    blockers = ["no answer region mapped for this submission/question"]
                    if page_order_blocker:
                        blockers.append(page_order_blocker)
                    packets.append(
                        {
                            "submission_id": submission.id,
                            "student_identifier": submission.student_identifier,
                            "grading_unit_label": question.question_no,
                            "max_marks": question.total_marks,
                            "evidence_status": "missing",
                            "continuation_check_status": "not_checked",
                            "ready_for_grading": False,
                            "quarantined": True,
                            "blockers": blockers,
                            "warnings": [],
                            "segment_count": 0,
                            "pages_covered": [],
                            "answer_region_id": None,
                            "question_id": question.id,
                            "correction_target": self._correction_target(
                                submission=submission,
                                question=question,
                                region=None,
                            ),
                        }
                    )
                    continue
                packet = self.grading_service.get_grading_evidence_packet(region.id)
                readiness = packet["readiness_result"]
                student_evidence = packet["student_answer_evidence"]
                canonical_unit = packet["canonical_grading_unit"]
                blockers = list(readiness["blockers"])
                warnings = list(readiness["warnings"])
                if page_order_blocker and page_order_blocker not in blockers:
                    blockers.append(page_order_blocker)
                packets.append(
                    {
                        "submission_id": submission.id,
                        "student_identifier": submission.student_identifier,
                        "grading_unit_label": canonical_unit["label"],
                        "max_marks": canonical_unit["max_marks"],
                        "evidence_status": student_evidence["packet_status"],
                        "continuation_check_status": student_evidence[
                            "continuation_check_status"
                        ],
                        "ready_for_grading": not blockers,
                        "quarantined": bool(blockers),
                        "blockers": blockers,
                        "warnings": warnings,
                        "segment_count": student_evidence["segment_count"],
                        "pages_covered": student_evidence["pages_covered"],
                        "answer_region_id": region.id,
                        "question_id": question.id,
                        "correction_target": self._correction_target(
                            submission=submission,
                            question=question,
                            region=region,
                        ),
                    }
                )
        return self._summarize_packets(assessment_id, len(submissions), packets)

    def _summarize_packets(
        self, assessment_id: int, total_submissions: int, packets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        ready_count = sum(1 for packet in packets if packet["ready_for_grading"])
        blocked_count = sum(1 for packet in packets if packet["quarantined"])
        status = "completed" if blocked_count == 0 else "completed_with_blockers"
        return {
            "assessment_id": assessment_id,
            "status": status,
            "total_submissions": total_submissions,
            "total_expected_packets": len(packets),
            "ready_packet_count": ready_count,
            "blocked_packet_count": blocked_count,
            "warning_packet_count": sum(1 for packet in packets if packet["warnings"]),
            "blank_packet_count": sum(
                1 for packet in packets if packet["evidence_status"] == "blank"
            ),
            "partial_packet_count": sum(
                1 for packet in packets if packet["evidence_status"] == "partial"
            ),
            "packets": packets,
            "error": None,
        }

    def _page_order_blocker(self, pages: list[SubmissionPage]) -> str | None:
        if not pages:
            return "page order unknown"
        page_numbers = sorted(page.page_no for page in pages)
        if page_numbers != list(range(1, len(page_numbers) + 1)):
            return "page order unknown"
        if len(set(page_numbers)) != len(page_numbers):
            return "page order unknown"
        return None

    def _correction_target(
        self, *, submission: Submission, question: Question, region: AnswerRegion | None
    ) -> dict[str, int | str | None]:
        return {
            "submission_id": submission.id,
            "student_identifier": submission.student_identifier,
            "question_id": question.id,
            "grading_unit_label": question.question_no,
            "answer_region_id": region.id if region else None,
            "correction_anchor": (
                f"answer-region-{region.id}" if region else "answer-region-create-form"
            ),
        }
