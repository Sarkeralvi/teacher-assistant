import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    AnswerRegionSegment,
    Assessment,
    BatchEvidencePrepRun,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingRun,
    Question,
    QuestionImportJob,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    BatchEvidencePrepRun,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    Question,
    QuestionImportJob,
    GradingRun,
    Assessment,
    Course,
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in CLEANUP_MODELS:
            db.execute(delete(model))
        db.commit()
        db.close()


@pytest.fixture()
def client(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def register_teacher(client: TestClient, prefix: str = "prep") -> tuple[dict[str, object], str]:
    response = client.post(
        "/auth/register",
        json={
            "name": "Teacher",
            "email": f"{prefix}-{uuid4().hex}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["user"], body["access_token"]


def make_png(path: Path, size: tuple[int, int] = (120, 100)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw_rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw_rows))
        + chunk(b"IEND", b"")
    )


def create_assessment_fixture(client: TestClient, tmp_path: Path) -> dict[str, object]:
    teacher, token = register_teacher(client)
    course = client.post(
        "/courses",
        json={"teacher_id": teacher["id"], "code": "BATCH101", "title": "Batch"},
    ).json()
    assessment = client.post(
        f"/courses/{course['id']}/assessments",
        json={"title": "Midterm", "assessment_type": "exam", "total_marks": "10.00"},
    ).json()
    question = client.post(
        f"/assessments/{assessment['id']}/questions",
        json={"question_no": "1", "question_text": "Explain.", "total_marks": "5.00"},
    ).json()
    rubric = client.post(
        f"/questions/{question['id']}/rubrics",
        json={
            "version": 1,
            "is_active": True,
            "rubric_json": {
                "total_marks": "5.00",
                "criteria": [
                    {
                        "id": "concept",
                        "name": "Concept",
                        "description": "Correct concept.",
                        "max_marks": "5.00",
                    }
                ],
            },
        },
    ).json()
    image = tmp_path / f"script-{uuid4().hex}.png"
    make_png(image)
    with image.open("rb") as file_obj:
        submission = client.post(
            f"/assessments/{assessment['id']}/submissions/upload",
            data={"student_identifier": "S-001", "student_name": "Student One"},
            files={"file": ("answer.png", file_obj, "image/png")},
        ).json()
    region = client.post(
        f"/submission-pages/{submission['pages'][0]['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 2, "width": 20, "height": 25},
    ).json()
    confirm_response = client.patch(
        f"/answer-regions/{region['id']}/corrections/full-answer-confirmation",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_answer_confirmed": True,
            "continuation_not_needed": True,
            "packet_status": "complete",
        },
    )
    assert confirm_response.status_code == 200
    return {
        "teacher": teacher,
        "token": token,
        "assessment": assessment,
        "question": question,
        "rubric": rubric,
        "submission": submission,
        "region": region,
    }


def test_create_prep_run_summarizes_ready_packet_without_grading_side_effects(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)

    response = client.post(
        f"/assessments/{data['assessment']['id']}/evidence-prep-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert response.status_code == 201
    run = response.json()
    assert run["assessment_id"] == data["assessment"]["id"]
    assert run["created_by_teacher_id"] == data["teacher"]["id"]
    assert run["status"] == "completed"
    assert run["total_submissions"] == 1
    assert run["total_expected_packets"] == 1
    assert run["ready_packet_count"] == 1
    assert run["blocked_packet_count"] == 0
    assert run["warning_packet_count"] == 1
    assert run["blank_packet_count"] == 0
    assert run["partial_packet_count"] == 0
    packet = run["packets"][0]
    assert packet["submission_id"] == data["submission"]["id"]
    assert packet["student_identifier"] == "S-001"
    assert packet["grading_unit_label"] == "1"
    assert packet["max_marks"] == "5.00"
    assert packet["evidence_status"] == "complete"
    assert packet["continuation_check_status"] == "continuation_confirmed_not_needed"
    assert packet["ready_for_grading"] is True
    assert packet["blockers"] == []
    assert packet["segment_count"] == 1
    assert packet["pages_covered"] == [1]
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0
    assert db_session.query(GradingJob).count() == 0

    detail = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-runs/{run['id']}",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == run["id"]


def test_prep_summary_quarantines_unconfirmed_partial_blank_and_continuation(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    region = db_session.get(AnswerRegion, data["region"]["id"])
    assert region is not None
    region.full_answer_confirmed = False
    region.evidence_status = "unconfirmed"
    db_session.commit()

    unconfirmed = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()
    assert unconfirmed["blocked_packet_count"] == 1
    assert unconfirmed["packets"][0]["quarantined"] is True
    assert "evidence packet is not confirmed complete" in unconfirmed["packets"][0]["blockers"]

    region.evidence_status = "partial"
    db_session.commit()
    partial = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()
    assert partial["partial_packet_count"] == 1
    assert partial["blocked_packet_count"] == 1
    assert "partial evidence packet requires teacher review" in partial["packets"][0]["blockers"]

    region.evidence_status = "blank"
    db_session.commit()
    blank = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()
    assert blank["blank_packet_count"] == 1
    assert blank["blocked_packet_count"] == 1
    assert "confirmed blank packet is not enabled for grading" in blank["packets"][0]["blockers"]

    region.evidence_status = "complete"
    region.full_answer_confirmed = False
    region.continuation_check_status = "not_checked"
    region.y = 82
    region.height = 15
    db_session.add(
        SubmissionPage(
            submission_id=region.submission_id,
            page_no=2,
            image_path=region.page.image_path,
        )
    )
    db_session.commit()
    continuation = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()
    assert continuation["blocked_packet_count"] == 1
    assert continuation["packets"][0]["continuation_check_status"] == "possible_continuation"
    assert "possible answer continuation not confirmed" in continuation["packets"][0]["blockers"]


def test_prep_summary_quarantines_missing_rubric_invalid_order_and_missing_region(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    question2 = client.post(
        f"/assessments/{data['assessment']['id']}/questions",
        json={"question_no": "2", "question_text": "Second.", "total_marks": "5.00"},
    ).json()
    region = db_session.get(AnswerRegion, data["region"]["id"])
    assert region is not None
    region.question_id = question2["id"]
    region.segments[0].order_index = 2
    db_session.commit()

    summary = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()

    assert summary["total_expected_packets"] == 2
    assert summary["ready_packet_count"] == 0
    assert summary["blocked_packet_count"] == 2
    by_label = {packet["grading_unit_label"]: packet for packet in summary["packets"]}
    assert "no answer region mapped for this submission/question" in by_label["1"]["blockers"]
    assert "missing active rubric" in by_label["2"]["blockers"]
    assert "answer segment order must be contiguous starting at 1" in by_label["2"]["blockers"]


def test_prep_run_requires_owner_teacher(client: TestClient, tmp_path: Path) -> None:
    data = create_assessment_fixture(client, tmp_path)
    _, other_token = register_teacher(client, "other-prep")

    response = client.post(
        f"/assessments/{data['assessment']['id']}/evidence-prep-runs",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404


def test_prep_summary_quarantines_page_order_unknown(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    page = db_session.get(SubmissionPage, data["submission"]["pages"][0]["id"])
    assert page is not None
    page.page_no = 3
    db_session.commit()

    summary = client.get(
        f"/assessments/{data['assessment']['id']}/evidence-prep-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    ).json()

    assert summary["blocked_packet_count"] == 1
    assert "page order unknown" in summary["packets"][0]["blockers"]
