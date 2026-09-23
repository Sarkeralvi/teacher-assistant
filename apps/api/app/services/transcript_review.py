from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AnswerEvidenceAssignment,
    ScriptPageTranscript,
    ScriptTranscript,
)


def load_transcript_review_graph(db: Session, transcript_id: int) -> ScriptTranscript:
    transcript = db.scalar(
        select(ScriptTranscript)
        .options(
            selectinload(ScriptTranscript.pages).selectinload(
                ScriptPageTranscript.blocks
            )
        )
        .where(ScriptTranscript.id == transcript_id)
    )
    if transcript is None:
        raise ValueError("Script transcript is unavailable")
    return transcript


def current_review_snapshot(db: Session, transcript: ScriptTranscript) -> str:
    assignments = list(
        db.scalars(
            select(AnswerEvidenceAssignment)
            .options(selectinload(AnswerEvidenceAssignment.spans))
            .where(
                AnswerEvidenceAssignment.script_transcript_id == transcript.id,
                AnswerEvidenceAssignment.is_current.is_(True),
            )
            .order_by(AnswerEvidenceAssignment.question_node_id)
        ).all()
    )
    payload = {
        "transcript_id": transcript.id,
        "source_manifest_sha256": transcript.source_manifest_sha256,
        "pages": [
            {
                "id": page.id,
                "page_no": page.page_no,
                "state": page.state,
                "teacher_classification": page.teacher_classification,
                "blocks": [
                    {
                        "id": block.id,
                        "effective_text": block.effective_text,
                        "revision": block.revision,
                        "effective_question_label": block.effective_question_label,
                        "effective_continues_from_previous": (
                            block.effective_continues_from_previous
                        ),
                        "assignment_override_revision": (
                            block.assignment_override_revision
                        ),
                    }
                    for block in sorted(page.blocks, key=lambda item: item.block_index)
                ],
            }
            for page in sorted(transcript.pages, key=lambda item: item.page_order)
        ],
        "assignments": [
            {
                "id": assignment.id,
                "question_node_id": assignment.question_node_id,
                "assignment_version": assignment.assignment_version,
                "state": assignment.state,
                "coverage_complete": assignment.coverage_complete,
                "unresolved_block_count": assignment.unresolved_block_count,
                "unassigned_block_count": assignment.unassigned_block_count,
                "spans": [
                    {
                        "block_id": span.script_transcript_block_id,
                        "page_no": span.page_no,
                        "order_index": span.order_index,
                        "basis": span.assignment_basis,
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                    }
                    for span in sorted(
                        assignment.spans, key=lambda item: item.order_index
                    )
                ],
            }
            for assignment in assignments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def transcript_review_is_current(db: Session, transcript: ScriptTranscript) -> bool:
    return bool(
        transcript.reviewed_at
        and transcript.reviewed_by_teacher_id
        and transcript.review_snapshot_sha256
        and transcript.review_snapshot_sha256 == current_review_snapshot(db, transcript)
    )
