"""Isolated Qwen3.6-versus-Qwen3.8 text-grading bake-off.

This module intentionally does *not* read a student's image or call a visual
model.  It forks an already teacher-confirmed 20-case evaluation, replays the
locked textual evidence into two disposable databases, and delegates each
candidate's eighteen text-only calls to the production safe-dispatch path.

The source evaluation remains immutable.  Neither candidate may create a
FinalGrade, and neither candidate can be treated as a teacher-pilot result
until its own grading-review workbook has been signed.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.brain.schemas_qwen38 import FINAL_INTENT_PROMPT_VERSION
from packages.evaluation import local_curated_evaluation as evaluation

BAKEOFF_SCHEMA_VERSION = 1
_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("qwen36", "qwen3.6-35b-a3b-q4km"),
    ("qwen38", "qwen3.8-27b-q4km"),
)


class GradingBakeoffError(RuntimeError):
    """Raised when an isolated grading comparison cannot be trusted."""


class GradingBakeoffVerdict(StrEnum):
    QWEN38_PROMOTED = "QWEN38_PROMOTED"
    QWEN36_RETAINED = "QWEN36_RETAINED"
    NO_GO_QUALITY = "NO_GO_QUALITY"


class SourceEvidenceLock(BaseModel):
    """Hashes that prove both candidates received the same confirmed evidence."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ground_truth_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ocr_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ocr_confirmation_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_ocr_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_reference_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_text_hashes: dict[str, str]
    source_image_hashes: dict[str, str]
    visual_model_alias: Literal["qwen3.8-27b-q4km"]
    visual_reasoning_mode: Literal["off"]
    source_visual_call_count: Literal[20]
    replay_visual_call_count: Literal[0]

    @model_validator(mode="after")
    def validate_lock(self) -> SourceEvidenceLock:
        if set(self.confirmed_text_hashes) != set(evaluation._EXPECTED_CASE_IDS):
            raise ValueError("source evidence lock must contain all confirmed text hashes")
        if set(self.source_image_hashes) != set(evaluation._EXPECTED_CASE_IDS):
            raise ValueError("source evidence lock must contain all source image hashes")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in [*self.confirmed_text_hashes.values(), *self.source_image_hashes.values()]
        ):
            raise ValueError("source evidence hashes must be SHA-256 values")
        return self


class GradingBakeoffCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["qwen36", "qwen38"]
    model_alias: Literal["qwen3.6-35b-a3b-q4km", "qwen3.8-27b-q4km"]
    run_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GradingBakeoffManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = BAKEOFF_SCHEMA_VERSION
    created_at: datetime
    source: SourceEvidenceLock
    candidates: list[GradingBakeoffCandidate] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_candidates(self) -> GradingBakeoffManifest:
        expected = {label: model for label, model in _CANDIDATES}
        actual = {candidate.label: candidate.model_alias for candidate in self.candidates}
        if actual != expected:
            raise ValueError("grading bake-off must contain one Qwen3.6 and one Qwen3.8 candidate")
        if len({candidate.run_id for candidate in self.candidates}) != 2:
            raise ValueError("grading bake-off candidate run IDs must be unique")
        return self


class CandidateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["qwen36", "qwen38"]
    model_alias: str
    grading_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_text_hashes: dict[str, str]
    process_checks_pass: bool
    teacher_review_pass: bool
    exact_count: int
    within_one_count: int
    mean_absolute_error: Decimal
    mean_normalized_absolute_error: Decimal
    severe_false_confident_count: int
    severe_low_confidence_count: int
    formula_multistep_within_one: bool
    irrelevant_over_limit_count: int
    wrong_over_half_count: int
    zero_reference_overscore_count: int
    p95_latency_ms: Decimal


class GradingBakeoffReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = BAKEOFF_SCHEMA_VERSION
    generated_at: datetime
    source_run_id: str
    source_evidence_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: GradingBakeoffVerdict
    reasons: list[str]
    recommended_grading_model: str | None
    candidates: list[CandidateSummary] = Field(min_length=2, max_length=2)


def _canonical_reference_bundle_sha256(
    manifest: evaluation.LocalCuratedEvaluationManifest,
) -> str:
    """Hash exactly the reference material a grading provider is allowed to see."""

    bundle = [
        {
            "case_id": case.case_id,
            "question": case.question_text,
            "model_answer": case.model_answer,
            "max_score": str(case.max_score),
            "rubric": [criterion.model_dump(mode="json") for criterion in case.rubric],
            "marking_policy": manifest.marking_policy,
            "prompt_version": manifest.prompt_version,
        }
        for case in manifest.cases
    ]
    return evaluation.sha256_text(evaluation._canonical_json(bundle))


def _source_files(source_run_dir: Path) -> dict[str, Path]:
    files = {
        "manifest": source_run_dir / "manifest.json",
        "ground_truth": source_run_dir / "ground_truth_lock.json",
        "ocr_results": source_run_dir / "ocr_results.json",
        "ocr_confirmations": source_run_dir / "ocr_confirmation_lock.json",
        "ocr_review": source_run_dir / "ocr_review.xlsx",
        "ground_truth_review": source_run_dir / "ground_truth_review.xlsx",
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        raise GradingBakeoffError("Source evaluation is missing: " + ", ".join(sorted(missing)))
    return files


def _load_source(source_run_dir: Path) -> tuple[
    evaluation.LocalCuratedEvaluationManifest,
    evaluation.GroundTruthLock,
    evaluation.OcrRunResult,
    evaluation.OcrConfirmationLock,
    SourceEvidenceLock,
]:
    if evaluation.current_state(source_run_dir) != "ocr_confirmed":
        raise GradingBakeoffError(
            "Source evaluation must be at ocr_confirmed; do not reuse a graded or rejected run"
        )
    evaluation.verify_locked_artifacts(source_run_dir)
    files = _source_files(source_run_dir)
    manifest = evaluation.load_manifest(source_run_dir)
    ground_truth = evaluation.GroundTruthLock.model_validate(
        evaluation.read_json(files["ground_truth"])
    )
    ocr_result = evaluation.OcrRunResult.model_validate(
        evaluation.read_json(files["ocr_results"])
    )
    confirmations = evaluation.OcrConfirmationLock.model_validate(
        evaluation.read_json(files["ocr_confirmations"])
    )
    if ground_truth.run_id != manifest.run_id or ocr_result.run_id != manifest.run_id:
        raise GradingBakeoffError("Source evaluation locks do not belong to its manifest")
    if confirmations.run_id != manifest.run_id:
        raise GradingBakeoffError("Source OCR confirmation lock does not belong to its manifest")
    if ground_truth.manifest_sha256 != evaluation.sha256_file(files["manifest"]):
        raise GradingBakeoffError("Source ground-truth lock does not match its manifest")
    if ground_truth.workbook_sha256 != evaluation.sha256_file(files["ground_truth_review"]):
        raise GradingBakeoffError("Source ground-truth workbook changed after sign-off")
    if confirmations.ocr_results_sha256 != evaluation.sha256_file(files["ocr_results"]):
        raise GradingBakeoffError("Source OCR confirmation lock does not match OCR results")
    if confirmations.workbook_sha256 != evaluation.sha256_file(files["ocr_review"]):
        raise GradingBakeoffError("Source OCR review workbook changed after sign-off")
    if ocr_result.first_call_at <= ground_truth.signed_at:
        raise GradingBakeoffError("Source visual calls predate teacher ground-truth lock")
    if confirmations.signed_at <= ocr_result.completed_at:
        raise GradingBakeoffError("Source OCR confirmation predates completed visual calls")
    ocr_by_id = {case.case_id: case for case in ocr_result.cases}
    text_hashes: dict[str, str] = {}
    image_hashes: dict[str, str] = {}
    for confirmation in confirmations.cases:
        source_case = ocr_by_id.get(confirmation.case_id)
        if source_case is None:
            raise GradingBakeoffError("Source OCR confirmation references an unknown case")
        if confirmation.confirmed_text_sha256 != source_case.draft_text_sha256:
            raise GradingBakeoffError(
                "Source confirmed text differs from visual-transcription draft"
            )
        if confirmation.confirmed_text != source_case.draft_text:
            raise GradingBakeoffError(
                "Source confirmed text was not the exact visual-transcription text"
            )
        text_hashes[confirmation.case_id] = confirmation.confirmed_text_sha256
        image_hashes[confirmation.case_id] = source_case.source_image_sha256
    source_lock = SourceEvidenceLock(
        source_run_id=manifest.run_id,
        source_manifest_sha256=evaluation.sha256_file(files["manifest"]),
        source_ground_truth_lock_sha256=evaluation.sha256_file(files["ground_truth"]),
        source_ocr_results_sha256=evaluation.sha256_file(files["ocr_results"]),
        source_ocr_confirmation_lock_sha256=evaluation.sha256_file(files["ocr_confirmations"]),
        source_ocr_review_sha256=evaluation.sha256_file(files["ocr_review"]),
        source_reference_bundle_sha256=_canonical_reference_bundle_sha256(manifest),
        confirmed_text_hashes=text_hashes,
        source_image_hashes=image_hashes,
        visual_model_alias=manifest.operator_assets.qwen38_vision.model_alias,
        visual_reasoning_mode="off",
        source_visual_call_count=20,
        replay_visual_call_count=0,
    )
    return manifest, ground_truth, ocr_result, confirmations, source_lock


def _candidate_run_id(source_run_id: str, label: str) -> str:
    candidate = f"{source_run_id}_{label}"
    if not evaluation._RUN_ID_PATTERN.fullmatch(candidate):
        raise GradingBakeoffError("Source run ID is too long to create bake-off candidates")
    return candidate


def _assert_same_rendered_images(
    source_manifest: evaluation.LocalCuratedEvaluationManifest,
    candidate_manifest: evaluation.LocalCuratedEvaluationManifest,
) -> None:
    source_hashes = {case.case_id: case.image_sha256 for case in source_manifest.cases}
    candidate_hashes = {case.case_id: case.image_sha256 for case in candidate_manifest.cases}
    if source_hashes != candidate_hashes:
        raise GradingBakeoffError("Candidate images differ from the locked source evaluation")


def create_grading_bakeoff(
    *,
    source_run_dir: Path,
    operator_assets_for_model: Any,
) -> GradingBakeoffManifest:
    """Fork a teacher-confirmed visual-evidence run into two grading candidates.

    ``operator_assets_for_model`` is injected to keep the filesystem-dependent
    asset hash check separate from the immutable source evidence logic.
    """

    source_run_dir = source_run_dir.resolve()
    source_manifest, source_ground_truth, _ocr, _confirm, source_lock = _load_source(
        source_run_dir
    )
    evaluation.require_clean_git_worktree()
    if evaluation.current_git_commit() != source_manifest.harness_commit:
        raise GradingBakeoffError(
            "Current Git commit differs from the source evaluation harness commit"
        )
    bakeoff_dir = source_run_dir / "grading_bakeoff"
    if bakeoff_dir.exists():
        raise GradingBakeoffError("A grading bake-off already exists for this source run")
    candidates: list[GradingBakeoffCandidate] = []
    target_root = source_run_dir.parent
    source_files = _source_files(source_run_dir)
    try:
        bakeoff_dir.mkdir(parents=False)
        for label, model_alias in _CANDIDATES:
            assets = operator_assets_for_model(model_alias)
            if assets.qwen38_vision != source_manifest.operator_assets.qwen38_vision:
                raise GradingBakeoffError(
                    "Qwen3.8 visual assets changed after the source evidence was confirmed"
                )
            candidate_id = _candidate_run_id(source_manifest.run_id, label)
            candidate_dir = evaluation.prepare_evaluation(
                run_id=candidate_id,
                output_root=target_root,
                integration_commit=source_manifest.integration_commit,
                harness_commit=source_manifest.harness_commit,
                operator_assets=assets,
                seed=source_manifest.seed,
            )
            candidate_manifest = evaluation.load_manifest(candidate_dir)
            _assert_same_rendered_images(source_manifest, candidate_manifest)
            # Preserve the signed source workbooks as immutable evidence, rather
            # than asking the teacher to sign the same text a second time.
            shutil.copyfile(
                source_files["ground_truth_review"],
                candidate_dir / "ground_truth_review.xlsx",
            )
            shutil.copyfile(source_files["ocr_review"], candidate_dir / "source_ocr_review.xlsx")
            shutil.copyfile(source_files["ocr_results"], candidate_dir / "source_ocr_results.json")
            shutil.copyfile(
                source_files["ocr_confirmations"],
                candidate_dir / "source_ocr_confirmation_lock.json",
            )
            candidate_ground_truth = evaluation.GroundTruthLock(
                run_id=candidate_id,
                reviewer_id=source_ground_truth.reviewer_id,
                signed_at=source_ground_truth.signed_at,
                manifest_sha256=evaluation.sha256_file(candidate_dir / "manifest.json"),
                workbook_sha256=evaluation.sha256_file(
                    candidate_dir / "ground_truth_review.xlsx"
                ),
                cases=source_ground_truth.cases,
            )
            ground_truth_path = candidate_dir / "ground_truth_lock.json"
            source_lock_path = candidate_dir / "source_evidence_lock.json"
            evaluation.write_json(ground_truth_path, candidate_ground_truth)
            evaluation.write_json(source_lock_path, source_lock)
            evaluation.append_state(
                candidate_dir,
                "ground_truth_locked",
                locked_artifacts={
                    "ground_truth_review.xlsx": evaluation.sha256_file(
                        candidate_dir / "ground_truth_review.xlsx"
                    ),
                    "ground_truth_lock.json": evaluation.sha256_file(ground_truth_path),
                    "source_ocr_review.xlsx": evaluation.sha256_file(
                        candidate_dir / "source_ocr_review.xlsx"
                    ),
                    "source_ocr_results.json": evaluation.sha256_file(
                        candidate_dir / "source_ocr_results.json"
                    ),
                    "source_ocr_confirmation_lock.json": evaluation.sha256_file(
                        candidate_dir / "source_ocr_confirmation_lock.json"
                    ),
                    "source_evidence_lock.json": evaluation.sha256_file(source_lock_path),
                },
                metadata={
                    "source_run_id": source_manifest.run_id,
                    "source_visual_call_count": 20,
                    "candidate_visual_call_count": 0,
                    "teacher_confirmed_evidence_replayed": True,
                },
            )
            candidates.append(
                GradingBakeoffCandidate(
                    label=label,
                    model_alias=model_alias,
                    run_id=candidate_id,
                    manifest_sha256=evaluation.sha256_file(candidate_dir / "manifest.json"),
                )
            )
        manifest = GradingBakeoffManifest(
            created_at=datetime.now(UTC),
            source=source_lock,
            candidates=candidates,
        )
        evaluation.write_json(bakeoff_dir / "manifest.json", manifest)
        return manifest
    except Exception:
        # Do not remove candidate artifacts: they are forensic evidence of an
        # interrupted fork and must be inspected rather than silently replaced.
        raise


def _load_candidate_source_lock(
    candidate_dir: Path,
    source_lock: SourceEvidenceLock,
) -> SourceEvidenceLock:
    lock = SourceEvidenceLock.model_validate(
        evaluation.read_json(candidate_dir / "source_evidence_lock.json")
    )
    if lock != source_lock:
        raise GradingBakeoffError("Candidate source-evidence lock differs from bake-off manifest")
    return lock


def seed_grading_bakeoff_candidate(
    *,
    candidate_run_dir: Path,
    database_url: str,
    local_ai_env: Path | None = None,
) -> evaluation.OcrConfirmationLock:
    """Replay source-confirmed evidence into one empty, disposable DB.

    No model is started or called in this function.  The only text copied is
    the source teacher-approved visual transcription and the server records the
    original Qwen3.8 source hashes in the audit trail.
    """

    candidate_run_dir = candidate_run_dir.resolve()
    if evaluation.current_state(candidate_run_dir) != "ground_truth_locked":
        raise GradingBakeoffError(
            "A candidate can be seeded only once, after its copied ground-truth lock"
        )
    evaluation.verify_locked_artifacts(candidate_run_dir)
    manifest = evaluation.load_manifest(candidate_run_dir)
    source_ocr = evaluation.OcrRunResult.model_validate(
        evaluation.read_json(candidate_run_dir / "source_ocr_results.json")
    )
    source_confirmations = evaluation.OcrConfirmationLock.model_validate(
        evaluation.read_json(candidate_run_dir / "source_ocr_confirmation_lock.json")
    )
    source_lock = SourceEvidenceLock.model_validate(
        evaluation.read_json(candidate_run_dir / "source_evidence_lock.json")
    )
    if (
        source_lock.source_run_id != source_ocr.run_id
        or source_lock.source_run_id != source_confirmations.run_id
    ):
        raise GradingBakeoffError("Candidate copied evidence does not have one source run")
    if source_lock.source_reference_bundle_sha256 != _canonical_reference_bundle_sha256(manifest):
        raise GradingBakeoffError("Candidate canonical references differ from source references")
    source_case_by_id = {case.case_id: case for case in source_ocr.cases}
    confirmation_by_id = {case.case_id: case for case in source_confirmations.cases}
    if {
        case_id: confirmation.confirmed_text_sha256
        for case_id, confirmation in confirmation_by_id.items()
    } != source_lock.confirmed_text_hashes:
        raise GradingBakeoffError("Source confirmation text hashes changed")
    if (
        evaluation.sha256_file(candidate_run_dir / "source_ocr_results.json")
        != source_lock.source_ocr_results_sha256
        or evaluation.sha256_file(candidate_run_dir / "source_ocr_confirmation_lock.json")
        != source_lock.source_ocr_confirmation_lock_sha256
        or evaluation.sha256_file(candidate_run_dir / "source_ocr_review.xlsx")
        != source_lock.source_ocr_review_sha256
    ):
        raise GradingBakeoffError("Candidate source evidence files changed")
    _settings, session_factory, _storage_root = evaluation._configure_runtime(
        candidate_run_dir,
        database_url=database_url,
        local_ai_env=local_ai_env,
        require_grading=True,
    )
    evaluation._database_is_migrated_and_empty(session_factory)
    seeded = evaluation._seed_production_evaluation(manifest, candidate_run_dir, session_factory)

    from fastapi import HTTPException

    from app.api.routes.answer_regions import (
        confirm_visual_transcription_run,
        correct_answer_region_full_answer_confirmation,
    )
    from app.models import AnswerRegion, AnswerRegionOcrRun, AuditLog, User
    from app.schemas import (
        AnswerRegionFullAnswerConfirmation,
        VisualTranscriptionConfirmationRequest,
    )

    now = datetime.now(UTC)
    candidate_ocr_cases: list[evaluation.OcrCaseResult] = []
    candidate_confirmations: list[evaluation.OcrConfirmationCase] = []
    with session_factory() as db:
        owner = db.get(User, int(seeded["owner_teacher_id"]))
        intruder = db.get(User, int(seeded["intruder_teacher_id"]))
        if owner is None or intruder is None:
            raise GradingBakeoffError("Candidate teachers were not seeded")
        runs_by_case: dict[str, AnswerRegionOcrRun] = {}
        for case in manifest.cases:
            source_case = source_case_by_id.get(case.case_id)
            confirmation = confirmation_by_id.get(case.case_id)
            region_id = int(seeded["region_ids"][case.case_id])
            region = db.get(AnswerRegion, region_id)
            if source_case is None or confirmation is None or region is None:
                raise GradingBakeoffError("Candidate evidence seed is incomplete")
            if source_case.source_image_sha256 != source_lock.source_image_hashes[case.case_id]:
                raise GradingBakeoffError("Source image provenance changed")
            if case.image_sha256 not in source_case.source_image_hashes:
                raise GradingBakeoffError(
                    "Candidate image no longer matches the source visual input"
                )
            if confirmation.confirmed_text != source_case.draft_text:
                raise GradingBakeoffError("Source confirmation is not the exact visual output")
            replay = AnswerRegionOcrRun(
                answer_region_id=region.id,
                requested_by_teacher_id=owner.id,
                request_id=f"bakeoff-replay-{manifest.run_id}-{case.case_id}",
                status="succeeded",
                profile="qwen38_verbatim_visual",
                task_kind="locked_bakeoff_evidence_replay",
                reasoning_mode="off",
                prompt_version=FINAL_INTENT_PROMPT_VERSION,
                source_image_sha256=source_case.source_image_sha256,
                source_image_hashes=source_case.source_image_hashes,
                input_manifest_sha256=source_case.source_image_sha256,
                output_sha256=source_case.draft_text_sha256,
                model_asset_sha256=manifest.operator_assets.qwen38_vision.model_sha256,
                mmproj_asset_sha256=manifest.operator_assets.qwen38_vision.mmproj_sha256,
                queued_at=now,
                started_at=now,
                heartbeat_at=now,
                completed_at=now,
                call_limit=0,
                calls_used=0,
                candidate_set_sha256=source_case.draft_text_sha256,
                provider="llama_cpp_qwen38",
                model_name=manifest.operator_assets.qwen38_vision.model_alias,
                layout_model_name=None,
                draft_text=source_case.draft_text,
                normalized_result={
                    "task_kind": "locked_bakeoff_evidence_replay",
                    "source_run_id": source_lock.source_run_id,
                    "source_ocr_results_sha256": source_lock.source_ocr_results_sha256,
                    "draft_text_sha256": source_case.draft_text_sha256,
                    "is_blank": source_case.is_blank,
                    "reasoning_mode": "off",
                    "replay_provider_calls": 0,
                },
                warnings=["teacher_confirmed_source_evidence_replay"],
                latency_ms=source_case.latency_ms,
            )
            db.add(replay)
            db.flush()
            db.add(
                AuditLog(
                    actor_type="system",
                    actor_id=None,
                    event_type="evaluation_bakeoff_visual_evidence_replayed",
                    entity_type="answer_region_ocr_run",
                    entity_id=replay.id,
                    payload_json={
                        "source_run_id": source_lock.source_run_id,
                        "source_ocr_results_sha256": source_lock.source_ocr_results_sha256,
                        "answer_region_id": region.id,
                        "source_image_sha256": source_case.source_image_sha256,
                        "draft_text_sha256": source_case.draft_text_sha256,
                        "provider_calls": 0,
                    },
                )
            )
            runs_by_case[case.case_id] = replay
        db.commit()

        for case in manifest.cases:
            confirmation = confirmation_by_id[case.case_id]
            replay = runs_by_case[case.case_id]
            region_id = int(seeded["region_ids"][case.case_id])
            request = VisualTranscriptionConfirmationRequest(
                teacher_confirmed=True,
                draft_text_sha256=confirmation.confirmed_text_sha256,
            )
            try:
                confirm_visual_transcription_run(region_id, replay.id, request, db, intruder)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise GradingBakeoffError(
                        "Candidate intruder was not refused visual-evidence confirmation"
                    ) from exc
            else:
                raise GradingBakeoffError(
                    "Candidate intruder was allowed to confirm visual evidence"
                )
            confirm_visual_transcription_run(region_id, replay.id, request, db, owner)
            correct_answer_region_full_answer_confirmation(
                region_id,
                AnswerRegionFullAnswerConfirmation(
                    full_answer_confirmed=confirmation.full_answer_confirmed,
                    continuation_not_needed=True,
                    packet_status=confirmation.evidence_status,
                    manual_answer_text=confirmation.confirmed_text,
                ),
                db,
                owner,
            )
            db.refresh(replay)
            region = db.get(AnswerRegion, region_id)
            if region is None or replay.status != "confirmed":
                raise GradingBakeoffError("Candidate replay confirmation did not persist")
            if (region.manual_answer_text or "") != confirmation.confirmed_text:
                raise GradingBakeoffError("Candidate confirmed text differs from source lock")
            if region.evidence_status != confirmation.evidence_status:
                raise GradingBakeoffError("Candidate evidence status differs from source lock")
            candidate_ocr_cases.append(
                source_case_by_id[case.case_id].model_copy(
                    update={
                        "answer_region_id": region_id,
                        "ocr_run_id": replay.id,
                    }
                )
            )
            candidate_confirmations.append(
                evaluation.OcrConfirmationCase(
                    case_id=case.case_id,
                    answer_region_id=region_id,
                    ocr_run_id=replay.id,
                    confirmed_text=confirmation.confirmed_text,
                    confirmed_text_sha256=confirmation.confirmed_text_sha256,
                    teacher_approved=True,
                    evidence_status=confirmation.evidence_status,
                    full_answer_confirmed=confirmation.full_answer_confirmed,
                )
            )
        db.commit()

    candidate_ocr = evaluation.OcrRunResult.model_validate(
        source_ocr.model_dump(mode="json")
        | {
            "run_id": manifest.run_id,
            "evidence_origin": "locked_bakeoff_replay",
            "source_evaluation_run_id": source_lock.source_run_id,
            "new_provider_call_count": 0,
            "assessment_id": int(seeded["assessment_id"]),
            "grading_run_id": int(seeded["grading_run_id"]),
            "owner_teacher_id": int(seeded["owner_teacher_id"]),
            "intruder_teacher_id": int(seeded["intruder_teacher_id"]),
            "question_ids": seeded["question_ids"],
            "rubric_ids": seeded["rubric_ids"],
            "database_name": evaluation.validate_database_url(database_url, manifest.run_id),
            "cases": [case.model_dump(mode="json") for case in candidate_ocr_cases],
        }
    )
    candidate_confirmation_lock = evaluation.OcrConfirmationLock(
        run_id=manifest.run_id,
        reviewer_id=source_confirmations.reviewer_id,
        signed_at=source_confirmations.signed_at,
        ocr_results_sha256="0" * 64,  # replaced after the immutable result is written
        workbook_sha256=source_lock.source_ocr_review_sha256,
        cases=candidate_confirmations,
    )
    ocr_result_path = candidate_run_dir / "ocr_results.json"
    runtime_path = candidate_run_dir / "ocr_runtime.json"
    evaluation.write_json(ocr_result_path, candidate_ocr)
    candidate_confirmation_lock = candidate_confirmation_lock.model_copy(
        update={"ocr_results_sha256": evaluation.sha256_file(ocr_result_path)}
    )
    confirmation_path = candidate_run_dir / "ocr_confirmation_lock.json"
    evaluation.write_json(confirmation_path, candidate_confirmation_lock)
    evaluation.write_json(
        runtime_path,
        {
            "evidence_origin": "locked_bakeoff_replay",
            "source_run_id": source_lock.source_run_id,
            "source_ocr_results_sha256": source_lock.source_ocr_results_sha256,
            "source_ocr_confirmation_lock_sha256": source_lock.source_ocr_confirmation_lock_sha256,
            "source_visual_call_count": 20,
            "candidate_visual_call_count": 0,
            "visual_reasoning_mode": "off",
            "image_input_to_grading": False,
        },
    )
    evaluation.append_state(
        candidate_run_dir,
        "ocr_completed",
        locked_artifacts={
            "ocr_results.json": evaluation.sha256_file(ocr_result_path),
            "ocr_runtime.json": evaluation.sha256_file(runtime_path),
        },
        metadata={
            "source_visual_call_count": 20,
            "candidate_visual_call_count": 0,
            "teacher_confirmed_evidence_replayed": True,
        },
    )
    evaluation.append_state(
        candidate_run_dir,
        "ocr_confirmed",
        locked_artifacts={
            "ocr_confirmation_lock.json": evaluation.sha256_file(confirmation_path),
        },
        metadata={
            "source_teacher_confirmation_reused": True,
            "confirmed_case_count": 20,
            "complete_case_count": 18,
            "blank_case_count": 2,
            "new_provider_calls": 0,
        },
    )
    return candidate_confirmation_lock


def _candidate_summary(
    *,
    candidate: GradingBakeoffCandidate,
    candidate_dir: Path,
    source_lock: SourceEvidenceLock,
) -> CandidateSummary:
    if evaluation.current_state(candidate_dir) != "review_completed":
        raise GradingBakeoffError(
            f"{candidate.label} has not completed teacher review; comparison is blocked"
        )
    evaluation.verify_locked_artifacts(candidate_dir)
    manifest = evaluation.load_manifest(candidate_dir)
    if manifest.expected_qwen_model != candidate.model_alias:
        raise GradingBakeoffError(f"{candidate.label} manifest model does not match bake-off")
    if _canonical_reference_bundle_sha256(manifest) != source_lock.source_reference_bundle_sha256:
        raise GradingBakeoffError(f"{candidate.label} references differ from the source lock")
    _load_candidate_source_lock(candidate_dir, source_lock)
    candidate_ocr = evaluation.OcrRunResult.model_validate(
        evaluation.read_json(candidate_dir / "ocr_results.json")
    )
    if (
        candidate_ocr.evidence_origin != "locked_bakeoff_replay"
        or candidate_ocr.source_evaluation_run_id != source_lock.source_run_id
        or candidate_ocr.new_provider_call_count != 0
    ):
        raise GradingBakeoffError(
            f"{candidate.label} does not prove zero-call replay of the locked visual evidence"
        )
    confirmations = evaluation.OcrConfirmationLock.model_validate(
        evaluation.read_json(candidate_dir / "ocr_confirmation_lock.json")
    )
    if confirmations.ocr_results_sha256 != evaluation.sha256_file(
        candidate_dir / "ocr_results.json"
    ):
        raise GradingBakeoffError(f"{candidate.label} OCR confirmation lock changed")
    confirmed_hashes = {
        case.case_id: case.confirmed_text_sha256 for case in confirmations.cases
    }
    if confirmed_hashes != source_lock.confirmed_text_hashes:
        raise GradingBakeoffError(f"{candidate.label} text hashes differ from source evidence")
    result = evaluation.GradingRunResult.model_validate(
        evaluation.read_json(candidate_dir / "grading_results.json")
    )
    evaluation._validate_complete_grading_safety_checks(result)
    review = evaluation.ReviewLock.model_validate(
        evaluation.read_json(candidate_dir / "review_lock.json")
    )
    if review.grading_results_sha256 != evaluation.sha256_file(
        candidate_dir / "grading_results.json"
    ):
        raise GradingBakeoffError(f"{candidate.label} review lock changed grading results")
    grading_workbook = candidate_dir / "grading_review.xlsx"
    if not grading_workbook.is_file() or review.workbook_sha256 != evaluation.sha256_file(
        grading_workbook
    ):
        raise GradingBakeoffError(f"{candidate.label} signed grading workbook is unavailable")
    if review.signed_at <= result.completed_at:
        raise GradingBakeoffError(f"{candidate.label} review predates grading completion")
    if any(case.disagreement_reason in {"dataset_error", "ocr_unfixed"} for case in review.cases):
        teacher_review_pass = False
    else:
        teacher_review_pass = True
    metrics = evaluation.calculate_grading_metrics(manifest, result.cases)
    latencies = [
        int(case.latency_ms or 0)
        for case in result.cases
        if case.outcome == "suggested"
    ]
    return CandidateSummary(
        label=candidate.label,
        model_alias=candidate.model_alias,
        grading_results_sha256=evaluation.sha256_file(candidate_dir / "grading_results.json"),
        review_lock_sha256=evaluation.sha256_file(candidate_dir / "review_lock.json"),
        reference_bundle_sha256=_canonical_reference_bundle_sha256(manifest),
        confirmed_text_hashes=confirmed_hashes,
        process_checks_pass=all(result.safety_checks.values()),
        teacher_review_pass=teacher_review_pass,
        exact_count=metrics["exact_count"],
        within_one_count=metrics["within_one_count"],
        mean_absolute_error=metrics["mean_absolute_error"],
        mean_normalized_absolute_error=metrics["mean_normalized_absolute_error"],
        severe_false_confident_count=metrics["severe_false_confident_count"],
        severe_low_confidence_count=metrics["severe_low_confidence_count"],
        formula_multistep_within_one=metrics["formula_multistep_within_one"],
        irrelevant_over_limit_count=metrics["irrelevant_over_limit_count"],
        wrong_over_half_count=metrics["wrong_over_half_count"],
        zero_reference_overscore_count=metrics["zero_reference_overscore_count"],
        p95_latency_ms=evaluation.percentile(latencies, Decimal("0.95")),
    )


def _candidate_quality_passes(
    summary: CandidateSummary,
    thresholds: evaluation.EvaluationThresholds,
) -> tuple[bool, list[str]]:
    checks = {
        "process": summary.process_checks_pass,
        "teacher_review": summary.teacher_review_pass,
        "exact": summary.exact_count >= thresholds.grading_exact_min,
        "within_one": summary.within_one_count >= thresholds.grading_within_one_min,
        "mae": summary.mean_absolute_error <= thresholds.grading_mae_max,
        "normalized_mae": (
            summary.mean_normalized_absolute_error <= thresholds.grading_normalized_mae_max
        ),
        "formula_multistep": summary.formula_multistep_within_one,
        "severe_high_confidence": summary.severe_false_confident_count == 0,
        "severe_low_confidence": (
            summary.severe_low_confidence_count <= thresholds.severe_low_confidence_max
        ),
        "irrelevant": summary.irrelevant_over_limit_count == 0,
        "wrong": summary.wrong_over_half_count == 0,
        "zero_reference": summary.zero_reference_overscore_count < 2,
    }
    return all(checks.values()), [name for name, passed in checks.items() if not passed]


def _report_markdown(report: GradingBakeoffReport) -> str:
    lines = [
        "# Local grading-model bake-off",
        "",
        f"Source run: `{report.source_run_id}`",
        f"Verdict: **{report.verdict.value}**",
        "",
        "## Recommendation",
        "",
        (
            f"- Recommended text-grading model: `{report.recommended_grading_model}`"
            if report.recommended_grading_model
            else "- No model is recommended for pilot grading."
        ),
        "",
        "## Candidate metrics",
        "",
        "| Candidate | Exact | Within 1 | MAE | Normalized MAE | p95 latency |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate in report.candidates:
        lines.append(
            f"| {candidate.model_alias} | {candidate.exact_count} | "
            f"{candidate.within_one_count} | {candidate.mean_absolute_error} | "
            f"{candidate.mean_normalized_absolute_error} | {candidate.p95_latency_ms} ms |"
        )
    lines.extend(["", "## Decision reasons", ""])
    lines.extend(f"- {reason}" for reason in report.reasons)
    lines.extend(
        [
            "",
            "Both candidates used identical hash-pinned teacher-confirmed text. "
            "No student image was supplied to either grading call, and this report does not "
            "create or approve a FinalGrade.",
            "",
        ]
    )
    return "\n".join(lines)


def compare_grading_bakeoff(*, source_run_dir: Path) -> GradingBakeoffReport:
    source_run_dir = source_run_dir.resolve()
    bakeoff_dir = source_run_dir / "grading_bakeoff"
    manifest_path = bakeoff_dir / "manifest.json"
    if not manifest_path.is_file():
        raise GradingBakeoffError("Grading bake-off manifest does not exist")
    bakeoff = GradingBakeoffManifest.model_validate(evaluation.read_json(manifest_path))
    source_manifest, _truth, _ocr, _confirm, source_lock = _load_source(source_run_dir)
    if bakeoff.source != source_lock:
        raise GradingBakeoffError("Bake-off source evidence has changed")
    candidates = [
        _candidate_summary(
            candidate=candidate,
            candidate_dir=source_run_dir.parent / candidate.run_id,
            source_lock=source_lock,
        )
        for candidate in sorted(bakeoff.candidates, key=lambda item: item.label)
    ]
    summary_by_label = {candidate.label: candidate for candidate in candidates}
    qwen36 = summary_by_label["qwen36"]
    qwen38 = summary_by_label["qwen38"]
    thresholds = source_manifest.thresholds
    qwen36_pass, qwen36_failures = _candidate_quality_passes(qwen36, thresholds)
    qwen38_pass, qwen38_failures = _candidate_quality_passes(qwen38, thresholds)
    qwen38_gain = (
        qwen38.exact_count >= qwen36.exact_count + 2
        or qwen38.mean_absolute_error <= qwen36.mean_absolute_error - Decimal("0.15")
    )
    qwen38_no_added_severe = (
        qwen38.severe_false_confident_count <= qwen36.severe_false_confident_count
        and qwen38.severe_low_confidence_count <= qwen36.severe_low_confidence_count
    )
    qwen38_latency_ok = (
        qwen38.p95_latency_ms <= Decimal("90000")
        and qwen38.p95_latency_ms <= qwen36.p95_latency_ms * Decimal("2")
    )
    reasons: list[str] = []
    recommended: str | None
    if qwen38_pass and qwen38_gain and qwen38_no_added_severe and qwen38_latency_ok:
        verdict = GradingBakeoffVerdict.QWEN38_PROMOTED
        recommended = qwen38.model_alias
        reasons.append("Qwen3.8 met all quality and safety gates and beat the Qwen3.6 baseline.")
    elif qwen36_pass:
        verdict = GradingBakeoffVerdict.QWEN36_RETAINED
        recommended = qwen36.model_alias
        reasons.append(
            "Qwen3.6 remains the default text grader; Qwen3.8 did not meet promotion gates."
        )
        if qwen38_failures:
            reasons.append("Qwen3.8 failed: " + ", ".join(qwen38_failures))
        if not qwen38_gain:
            reasons.append("Qwen3.8 did not improve exact agreement by two cases or MAE by 0.15.")
        if not qwen38_no_added_severe:
            reasons.append("Qwen3.8 introduced additional severe grading errors.")
        if not qwen38_latency_ok:
            reasons.append("Qwen3.8 exceeded the bake-off latency gate.")
    else:
        verdict = GradingBakeoffVerdict.NO_GO_QUALITY
        recommended = None
        reasons.append("Neither candidate met the required grading-quality and review gates.")
        reasons.append("Qwen3.6 failed: " + ", ".join(qwen36_failures))
        reasons.append("Qwen3.8 failed: " + ", ".join(qwen38_failures))
    report = GradingBakeoffReport(
        generated_at=datetime.now(UTC),
        source_run_id=source_manifest.run_id,
        source_evidence_lock_sha256=evaluation.sha256_file(
            source_run_dir.parent
            / _candidate_run_id(source_manifest.run_id, "qwen36")
            / "source_evidence_lock.json"
        ),
        verdict=verdict,
        reasons=reasons,
        recommended_grading_model=recommended,
        candidates=candidates,
    )
    evaluation.write_json(bakeoff_dir / "report.json", report)
    (bakeoff_dir / "report.md").write_text(_report_markdown(report), encoding="utf-8")
    return report


def _resolve_source_run(root: Path, run_id: str) -> Path:
    if not evaluation._RUN_ID_PATTERN.fullmatch(run_id):
        raise GradingBakeoffError("Invalid source run ID")
    source = (root.resolve() / run_id).resolve()
    if source.parent != root.resolve() or not source.is_dir():
        raise GradingBakeoffError("Source evaluation run does not exist")
    return source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Qwen3.6 and Qwen3.8 text grading")
    parser.add_argument("--root", type=Path, default=evaluation.default_evaluation_root())
    commands = parser.add_subparsers(dest="command", required=True)
    fork = commands.add_parser("fork")
    fork.add_argument("--source-run-id", required=True)
    seed = commands.add_parser("seed")
    seed.add_argument("--source-run-id", required=True)
    seed.add_argument("--candidate", choices=[label for label, _ in _CANDIDATES], required=True)
    seed.add_argument("--database-url", required=True)
    seed.add_argument("--local-ai-env", type=Path, default=None)
    compare = commands.add_parser("compare")
    compare.add_argument("--source-run-id", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        source_run_dir = _resolve_source_run(args.root, args.source_run_id)
        if args.command == "fork":
            result = create_grading_bakeoff(
                source_run_dir=source_run_dir,
                operator_assets_for_model=evaluation._operator_asset_metadata,
            )
            print(
                json.dumps(
                    {
                        "source_run_id": result.source.source_run_id,
                        "candidates": [
                            candidate.model_dump(mode="json") for candidate in result.candidates
                        ],
                        "new_provider_calls": 0,
                    },
                    indent=2,
                )
            )
            return
        if args.command == "seed":
            bakeoff = GradingBakeoffManifest.model_validate(
                evaluation.read_json(source_run_dir / "grading_bakeoff" / "manifest.json")
            )
            candidate = next(item for item in bakeoff.candidates if item.label == args.candidate)
            lock = seed_grading_bakeoff_candidate(
                candidate_run_dir=source_run_dir.parent / candidate.run_id,
                database_url=args.database_url,
                local_ai_env=args.local_ai_env,
            )
            print(
                json.dumps(
                    {
                        "candidate": candidate.label,
                        "run_id": candidate.run_id,
                        "state": "ocr_confirmed",
                        "confirmed_case_count": len(lock.cases),
                        "new_visual_provider_calls": 0,
                    },
                    indent=2,
                )
            )
            return
        report = compare_grading_bakeoff(source_run_dir=source_run_dir)
        print(
            json.dumps(
                {
                    "verdict": report.verdict.value,
                    "recommended_grading_model": report.recommended_grading_model,
                    "report": str(source_run_dir / "grading_bakeoff" / "report.md"),
                },
                indent=2,
            )
        )
    except (GradingBakeoffError, evaluation.LocalCuratedEvaluationError) as exc:
        raise SystemExit(f"Grading bake-off refused: {exc}") from exc


if __name__ == "__main__":
    main()
