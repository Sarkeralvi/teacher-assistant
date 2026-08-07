from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.local_ocr_client import LocalOcrResult
from packages.brain.adapter import BrainAdapter
from packages.brain.provider_base import BrainProvider
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem
from packages.evaluation import local_curated_evaluation as evaluation
from tests.test_cohort_grading_api import CLEANUP_MODELS


class SequencedFakeOcrClient:
    def __init__(self, texts: list[str]) -> None:
        self._texts = iter(texts)
        self.call_count = 0

    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        text = next(self._texts)
        self.call_count += 1
        blocks = []
        if text:
            blocks.append(
                {
                    "page": 1,
                    "order": 1,
                    "label": "text",
                    "text": text,
                    "bbox": [20, 20, 1500, 850],
                }
            )
        return LocalOcrResult.model_validate(
            {
                "request_id": str(kwargs["request_id"]),
                "mode": "answer_region",
                "text": text,
                "normalized_text": text,
                "markdown": text,
                "blocks": blocks,
                "warnings": [],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "cpu",
                "latency_ms": 5,
            }
        )


class FakeLocalQwenProvider(BrainProvider):
    provider_name = "llama_cpp_qwen"
    model_name = "qwen3.6-35b-a3b-q4km"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def grade(
        self,
        *,
        question_text: str,
        question_total_marks: Decimal,
        rubric_json: dict[str, Any],
        answer_image_path: str,
        prompt_version: str,
        student_answer_text: str | None = None,
        task_name: str = "answer_region_grading",
        model_policy: object | None = None,
        messages: list[dict[str, Any]] | None = None,
        image_data_url: str | None = None,
        marking_policy: str = "general",
    ) -> GradeSuggestionOutput:
        del question_text, task_name, model_policy, messages
        assert answer_image_path == "[image input disabled]"
        assert image_data_url is None
        assert student_answer_text
        assert prompt_version == "real-grading-v1"
        assert marking_policy == "general"
        self.calls.append(student_answer_text)
        criteria = rubric_json["criteria"]
        breakdown = [
            RubricBreakdownItem(
                criterion_id=str(criterion["id"]),
                criterion=str(criterion["name"]),
                max_marks=Decimal(str(criterion["max_marks"])),
                awarded_marks=Decimal("0"),
                reason="Fake provider deliberately awards zero for pipeline rehearsal.",
                evidence=None,
                confidence=Decimal("0.50"),
            )
            for criterion in criteria
        ]
        return GradeSuggestionOutput(
            score=Decimal("0"),
            max_score=Decimal(str(rubric_json.get("total_marks", question_total_marks))),
            confidence=Decimal("0.50"),
            needs_review=True,
            rubric_breakdown=breakdown,
            detected_answer_summary="Synthetic fake-provider result.",
            major_errors=[],
            feedback_to_student="Teacher review is required.",
            review_flags=[
                "image_input_disabled",
                "local_provider",
                "teacher_review_required",
            ],
            model_provider=self.provider_name,
            model_name=self.model_name,
            prompt_version=prompt_version,
            cost_estimate=Decimal("0"),
            latency_ms=1,
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
        )


@pytest.fixture()
def clean_database() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()
        get_settings.cache_clear()


def _assets() -> evaluation.OperatorAssetMetadata:
    return evaluation.OperatorAssetMetadata.model_validate(
        {
            "llama_cpp": {
                "build": "10249",
                "model_alias": "qwen3.6-35b-a3b-q4km",
                "model_sha256": "1" * 64,
                "model_size_bytes": 1024,
                "device": "gpu_hybrid",
            },
            "paddle": {
                "packages": {
                    "paddleocr": "3.7.0",
                    "paddlex": "3.7.2",
                    "paddlepaddle-gpu": "3.2.1",
                },
                "model": "PaddleOCR-VL-1.6",
                "model_sha256": "2" * 64,
                "model_size_bytes": 1024,
                "model_file_count": 1,
                "layout_model": "PP-DocLayoutV3",
                "layout_model_sha256": "3" * 64,
                "layout_model_size_bytes": 1024,
                "layout_model_file_count": 1,
                "device": "cpu",
            },
        }
    )


def _complete_ground_truth(run_dir: Path) -> None:
    manifest = evaluation.load_manifest(run_dir)
    workbook_path = run_dir / "ground_truth_review.xlsx"
    workbook = load_workbook(workbook_path)
    sheet = workbook["Cases"]
    headers = {str(cell.value): index for index, cell in enumerate(sheet[1], start=1)}
    for row, case in enumerate(manifest.cases, start=2):
        sheet.cell(row, headers["teacher_transcription"], case.authored_transcription)
        sheet.cell(row, headers["teacher_score"], str(case.expected_score))
        sheet.cell(row, headers["teacher_notes"], "Independent fake-provider rehearsal")
        if case.primary_category == evaluation.PrimaryCategory.DIFFICULT_HANDWRITING:
            sheet.cell(row, headers["handwriting_acceptable"], "yes")
        sheet.cell(row, headers["teacher_approved"], "yes")
    workbook.save(workbook_path)


def _complete_ocr_review(run_dir: Path) -> None:
    ground_truth = evaluation.GroundTruthLock.model_validate(
        evaluation.read_json(run_dir / "ground_truth_lock.json")
    )
    truth_by_id = {case.case_id: case.teacher_transcription for case in ground_truth.cases}
    workbook_path = run_dir / "ocr_review.xlsx"
    workbook = load_workbook(workbook_path)
    sheet = workbook["OCR Review"]
    headers = {str(cell.value): index for index, cell in enumerate(sheet[1], start=1)}
    for row in range(2, 22):
        case_id = str(sheet.cell(row, headers["case_id"]).value)
        sheet.cell(row, headers["confirmed_text"], truth_by_id[case_id])
        sheet.cell(row, headers["teacher_notes"], "Confirmed in fake-provider rehearsal")
        sheet.cell(row, headers["teacher_approved"], "yes")
    workbook.save(workbook_path)


def _complete_grading_review(run_dir: Path) -> None:
    manifest = evaluation.load_manifest(run_dir)
    result = evaluation.GradingRunResult.model_validate(
        evaluation.read_json(run_dir / "grading_results.json")
    )
    definitions = {case.case_id: case for case in manifest.cases}
    results = {case.case_id: case for case in result.cases}
    workbook_path = run_dir / "grading_review.xlsx"
    workbook = load_workbook(workbook_path)
    sheet = workbook["Grading Review"]
    headers = {str(cell.value): index for index, cell in enumerate(sheet[1], start=1)}
    for row in range(2, 22):
        case_id = str(sheet.cell(row, headers["case_id"]).value)
        case_result = results[case_id]
        definition = definitions[case_id]
        if case_result.outcome == "not_called_blank_safety_gate":
            reason = "none"
            useful = "no"
        else:
            reason = "none" if case_result.ai_score == definition.expected_score else "model_error"
            useful = "yes"
        sheet.cell(row, headers["disagreement_reason"], reason)
        sheet.cell(row, headers["teacher_notes"], "Fake-provider rehearsal review")
        sheet.cell(row, headers["useful_draft"], useful)
        sheet.cell(row, headers["approved_review"], "yes")
    workbook.save(workbook_path)


def _status() -> dict[str, Any]:
    return {
        "real_providers_allowed": True,
        "cohort_model_grading_enabled": True,
        "qwen": {
            "enabled": True,
            "available": True,
            "provider": "llama_cpp_qwen",
            "model": "qwen3.6-35b-a3b-q4km",
            "layout_model": None,
            "device": "gpu_hybrid",
            "detail": "ready",
        },
        "ocr": {
            "enabled": True,
            "available": True,
            "provider": "local_paddle_qwen",
            "model": "PaddleOCR-VL-1.6",
            "layout_model": "PP-DocLayoutV3",
            "device": "cpu",
            "detail": "ready",
            "version": "3.7.0",
            "max_concurrency": 1,
            "offline": True,
        },
    }


def test_full_harness_rehearsal_uses_only_fake_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_database: Session,
) -> None:
    del clean_database
    run_id = "fake_full_rehearsal"
    assets = _assets()
    run_dir = evaluation.prepare_evaluation(
        run_id=run_id,
        output_root=tmp_path / "evaluation",
        integration_commit="d" * 40,
        harness_commit="e" * 40,
        operator_assets=assets,
        seed=12345,
    )
    _complete_ground_truth(run_dir)
    evaluation.lock_ground_truth(
        run_dir,
        reviewer_id="fake-teacher",
        confirm_teacher_signoff=True,
    )

    runtime_storage = run_dir / "runtime_storage"
    monkeypatch.setenv("BRAIN_PROVIDER", "mock")
    monkeypatch.setenv("BRAIN_ALLOW_REAL_PROVIDERS", "true")
    monkeypatch.setenv("LOCAL_QWEN_ENABLED", "true")
    monkeypatch.setenv("LOCAL_QWEN_API_KEY", "fake-qwen-key")
    monkeypatch.setenv("LOCAL_QWEN_MODEL", "qwen3.6-35b-a3b-q4km")
    monkeypatch.setenv("LOCAL_OCR_ENABLED", "true")
    monkeypatch.setenv("LOCAL_OCR_API_KEY", "fake-ocr-key")
    monkeypatch.setenv("COHORT_MODEL_GRADING_ENABLED", "true")
    monkeypatch.setenv("COHORT_MAX_PROVIDER_CALLS", "25")
    monkeypatch.setenv("COHORT_PROVIDER_RETRY_COUNT", "0")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(runtime_storage))
    monkeypatch.setenv("UPLOADS_DIR", str(runtime_storage / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(runtime_storage / "artifacts"))
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(evaluation, "require_clean_git_worktree", lambda: None)
    monkeypatch.setattr(evaluation, "current_git_commit", lambda: "e" * 40)
    monkeypatch.setattr(evaluation, "_sanitized_status", _status)
    monkeypatch.setattr(
        evaluation,
        "_gpu_safety_snapshot",
        lambda: {
            "qwen_present_in_gpu_compute_clients": True,
            "ocr_absent_from_gpu_compute_clients": True,
            "gpu_compute_client_names": ["fake-llama-server.exe"],
        },
    )
    monkeypatch.setattr(evaluation, "_operator_asset_metadata", lambda: assets)
    monkeypatch.setattr(
        evaluation,
        "_configure_runtime",
        lambda *_args, **_kwargs: (settings, SessionLocal, runtime_storage),
    )
    fake_ocr = SequencedFakeOcrClient(
        [case.authored_transcription for case in evaluation.load_manifest(run_dir).cases]
    )
    monkeypatch.setattr(
        "app.services.answer_region_ocr_service.LocalOcrClient.from_settings",
        lambda: fake_ocr,
    )
    database_url = (
        "postgresql+psycopg://postgres@127.0.0.1:55432/"
        f"teacher_assistant_eval_{run_id}"
    )

    ocr_result = evaluation.run_ocr_stage(
        run_dir,
        allow_local_ocr=True,
        max_ocr_calls=20,
        database_url=database_url,
    )
    assert fake_ocr.call_count == 20
    assert ocr_result.retry_count == 0
    assert evaluation.current_state(run_dir) == "ocr_completed"

    _complete_ocr_review(run_dir)
    confirmations = evaluation.lock_ocr_confirmations(
        run_dir,
        reviewer_id="fake-teacher",
        confirm_teacher_signoff=True,
        database_url=database_url,
    )
    assert len([case for case in confirmations.cases if case.evidence_status == "complete"]) == 18
    assert len([case for case in confirmations.cases if case.evidence_status == "blank"]) == 2

    fake_qwen = FakeLocalQwenProvider()
    adapter = BrainAdapter(
        fake_qwen,
        image_input_enabled=False,
        storage_root=str(runtime_storage),
    )

    def fake_for_provider(
        cls: type[BrainAdapter],
        provider_settings: Any,
        requested_provider: str,
    ) -> BrainAdapter:
        del cls, provider_settings
        assert requested_provider == "llama_cpp_qwen"
        return adapter

    monkeypatch.setattr(BrainAdapter, "for_provider", classmethod(fake_for_provider))
    grading_result = evaluation.run_grading_stage(
        run_dir,
        allow_local_qwen=True,
        max_qwen_calls=18,
        expected_model="qwen3.6-35b-a3b-q4km",
        database_url=database_url,
    )
    assert len(fake_qwen.calls) == 18
    assert all(fake_qwen.calls)
    assert grading_result.qwen_call_count == 18
    assert grading_result.blank_refusal_count == 2
    assert grading_result.retry_count == 0
    assert evaluation.current_state(run_dir) == "grading_completed"

    _complete_grading_review(run_dir)
    evaluation.lock_grading_review(
        run_dir,
        reviewer_id="fake-teacher",
        confirm_teacher_signoff=True,
    )
    report = evaluation.generate_report(run_dir)
    assert report["verdict"] == evaluation.EvaluationVerdict.NO_GO_QUALITY.value
    assert evaluation.current_state(run_dir) == "reported"
    assert report["process_checks"]["exactly_eighteen_qwen_calls"] is True
    assert report["process_checks"]["two_blank_policy_refusals"] is True
    assert not (run_dir / "invalid_run.json").exists()
    get_settings.cache_clear()
