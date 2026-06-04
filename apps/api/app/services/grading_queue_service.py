from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import GradingQueueItem, GradingQueueRun
from app.services.evidence_prep_service import EvidencePrepService

ALLOWED_CONTINUATION_STATUSES = {
    "checked_no_continuation",
    "continuation_confirmed_included",
    "continuation_confirmed_not_needed",
}


class GradingQueueService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.evidence_prep_service = EvidencePrepService(db)

    def build_queue_run(
        self,
        *,
        assessment_id: int,
        created_by_teacher_id: int,
        evidence_prep_run_id: int | None = None,
    ) -> tuple[GradingQueueRun, list[dict[str, Any]]]:
        summary = self.evidence_prep_service.summarize_assessment(assessment_id)
        run = GradingQueueRun(
            assessment_id=assessment_id,
            evidence_prep_run_id=evidence_prep_run_id,
            created_by_teacher_id=created_by_teacher_id,
            status="pending",
            total_candidate_packets=int(summary["total_expected_packets"]),
        )
        self.db.add(run)
        self.db.flush()

        refused_items: list[dict[str, Any]] = []
        queued_count = 0
        for packet in summary["packets"]:
            refusal_reasons = self.refusal_reasons(packet)
            if refusal_reasons:
                refused_items.append(self.refused_item_from_packet(packet, refusal_reasons))
                continue
            self.db.add(self.queue_item_from_packet(run.id, assessment_id, packet))
            queued_count += 1

        run.queued_item_count = queued_count
        run.refused_item_count = len(refused_items)
        run.status = "built" if queued_count > 0 else "blocked"
        run.error = None
        self.db.commit()
        self.db.refresh(run)
        return run, refused_items

    def summarize_queue_run(
        self, run: GradingQueueRun
    ) -> tuple[list[GradingQueueItem], list[dict[str, Any]]]:
        summary = self.evidence_prep_service.summarize_assessment(run.assessment_id)
        refused_items = [
            self.refused_item_from_packet(packet, reasons)
            for packet in summary["packets"]
            if (reasons := self.refusal_reasons(packet))
        ]
        return list(run.items), refused_items

    def summarize_assessment(self, assessment_id: int) -> dict[str, Any]:
        summary = self.evidence_prep_service.summarize_assessment(assessment_id)
        refused_items = []
        queued_items = []
        for packet in summary["packets"]:
            reasons = self.refusal_reasons(packet)
            if reasons:
                refused_items.append(self.refused_item_from_packet(packet, reasons))
            else:
                queued_items.append(packet)
        return {
            "assessment_id": assessment_id,
            "status": "built" if queued_items else "blocked",
            "total_candidate_packets": int(summary["total_expected_packets"]),
            "queued_item_count": len(queued_items),
            "refused_item_count": len(refused_items),
            "items": [],
            "refused_items": refused_items,
            "error": None,
        }

    def refusal_reasons(self, packet: dict[str, Any]) -> list[str]:
        reasons = list(packet.get("blockers", []))
        evidence_status = packet.get("evidence_status")
        continuation_status = packet.get("continuation_check_status")
        if packet.get("answer_region_id") is None:
            self._append_once(reasons, "no answer region")
        if evidence_status != "complete":
            self._append_once(reasons, f"evidence_status={evidence_status} refused")
        if packet.get("ready_for_grading") is not True:
            self._append_once(reasons, "packet is not ready_for_grading")
        max_marks = packet.get("max_marks")
        if max_marks is None or Decimal(str(max_marks)) <= 0:
            self._append_once(reasons, "max marks must be positive")
        if int(packet.get("segment_count") or 0) < 1:
            self._append_once(reasons, "no confirmed answer segment")
        if not packet.get("pages_covered"):
            self._append_once(reasons, "missing crop/context")
        if continuation_status not in ALLOWED_CONTINUATION_STATUSES:
            self._append_once(reasons, f"continuation_status={continuation_status} refused")
        return reasons

    def queue_item_from_packet(
        self, queue_run_id: int, assessment_id: int, packet: dict[str, Any]
    ) -> GradingQueueItem:
        snapshot = self.snapshot_from_packet(packet)
        question_id = int(packet["question_id"])
        return GradingQueueItem(
            queue_run_id=queue_run_id,
            assessment_id=assessment_id,
            submission_id=int(packet["submission_id"]),
            student_identifier=packet.get("student_identifier"),
            question_id=question_id,
            grading_unit_id=question_id,
            grading_unit_label=str(packet["grading_unit_label"]),
            max_marks=Decimal(str(packet["max_marks"])),
            answer_region_id=int(packet["answer_region_id"]),
            segment_count=int(packet["segment_count"]),
            pages_covered=list(packet["pages_covered"]),
            evidence_status=str(packet["evidence_status"]),
            continuation_check_status=str(packet["continuation_check_status"]),
            queue_status="pending_review",
            provider_allowed=False,
            evidence_snapshot_hash=self.snapshot_hash(snapshot),
            readiness_snapshot_json=snapshot,
        )

    def refused_item_from_packet(
        self, packet: dict[str, Any], refusal_reasons: list[str]
    ) -> dict[str, Any]:
        question_id = packet.get("question_id")
        return {
            "submission_id": packet["submission_id"],
            "student_identifier": packet.get("student_identifier"),
            "question_id": question_id,
            "grading_unit_id": question_id,
            "grading_unit_label": packet.get("grading_unit_label"),
            "answer_region_id": packet.get("answer_region_id"),
            "evidence_status": packet["evidence_status"],
            "continuation_check_status": packet["continuation_check_status"],
            "segment_count": packet["segment_count"],
            "pages_covered": packet["pages_covered"],
            "refusal_reasons": refusal_reasons,
            "readiness_snapshot_json": self.snapshot_from_packet(packet),
        }

    def snapshot_from_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "submission_id": packet["submission_id"],
            "student_identifier": packet.get("student_identifier"),
            "question_id": packet.get("question_id"),
            "grading_unit_label": packet.get("grading_unit_label"),
            "max_marks": str(packet.get("max_marks")),
            "answer_region_id": packet.get("answer_region_id"),
            "evidence_status": packet["evidence_status"],
            "continuation_check_status": packet["continuation_check_status"],
            "ready_for_grading": packet["ready_for_grading"],
            "blockers": list(packet.get("blockers", [])),
            "warnings": list(packet.get("warnings", [])),
            "segment_count": packet["segment_count"],
            "pages_covered": list(packet.get("pages_covered", [])),
        }

    def snapshot_hash(self, snapshot: dict[str, Any]) -> str:
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _append_once(self, reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
