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
from app.models import AnswerRegion, AnswerRegionOcrRun, AuditLog
from app.services.local_ocr_client import LocalOcrResult
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
