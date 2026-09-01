"""Synthetic-only source material for the bounded 180-script bulk preflight.

This module intentionally contains no student data and no provider integration.
It creates a deterministic ZIP layout that the normal bulk importer accepts,
plus the canonical labels and answer ground truth needed by a later, separately
authorized fidelity evaluation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw, ImageFont

SYNTHETIC_SUBMISSION_COUNT: Final = 180
SYNTHETIC_PAGES_PER_SUBMISSION: Final = 4
SYNTHETIC_QUESTION_COUNT: Final = 6
SYNTHETIC_ITEM_COUNT: Final = SYNTHETIC_SUBMISSION_COUNT * SYNTHETIC_QUESTION_COUNT
SYNTHETIC_PAGE_COUNT: Final = SYNTHETIC_SUBMISSION_COUNT * SYNTHETIC_PAGES_PER_SUBMISSION
SYNTHETIC_PAGE_READ_CALLS: Final = SYNTHETIC_PAGE_COUNT
SYNTHETIC_GRADING_CALLS: Final = SYNTHETIC_ITEM_COUNT
SYNTHETIC_PAGE_READ_CALL_LIMIT: Final = SYNTHETIC_PAGE_READ_CALLS + SYNTHETIC_GRADING_CALLS
DEFAULT_PAGE_SIZE: Final = (1200, 1600)


@dataclass(frozen=True)
class SyntheticQuestion:
    question_no: str
    question_text: str
    total_marks: int
    model_answer: str
    rubric_json: dict[str, object]


@dataclass(frozen=True)
class RenderedAnswerBlock:
    """One labelled answer block rendered on a synthetic page."""

    question_no: str
    text: str
    annotation: str | None = None


@dataclass(frozen=True)
class SyntheticScript:
    source: str
    student_identifier: str
    pages: tuple[tuple[RenderedAnswerBlock, ...], ...]
    answer_ground_truth: dict[str, str]


@dataclass(frozen=True)
class SyntheticCorpus:
    archive_path: Path
    questions: tuple[SyntheticQuestion, ...]
    scripts: tuple[SyntheticScript, ...]


def canonical_questions() -> tuple[SyntheticQuestion, ...]:
    """Return six finalized, labelled, self-contained synthetic questions."""

    result: list[SyntheticQuestion] = []
    for index in range(1, SYNTHETIC_QUESTION_COUNT + 1):
        total_marks = 4
        result.append(
            SyntheticQuestion(
                question_no=f"Q{index}",
                question_text=f"Synthetic canonical prompt {index}.",
                total_marks=total_marks,
                model_answer=f"Synthetic model answer for Q{index}.",
                rubric_json={
                    "total_marks": total_marks,
                    "criteria": [
                        {
                            "id": "method",
                            "name": "Method",
                            "description": "Uses the required synthetic method.",
                            "max_marks": 2,
                        },
                        {
                            "id": "result",
                            "name": "Result",
                            "description": "States the synthetic result.",
                            "max_marks": 2,
                        },
                    ],
                },
            )
        )
    return tuple(result)


def build_synthetic_bulk_archive(
    archive_path: Path,
    *,
    page_size: tuple[int, int] = DEFAULT_PAGE_SIZE,
) -> SyntheticCorpus:
    """Write 180 four-page, image-only scripts in the supported ZIP layout."""

    questions = canonical_questions()
    scripts = tuple(_script_for(index) for index in range(1, SYNTHETIC_SUBMISSION_COUNT + 1))
    validate_synthetic_corpus(questions=questions, scripts=scripts)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.csv", _manifest_csv(scripts))
        for script in scripts:
            for page_no, blocks in enumerate(script.pages, start=1):
                archive.writestr(
                    f"{script.source}/page-{page_no:02d}.png",
                    _render_page(
                        script=script,
                        page_no=page_no,
                        blocks=blocks,
                        page_size=page_size,
                    ),
                )
    return SyntheticCorpus(archive_path=archive_path, questions=questions, scripts=scripts)


def validate_synthetic_corpus(
    *,
    questions: tuple[SyntheticQuestion, ...],
    scripts: tuple[SyntheticScript, ...],
) -> None:
    """Fail closed if the rendered-label or coverage contract drifts."""

    canonical_labels = {question.question_no for question in questions}
    if len(questions) != SYNTHETIC_QUESTION_COUNT:
        raise ValueError("Synthetic corpus must contain exactly six canonical questions")
    if canonical_labels != {f"Q{index}" for index in range(1, SYNTHETIC_QUESTION_COUNT + 1)}:
        raise ValueError("Synthetic canonical labels must be exactly Q1 through Q6")
    if len(scripts) != SYNTHETIC_SUBMISSION_COUNT:
        raise ValueError("Synthetic corpus must contain exactly 180 scripts")

    for script in scripts:
        if len(script.pages) != SYNTHETIC_PAGES_PER_SUBMISSION:
            raise ValueError("Every synthetic script must contain exactly four pages")
        rendered_labels = {
            block.question_no for page in script.pages for block in page
        }
        if rendered_labels != canonical_labels:
            raise ValueError("Canonical labels must exactly match labels rendered on every script")
        expected_ground_truth = _ground_truth(script.pages)
        if script.answer_ground_truth != expected_ground_truth:
            raise ValueError("Synthetic answer ground truth must match rendered block text")

        # Q3 precedes Q1 on the first page. Q1 then continues across pages and
        # returns on the final page, exercising both claimed page-read advantages.
        first_page_labels = [block.question_no for block in script.pages[0]]
        if first_page_labels[:2] != ["Q3", "Q1"]:
            raise ValueError("Synthetic out-of-order layout must render Q3 before Q1")
        q1_pages = [
            page_no
            for page_no, page in enumerate(script.pages, start=1)
            if any(block.question_no == "Q1" for block in page)
        ]
        if q1_pages != [1, 2, 4]:
            raise ValueError("Synthetic Q1 must continue and return on pages 1, 2, and 4")


def _script_for(index: int) -> SyntheticScript:
    source = f"synthetic-{index:03d}"
    student_identifier = f"SYN-180-{index:03d}"

    def answer(question_no: str, suffix: str) -> str:
        return f"Synthetic {question_no} response {index:03d}: {suffix}."

    pages = (
        (
            RenderedAnswerBlock("Q3", answer("Q3", "out-of-order opening")),
            RenderedAnswerBlock("Q1", answer("Q1", "first section")),
        ),
        (
            RenderedAnswerBlock(
                "Q1",
                answer("Q1", "continued section"),
                annotation="continued from previous page",
            ),
            RenderedAnswerBlock("Q2", answer("Q2", "complete response")),
        ),
        (
            RenderedAnswerBlock("Q4", answer("Q4", "complete response")),
            RenderedAnswerBlock("Q5", answer("Q5", "complete response")),
        ),
        (
            RenderedAnswerBlock("Q6", answer("Q6", "complete response")),
            RenderedAnswerBlock("Q1", answer("Q1", "returned final section")),
        ),
    )
    return SyntheticScript(
        source=source,
        student_identifier=student_identifier,
        pages=pages,
        answer_ground_truth=_ground_truth(pages),
    )


def _ground_truth(
    pages: tuple[tuple[RenderedAnswerBlock, ...], ...]
) -> dict[str, str]:
    by_question: defaultdict[str, list[str]] = defaultdict(list)
    for page in pages:
        for block in page:
            by_question[block.question_no].append(block.text)
    return {question_no: "\n".join(parts) for question_no, parts in sorted(by_question.items())}


def _manifest_csv(scripts: tuple[SyntheticScript, ...]) -> str:
    rows = ["source,student_identifier,student_name"]
    rows.extend(f"{script.source},{script.student_identifier}," for script in scripts)
    return "\n".join(rows) + "\n"


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _render_page(
    *,
    script: SyntheticScript,
    page_no: int,
    blocks: tuple[RenderedAnswerBlock, ...],
    page_size: tuple[int, int],
) -> bytes:
    width, height = page_size
    image = Image.new("RGB", page_size, "white")
    draw = ImageDraw.Draw(image)
    margin = max(24, width // 24)
    label_font = _font(max(18, width // 32))
    body_font = _font(max(14, width // 48))
    draw.text((margin, margin), "SYNTHETIC SCRIPT", fill="black", font=label_font)
    draw.text(
        (margin, margin + max(28, height // 26)),
        f"{script.student_identifier} / page {page_no}",
        fill="black",
        font=body_font,
    )
    top = margin + max(72, height // 12)
    gap = max(18, height // 48)
    block_height = max(100, (height - top - margin - gap * (len(blocks) - 1)) // len(blocks))
    for index, block in enumerate(blocks):
        y = top + index * (block_height + gap)
        draw.rectangle((margin, y, width - margin, y + block_height), outline="black", width=2)
        # The label is intentionally rendered verbatim (for example, "Q1"),
        # rather than as a numeric shorthand such as "1.".
        draw.text((margin + 18, y + 16), block.question_no, fill="black", font=label_font)
        annotation = f" ({block.annotation})" if block.annotation else ""
        draw.text(
            (margin + 18, y + max(48, block_height // 4)),
            f"{block.text}{annotation}",
            fill="black",
            font=body_font,
        )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
