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
        task_name: str = "answer_region_grading",
        model_policy: object | None = None,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
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
            review_flags=["mock_provider", "teacher_review_required"],
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=estimate_mock_cost(),
            latency_ms=0,
        )
