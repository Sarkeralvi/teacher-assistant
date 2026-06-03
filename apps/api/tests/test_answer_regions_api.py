from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AnswerRegion,
    AnswerRegionSegment,
    Assessment,
    Course,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    Question,
    Submission,
    SubmissionPage,
    User,
)

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Question,
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


def make_png(path: Path, size: tuple[int, int] = (100, 80)) -> None:
    Image.new("RGB", size, color="white").save(path, format="PNG")


def create_uploaded_page(
    client: TestClient, tmp_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    image_path = tmp_path / f"answer-{len(list(tmp_path.glob('answer-*.png')))}.png"
    email = f"regions-{image_path.stem}@example.com"
    user_response = client.post("/users", json={"name": "Teacher", "email": email})
    assert user_response.status_code == 201
    course_response = client.post(
        "/courses",
        json={"teacher_id": user_response.json()["id"], "code": "REG101", "title": "Regions"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "10.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        json={"question_no": "1", "question_text": "Answer this.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    image_path = tmp_path / f"answer-{len(list(tmp_path.glob('answer-*.png')))}.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            data={"student_identifier": "S-001"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]
    return question_response.json(), page


def test_create_answer_region_crops_image_and_serves_png(
    client: TestClient, tmp_path: Path
) -> None:
    question, page = create_uploaded_page(client, tmp_path)

    response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 10, "y": 12, "width": 30, "height": 20},
    )

    assert response.status_code == 201
    region = response.json()
    assert region["submission_id"] == page["submission_id"]
    assert region["page_id"] == page["id"]
    assert region["question_id"] == question["id"]
    assert region["x"] == "10.00"
    assert region["y"] == "12.00"
    assert region["width"] == "30.00"
    assert region["height"] == "20.00"
    assert region["image_path"].endswith(".png")
    assert not region["image_path"].startswith("/")
    assert ".." not in region["image_path"]

    image_response = client.get(f"/answer-regions/{region['id']}/image")
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.content.startswith(b"\x89PNG")

    cropped_path = tmp_path / "cropped.png"
    cropped_path.write_bytes(image_response.content)
    with Image.open(cropped_path) as cropped:
        assert cropped.size == (30, 20)


def test_answer_region_list_endpoints_and_question_filter(
    client: TestClient, tmp_path: Path
) -> None:
    question, page = create_uploaded_page(client, tmp_path)
    create_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 2, "width": 10, "height": 12},
    )
    assert create_response.status_code == 201
    region = create_response.json()

    submission_list = client.get(f"/submissions/{page['submission_id']}/answer-regions")
    assert submission_list.status_code == 200
    assert [item["id"] for item in submission_list.json()] == [region["id"]]

    assessment_list = client.get(f"/assessments/{question['assessment_id']}/answer-regions")
    assert assessment_list.status_code == 200
    assert [item["id"] for item in assessment_list.json()] == [region["id"]]

    filtered = client.get(
        f"/assessments/{question['assessment_id']}/answer-regions",
        params={"question_id": question["id"]},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [region["id"]]

    no_match = client.get(
        f"/assessments/{question['assessment_id']}/answer-regions",
        params={"question_id": 999999},
    )
    assert no_match.status_code == 200
    assert no_match.json() == []

    detail = client.get(f"/answer-regions/{region['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == region["id"]


def test_answer_region_validation_errors(client: TestClient, tmp_path: Path) -> None:
    question, page = create_uploaded_page(client, tmp_path)

    missing_page = client.post(
        "/submission-pages/999999/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 1, "width": 10, "height": 10},
    )
    assert missing_page.status_code == 404

    missing_question = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": 999999, "x": 1, "y": 1, "width": 10, "height": 10},
    )
    assert missing_question.status_code == 404

    negative_xy = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": -1, "y": 1, "width": 10, "height": 10},
    )
    assert negative_xy.status_code == 422

    zero_width = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 1, "width": 0, "height": 10},
    )
    assert zero_width.status_code == 422

    outside_bounds = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 90, "y": 70, "width": 20, "height": 20},
    )
    assert outside_bounds.status_code == 422


def test_rejects_question_from_different_assessment(client: TestClient, tmp_path: Path) -> None:
    _question, page = create_uploaded_page(client, tmp_path)
    other_question, _other_page = create_uploaded_page(client, tmp_path)

    response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": other_question["id"], "x": 1, "y": 1, "width": 10, "height": 10},
    )

    assert response.status_code == 422
    assert "Question assessment must match submission assessment" in response.text


def test_answer_region_suggestion_endpoint_returns_draft_and_does_not_persist(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    image_path = tmp_path / "suggest-page.png"
    make_png(image_path, size=(320, 240))
    email = f"suggest-{image_path.stem}@example.com"
    user_response = client.post("/users", json={"name": "Teacher", "email": email})
    assert user_response.status_code == 201
    course_response = client.post(
        "/courses",
        json={"teacher_id": user_response.json()["id"], "code": "SUG101", "title": "Suggest"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "10.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        json={"question_no": "1", "question_text": "Answer this.", "total_marks": "5.00"},
    )
    assert question_response.status_code == 201
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            data={"student_identifier": "SUG-001"},
            files={"file": ("suggest.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]

    suggest_response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "mock", "question_ids": [question_response.json()["id"]]},
    )
    assert suggest_response.status_code == 200
    body = suggest_response.json()
    assert body["page_id"] == page["id"]
    assert body["provider"] == "mock"
    assert body["needs_review"] is True
    assert body["suggestions"]
    suggestion = body["suggestions"][0]
    assert suggestion["needs_review"] is True
    assert suggestion["suggested_question_id"] == question_response.json()["id"]
    assert suggestion["suggested_question_no"] == "1"
    assert suggestion["provider"] == "mock"
    assert suggestion["warnings"]
    assert suggestion["confidence"] == "0.35"
    assert float(suggestion["x"]) >= 0
    assert float(suggestion["y"]) >= 0
    assert float(suggestion["width"]) > 0
    assert float(suggestion["height"]) > 0

    list_response = client.get(f"/submissions/{page['submission_id']}/answer-regions")
    assert list_response.status_code == 200
    assert list_response.json() == []

    created_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={
            "question_id": suggestion["suggested_question_id"],
            "x": suggestion["x"],
            "y": suggestion["y"],
            "width": suggestion["width"],
            "height": suggestion["height"],
        },
    )
    assert created_response.status_code == 201

    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0


def test_answer_region_suggestion_endpoint_handles_small_page_cleanly(
    client: TestClient, tmp_path: Path
) -> None:
    _question, page = create_uploaded_page(client, tmp_path)

    suggest_response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "mock"},
    )
    assert suggest_response.status_code == 200
    body = suggest_response.json()
    assert body["page_id"] == page["id"]
    assert body["suggestions"] == []
    assert "too small" in body["message"]

    assert client.get(f"/submissions/{page['submission_id']}/answer-regions").json() == []


def test_answer_region_suggestion_rejects_cross_assessment_questions(
    client: TestClient, tmp_path: Path
) -> None:
    question, page = create_uploaded_page(client, tmp_path)
    other_question, _other_page = create_uploaded_page(client, tmp_path)

    response = client.post(
        f"/submission-pages/{page['id']}/answer-region-suggestions",
        json={"provider": "mock", "question_ids": [other_question["id"]]},
    )

    assert response.status_code == 422
    assert "same assessment" in response.text

    accept_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 1, "width": 10, "height": 10},
    )
    assert accept_response.status_code == 201


def test_add_answer_region_segment_persists_ordered_crop_and_confirmation(
    client: TestClient, tmp_path: Path
) -> None:
    question, page = create_uploaded_page(client, tmp_path)
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 2, "width": 20, "height": 20},
    )
    assert region_response.status_code == 201
    region = region_response.json()

    segment_response = client.post(
        f"/answer-regions/{region['id']}/segments",
        json={
            "page_id": page["id"],
            "x": 4,
            "y": 5,
            "width": 30,
            "height": 22,
            "order_index": 2,
            "source": "manual",
            "confirmed": True,
        },
    )

    assert segment_response.status_code == 201
    segment = segment_response.json()
    assert segment["answer_region_id"] == region["id"]
    assert segment["page_id"] == page["id"]
    assert segment["order_index"] == 2
    assert segment["source"] == "manual"
    assert segment["confirmed"] is True
    assert segment["image_path"].endswith(".png")
    assert not segment["image_path"].startswith("/")

    detail_response = client.get(f"/answer-regions/{region['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["full_answer_confirmed"] is False
    assert [item["order_index"] for item in detail["segments"]] == [1, 2]
    assert detail["segments"][0]["is_primary"] is True
    assert detail["segments"][1]["is_primary"] is False

    confirm_response = client.patch(
        f"/answer-regions/{region['id']}/full-answer-confirmation",
        json={"full_answer_confirmed": True},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["full_answer_confirmed"] is True


def test_answer_region_segment_rejects_page_from_other_submission(
    client: TestClient, tmp_path: Path
) -> None:
    question, page = create_uploaded_page(client, tmp_path)
    _other_question, other_page = create_uploaded_page(client, tmp_path)
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={"question_id": question["id"], "x": 1, "y": 2, "width": 20, "height": 20},
    )
    assert region_response.status_code == 201

    response = client.post(
        f"/answer-regions/{region_response.json()['id']}/segments",
        json={
            "page_id": other_page["id"],
            "x": 4,
            "y": 5,
            "width": 30,
            "height": 22,
            "order_index": 2,
        },
    )

    assert response.status_code == 422
    assert "Segment page must belong to the same submission" in response.text
