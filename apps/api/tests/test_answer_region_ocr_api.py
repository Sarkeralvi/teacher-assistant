import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrBand,
    AnswerRegionOcrCandidate,
    AnswerRegionOcrRun,
    AuditLog,
    ExtractionRun,
    QuestionNode,
)
from app.services.local_ocr_client import LocalOcrResult
from app.services.ocr_rescue_service import OcrRescueService
from tests.test_grading_api import CLEANUP_MODELS, create_answer_region_with_optional_rubric


class FakeOcrClient:
    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        request_id = str(kwargs["request_id"])
        return LocalOcrResult.model_validate(
            {
                "request_id": request_id,
                "mode": "answer_region",
                "text": "OCR draft answer",
                "normalized_text": "OCR draft answer",
                "markdown": "OCR draft answer",
                "blocks": [
                    {
                        "page": 1,
                        "order": 1,
                        "label": "text",
                        "text": "OCR draft answer",
                        "bbox": [1, 2, 20, 25],
                    }
                ],
                "warnings": ["handwriting_uncertain"],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "cpu",
                "latency_ms": 7,
            }
        )


class MismatchedOcrClient(FakeOcrClient):
    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        result = super().ocr_image(**kwargs)
        return result.model_copy(update={"model": "unexpected-ocr-model"})


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in (AuditLog, AnswerRegionOcrRun, *CLEANUP_MODELS):
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        db.rollback()
        for model in (AuditLog, AnswerRegionOcrRun, *CLEANUP_MODELS):
            db.execute(delete(model))
        db.commit()
        db.close()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    monkeypatch.setenv("BRAIN_ALLOW_REAL_PROVIDERS", "true")
    monkeypatch.setenv("LOCAL_OCR_ENABLED", "true")
    monkeypatch.setenv("LOCAL_OCR_RESCUE_ENABLED", "true")
    monkeypatch.setenv("LOCAL_OCR_API_KEY", "test-local-ocr-key")
    monkeypatch.setattr(
        "app.services.answer_region_ocr_service.LocalOcrClient.from_settings",
        lambda: FakeOcrClient(),
    )
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def test_ocr_success_is_draft_only_until_teacher_confirms(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(
        client,
        tmp_path,
        manual_answer_text="Existing teacher text",
    )

    response = client.post(
        f"/answer-regions/{region['id']}/ocr-runs",
        headers=region["_auth_headers"],
    )

    assert response.status_code == 201
    draft = response.json()
    assert draft["status"] == "succeeded"
    assert draft["draft_text"] == "OCR draft answer"
    assert draft["warnings"] == ["handwriting_uncertain"]
    db_session.expire_all()
    stored_region = db_session.get(AnswerRegion, region["id"])
    assert stored_region is not None
    assert stored_region.manual_answer_text == "Existing teacher text"
    assert stored_region.full_answer_confirmed is False
    assert stored_region.evidence_status == region["evidence_status"]

    confirmation = client.post(
        f"/answer-regions/{region['id']}/ocr-runs/{draft['id']}/confirm",
        headers=region["_auth_headers"],
        json={"confirmed_text": "Teacher edited OCR text"},
    )

    assert confirmation.status_code == 200
    assert confirmation.json()["status"] == "confirmed"
    db_session.expire_all()
    stored_region = db_session.get(AnswerRegion, region["id"])
    assert stored_region is not None
    assert stored_region.manual_answer_text == "Teacher edited OCR text"
    assert stored_region.full_answer_confirmed is False
    assert stored_region.evidence_status == region["evidence_status"]
    audit_payloads = list(
        db_session.scalars(
            select(AuditLog.payload_json).where(
                AuditLog.event_type == "answer_region_ocr_text_confirmed"
            )
        ).all()
    )
    assert audit_payloads
    assert "Teacher edited OCR text" not in str(audit_payloads[-1])


def test_ocr_run_list_detail_and_confirmation_enforce_ownership(
    client: TestClient, tmp_path: Path
) -> None:
    owner_region = create_answer_region_with_optional_rubric(client, tmp_path)
    run = client.post(
        f"/answer-regions/{owner_region['id']}/ocr-runs",
        headers=owner_region["_auth_headers"],
    ).json()
    intruder = client.post(
        "/auth/register",
        json={
            "name": "OCR Intruder",
            "email": "ocr-intruder@example.com",
            "password": "password123",
        },
    ).json()
    intruder_headers = {"Authorization": f"Bearer {intruder['access_token']}"}

    assert client.get(f"/answer-region-ocr-runs/{run['id']}").status_code == 401
    assert (
        client.get(
            f"/answer-region-ocr-runs/{run['id']}", headers=intruder_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/answer-regions/{owner_region['id']}/ocr-runs/{run['id']}/confirm",
            headers=intruder_headers,
            json={"confirmed_text": "tampered"},
        ).status_code
        == 404
    )
    listed = client.get(
        f"/answer-regions/{owner_region['id']}/ocr-runs",
        headers=owner_region["_auth_headers"],
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run["id"]]


def test_ocr_runs_cascade_when_answer_region_is_deleted(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    response = client.post(
        f"/answer-regions/{region['id']}/ocr-runs",
        headers=region["_auth_headers"],
    )
    assert response.status_code == 201

    db_session.execute(delete(AnswerRegion).where(AnswerRegion.id == region["id"]))
    db_session.commit()

    remaining = db_session.scalar(
        select(func.count(AnswerRegionOcrRun.id)).where(
            AnswerRegionOcrRun.answer_region_id == region["id"]
        )
    )
    assert remaining == 0


def test_ocr_provider_metadata_mismatch_fails_without_creating_draft(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.answer_region_ocr_service.LocalOcrClient.from_settings",
        lambda: MismatchedOcrClient(),
    )
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(
        f"/answer-regions/{region['id']}/ocr-runs",
        headers=region["_auth_headers"],
    )

    assert response.status_code == 502
    db_session.expire_all()
    run = db_session.scalars(
        select(AnswerRegionOcrRun).where(
            AnswerRegionOcrRun.answer_region_id == region["id"]
        )
    ).one()
    assert run.status == "failed"
    assert run.draft_text is None
    assert run.error == "Local OCR provider metadata does not match the baseline"


def test_rescue_candidate_confirmation_is_id_only_and_keeps_full_answer_blocked(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    region_data = create_answer_region_with_optional_rubric(client, tmp_path)
    region = db_session.get(AnswerRegion, region_data["id"])
    assert region is not None
    extraction = ExtractionRun(
        assessment_id=region.question.assessment_id,
        artifact_file_path="ignored-reference.pdf",
        original_filename="reference.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="local_paddle_qwen",
        status="succeeded",
        blockers=[],
    )
    db_session.add(extraction)
    db_session.flush()
    node = QuestionNode(
        assessment_id=region.question.assessment_id,
        extraction_run_id=extraction.id,
        question_number=region.question.question_no,
        label=region.question.question_no,
        text=region.question.question_text,
        node_type="question",
        source_page=1,
        confidence="0.9",
        teacher_confirmed=True,
    )
    db_session.add(node)
    db_session.flush()
    mapping = AnswerRegionMapping(
        assessment_id=region.question.assessment_id,
        submission_id=region.submission_id,
        question_node_id=node.id,
        question_id=region.question_id,
        answer_region_id=region.id,
        source_page=1,
        source_reference={},
        confidence="0.8",
        mapping_status="uncertain",
        provider="local_paddle_qwen",
        teacher_confirmed=False,
    )
    db_session.add(mapping)
    db_session.commit()

    class RecordingQueue:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def enqueue(self, function: Any, run_id: int, **kwargs: Any) -> None:
            self.calls.append({"function": function, "run_id": run_id, **kwargs})

    queue = RecordingQueue()
    monkeypatch.setattr("app.api.routes.ocr.get_default_queue", lambda: queue)
    response = client.post(
        f"/answer-regions/{region.id}/ocr-rescue-runs",
        headers=region_data["_auth_headers"],
        json={
            "profile": "math_handwriting_rescue_v2",
            "expected_vl_model": "PaddleOCR-VL-1.6",
            "expected_layout_model": "PP-DocLayoutV3",
            "expected_text_detection_model": "PP-OCRv6_medium_det",
            "expected_text_recognition_model": "PP-OCRv6_medium_rec",
            "max_calls": 8,
            "draft_only_confirmed": True,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert queue.calls == [
        {
            "function": queue.calls[0]["function"],
            "run_id": run_id,
            "retry": None,
        }
    ]

    db_session.expire_all()
    run = db_session.get(AnswerRegionOcrRun, run_id)
    region = db_session.get(AnswerRegion, region_data["id"])
    mapping = db_session.get(AnswerRegionMapping, mapping.id)
    assert run is not None and region is not None and mapping is not None
    source_hash = hashlib.sha256(
        OcrRescueService(db_session)._source_image_bytes(region)
    ).hexdigest()
    run.source_image_sha256 = source_hash
    run.status = "succeeded"
    run.normalized_result = {"mapping_id": mapping.id}
    band = AnswerRegionOcrBand(
        ocr_run_id=run.id,
        order_index=1,
        x=0,
        y=0,
        width=100,
        height=40,
        image_path=region.image_path,
        image_sha256=source_hash,
        classification="formula",
    )
    db_session.add(band)
    db_session.flush()
    candidate_text = "7/12 × 0.5"
    candidate = AnswerRegionOcrCandidate(
        band_id=band.id,
        engine="paddleocr_vl",
        model_name="PaddleOCR-VL-1.6",
        prompt_label="formula",
        preprocessing_profile="math_handwriting_rescue",
        text=candidate_text,
        text_sha256=hashlib.sha256(candidate_text.encode()).hexdigest(),
        warnings=[],
    )
    db_session.add(candidate)
    db_session.commit()

    forged = client.post(
        f"/answer-regions/{region.id}/ocr-runs/{run.id}/confirm-candidates",
        headers=region_data["_auth_headers"],
        json={"candidate_ids": [candidate.id + 9999]},
    )
    assert forged.status_code == 422
    confirmed = client.post(
        f"/answer-regions/{region.id}/ocr-runs/{run.id}/confirm-candidates",
        headers=region_data["_auth_headers"],
        json={"candidate_ids": [candidate.id]},
    )
    assert confirmed.status_code == 200
    db_session.expire_all()
    stored_region = db_session.get(AnswerRegion, region.id)
    stored_mapping = db_session.get(AnswerRegionMapping, mapping.id)
    assert stored_region is not None and stored_mapping is not None
    assert stored_region.manual_answer_text == candidate_text
    assert stored_region.full_answer_confirmed is False
    assert stored_region.evidence_status == "unconfirmed"
    assert stored_mapping.teacher_confirmed is True
    audits = list(
        db_session.scalars(
            select(AuditLog.payload_json).where(
                AuditLog.event_type == "answer_region_ocr_candidates_confirmed"
            )
        )
    )
    assert audits and candidate_text not in str(audits[-1])
