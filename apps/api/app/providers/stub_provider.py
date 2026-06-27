"""
Stub AI provider for CI and local testing.
Returns deterministic fixture responses without making any API calls.
Use by setting USE_STUB_PROVIDER=true in environment.
"""


def extract_questions_from_pdf(pdf_path: str) -> dict:
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


def extract_rubric_from_pdf(pdf_path: str) -> dict:
    return {
        "criteria": [
            {
                "question_number": "1",
                "criterion_text": "Stub: Award marks for correct explanation of photosynthesis.",
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


def grade_answer(
    question_text: str,
    rubric_text: str,
    student_answer: str,
    policy: str = "general",
) -> dict:
    # Returns a mid-range score to exercise the review/approval flow
    return {
        "score": 7,
        "max_score": 10,
        "feedback": (
            "Stub feedback: The answer demonstrates partial understanding. "
            "Key points were addressed but some detail was missing."
        ),
        "confidence": "high",
        "warnings": [],
    }
