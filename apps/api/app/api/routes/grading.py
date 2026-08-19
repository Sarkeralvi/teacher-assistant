from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.ownership import get_owned_assessment_or_404, get_owned_question_or_404
from app.db.session import get_db
from app.models import (
    AnswerRegion,
    Assessment,
    AuditLog,
    Course,
    GradeSuggestion,
    GradingDispatchRun,
    GradingJob,
    GradingRun,
    Rubric,
    Submission,
    User,
)
from app.schemas import (
    BatchMockGradeResponse,
    BrowserCodexGradeResponse,
    CohortDispatchPreflightRead,
    CohortDispatchRequest,
    CohortGradeSummaryResponse,
    GradeAnswerRegionResponse,
    GradeSuggestionRead,
    GradingDispatchRunRead,
    GradingEvidencePacketRead,
    GradingJobRead,
    LocalQwenGradeRequest,
)
from app.services.grading_dispatch_service import GradingDispatchService
from app.services.grading_integrity import canonical_json_hash, rubric_snapshot_hash
from app.services.grading_service import GradingService
from app.services.local_ai_phase_manager import LocalAiPhaseError, LocalAiPhaseManager
from app.worker.jobs import run_grade_answer_region_job, run_grading_dispatch_job
from app.worker.rq_app import get_default_queue
from packages.brain.adapter import BrainAdapter, BrainProviderConfigurationError

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(tags=["grading"])


def make_browser_codex_grade_response(
    job: GradingJob, suggestion: GradeSuggestion
) -> dict[str, object]:
    raw = suggestion.raw_response_json or {}
    review_flags = raw.get("review_flags", [])
    if not isinstance(review_flags, list):
        review_flags = []
    return {
        "job": job,
        "suggestion": {
            "id": suggestion.id,
            "grading_job_id": suggestion.grading_job_id,
            "answer_region_id": suggestion.answer_region_id,
            "question_id": suggestion.question_id,
            "model_provider": suggestion.model_provider,
            "model_name": suggestion.model_name,
            "prompt_version": suggestion.prompt_version,
            "marking_policy": suggestion.marking_policy,
            "score": suggestion.score,
            "max_score": suggestion.max_score,
            "confidence": suggestion.confidence,
            "needs_review": suggestion.needs_review,
            "feedback": suggestion.feedback,
            "cost_estimate": suggestion.cost_estimate,
            "review_flags": review_flags,
            "created_at": suggestion.created_at,
        },
    }


def assert_teacher_owns_answer_region(
    answer_region_id: int, db: Session, current_user: User
) -> AnswerRegion:
    statement = (
        select(AnswerRegion)
        .join(Submission, AnswerRegion.submission_id == Submission.id)
        .join(Assessment, Submission.assessment_id == Assessment.id)
        .join(Course, Assessment.course_id == Course.id)
        .where(AnswerRegion.id == answer_region_id)
        .where(Course.teacher_id == current_user.id)
    )
    region = db.scalars(statement).first()
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer region not found")
    return region


@router.get(
    "/answer-regions/{answer_region_id}/grading-evidence-packet",
    response_model=GradingEvidencePacketRead,
)
def get_grading_evidence_packet(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    return GradingService(db).get_grading_evidence_packet(answer_region_id)


@router.post(
    "/answer-regions/{answer_region_id}/grade",
    response_model=GradeAnswerRegionResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    job, suggestion = GradingService(db).grade_answer_region(answer_region_id)
    return {"job": job, "suggestion": suggestion}


@router.post(
    "/answer-regions/{answer_region_id}/grade-local-qwen",
    response_model=GradeAnswerRegionResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region_with_local_qwen(
    answer_region_id: int,
    payload: LocalQwenGradeRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    region = assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    settings = get_settings()
    if not settings.brain_allow_real_providers:
        raise HTTPException(status_code=409, detail="Real local providers are disabled")
    if not (settings.local_single_answer_grading_enabled or settings.local_qwen38_grading_enabled):
        raise HTTPException(status_code=409, detail="Local single-answer grading is disabled")
    if payload.provider == "llama_cpp_qwen38":
        enabled = settings.local_qwen38_enabled and settings.local_qwen38_grading_enabled
        expected_model = settings.local_qwen38_model
    else:
        enabled = settings.local_qwen_enabled
        expected_model = settings.local_qwen_model
    if not enabled:
        raise HTTPException(status_code=409, detail="Requested local Qwen provider is disabled")
    if payload.expected_model != expected_model:
        raise HTTPException(
            status_code=409, detail="Expected local Qwen model alias does not match"
        )
    grading_run = db.get(GradingRun, payload.grading_run_id)
    if (
        grading_run is None
        or grading_run.created_by_teacher_id != current_user.id
        or grading_run.assessment_id != region.submission.assessment_id
    ):
        raise HTTPException(status_code=404, detail="Grading run not found")
    existing = db.scalars(
        select(GradeSuggestion).where(GradeSuggestion.answer_region_id == region.id)
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="This answer already has an AI draft suggestion for teacher review",
        )

    preflight_service = GradingService(db, use_configured_adapter=False)
    before_packet = preflight_service.get_grading_evidence_packet(region.id)
    before_hash = canonical_json_hash(before_packet)
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="local_qwen_single_grade_requested",
            entity_type="answer_region",
            entity_id=region.id,
            payload_json={
                "grading_run_id": grading_run.id,
                "provider": payload.provider,
                "expected_model": payload.expected_model,
                "draft_only": True,
                "evidence_hash": before_hash,
            },
        )
    )
    db.commit()
    try:
        if settings.local_ai_phase_switch_enabled:
            phase = "Qwen38" if payload.provider == "llama_cpp_qwen38" else "Qwen"
            LocalAiPhaseManager(settings=settings).switch(phase)
        adapter = BrainAdapter.for_provider(settings, payload.provider)
        adapter.verify_available_model()
    except (LocalAiPhaseError, BrainProviderConfigurationError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local Qwen could not be prepared with the expected model",
        ) from exc

    region = assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    grading_service = GradingService(db, adapter=adapter)
    after_packet = grading_service.get_grading_evidence_packet(region.id)
    if canonical_json_hash(after_packet) != before_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Grading evidence changed while local Qwen was starting",
        )
    rubric = db.scalars(
        select(Rubric)
        .where(Rubric.question_id == region.question_id)
        .where(Rubric.is_active.is_(True))
        .order_by(Rubric.version.desc(), Rubric.id.desc())
    ).first()
    if rubric is None:
        raise HTTPException(status_code=409, detail="Active rubric is unavailable")
    pinned_hash = rubric_snapshot_hash(region.question, rubric)
    job = grading_service.create_queued_grading_job(region.id)
    job, suggestion = grading_service.run_queued_job(
        job.id,
        marking_policy=grading_run.marking_policy,
        expected_rubric_id=rubric.id,
        expected_rubric_hash=pinned_hash,
    )
    db.add(
        AuditLog(
            actor_type="teacher",
            actor_id=current_user.id,
            event_type="local_qwen_single_grade_succeeded",
            entity_type="grading_job",
            entity_id=job.id,
            payload_json={
                "answer_region_id": region.id,
                "suggestion_id": suggestion.id,
                "provider": suggestion.model_provider,
                "model": suggestion.model_name,
                "rubric_hash": pinned_hash,
                "evidence_hash": before_hash,
                "needs_review": True,
            },
        )
    )
    db.commit()
    return {"job": job, "suggestion": suggestion}


@router.post(
    "/answer-regions/{answer_region_id}/grade-async",
    response_model=GradingJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def grade_answer_region_async(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> GradingJob:
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    job = GradingService(db).create_queued_grading_job(answer_region_id)
    get_default_queue().enqueue(run_grade_answer_region_job, job.id)
    return job


@router.post(
    "/assessments/{assessment_id}/questions/{question_id}/grade-cohort/preflight",
    response_model=CohortDispatchPreflightRead,
)
def preflight_question_cohort(
    assessment_id: int,
    question_id: int,
    payload: CohortDispatchRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    question = get_owned_question_or_404(question_id, db, current_user)
    if question.assessment_id != assessment_id:
        raise HTTPException(status_code=404, detail="Question not found")
    return GradingDispatchService(db).preflight(
        assessment_id=assessment_id,
        question_id=question_id,
        teacher_id=current_user.id,
        request=payload,
    )


@router.post(
    "/assessments/{assessment_id}/questions/{question_id}/grade-cohort",
    response_model=GradingDispatchRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def grade_question_cohort(
    assessment_id: int,
    question_id: int,
    payload: CohortDispatchRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> GradingDispatchRun:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    question = get_owned_question_or_404(question_id, db, current_user)
    if question.assessment_id != assessment_id:
        raise HTTPException(status_code=404, detail="Question not found")
    service = GradingDispatchService(db)
    run = service.create_dispatch(
        assessment_id=assessment_id,
        question_id=question_id,
        teacher_id=current_user.id,
        request=payload,
    )
    if run.status == "queued":
        try:
            get_default_queue().enqueue(run_grading_dispatch_job, run.id)
        except Exception as exc:
            service.mark_enqueue_failed(run.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Grading dispatch could not be enqueued",
            ) from exc
    return run


@router.get(
    "/grading-dispatch-runs/{run_id}",
    response_model=GradingDispatchRunRead,
)
def read_grading_dispatch_run(
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> GradingDispatchRun:
    service = GradingDispatchService(db)
    run = service.get_owned_run(run_id, current_user.id)
    service.reconcile_stale_worker(run, actor_id=current_user.id)
    return service.get_owned_run(run_id, current_user.id)


@router.post(
    "/grading-dispatch-runs/{run_id}/stop",
    response_model=GradingDispatchRunRead,
)
def stop_grading_dispatch_run(
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> GradingDispatchRun:
    service = GradingDispatchService(db)
    run = service.get_owned_run(run_id, current_user.id)
    return service.request_stop(run, current_user.id)


@router.post(
    "/grading-dispatch-runs/{run_id}/resume",
    response_model=GradingDispatchRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_grading_dispatch_run(
    run_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> GradingDispatchRun:
    service = GradingDispatchService(db)
    run = service.get_owned_run(run_id, current_user.id)
    run = service.resume(run, current_user.id)
    try:
        get_default_queue().enqueue(run_grading_dispatch_job, run.id)
    except Exception as exc:
        service.mark_enqueue_failed(run.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Grading dispatch could not be re-enqueued",
        ) from exc
    return run


@router.get(
    "/assessments/{assessment_id}/questions/{question_id}/cohort-grades",
    response_model=CohortGradeSummaryResponse,
)
def read_question_cohort_grades(
    assessment_id: int,
    question_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    get_owned_question_or_404(question_id, db, current_user)
    return GradingService(db).cohort_grade_summary(assessment_id, question_id)


@router.post(
    "/answer-regions/{answer_region_id}/grade-codex-dev",
    response_model=BrowserCodexGradeResponse,
    status_code=status.HTTP_201_CREATED,
)
def grade_answer_region_with_codex_dev(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    settings = get_settings()
    if not settings.codex_browser_grading_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Codex browser grading is unavailable in this backend runtime. "
                "Use host-backend Codex dev mode with CODEX_BROWSER_GRADING_ENABLED=true."
            ),
        )
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    try:
        job, suggestion = GradingService(db).grade_answer_region_with_codex_cli(answer_region_id)
    except HTTPException as exc:
        if "codex command not found" in str(exc.detail).lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Codex CLI is not available in this backend runtime. "
                    "Use host-backend Codex dev mode."
                ),
            ) from exc
        raise
    return make_browser_codex_grade_response(job, suggestion)


@router.post(
    "/assessments/{assessment_id}/grade-all-mock",
    response_model=BatchMockGradeResponse,
    status_code=status.HTTP_201_CREATED,
)
def batch_mock_grade_assessment(
    assessment_id: int, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    get_owned_assessment_or_404(assessment_id, db, current_user)
    return GradingService(db, use_configured_adapter=False).grade_assessment_ungraded_regions_mock(
        assessment_id
    )


@router.get(
    "/answer-regions/{answer_region_id}/grade-suggestions",
    response_model=list[GradeSuggestionRead],
)
def list_grade_suggestions(
    answer_region_id: int, db: DbSession, current_user: CurrentUser
) -> Sequence[GradeSuggestion]:
    assert_teacher_owns_answer_region(answer_region_id, db, current_user)
    statement = (
        select(GradeSuggestion)
        .where(GradeSuggestion.answer_region_id == answer_region_id)
        .order_by(GradeSuggestion.id)
    )
    return db.scalars(statement).all()


@router.get("/grade-suggestions/{grade_suggestion_id}", response_model=GradeSuggestionRead)
def get_grade_suggestion(
    grade_suggestion_id: int, db: DbSession, current_user: CurrentUser
) -> GradeSuggestion:
    suggestion = db.get(GradeSuggestion, grade_suggestion_id)
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grade suggestion not found",
        )
    assert_teacher_owns_answer_region(suggestion.answer_region_id, db, current_user)
    return suggestion


@router.get("/grading-jobs/{grading_job_id}", response_model=GradingJobRead)
def get_grading_job(grading_job_id: int, db: DbSession, current_user: CurrentUser) -> GradingJob:
    job = db.get(GradingJob, grading_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grading job not found")
    assert_teacher_owns_answer_region(job.answer_region_id, db, current_user)
    return job
