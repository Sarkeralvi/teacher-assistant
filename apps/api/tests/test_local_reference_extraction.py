from pathlib import Path
from typing import Any

from PIL import Image

from app.services.document_extraction import LocalPaddleQwenDocumentExtractor
from app.services.local_ocr_client import LocalOcrResult
from app.services.local_reference_extraction import LocalReferenceExtractor
from app.services.question_import_extractor import LocalPaddleQwenQuestionExtractor


class FakeOcrClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        self.calls.append(kwargs)
        return LocalOcrResult.model_validate(
            {
                "request_id": kwargs["request_id"],
                "mode": "document",
                "text": "Q1 Explain gravity. [5 marks] Model answer: attraction.",
                "normalized_text": (
                    "Q1 Explain gravity. [5 marks] Model answer: attraction."
                ),
                "markdown": "Q1 Explain gravity. **[5 marks]**",
                "blocks": [
                    {
                        "page": 1,
                        "order": 1,
                        "label": "text",
                        "text": "Q1 Explain gravity.",
                        "bbox": [0, 0, 50, 20],
                    }
                ],
                "warnings": ["review_formula_layout"],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "cpu",
                "latency_ms": 8,
            }
        )


class FakeQwenAdapter:
    class Provider:
        provider_name = "llama_cpp_qwen"

    def __init__(self) -> None:
        self.provider = self.Provider()
        self.question_pages: list[dict[str, Any]] = []

    def extract_questions_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.question_pages = pages
        return {
            "questions": [
                {
                    "question_number": "Q1",
                    "parent_question_number": None,
                    "label": "Q1",
                    "question_text": "Explain gravity.",
                    "model_answer": "Gravity is attraction between masses.",
                    "marks": "5.00",
                    "node_type": "question",
                    "source_page": 1,
                    "source_text_excerpt": "Q1 Explain gravity. [5 marks]",
                    "confidence": "0.82",
                    "needs_review": True,
                }
            ],
            "warnings": ["teacher_confirmation_required"],
        }

    def extract_rubric_from_ocr_pages(
        self, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        del pages
        return {
            "criteria": [
                {
                    "question_number": "Q1",
                    "criterion_label": "Concept",
                    "description": "Explains attraction between masses.",
                    "max_marks": "5.00",
                    "confidence": "0.80",
                    "blocker": None,
                    "needs_review": True,
                }
            ],
            "warnings": [],
        }


def make_image(path: Path) -> None:
    Image.new("RGB", (80, 60), "white").save(path, format="PNG")


def make_extractor() -> tuple[LocalReferenceExtractor, FakeOcrClient, FakeQwenAdapter]:
    ocr = FakeOcrClient()
    qwen = FakeQwenAdapter()
    extractor = LocalReferenceExtractor(ocr_client=ocr, qwen_adapter=qwen)  # type: ignore[arg-type]
    return extractor, ocr, qwen


def test_local_reference_pipeline_uses_page_order_and_returns_teacher_drafts(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "question.png"
    make_image(image_path)
    extractor, ocr, qwen = make_extractor()

    result = extractor.extract_questions(image_path, "image/png")

    assert len(ocr.calls) == 1
    assert ocr.calls[0]["mode"] == "document"
    assert isinstance(ocr.calls[0]["image_bytes"], bytes)
    assert qwen.question_pages[0]["page"] == 1
    assert result["questions"][0]["model_answer"].startswith("Gravity")
    assert result["questions"][0]["needs_review"] is True
    assert result["warnings"] == [
        "page 1: review_formula_layout",
        "teacher_confirmation_required",
    ]


def test_local_question_import_and_document_extraction_remain_noncanonical_drafts(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "question.png"
    make_image(image_path)
    extractor, _ocr, _qwen = make_extractor()

    import_result = LocalPaddleQwenQuestionExtractor(extractor).extract(
        image_path, "image/png"
    )
    assert import_result.draft_questions[0].model_answer is not None
    assert import_result.draft_questions[0].needs_review is True

    document_result = LocalPaddleQwenDocumentExtractor(extractor).extract(
        image_path, "question_paper", "image/png"
    )
    node = document_result.normalized_output["question_nodes"][0]
    assert node["teacher_confirmed"] is False
    assert node["source_reference"]["model_answer_draft"].startswith("Gravity")
    assert document_result.blockers == []


def test_local_rubric_extraction_is_unconfirmed_and_does_not_create_a_rubric(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "rubric.png"
    make_image(image_path)
    extractor, _ocr, _qwen = make_extractor()

    document_result = LocalPaddleQwenDocumentExtractor(extractor).extract(
        image_path, "rubric", "image/png"
    )

    criterion = document_result.normalized_output["criteria"][0]
    assert criterion["teacher_confirmed"] is False
    assert criterion["criterion_label"] == "Concept"
