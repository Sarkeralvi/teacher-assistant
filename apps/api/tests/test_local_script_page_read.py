from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.services.local_script_page_read import (
    LocalScriptPageReadError,
    LocalScriptPageReadService,
)
from packages.brain.schemas_qwen38 import VisualPageBlock, VisualPageTranscriptOutput


def _page(tmp_path: Path, page_no: int, *, ink: bool = True) -> SimpleNamespace:
    path = tmp_path / f"page-{page_no}.png"
    image = Image.new("RGB", (1000, 1000), "white")
    if ink:
        ImageDraw.Draw(image).rectangle((80, 80, 920, 920), fill="black")
    image.save(path)
    return SimpleNamespace(id=page_no, page_no=page_no, image_path=str(path))


def _questions(*labels: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id=index, question_no=label)
        for index, label in enumerate(labels, start=1)
    ]


def _block(
    label: str | None,
    bbox: list[int],
    text: str,
    *,
    continues_from_previous: bool = False,
    label_source: str | None = None,
) -> VisualPageBlock:
    return VisualPageBlock(
        question_label=label,
        bbox=bbox,
        text=text,
        continues_from_previous=continues_from_previous,
        label_source=label_source or ("continuation" if label is None else "heading"),
        confidence=Decimal("0.96"),
    )


def _output(*blocks: VisualPageBlock, blank: bool = False) -> VisualPageTranscriptOutput:
    return VisualPageTranscriptOutput(blocks=list(blocks), is_blank_page=blank)


def test_omitted_label_source_defaults_without_discarding_the_page() -> None:
    # A real read returned null here and the schema error threw away every block
    # on the page plus the call that paid for it. An unlabelled block has only
    # one valid source; a labelled one degrades to the value that cannot
    # auto-pass, so the omission costs a teacher review rather than the page.
    payload = {
        "blocks": [
            {
                "question_label": None,
                "bbox": [0, 0, 1000, 400],
                "text": "carries on from the previous page",
                "continues_from_previous": True,
                "label_source": None,
                "confidence": "0.95",
            },
            {
                "question_label": "Q2",
                "bbox": [0, 400, 1000, 900],
                "text": "the answer to two",
                "continues_from_previous": False,
                "label_source": None,
                "confidence": "0.95",
            },
        ],
        "is_blank_page": False,
    }

    output = VisualPageTranscriptOutput.model_validate(payload)

    assert output.blocks[0].label_source == "continuation"
    assert output.blocks[1].label_source == "inferred"


def test_null_label_with_contradictory_source_is_reconciled_not_rejected() -> None:
    # A real read returned a null question_label alongside "heading", which is
    # self-contradictory. The provider rejected it and the whole page was lost.
    # An unlabelled block has exactly one coherent source, so impose it.
    block = VisualPageBlock.model_validate(
        {
            "question_label": None,
            "bbox": [0, 0, 800, 300],
            "text": "continues from the block above",
            "continues_from_previous": True,
            "label_source": "heading",
            "confidence": "0.93",
        }
    )

    assert block.label_source == "continuation"


def test_supplied_label_source_is_never_overridden() -> None:
    block = VisualPageBlock.model_validate(
        {
            "question_label": "Q1",
            "bbox": [0, 0, 500, 500],
            "text": "seen heading",
            "continues_from_previous": False,
            "label_source": "heading",
            "confidence": "0.99",
        }
    )

    assert block.label_source == "heading"


def _service() -> LocalScriptPageReadService:
    storage = SimpleNamespace(resolve_relative=lambda path: Path(path))
    return LocalScriptPageReadService(
        MagicMock(),
        settings=Settings(LOCAL_SCRIPT_UNASSIGNED_INK_WARN_ABOVE=Decimal("0.35")),
        storage=storage,
    )


def test_mock_page_read_assembly_keeps_labels_in_visual_order(tmp_path: Path) -> None:
    questions = _questions("Q1", "Q2")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1)],
        page_outputs=[
            _output(
                _block("Q1", [50, 100, 950, 420], "Q1 working"),
                _block("Q2", [50, 560, 950, 900], "Q2 working"),
            )
        ],
        questions=questions,
    )

    assert assembly.text_by_question[1] == "Q1 working"
    assert assembly.text_by_question[2] == "Q2 working"
    assert [segment.page_no for segment in assembly.segments_by_question[1]] == [1]
    assert [segment.page_no for segment in assembly.segments_by_question[2]] == [1]
    assert assembly.segments_by_question[1][0].y < assembly.segments_by_question[2][0].y


def test_mock_page_read_groups_one_label_across_nonadjacent_pages(tmp_path: Path) -> None:
    questions = _questions("Q1", "Q2")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1), _page(tmp_path, 2), _page(tmp_path, 3)],
        page_outputs=[
            _output(_block("Q1", [50, 100, 950, 800], "first Q1 work")),
            _output(_block("Q2", [50, 100, 950, 800], "Q2 work")),
            _output(_block("Q1", [50, 100, 950, 800], "returned Q1 work")),
        ],
        questions=questions,
    )

    assert [segment.page_no for segment in assembly.segments_by_question[1]] == [1, 3]
    assert assembly.text_by_question[1] == "first Q1 work\nreturned Q1 work"
    assert assembly.text_by_question[2] == "Q2 work"


def test_mock_page_read_leading_null_block_is_hard_blocked(tmp_path: Path) -> None:
    questions = _questions("Q1")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1)],
        page_outputs=[
            _output(
                _block(None, [50, 80, 950, 300], "unowned leading work"),
                _block("Q1", [50, 450, 950, 900], "labelled work"),
            )
        ],
        questions=questions,
    )

    assert "unlabeled block" in assembly.blockers_by_question[1][0]
    assert "hard blocked" in assembly.blockers_by_question[1][0]


def test_mock_page_read_carries_last_label_across_page_break(tmp_path: Path) -> None:
    questions = _questions("Q1")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1), _page(tmp_path, 2)],
        page_outputs=[
            _output(_block("Q1", [50, 100, 950, 900], "first page")),
            _output(
                _block(
                    None,
                    [50, 80, 950, 700],
                    "continued final line",
                    continues_from_previous=True,
                )
            ),
        ],
        questions=questions,
    )

    assert [segment.page_no for segment in assembly.segments_by_question[1]] == [1, 2]
    assert assembly.text_by_question[1] == "first page\ncontinued final line"
    assert assembly.continuation_by_question[1] is True


def test_mock_page_read_handles_out_of_order_answers_without_forward_carry(
    tmp_path: Path,
) -> None:
    questions = _questions("Q1", "Q2", "Q3")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1), _page(tmp_path, 2)],
        page_outputs=[
            _output(
                _block("Q3", [50, 100, 950, 400], "Q3 first"),
                _block("Q1", [50, 550, 950, 900], "Q1 later"),
            ),
            _output(_block("Q1", [50, 100, 950, 800], "Q1 returned")),
        ],
        questions=questions,
    )

    assert assembly.text_by_question[3] == "Q3 first"
    assert assembly.text_by_question[1] == "Q1 later\nQ1 returned"
    assert assembly.text_by_question[2] == ""
    assert [segment.page_no for segment in assembly.segments_by_question[1]] == [1, 2]


def test_mock_page_read_rejects_an_unknown_label(tmp_path: Path) -> None:
    with pytest.raises(LocalScriptPageReadError, match="unknown finalized question"):
        _service().assemble(
            pages=[_page(tmp_path, 1)],
            page_outputs=[_output(_block("Q99", [50, 100, 950, 800], "unknown"))],
            questions=_questions("Q1"),
        )


def test_unassigned_ink_is_a_hard_blocker_not_a_warning(tmp_path: Path) -> None:
    questions = _questions("Q1")
    assembly = _service().assemble(
        pages=[_page(tmp_path, 1, ink=True)],
        page_outputs=[_output()],
        questions=questions,
    )

    assert assembly.unassigned_pages == [{"page_no": 1, "blank": False, "ratio": "1.000000"}]
    assert any(
        "uncovered ink outside every page-read answer band" in value
        for value in assembly.blockers_by_question[1]
    )
