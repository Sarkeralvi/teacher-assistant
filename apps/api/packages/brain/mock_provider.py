from decimal import Decimal
from typing import Any

from packages.brain.cost_tracker import estimate_mock_cost
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem


class MockBrainProvider(BrainProvider):
    provider_name = "mock"
    model_name = "mock-grader-v1"

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
        model_policy: object | None = None,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        criteria = rubric_json.get("criteria", [])
        breakdown = [
            RubricBreakdownItem(
                criterion_id=str(criterion["id"]),
                criterion=str(criterion["name"]),
                max_marks=Decimal(str(criterion["max_marks"])),
                awarded_marks=Decimal("0"),
                reason="Mock provider does not evaluate content.",
                evidence=None,
                confidence=Decimal("0"),
            )
            for criterion in criteria
        ]
        max_score = Decimal(str(rubric_json.get("total_marks", question_total_marks)))
        flags = ["mock_provider", "teacher_review_required", f"marking_policy:{marking_policy}"]
        return GradeSuggestionOutput(
            score=Decimal("0"),
            max_score=max_score,
            confidence=Decimal("0"),
            needs_review=True,
            rubric_breakdown=breakdown,
            detected_answer_summary=(
                "Mock grading result. No real answer understanding was performed."
            ),
            major_errors=[],
            feedback_to_student="This is a mock grading suggestion for pipeline validation only.",
            review_flags=flags,
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=estimate_mock_cost(),
            latency_ms=0,
        )

    def extract_questions_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        del pdf_path
        return {
            "questions": [
                {
                    "question_number": "1",
                    "question_text": "Stub: Explain the concept of photosynthesis.",
                    "marks": 10,
                    "sub_questions": [
                        {
                            "question_number": "1(a)",
                            "question_text": "Stub: What is the role of chlorophyll?",
                            "marks": 5,
                            "sub_questions": [],
                        },
                        {
                            "question_number": "1(b)",
                            "question_text": "Stub: Write the chemical equation.",
                            "marks": 5,
                            "sub_questions": [],
                        },
                    ],
                }
            ],
            "warnings": [],
        }

    def extract_rubric_from_pdf(self, pdf_path: str) -> dict[str, Any]:
        del pdf_path
        return {
            "criteria": [
                {
                    "question_number": "1",
                    "criterion_text": (
                        "Stub: Award marks for correct explanation of photosynthesis."
                    ),
                    "max_marks": 10,
                    "sub_criteria": [
                        {
                            "question_number": "1(a)",
                            "criterion_text": "Stub: Correct role of chlorophyll stated.",
                            "max_marks": 5,
                            "sub_criteria": [],
                        },
                        {
                            "question_number": "1(b)",
                            "criterion_text": "Stub: Correct chemical equation written.",
                            "max_marks": 5,
                            "sub_criteria": [],
                        },
                    ],
                }
            ],
            "warnings": [],
        }
