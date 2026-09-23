"""Shared contract for assigning a complete saved transcript to questions.

The vision pass owns transcription.  This pass receives only the immutable
page/block identifiers and saved text, then selects which blocks belong to each
finalized question.  It cannot alter text, create geometry, or grade work.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FULL_TRANSCRIPT_ASSIGNMENT_PROMPT_VERSION = "full-transcript-assignment-v1"


class TranscriptBlockReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_no: int = Field(ge=1)
    block_orders: list[int] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def block_orders_are_unique(self) -> TranscriptBlockReference:
        if len(self.block_orders) != len(set(self.block_orders)):
            raise ValueError("transcript block orders must be unique")
        return self


class TranscriptQuestionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: int = Field(gt=0)
    question_no: str = Field(min_length=1, max_length=128)
    status: Literal["mapped", "uncertain", "not_found"]
    block_references: list[TranscriptBlockReference] = Field(default_factory=list)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    warnings: list[str] = Field(default_factory=list, max_length=20)
    needs_review: bool = True

    @model_validator(mode="after")
    def references_match_status(self) -> TranscriptQuestionAssignment:
        if self.status == "not_found" and self.block_references:
            raise ValueError("not_found assignments cannot contain block references")
        if self.status != "not_found" and not self.block_references:
            raise ValueError("mapped or uncertain assignments require block references")
        if self.needs_review is not True:
            raise ValueError("transcript assignments always require teacher review")
        return self


class FullTranscriptAssignmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[TranscriptQuestionAssignment] = Field(min_length=1, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=20)


def build_full_transcript_assignment_prompt(
    *,
    pages: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> str:
    """Build one bounded text-only assignment prompt for the whole script."""

    if not questions:
        raise ValueError("Finalized questions are required for transcript assignment")
    references = [
        {
            "question_id": int(question["question_id"]),
            "question_no": str(question["question_no"]).strip(),
            "question_text": str(question.get("question_text") or "").strip(),
        }
        for question in questions
    ]
    if any(not item["question_no"] for item in references):
        raise ValueError("Finalized question labels must be nonempty")

    block_lines: list[str] = []
    seen: set[tuple[int, int]] = set()
    for page in pages:
        page_no = int(page.get("page") or page.get("page_no") or 0)
        if page_no < 1:
            raise ValueError("Transcript page number is invalid")
        block_lines.append(f"--- SCRIPT PAGE {page_no} ---")
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError("Transcript blocks are missing")
        for block in blocks:
            order = int(block.get("order") or 0)
            text = str(block.get("text") or "").strip()
            if order < 1 or not text:
                continue
            key = (page_no, order)
            if key in seen:
                raise ValueError("Transcript block identifiers are not unique")
            seen.add(key)
            block_lines.append(f"[page={page_no} block={order}] {text}")
    if not seen:
        raise ValueError("The saved transcript contains no writing to assign")

    schema_example = (
        '{"mappings":[{"question_id":1,"question_no":"1(a)",'
        '"status":"mapped|uncertain|not_found",'
        '"block_references":[{"page_no":1,"block_orders":[1,2]}],'
        '"confidence":0.0,"warnings":[],"needs_review":true}],"warnings":[]}'
    )
    return (
        "Assign the SAVED COMPLETE-SCRIPT TRANSCRIPT below to the finalized questions. "
        "This is a text-evidence boundary task, not grading and not transcription. Use only "
        "the supplied immutable page/block identifiers. Never rewrite, correct, solve, score, "
        "or invent student work. Use headings when present, but also use the whole document's "
        "reading order, hierarchical numbering such as (a)/(i), continuation across pages, "
        "and question subject matter when a student omitted or abbreviated a heading. Wrong, "
        "partial, crossed-out, and irrelevant work still belongs to its physical question. "
        "Each block may belong to at most one question. Return every finalized question exactly "
        "once. Use uncertain when a boundary has more than one plausible owner. Use not_found "
        "only when no supplied block answers that question. Every mapping must keep "
        "needs_review=true. Return exactly this JSON shape with no extra keys: "
        f"{schema_example}\n\nFINALIZED QUESTIONS\n"
        + json.dumps(references, ensure_ascii=False, separators=(",", ":"))
        + "\n\nSAVED COMPLETE-SCRIPT TRANSCRIPT\n"
        + "\n".join(block_lines)
    )


def validate_full_transcript_assignment(
    output: FullTranscriptAssignmentOutput,
    *,
    pages: list[dict[str, Any]],
    questions: list[dict[str, Any]],
) -> None:
    """Fail closed if identity or block ownership escaped the supplied inputs."""

    expected = {
        (int(question["question_id"]), str(question["question_no"]).strip())
        for question in questions
    }
    actual = {(item.question_id, item.question_no.strip()) for item in output.mappings}
    if actual != expected:
        raise ValueError("Transcript assignment changed or omitted finalized questions")

    valid_blocks = {
        (int(page.get("page") or page.get("page_no") or 0), int(block.get("order") or 0))
        for page in pages
        for block in (page.get("blocks") or [])
        if int(block.get("order") or 0) > 0 and str(block.get("text") or "").strip()
    }
    claimed: set[tuple[int, int]] = set()
    for mapping in output.mappings:
        for reference in mapping.block_references:
            for order in reference.block_orders:
                key = (reference.page_no, order)
                if key not in valid_blocks:
                    raise ValueError("Transcript assignment referenced an unknown block")
                if key in claimed:
                    raise ValueError("Transcript assignment claimed one block more than once")
                claimed.add(key)
