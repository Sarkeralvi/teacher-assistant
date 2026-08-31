from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.models import (
    AnswerRegion,
    Assessment,
    AuditLog,
    Course,
    GradeSuggestion,
    GradingDispatchItem,
    GradingDispatchRun,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    GradingRun,
    Question,
    Rubric,
    Submission,
)
from app.schemas import CohortDispatchRequest
from app.services.grading_integrity import rubric_snapshot_hash
from app.services.grading_queue_service import GradingQueueService
from app.services.grading_service import GradingService, sanitize_provider_error
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError
from packages.brain.capabilities import BrainCapability
from packages.brain.policy import brain_policy_from_settings


class GradingDispatchService:
    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def preflight(
        self,
        *,
        assessment_id: int,
        question_id: int,
        teacher_id: int,
        request: CohortDispatchRequest,
    ) -> dict[str, Any]:
        context = self._authorized_context(
            assessment_id=assessment_id,
            question_id=question_id,
            teacher_id=teacher_id,
            request=request,
        )
        return self._build_preflight(context, request.call_limit)

    def create_dispatch(
        self,
        *,
        assessment_id: int,
        question_id: int,
        teacher_id: int,
        request: CohortDispatchRequest,
    ) -> GradingDispatchRun:
        context = self._authorized_context(
            assessment_id=assessment_id,
            question_id=question_id,
            teacher_id=teacher_id,
            request=request,
        )
        preflight = self._build_preflight(context, request.call_limit)
        queue_run: GradingQueueRun = context["queue_run"]
        grading_run: GradingRun = context["grading_run"]
        rubric: Rubric = context["rubric"]
        question: Question = context["question"]
        pinned_rubric_hash = rubric_snapshot_hash(question, rubric)
        run = GradingDispatchRun(
            queue_run_id=queue_run.id,
            grading_run_id=grading_run.id,
            assessment_id=assessment_id,
            question_id=question_id,
            created_by_teacher_id=teacher_id,
            provider=str(context["provider"]),
            model_name=str(context["model_name"]),
            marking_policy=grading_run.marking_policy,
            maximum_calls=request.call_limit,
            draft_only_confirmed=request.draft_only_confirmed,
            status="queued",
            stop_requested=False,
            total_count=len(preflight["items"]),
            selected_count=preflight["selected_call_count"],
        )
        self.db.add(run)
        try:
            self.db.flush()
            for item_state in preflight["items"]:
                queue_item = self.db.get(GradingQueueItem, item_state["queue_item_id"])
                if queue_item is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A grading queue item disappeared during dispatch authorization",
                    )
                dispatch_status, reason = self._initial_item_status(item_state)
                grading_job_id = None
                if dispatch_status == "pending":
                    job = GradingJob(answer_region_id=queue_item.answer_region_id, status="queued")
                    self.db.add(job)
                    self.db.flush()
                    grading_job_id = job.id
                evidence_hash = (
                    item_state.get("evidence_snapshot_hash")
                    or queue_item.evidence_snapshot_hash
                    or "missing"
                )
                run.items.append(
                    GradingDispatchItem(
                        queue_item_id=queue_item.id,
                        answer_region_id=queue_item.answer_region_id,
                        grading_job_id=grading_job_id,
                        rubric_id=rubric.id,
                        evidence_snapshot_hash=evidence_hash,
                        rubric_snapshot_hash=pinned_rubric_hash,
                        status=dispatch_status,
                        attempt_count=0,
                        refusal_reason=reason,
                    )
                )
            self.db.flush()
            self._refresh_counts(run)
            if run.pending_count == 0:
                run.status = "completed"
                run.completed_at = datetime.now(UTC)
            self._audit(
                run,
                "grading_dispatch_requested",
                actor_type="teacher",
                actor_id=teacher_id,
                payload={
                    "queue_run_id": queue_run.id,
                    "grading_run_id": grading_run.id,
                    "question_id": question_id,
                    "provider": context["provider"],
                    "model": context["model_name"],
                    "maximum_calls": request.call_limit,
                    "selected_count": run.selected_count,
                    "draft_only_confirmed": True,
                },
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A queued or running grading job already exists for this answer region",
            ) from exc
        self.db.refresh(run)
        return self.get_run(run.id)

    def get_owned_run(self, run_id: int, teacher_id: int) -> GradingDispatchRun:
        run = self.get_run(run_id)
        if run.created_by_teacher_id != teacher_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Grading dispatch run not found",
            )
        return run

    def get_run(self, run_id: int) -> GradingDispatchRun:
        run = self.db.scalars(
            select(GradingDispatchRun)
            .options(selectinload(GradingDispatchRun.items))
            .where(GradingDispatchRun.id == run_id)
        ).first()
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Grading dispatch run not found",
            )
        return run

    def request_stop(self, run: GradingDispatchRun, teacher_id: int) -> GradingDispatchRun:
        if run.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Completed grading dispatches cannot be stopped",
            )
        if run.status == "stopped":
            return run
        run.stop_requested = True
        has_running_item = any(item.status == "running" for item in run.items)
        if run.status in {"queued", "failed"} and not has_running_item:
            run.status = "stopped"
            run.completed_at = datetime.now(UTC)
        else:
            run.status = "stopping"
        run.heartbeat_at = datetime.now(UTC)
        self._audit(
            run,
            "grading_dispatch_stop_requested",
            actor_type="teacher",
            actor_id=teacher_id,
        )
        self.db.commit()
        return self.get_run(run.id)

    def resume(self, run: GradingDispatchRun, teacher_id: int) -> GradingDispatchRun:
        self.reconcile_stale_worker(run, actor_id=teacher_id)
        run = self.get_run(run.id)
        if run.status not in {"stopped", "failed"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only stopped or failed grading dispatches can be resumed",
            )
        resumable = [
            item
            for item in run.items
            if item.status == "pending" and item.attempt_count == 0
        ]
        if not resumable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No never-started dispatch items remain",
            )
        run.stop_requested = False
        run.status = "queued"
        run.completed_at = None
        run.heartbeat_at = datetime.now(UTC)
        self._audit(
            run,
            "grading_dispatch_resumed",
            actor_type="teacher",
            actor_id=teacher_id,
            payload={"remaining_never_started_count": len(resumable)},
        )
        self.db.commit()
        return self.get_run(run.id)

    def reconcile_stale_worker(
        self, run: GradingDispatchRun, *, actor_id: int | None = None
    ) -> bool:
        if run.status not in {"running", "stopping"} or run.heartbeat_at is None:
            return False
        now = datetime.now(UTC)
        heartbeat = run.heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        timeout = timedelta(seconds=self.settings.cohort_dispatch_heartbeat_timeout_seconds)
        if now - heartbeat <= timeout:
            return False
        changed = False
        for item in run.items:
            if item.status != "running":
                continue
            item.status = "uncertain"
            item.error = "Worker heartbeat expired during a provider call; no retry is allowed"
            item.completed_at = now
            if item.grading_job_id is not None:
                job = self.db.get(GradingJob, item.grading_job_id)
                if job is not None:
                    job.status = "uncertain"
                    job.error = "Provider-call outcome is uncertain"
                    job.completed_at = now
            changed = True
        if changed:
            run.status = "failed"
            run.completed_at = now
            run.heartbeat_at = now
            self._refresh_counts(run)
            self._audit(
                run,
                "grading_dispatch_worker_outcome_uncertain",
                actor_type="teacher" if actor_id is not None else "system",
                actor_id=actor_id,
            )
            self.db.commit()
        return changed

    def mark_enqueue_failed(self, run_id: int) -> None:
        run = self.get_run(run_id)
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        self._audit(run, "grading_dispatch_enqueue_failed", actor_type="system")
        self.db.commit()

    def run_dispatch(self, run_id: int) -> None:
        run = self.db.scalars(
            select(GradingDispatchRun)
            .where(GradingDispatchRun.id == run_id)
            .with_for_update()
        ).first()
        if run is None or run.status != "queued":
            self.db.rollback()
            return
        now = datetime.now(UTC)
        if run.stop_requested:
            run.status = "stopped"
            run.completed_at = now
            run.heartbeat_at = now
            self.db.commit()
            return
        run.status = "running"
        run.started_at = run.started_at or now
        run.heartbeat_at = now
        self.db.commit()
        try:
            adapter = BrainAdapter.for_provider(self.settings, run.provider)
        except BrainProviderConfigurationError as exc:
            self._fail_run_configuration(run_id, str(exc))
            return
        if getattr(adapter.provider, "model_name", "") != run.model_name:
            self._fail_run_configuration(run_id, "Configured provider model changed")
            return

        while True:
            self.db.expire_all()
            run = self.get_run(run_id)
            if run.stop_requested:
                run.status = "stopped"
                run.completed_at = datetime.now(UTC)
                run.heartbeat_at = run.completed_at
                self._refresh_counts(run)
                self._audit(run, "grading_dispatch_stopped", actor_type="worker")
                self.db.commit()
                return
            item = next(
                (
                    candidate
                    for candidate in run.items
                    if candidate.status == "pending" and candidate.attempt_count == 0
                ),
                None,
            )
            if item is None:
                run.status = "completed"
                run.completed_at = datetime.now(UTC)
                run.heartbeat_at = run.completed_at
                self._refresh_counts(run)
                self._audit(run, "grading_dispatch_completed", actor_type="worker")
                self.db.commit()
                return
            if run.calls_started >= run.maximum_calls:
                run.status = "stopped"
                run.stop_requested = True
                run.completed_at = datetime.now(UTC)
                self._audit(
                    run,
                    "grading_dispatch_call_limit_reached",
                    actor_type="worker",
                )
                self.db.commit()
                return
            refusal = self._pre_call_refusal(run, item)
            if refusal is not None:
                self._refuse_item(run, item, refusal)
                continue
            started = datetime.now(UTC)
            item.status = "running"
            item.attempt_count = 1
            item.started_at = started
            run.calls_started += 1
            run.heartbeat_at = started
            if item.grading_job_id is None:
                self._refuse_item(run, item, "Dispatch item has no grading job")
                continue
            job = self.db.get(GradingJob, item.grading_job_id)
            if job is None:
                self._refuse_item(run, item, "Dispatch grading job is missing")
                continue
            job.status = "running"
            self._refresh_counts(run)
            self._audit(
                run,
                "grading_dispatch_item_started",
                actor_type="worker",
                item=item,
                payload={"attempt_count": 1, "provider_call_number": run.calls_started},
            )
            self.db.commit()
            try:
                _job, suggestion = GradingService(
                    self.db, adapter=adapter
                ).run_queued_job(
                    item.grading_job_id,
                    marking_policy=run.marking_policy,
                    expected_rubric_id=item.rubric_id,
                    expected_rubric_hash=item.rubric_snapshot_hash,
                )
            except Exception as exc:
                self.db.rollback()
                run = self.get_run(run_id)
                item = next(candidate for candidate in run.items if candidate.id == item.id)
                item.status = "failed"
                item.error = sanitize_provider_error(str(exc))[:1000]
                item.completed_at = datetime.now(UTC)
                run.status = "failed"
                run.completed_at = item.completed_at
                run.heartbeat_at = item.completed_at
                self._refresh_counts(run)
                self._audit(
                    run,
                    "grading_dispatch_item_failed",
                    actor_type="worker",
                    item=item,
                    payload={"provider_failure": True},
                )
                self.db.commit()
                return
            run = self.get_run(run_id)
            item = next(candidate for candidate in run.items if candidate.id == item.id)
            item.status = "succeeded"
            item.completed_at = datetime.now(UTC)
            run.heartbeat_at = item.completed_at
            self._refresh_counts(run)
            self._audit(
                run,
                "grading_dispatch_item_succeeded",
                actor_type="worker",
                item=item,
                payload={"grade_suggestion_id": suggestion.id},
            )
            self.db.commit()

    def _authorized_context(
        self,
        *,
        assessment_id: int,
        question_id: int,
        teacher_id: int,
        request: CohortDispatchRequest,
    ) -> dict[str, Any]:
        if not self.settings.cohort_model_grading_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="COHORT_MODEL_GRADING_ENABLED must be true",
            )
        queue_run = self.db.get(
            GradingQueueRun,
            request.queue_run_id,
            options=(selectinload(GradingQueueRun.items),),
        )
        if (
            queue_run is None
            or queue_run.assessment_id != assessment_id
            or queue_run.created_by_teacher_id != teacher_id
        ):
            raise HTTPException(status_code=404, detail="Grading queue run not found")
        if queue_run.status != "built":
            raise HTTPException(status_code=409, detail="Grading queue run is not built")
        grading_run = self.db.get(GradingRun, request.grading_run_id)
        if (
            grading_run is None
            or grading_run.assessment_id != assessment_id
            or grading_run.created_by_teacher_id != teacher_id
        ):
            raise HTTPException(status_code=404, detail="Grading run not found")
        if grading_run.mode != "custom_controlled":
            raise HTTPException(
                status_code=409,
                detail="Only Custom Controlled grading runs may dispatch a cohort",
            )
        question = self.db.get(Question, question_id)
        if question is None or question.assessment_id != assessment_id:
            raise HTTPException(status_code=404, detail="Question not found")
        if not (question.model_answer or "").strip():
            raise HTTPException(status_code=409, detail="Question has no model answer")
        rubrics = list(
            self.db.scalars(
                select(Rubric).where(
                    Rubric.question_id == question_id,
                    Rubric.is_active.is_(True),
                )
            ).all()
        )
        if len(rubrics) != 1:
            raise HTTPException(
                status_code=409,
                detail="Question must have exactly one active rubric",
            )
        try:
            policy = brain_policy_from_settings(
                self.settings,
                requested_provider=request.provider,
            )
            policy.validate_request(
                requested_provider=request.provider,
                expected_model=request.expected_model,
                capability=BrainCapability.GRADING,
                feature_enabled=self.settings.cohort_model_grading_enabled,
            )
        except BrainProviderConfigurationError as exc:
            detail = str(exc)
            status_code = (
                status.HTTP_409_CONFLICT
                if "Expected model does not match" in detail
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc
        try:
            policy.require_data_boundary_confirmation(
                confirmed=request.provider_data_boundary_confirmed
            )
        except BrainProviderConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        adapter = policy.adapter
        actual_model = getattr(adapter.provider, "model_name", "")
        if request.expected_model != actual_model:
            raise HTTPException(
                status_code=409,
                detail="Expected model does not match the configured provider model",
            )
        try:
            adapter.verify_available_model()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Configured grading provider is unavailable or its model alias "
                    "does not match"
                ),
            ) from exc
        if request.call_limit > self.settings.cohort_max_provider_calls:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Requested call limit exceeds the configured cohort provider-call ceiling"
                ),
            )
        return {
            "queue_run": queue_run,
            "grading_run": grading_run,
            "question": question,
            "rubric": rubrics[0],
            "provider": adapter.runtime.provider,
            "model_name": actual_model,
        }

    def _build_preflight(
        self, context: dict[str, Any], call_limit: int
    ) -> dict[str, Any]:
        queue_run: GradingQueueRun = context["queue_run"]
        grading_run: GradingRun = context["grading_run"]
        question: Question = context["question"]
        queue_views, _refused = GradingQueueService(self.db).summarize_queue_run(queue_run)
        view_by_id = {int(view["id"]): view for view in queue_views}
        question_items = sorted(
            (item for item in queue_run.items if item.question_id == question.id),
            key=lambda item: item.id,
        )
        region_ids = [item.answer_region_id for item in question_items]
        existing_regions = set(
            self.db.scalars(
                select(GradeSuggestion.answer_region_id).where(
                    GradeSuggestion.answer_region_id.in_(region_ids)
                )
            ).all()
        )
        active_regions = set(
            self.db.scalars(
                select(GradingJob.answer_region_id).where(
                    GradingJob.answer_region_id.in_(region_ids),
                    GradingJob.status.in_(["queued", "running"]),
                )
            ).all()
        )
        grader = GradingService(self.db, use_configured_adapter=False)
        items: list[dict[str, Any]] = []
        for queue_item in question_items:
            view = view_by_id.get(queue_item.id, {})
            current_hash = view.get("current_evidence_snapshot_hash")
            state: dict[str, Any] = {
                "queue_item_id": queue_item.id,
                "answer_region_id": queue_item.answer_region_id,
                "status": "eligible",
                "reason": None,
                "evidence_snapshot_hash": current_hash,
            }
            if queue_item.answer_region_id in existing_regions:
                state.update(status="existing", reason="already has a grade suggestion")
            elif view.get("stale_status") != "fresh":
                state.update(
                    status="stale",
                    reason=(
                        ", ".join(view.get("current_refusal_reasons") or [])
                        or f"evidence snapshot is {view.get('stale_status', 'missing')}"
                    ),
                )
            elif queue_item.answer_region_id in active_regions:
                state.update(status="active", reason="already has a queued or running job")
            else:
                try:
                    packet = grader.get_grading_evidence_packet(queue_item.answer_region_id)
                    readiness = packet["readiness_result"]
                    if not readiness["ready_for_grading"]:
                        state.update(
                            status="refused",
                            reason=", ".join(readiness.get("blockers", [])),
                        )
                except HTTPException as exc:
                    state.update(status="refused", reason=str(exc.detail))
            items.append(state)
        selected = 0
        for item in items:
            if item["status"] == "eligible" and selected < call_limit:
                item["status"] = "selected"
                selected += 1
        counts = Counter(str(item["status"]) for item in items)
        return {
            "assessment_id": queue_run.assessment_id,
            "question_id": question.id,
            "queue_run_id": queue_run.id,
            "grading_run_id": grading_run.id,
            "provider": context["provider"],
            "model_name": context["model_name"],
            "marking_policy": grading_run.marking_policy,
            "server_call_ceiling": self.settings.cohort_max_provider_calls,
            "requested_call_limit": call_limit,
            "total_queue_items": len(items),
            "fresh_count": counts["selected"] + counts["eligible"],
            "refused_count": counts["refused"] + counts["active"],
            "existing_count": counts["existing"],
            "stale_count": counts["stale"],
            "active_job_count": sum(
                1 for item in question_items if item.answer_region_id in active_regions
            ),
            "eligible_count": counts["selected"] + counts["eligible"],
            "selected_call_count": counts["selected"],
            "items": items,
        }

    def _initial_item_status(self, item_state: dict[str, Any]) -> tuple[str, str | None]:
        state = item_state["status"]
        if state == "selected":
            return "pending", None
        if state in {"existing", "eligible"}:
            reason = (
                item_state.get("reason")
                or "Not selected because the dispatch call limit was reached"
            )
            return "skipped", reason
        return "refused", item_state.get("reason") or "Dispatch preflight refused the item"

    def _pre_call_refusal(
        self, run: GradingDispatchRun, item: GradingDispatchItem
    ) -> str | None:
        queue_run = self.db.get(
            GradingQueueRun,
            run.queue_run_id,
            options=(selectinload(GradingQueueRun.items),),
        )
        queue_item = self.db.get(GradingQueueItem, item.queue_item_id)
        if queue_run is None or queue_item is None or queue_item.queue_run_id != queue_run.id:
            return "Pinned grading queue item is missing"
        if (
            queue_run.created_by_teacher_id != run.created_by_teacher_id
            or queue_run.assessment_id != run.assessment_id
        ):
            return "Grading queue ownership or assessment changed"
        views, _refused = GradingQueueService(self.db).summarize_queue_run(queue_run)
        view = next((candidate for candidate in views if candidate["id"] == queue_item.id), None)
        if view is None or view.get("stale_status") != "fresh":
            return "Evidence is no longer fresh"
        if view.get("current_evidence_snapshot_hash") != item.evidence_snapshot_hash:
            return "Evidence snapshot hash changed"
        region = self.db.get(AnswerRegion, item.answer_region_id)
        if region is None or region.question_id != run.question_id:
            return "Answer region no longer belongs to the dispatched question"
        submission = self.db.get(Submission, region.submission_id)
        if submission is None or submission.assessment_id != run.assessment_id:
            return "Answer region no longer belongs to the dispatched assessment"
        owner_id = self.db.scalar(
            select(Course.teacher_id)
            .join(Assessment, Assessment.course_id == Course.id)
            .where(Assessment.id == run.assessment_id)
        )
        if owner_id != run.created_by_teacher_id:
            return "Assessment ownership changed"
        if self.db.scalar(
            select(GradeSuggestion.id).where(
                GradeSuggestion.answer_region_id == item.answer_region_id
            )
        ) is not None:
            return "Answer region already has a grade suggestion"
        job = self.db.get(GradingJob, item.grading_job_id) if item.grading_job_id else None
        if job is None or job.answer_region_id != item.answer_region_id or job.status != "queued":
            return "Pinned grading job is not queued"
        question = self.db.get(Question, run.question_id)
        rubric = self.db.get(Rubric, item.rubric_id)
        if (
            question is None
            or rubric is None
            or not rubric.is_active
            or rubric.question_id != question.id
        ):
            return "Pinned rubric is no longer active"
        active_rubric_ids = list(
            self.db.scalars(
                select(Rubric.id).where(
                    Rubric.question_id == question.id,
                    Rubric.is_active.is_(True),
                )
            ).all()
        )
        if active_rubric_ids != [item.rubric_id]:
            return "Active rubric set changed"
        if rubric_snapshot_hash(question, rubric) != item.rubric_snapshot_hash:
            return "Question, model answer, or rubric hash changed"
        try:
            packet = GradingService(
                self.db, use_configured_adapter=False
            ).get_grading_evidence_packet(item.answer_region_id)
        except HTTPException as exc:
            return f"Evidence readiness check failed: {exc.detail}"
        readiness = packet["readiness_result"]
        if not readiness["ready_for_grading"]:
            return "Evidence packet is no longer ready"
        return None

    def _refuse_item(
        self, run: GradingDispatchRun, item: GradingDispatchItem, reason: str
    ) -> None:
        item.status = "refused"
        item.refusal_reason = reason[:1000]
        item.completed_at = datetime.now(UTC)
        if item.grading_job_id is not None:
            job = self.db.get(GradingJob, item.grading_job_id)
            if job is not None:
                job.status = "failed"
                job.error = "Dispatch safety recheck refused provider execution"
                job.completed_at = item.completed_at
        run.heartbeat_at = item.completed_at
        self._refresh_counts(run)
        self._audit(
            run,
            "grading_dispatch_item_refused",
            actor_type="worker",
            item=item,
            payload={"reason": reason[:500]},
        )
        self.db.commit()

    def _fail_run_configuration(self, run_id: int, reason: str) -> None:
        run = self.get_run(run_id)
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.heartbeat_at = run.completed_at
        self._audit(
            run,
            "grading_dispatch_provider_configuration_failed",
            actor_type="worker",
            payload={"reason": sanitize_provider_error(reason)[:500]},
        )
        self.db.commit()

    def _refresh_counts(self, run: GradingDispatchRun) -> None:
        statuses = Counter(item.status for item in run.items)
        run.pending_count = statuses["pending"]
        run.running_count = statuses["running"]
        run.succeeded_count = statuses["succeeded"]
        run.failed_count = statuses["failed"]
        run.refused_count = statuses["refused"]
        run.skipped_count = statuses["skipped"]
        run.uncertain_count = statuses["uncertain"]

    def _audit(
        self,
        run: GradingDispatchRun,
        event_type: str,
        *,
        actor_type: str,
        actor_id: int | None = None,
        item: GradingDispatchItem | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        safe_payload: dict[str, Any] = {
            "assessment_id": run.assessment_id,
            "question_id": run.question_id,
            "queue_run_id": run.queue_run_id,
            "grading_run_id": run.grading_run_id,
            "provider": run.provider,
            "model": run.model_name,
        }
        if item is not None:
            safe_payload.update(
                {
                    "dispatch_item_id": item.id,
                    "queue_item_id": item.queue_item_id,
                    "answer_region_id": item.answer_region_id,
                    "grading_job_id": item.grading_job_id,
                    "attempt_count": item.attempt_count,
                    "evidence_snapshot_hash": item.evidence_snapshot_hash,
                    "rubric_snapshot_hash": item.rubric_snapshot_hash,
                }
            )
        if payload:
            safe_payload.update(payload)
        self.db.add(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=event_type,
                entity_type="grading_dispatch_run",
                entity_id=run.id,
                payload_json=safe_payload,
            )
        )
