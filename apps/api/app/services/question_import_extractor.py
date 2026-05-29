from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import fitz

from app.schemas import DraftQuestion

QUESTION_PATTERN = re.compile(
    r"^\s*(?:Q\.?\s*|Question\s+)?(?P<number>\d+)[\.)\:]?\s*(?P<text>.*)$",
    re.IGNORECASE,
)
MARK_PATTERNS = (
    re.compile(r"\[(?P<marks>\d+(?:\.\d+)?)\s*marks?\]", re.IGNORECASE),
    re.compile(r"\((?P<marks>\d+(?:\.\d+)?)\)", re.IGNORECASE),
    re.compile(r"(?P<marks>\d+(?:\.\d+)?)\s*marks?\b", re.IGNORECASE),
)


class QuestionExtractor(Protocol):
    provider: str

    def extract(self, file_path: Path, content_type: str) -> list[DraftQuestion]: ...


class MockQuestionExtractor:
    provider = "mock"

    def extract(self, file_path: Path, content_type: str) -> list[DraftQuestion]:
        source_lines = extract_text_lines(file_path, content_type)
        drafts: list[DraftQuestion] = []
        for page_no, line in source_lines:
            match = QUESTION_PATTERN.match(line)
            if not match:
                continue
            question_text, marks = extract_marks(match.group("text").strip())
            question_text = question_text.strip(" -:")
            if not question_text:
                question_text = line.strip()
            drafts.append(
                DraftQuestion(
                    draft_id=f"draft-{len(drafts) + 1}",
                    question_no=match.group("number"),
                    question_text=question_text,
                    model_answer=None,
                    total_marks=marks,
                    confidence=Decimal("0.80") if marks is not None else Decimal("0.65"),
                    source_page=page_no,
                    source_text_excerpt=line.strip()[:500],
                    needs_review=True,
                )
            )
        if drafts:
            return drafts
        fallback_excerpt = source_lines[0][1].strip()[:500] if source_lines else file_path.name
        return [
            DraftQuestion(
                draft_id="draft-1",
                question_no="1",
                question_text="Review uploaded question paper and enter extracted question text.",
                model_answer=None,
                total_marks=None,
                confidence=Decimal("0.20"),
                source_page=1,
                source_text_excerpt=fallback_excerpt,
                needs_review=True,
            )
        ]


def extract_text_lines(file_path: Path, content_type: str) -> list[tuple[int, str]]:
    if content_type == "application/pdf":
        return extract_pdf_lines(file_path)
    return []


def extract_pdf_lines(file_path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document, start=1):
            for raw_line in page.get_text("text").splitlines():
                line = raw_line.strip()
                if line:
                    lines.append((index, line))
    return lines


def extract_marks(text: str) -> tuple[str, Decimal | None]:
    for pattern in MARK_PATTERNS:
        match = pattern.search(text)
        if match:
            marks = Decimal(match.group("marks")).quantize(Decimal("0.01"))
            cleaned = (text[: match.start()] + text[match.end() :]).strip()
            return cleaned, marks
    return text, None
