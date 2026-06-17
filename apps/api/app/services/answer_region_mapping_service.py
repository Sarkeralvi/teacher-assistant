from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import fitz
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionSegment,
    Question,
    QuestionNode,
    Submission,
)
from app.services.answer_region_processing import crop_answer_region_image
from app.services.storage import LocalStorage

LABEL_PATTERN_TEMPLATE = r"(?<!\w){label}(?!\w)"
TOP_LEVEL_QUESTION_PATTERN = re.compile(r"^(Q\d+)", re.IGNORECASE)


@dataclass
class PageTextMatch:
    page_no: int
    page_index: int
    start: int
    end: int
    label: str
    page_text: str


@dataclass
class DeterministicMappingCandidate:
    question_node: QuestionNode
    question: Question | None
    status: str
    blocker_reason: str | None
    confidence: Decimal | None
    source_page: int | None
    source_reference: dict[str, Any] | None
    page_id: int | None
    x: Decimal | None
    y: Decimal | None
    width: Decimal | None
    height: Decimal | None


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _label_variants(node: QuestionNode) -> list[str]:
    variants: list[str] = []
    for raw in (node.label, node.question_number):
        if not raw:
            continue
        normalized = _normalize_space(raw)
        if normalized:
            variants.append(normalized)
        compact = normalized.replace(" ", "")
        if compact and compact not in variants:
            variants.append(compact)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in variants:
        key = value.casefold()
        if key not in seen:
            deduped.append(value)
            seen.add(key)
    return deduped


def _find_original_upload_path(storage: LocalStorage, submission_id: int) -> Path | None:
    upload_dir = storage.uploads_dir / "submissions" / str(submission_id)
    if not upload_dir.is_dir():
        return None
    files = sorted(upload_dir.glob("original-*"))
    return files[-1] if files else None


def _extract_pdf_page_texts(pdf_path: Path) -> list[tuple[int, str]]:
    doc = fitz.open(pdf_path)
    try:
        return [
            (index + 1, _normalize_space(doc.load_page(index).get_text("text")))
            for index in range(len(doc))
        ]
    finally:
        doc.close()


def _find_matches(page_texts: list[tuple[int, str]], variants: list[str]) -> list[PageTextMatch]:
    matches: list[PageTextMatch] = []
    seen: set[tuple[int, int, int]] = set()
    for page_index, (page_no, page_text) in enumerate(page_texts):
        for label in variants:
            pattern = re.compile(
                LABEL_PATTERN_TEMPLATE.format(label=re.escape(label)), re.IGNORECASE
            )
            for match in pattern.finditer(page_text):
                key = (page_no, match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                matches.append(
                    PageTextMatch(
                        page_no=page_no,
                        page_index=page_index,
                        start=match.start(),
                        end=match.end(),
                        label=label,
                        page_text=page_text,
                    )
                )
    matches.sort(key=lambda item: (item.page_no, item.start, item.end))
    return matches


def _resolve_question_for_node(
    db: Session, assessment_id: int, node: QuestionNode
) -> Question | None:
    questions = db.scalars(
        select(Question).where(Question.assessment_id == assessment_id).order_by(Question.id)
    ).all()
    variants = [value.casefold() for value in _label_variants(node)]
    for question in questions:
        if question.question_no.casefold() in variants:
            return question
    top_level = TOP_LEVEL_QUESTION_PATTERN.match(node.question_number or node.label or "")
    if top_level is not None:
        target = top_level.group(1).casefold()
        for question in questions:
            if question.question_no.casefold() == target:
                return question
    return questions[0] if len(questions) == 1 else None


def _estimate_box(
    submission: Submission, page_id: int, ordinal_index: int, total_count: int
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    page = next(page for page in submission.pages if page.id == page_id)
    with Image.open(LocalStorage().resolve_relative(page.image_path)) as image:
        width = Decimal(str(image.width))
        height = Decimal(str(image.height))
    margin_x = Decimal("24")
    usable_width = max(width - (margin_x * 2), Decimal("120"))
    section_height = max(
        (height - Decimal("48")) / Decimal(str(max(total_count, 1))), Decimal("120")
    )
    y = Decimal("24") + (section_height * Decimal(str(ordinal_index)))
    if y + section_height > height - Decimal("12"):
        section_height = max(height - y - Decimal("12"), Decimal("80"))
    return (margin_x, y, usable_width, section_height)


def build_submission_mapping_candidates(
    db: Session, submission: Submission
) -> list[DeterministicMappingCandidate]:
    confirmed_nodes = db.scalars(
        select(QuestionNode)
        .where(QuestionNode.assessment_id == submission.assessment_id)
        .where(QuestionNode.teacher_confirmed.is_(True))
        .where(QuestionNode.node_type.in_(["question", "subquestion"]))
        .order_by(QuestionNode.source_page.asc().nulls_last(), QuestionNode.id.asc())
    ).all()
    if not confirmed_nodes:
        return []

    storage = LocalStorage()
    upload_path = _find_original_upload_path(storage, submission.id)
    if upload_path is None or upload_path.suffix.lower() != ".pdf":
        return [
            DeterministicMappingCandidate(
                question_node=node,
                question=_resolve_question_for_node(db, submission.assessment_id, node),
                status="blocked",
                blocker_reason=(
                    "Automatic mapping currently requires a text-based PDF upload "
                    "for deterministic label detection."
                ),
                confidence=None,
                source_page=None,
                source_reference=None,
                page_id=None,
                x=None,
                y=None,
                width=None,
                height=None,
            )
            for node in confirmed_nodes
        ]

    page_texts = _extract_pdf_page_texts(upload_path)
    page_id_by_no = {page.page_no: page.id for page in submission.pages}
    counts_by_page: dict[int, int] = defaultdict(int)
    page_ordinals: dict[tuple[int, int], int] = {}
    matches_by_node: dict[int, list[PageTextMatch]] = {}
    for node in confirmed_nodes:
        matches = _find_matches(page_texts, _label_variants(node))
        matches_by_node[node.id] = matches
    for node in confirmed_nodes:
        matches = matches_by_node[node.id]
        if len(matches) == 1 and matches[0].page_no in page_id_by_no:
            counts_by_page[matches[0].page_no] += 1
            page_ordinals[(node.id, matches[0].page_no)] = counts_by_page[matches[0].page_no] - 1

    candidates: list[DeterministicMappingCandidate] = []
    for node in confirmed_nodes:
        question = _resolve_question_for_node(db, submission.assessment_id, node)
        matches = matches_by_node[node.id]
        if question is None:
            candidates.append(
                DeterministicMappingCandidate(
                    question_node=node,
                    question=None,
                    status="blocked",
                    blocker_reason=(
                        "No confirmed grading question matches this confirmed "
                        "question node yet."
                    ),
                    confidence=None,
                    source_page=None,
                    source_reference=None,
                    page_id=None,
                    x=None,
                    y=None,
                    width=None,
                    height=None,
                )
            )
            continue
        if len(matches) == 0:
            candidates.append(
                DeterministicMappingCandidate(
                    question_node=node,
                    question=question,
                    status="blocked",
                    blocker_reason=(
                        f"No visible label match found for {node.label} in the "
                        "uploaded script."
                    ),
                    confidence=Decimal("0.00"),
                    source_page=None,
                    source_reference={"label_variants": _label_variants(node)},
                    page_id=None,
                    x=None,
                    y=None,
                    width=None,
                    height=None,
                )
            )
            continue
        if len(matches) > 1:
            candidates.append(
                DeterministicMappingCandidate(
                    question_node=node,
                    question=question,
                    status="uncertain",
                    blocker_reason=(
                        f"Multiple visible label matches found for {node.label}; "
                        "teacher confirmation/correction required."
                    ),
                    confidence=Decimal("0.45"),
                    source_page=matches[0].page_no,
                    source_reference={
                        "label_variants": _label_variants(node),
                        "matches": [
                            {
                                "page_no": match.page_no,
                                "start": match.start,
                                "end": match.end,
                                "label": match.label,
                            }
                            for match in matches
                        ],
                    },
                    page_id=page_id_by_no.get(matches[0].page_no),
                    x=None,
                    y=None,
                    width=None,
                    height=None,
                )
            )
            continue
        match = matches[0]
        page_id = page_id_by_no.get(match.page_no)
        if page_id is None:
            candidates.append(
                DeterministicMappingCandidate(
                    question_node=node,
                    question=question,
                    status="blocked",
                    blocker_reason="Matched source page is not available in stored page images.",
                    confidence=Decimal("0.00"),
                    source_page=match.page_no,
                    source_reference={"start": match.start, "end": match.end, "label": match.label},
                    page_id=None,
                    x=None,
                    y=None,
                    width=None,
                    height=None,
                )
            )
            continue
        ordinal_index = page_ordinals.get((node.id, match.page_no), 0)
        total_count = max(counts_by_page.get(match.page_no, 1), 1)
        x, y, width, height = _estimate_box(submission, page_id, ordinal_index, total_count)
        candidates.append(
            DeterministicMappingCandidate(
                question_node=node,
                question=question,
                status="mapped",
                blocker_reason=None,
                confidence=Decimal("0.95"),
                source_page=match.page_no,
                source_reference={
                    "label": match.label,
                    "start": match.start,
                    "end": match.end,
                    "page_text_excerpt": match.page_text[
                        max(0, match.start - 40) : min(len(match.page_text), match.end + 120)
                    ],
                    "bbox_strategy": "estimated_page_partition",
                },
                page_id=page_id,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )
    return candidates


def upsert_answer_region_for_mapping(
    candidate: DeterministicMappingCandidate, submission: Submission, mapping: AnswerRegionMapping
) -> AnswerRegion | None:
    if (
        candidate.page_id is None
        or candidate.x is None
        or candidate.y is None
        or candidate.width is None
        or candidate.height is None
    ):
        return None
    storage = LocalStorage()
    page = next(page for page in submission.pages if page.id == candidate.page_id)
    image_path = crop_answer_region_image(
        storage=storage,
        source_image_path=page.image_path,
        submission_id=submission.id,
        x=candidate.x,
        y=candidate.y,
        width=candidate.width,
        height=candidate.height,
    )
    region = mapping.answer_region
    if region is None:
        region = AnswerRegion(
            submission_id=submission.id,
            question_id=candidate.question.id,
            question_node_id=candidate.question_node.id,
            page_id=page.id,
            x=candidate.x,
            y=candidate.y,
            width=candidate.width,
            height=candidate.height,
            image_path=image_path,
            evidence_status="unconfirmed",
            continuation_check_status="not_checked",
        )
    else:
        region.question_id = candidate.question.id
        region.question_node_id = candidate.question_node.id
        region.page_id = page.id
        region.x = candidate.x
        region.y = candidate.y
        region.width = candidate.width
        region.height = candidate.height
        region.image_path = image_path
    return region


def ensure_primary_segment(region: AnswerRegion) -> None:
    if region.segments:
        primary = region.segments[0]
        primary.submission_page_id = region.page_id
        primary.order_index = 1
        primary.x = region.x
        primary.y = region.y
        primary.width = region.width
        primary.height = region.height
        primary.image_path = region.image_path
        primary.source = "suggestion"
        primary.confirmed = region.full_answer_confirmed
        primary.is_primary = True
        return
    region.segments.append(
        AnswerRegionSegment(
            submission_page_id=region.page_id,
            order_index=1,
            x=region.x,
            y=region.y,
            width=region.width,
            height=region.height,
            image_path=region.image_path,
            source="suggestion",
            confirmed=region.full_answer_confirmed,
            is_primary=True,
        )
    )
