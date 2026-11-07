"""Tie a draft grade to the exact evidence it was graded against.

A suggestion pinned its rubric but not its evidence, so re-reading a page,
re-deriving an assignment, editing a transcript or changing a model answer left
an existing draft sitting next to evidence it had never seen, looking current.

Two mechanisms, deliberately not one:

* ``supersede_stale_suggestions`` marks what the workflow already knows is out
  of date, so a reviewer sees it. Nothing is deleted; the superseded draft and
  its reason stay readable.
* ``assert_suggestion_matches_current_evidence`` re-checks at finalization. A
  gate that depends on an invalidation hook having been called at every write
  site is a gate that fails the first time someone adds a write site, so the
  decisive check happens where the irreversible action is.

Neither approves, rejects or scores anything. Finalization remains a teacher
action; this only refuses to let one happen against evidence that has moved.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnswerEvidenceAssignment,
    AnswerRegion,
    BulkEvaluationItem,
    BulkEvaluationRun,
    GradeSuggestion,
    Question,
    Rubric,
    ScriptTranscript,
    ScriptTranscriptBlock,
)


class EvidenceChangedError(RuntimeError):
    """The evidence under a draft grade is not the evidence it was graded on."""


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class EvidenceInvalidationService:
    """Compute and enforce the source-evidence fingerprint of a draft grade."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def fingerprint_for_region(self, region: AnswerRegion) -> str:
        """Digest everything a grade depends on that is not the grade itself.

        Covers the four things the work order requires to invalidate a draft:
        the source pages and their transcript, the question assignment, the
        canonical question and its solution, and the active rubric. Transcript
        block revisions are included, so a teacher's correction to the text
        counts as a change even though the source image did not move.
        """

        question = self.db.get(Question, region.question_id) if region.question_id else None
        rubric = None
        if question is not None:
            rubric = self.db.scalars(
                select(Rubric)
                .where(Rubric.question_id == question.id)
                .where(Rubric.is_active.is_(True))
                .order_by(Rubric.version.desc(), Rubric.id.desc())
            ).first()

        assignment = None
        if region.question_id is not None:
            assignment = self.db.scalars(
                select(AnswerEvidenceAssignment)
                .join(
                    ScriptTranscript,
                    ScriptTranscript.id == AnswerEvidenceAssignment.script_transcript_id,
                )
                .where(
                    AnswerEvidenceAssignment.submission_id == region.submission_id,
                    AnswerEvidenceAssignment.question_id == region.question_id,
                    AnswerEvidenceAssignment.is_current.is_(True),
                )
                .order_by(AnswerEvidenceAssignment.id.desc())
            ).first()

        transcript_part: dict[str, Any] = {}
        if assignment is not None:
            transcript = self.db.get(ScriptTranscript, assignment.script_transcript_id)
            block_ids = [span.script_transcript_block_id for span in assignment.spans]
            blocks = (
                self.db.scalars(
                    select(ScriptTranscriptBlock).where(ScriptTranscriptBlock.id.in_(block_ids))
                ).all()
                if block_ids
                else []
            )
            transcript_part = {
                "script_transcript_id": assignment.script_transcript_id,
                "source_manifest_sha256": (
                    transcript.source_manifest_sha256 if transcript else None
                ),
                "transcript_status": transcript.status if transcript else None,
                "assignment_version": assignment.assignment_version,
                "evidence_state": assignment.state,
                "coverage_complete": assignment.coverage_complete,
                "spans": [
                    {
                        "block_id": span.script_transcript_block_id,
                        "order_index": span.order_index,
                        "basis": span.assignment_basis,
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                    }
                    for span in sorted(assignment.spans, key=lambda item: item.order_index)
                ],
                # A teacher's correction changes the evidence without moving a
                # single source pixel, so the text itself is part of identity.
                "block_text": sorted(
                    (block.id, _digest(block.text), block.revision) for block in blocks
                ),
            }

        return _digest(
            {
                "answer_region_id": region.id,
                "submission_id": region.submission_id,
                "question_id": region.question_id,
                "manual_answer_text": _digest(region.manual_answer_text or ""),
                "full_answer_confirmed": region.full_answer_confirmed,
                "segments": [
                    {
                        "id": segment.id,
                        "page_id": segment.submission_page_id,
                        "order_index": segment.order_index,
                        "confirmed": segment.confirmed,
                        "image_path": segment.image_path,
                    }
                    for segment in sorted(region.segments, key=lambda item: item.order_index)
                ],
                "model_answer": _digest((question.model_answer or "") if question else ""),
                "question_text": _digest((question.question_text or "") if question else ""),
                "rubric_id": rubric.id if rubric else None,
                "rubric_version": rubric.version if rubric else None,
                "rubric_json": _digest(rubric.rubric_json if rubric else None),
                "transcript": transcript_part,
            }
        )

    def fingerprint_for_region_id(self, answer_region_id: int) -> str | None:
        region = self.db.get(AnswerRegion, answer_region_id)
        if region is None:
            return None
        return self.fingerprint_for_region(region)

    def supersede_stale_suggestions(
        self,
        *,
        submission_id: int,
        reason: str,
    ) -> list[GradeSuggestion]:
        """Mark every draft whose evidence has moved. Deletes nothing."""

        suggestions = self.db.scalars(
            select(GradeSuggestion)
            .join(AnswerRegion, AnswerRegion.id == GradeSuggestion.answer_region_id)
            .where(
                AnswerRegion.submission_id == submission_id,
                GradeSuggestion.superseded_at.is_(None),
            )
        ).all()
        changed: list[GradeSuggestion] = []
        for suggestion in suggestions:
            if suggestion.source_evidence_fingerprint is None:
                # Never recorded, so there is nothing to compare. Saying such a
                # draft is stale would be a guess, and saying it is fresh would
                # be a stronger claim than the data supports; the finalization
                # gate treats it as unverified either way.
                continue
            region = self.db.get(AnswerRegion, suggestion.answer_region_id)
            if region is None:
                continue
            if self.fingerprint_for_region(region) == suggestion.source_evidence_fingerprint:
                continue
            suggestion.superseded_at = datetime.now(UTC)
            suggestion.superseded_reason = reason
            changed.append(suggestion)
        if changed:
            self._quarantine_superseded_bulk_drafts(changed, reason)
            self.db.commit()
        return changed

    def _quarantine_superseded_bulk_drafts(
        self, suggestions: list[GradeSuggestion], reason: str
    ) -> None:
        """Take a superseded draft out of its bulk run's clean set, visibly.

        A bulk item still 'graded' would keep offering the draft for bulk approval although
        finalization refuses it. It becomes a 'stale_evidence' exception instead; the teacher
        resumes it (re-grade on the current evidence) or rejects the draft.
        """

        items = self.db.scalars(
            select(BulkEvaluationItem).where(
                BulkEvaluationItem.grade_suggestion_id.in_([s.id for s in suggestions]),
                BulkEvaluationItem.status == "graded",
                BulkEvaluationItem.final_grade_id.is_(None),
            )
        ).all()
        warning = f"Draft superseded after grading: {reason}"[:500]
        for item in items:
            item.status = "exception"
            item.exception_codes = list(
                dict.fromkeys([*(item.exception_codes or []), "stale_evidence"])
            )
            item.warnings = list(dict.fromkeys([*(item.warnings or []), warning]))
            run = self.db.get(BulkEvaluationRun, item.run_id)
            if run is not None:
                run.clean_item_count = max(0, run.clean_item_count - 1)
                run.exception_count += 1

    def suggestion_evidence_status(self, suggestion: GradeSuggestion) -> str:
        """``current``, ``stale``, ``unverified`` or ``evidence_missing``."""

        if suggestion.source_evidence_fingerprint is None:
            return "unverified"
        region = self.db.get(AnswerRegion, suggestion.answer_region_id)
        if region is None:
            return "evidence_missing"
        if self.fingerprint_for_region(region) != suggestion.source_evidence_fingerprint:
            return "stale"
        return "current"

    def assert_suggestion_matches_current_evidence(
        self, suggestion: GradeSuggestion
    ) -> None:
        """Refuse to finalize a draft graded against evidence that has moved.

        Checked here rather than only at the point evidence changes, because a
        new write site that forgets to invalidate must not be able to open a
        path to a final grade.
        """

        status = self.suggestion_evidence_status(suggestion)
        if status == "current" or status == "unverified":
            return
        if status == "evidence_missing":
            raise EvidenceChangedError(
                "The answer evidence behind this draft no longer exists; it cannot be finalized"
            )
        raise EvidenceChangedError(
            "The evidence behind this draft has changed since it was graded. "
            "Re-run grading against the current evidence before finalizing it."
        )
