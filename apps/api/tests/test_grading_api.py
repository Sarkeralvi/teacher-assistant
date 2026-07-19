import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, select
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
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from packages.brain.schemas import GradeSuggestionOutput, RubricBreakdownItem

CLEANUP_MODELS = (
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
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


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_auth_teacher(client: TestClient, email: str) -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={"name": "Grading Auth Teacher", "email": email, "password": "grading-password"},
    )
    assert response.status_code == 201
    return response.json()


def strict_rubric() -> dict[str, object]:
    return {
        "total_marks": "5.00",
        "criteria": [
            {
                "id": "concept",
                "name": "Core concept",
                "description": "Identifies the correct principle or idea.",
                "max_marks": "3.00",
            },
            {
                "id": "clarity",
                "name": "Clarity",
                "description": "Explains the answer clearly.",
                "max_marks": "2.00",
            },
        ],
    }


def create_answer_region_with_optional_rubric(
    client: TestClient,
    tmp_path: Path,
    *,
    create_rubric: bool = True,
    manual_answer_text: str | None = "A complete answer explains the concept.",
) -> dict[str, object]:
    email = f"grade-{len(list(tmp_path.glob('*.png')))}@example.com"
    user_response = client.post(
        "/auth/register",
        json={"name": "Teacher", "email": email, "password": "grading-password"},
    )
    assert user_response.status_code == 201
    token = user_response.json()["access_token"]
    headers = auth_header(token)
    course_response = client.post(
        "/courses",
        headers=headers,
        json={"code": "GRD101", "title": "Grading"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=headers,
        json={"title": "Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        headers=headers,
        json={
            "question_no": "1",
            "question_text": "Explain.",
            "model_answer": "A complete answer explains the concept.",
            "total_marks": "5.00",
        },
    )
    assert question_response.status_code == 201
    if create_rubric:
        rubric_response = client.post(
            f"/questions/{question_response.json()['id']}/rubrics",
            headers=headers,
            json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
        )
        assert rubric_response.status_code == 201

    image_path = tmp_path / f"grading-source-{len(list(tmp_path.glob('*.png')))}.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            headers=headers,
            data={"student_identifier": "S-001"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        headers=headers,
        json={
            "question_id": question_response.json()["id"],
            "x": 1,
            "y": 2,
            "width": 20,
            "height": 25,
            "manual_answer_text": manual_answer_text,
        },
    )
    assert region_response.status_code == 201
    return region_response.json()


def create_owned_answer_region(client: TestClient, tmp_path: Path, email: str) -> dict[str, object]:
    auth = register_auth_teacher(client, email)
    headers = auth_header(str(auth["access_token"]))
    course_response = client.post(
        "/courses",
        headers=headers,
        json={"code": "OWN-GRD", "title": "Owned Grading"},
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        headers=headers,
        json={"title": "Owned Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    question_response = client.post(
        f"/assessments/{assessment_response.json()['id']}/questions",
        json={
            "question_no": "1",
            "question_text": "Explain.",
            "model_answer": "A complete answer explains the concept.",
            "total_marks": "5.00",
        },
    )
    assert question_response.status_code == 201
    rubric_response = client.post(
        f"/questions/{question_response.json()['id']}/rubrics",
        json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
    )
    assert rubric_response.status_code == 201
    image_path = tmp_path / f"owned-grading-{email}.png"
    make_png(image_path)
    with image_path.open("rb") as file_obj:
        submission_response = client.post(
            f"/assessments/{assessment_response.json()['id']}/submissions/upload",
            headers=headers,
            data={"student_identifier": "S-OWN"},
            files={"file": ("answer.png", file_obj, "image/png")},
        )
    assert submission_response.status_code == 201
    page = submission_response.json()["pages"][0]
    region_response = client.post(
        f"/submission-pages/{page['id']}/answer-regions",
        json={
            "question_id": question_response.json()["id"],
            "x": 1,
            "y": 2,
            "width": 20,
            "height": 25,
        },
    )
    assert region_response.status_code == 201
    return {"auth": auth, "headers": headers, "region": region_response.json()}


def create_assessment_with_answer_regions(
    client: TestClient, tmp_path: Path, *, region_count: int = 3
) -> dict[str, object]:
    email = f"batch-{len(list(tmp_path.glob('batch-*.png')))}@example.com"
    register_response = client.post(
        "/auth/register",
        json={"name": "Batch Teacher", "email": email, "password": "batch test password"},
    )
    assert register_response.status_code == 201
    batch_headers = {"Authorization": f"Bearer {register_response.json()['access_token']}"}
    course_response = client.post(
        "/courses",
        json={
            "teacher_id": register_response.json()["user"]["id"],
            "code": "BATCH101",
            "title": "Batch",
        },
    )
    assert course_response.status_code == 201
    assessment_response = client.post(
        f"/courses/{course_response.json()['id']}/assessments",
        json={"title": "Batch Quiz", "assessment_type": "quiz", "total_marks": "5.00"},
    )
    assert assessment_response.status_code == 201
    assessment_id = assessment_response.json()["id"]
    question_response = client.post(
        f"/assessments/{assessment_id}/questions",
        json={
            "question_no": "1",
            "question_text": "Explain.",
            "model_answer": "A complete answer explains the concept.",
            "total_marks": "5.00",
        },
    )
    assert question_response.status_code == 201
    rubric_response = client.post(
        f"/questions/{question_response.json()['id']}/rubrics",
        json={"version": 1, "rubric_json": strict_rubric(), "is_active": True},
    )
    assert rubric_response.status_code == 201
    regions = []
    for index in range(region_count):
        image_path = tmp_path / f"batch-{index}.png"
        make_png(image_path)
        with image_path.open("rb") as file_obj:
            submission_response = client.post(
                f"/assessments/{assessment_id}/submissions/upload",
                headers=batch_headers,
                data={"student_identifier": f"S-{index:03d}"},
                files={"file": ("answer.png", file_obj, "image/png")},
            )
        assert submission_response.status_code == 201
        page = submission_response.json()["pages"][0]
        region_response = client.post(
            f"/submission-pages/{page['id']}/answer-regions",
            json={
                "question_id": question_response.json()["id"],
                "x": 1,
                "y": 2,
                "width": 20,
                "height": 25,
                "manual_answer_text": f"Batch answer {index}.",
                "full_answer_confirmed": True,
            },
        )
        assert region_response.status_code == 201
        regions.append(region_response.json())
    return {"assessment_id": assessment_id, "regions": regions}


def test_grade_answer_region_creates_job_and_mock_suggestion(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 201
    payload = response.json()
    assert payload["job"]["answer_region_id"] == region["id"]
    assert payload["job"]["status"] == "succeeded"
    suggestion = payload["suggestion"]
    assert suggestion["answer_region_id"] == region["id"]
    assert suggestion["model_provider"] == "mock"
    assert suggestion["model_name"] == "mock-grader-v1"
    assert suggestion["score"] == "0.00"
    assert suggestion["max_score"] == "5.00"
    assert suggestion["confidence"] == "0.0000"
    assert suggestion["needs_review"] is True
    assert (
        suggestion["feedback"] == "This is a mock grading suggestion for pipeline validation only."
    )
    raw = suggestion["raw_response_json"]
    assert set(raw["review_flags"]) == {
        "mock_provider",
        "teacher_review_required",
        "grading_crop_padded",
        "marking_policy:general",
    }
    assert raw["marking_policy"] == "general"
    assert raw["grading_context"]["original_image_path"] == region["image_path"]
    assert "grading_context" in raw["grading_context"]["answer_image_path"]
    assert [item["criterion_id"] for item in raw["rubric_breakdown"]] == ["concept", "clarity"]

    db_session.expire_all()
    assert db_session.scalars(select(GradingJob)).one().status == "succeeded"
    assert db_session.scalars(select(GradeSuggestion)).one().model_provider == "mock"


def test_grading_uses_padded_context_crop_without_changing_region_coordinates(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.grading_service import GradingService

    region_payload = create_answer_region_with_optional_rubric(client, tmp_path)
    region = db_session.get(AnswerRegion, region_payload["id"])
    assert region is not None
    original_image_path = region.image_path
    original_coordinates = (region.x, region.y, region.width, region.height)

    class RecordingAdapter:
        provider = type("Provider", (), {"provider_name": "mock"})()

        def __init__(self) -> None:
            self.answer_image_path: str | None = None
            self.student_answer_text: str | None = None

        def grade_answer_region(self, **kwargs: object) -> GradeSuggestionOutput:
            self.answer_image_path = str(kwargs["answer_image_path"])
            self.student_answer_text = str(kwargs["student_answer_text"])
            return GradeSuggestionOutput(
                model_provider="mock",
                model_name="mock-grader-v1",
                prompt_version="mock-grading-v1",
                score=Decimal("0.00"),
                max_score=Decimal("5.00"),
                confidence=Decimal("0.00"),
                feedback_to_student="mock",
                detected_answer_summary="mock summary",
                major_errors=[],
                rubric_breakdown=[
                    RubricBreakdownItem(
                        criterion_id="concept",
                        criterion="Core concept",
                        max_marks=Decimal("5.00"),
                        awarded_marks=Decimal("0.00"),
                        reason="mock",
                        confidence=Decimal("0.00"),
                    )
                ],
                needs_review=True,
                review_flags=["mock_provider", "teacher_review_required"],
            )

    monkeypatch.setenv("ANSWER_REGION_GRADING_CROP_PADDING_RATIO", "0.10")
    get_settings.cache_clear()
    service = GradingService(db_session, use_configured_adapter=False)
    recording_adapter = RecordingAdapter()
    service.adapter = recording_adapter  # type: ignore[assignment]

    service.grade_answer_region(region.id)

    assert recording_adapter.answer_image_path is not None
    assert recording_adapter.student_answer_text == "A complete answer explains the concept."
    assert recording_adapter.answer_image_path != original_image_path
    assert "grading_context" in recording_adapter.answer_image_path
    padded_path = service.storage.resolve_relative(recording_adapter.answer_image_path)
    original_path = service.storage.resolve_relative(original_image_path)
    with Image.open(original_path) as original_image, Image.open(padded_path) as padded_image:
        assert padded_image.width > original_image.width
        assert padded_image.height > original_image.height

    db_session.refresh(region)
    assert (region.x, region.y, region.width, region.height) == original_coordinates
    suggestion = db_session.scalars(select(GradeSuggestion)).one()
    assert "grading_crop_padded" in suggestion.raw_response_json["review_flags"]
    assert (
        suggestion.raw_response_json["grading_context"]["original_image_path"]
        == original_image_path
    )
    assert (
        suggestion.raw_response_json["grading_context"]["answer_image_path"]
        == recording_adapter.answer_image_path
    )


def test_grading_evidence_packet_reports_ready_state_and_auditable_fields(
    client: TestClient, tmp_path: Path
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.get(f"/answer-regions/{region['id']}/grading-evidence-packet")

    assert response.status_code == 200
    packet = response.json()
    assert packet["assessment_context"]["answer_region_id"] == region["id"]
    assert packet["assessment_context"]["submission_id"] == region["submission_id"]
    assert packet["assessment_context"]["page_id"] == region["page_id"]
    assert packet["canonical_grading_unit"]["label"] == "1"
    assert packet["canonical_grading_unit"]["max_marks"] == "5.00"
    assert packet["canonical_grading_unit"]["active_rubric_present"] is True
    assert packet["canonical_grading_unit"]["rubric_total_matches_grading_unit"] is True
    assert packet["question_evidence"]["confirmed_status"] == "unknown"
    assert packet["rubric_evidence"]["confirmed_status"] == "unknown"
    assert packet["student_answer_evidence"]["answer_region_coordinates"] == {
        "x": "1.00",
        "y": "2.00",
        "width": "20.00",
        "height": "25.00",
    }
    assert packet["student_answer_evidence"]["crop_path"] == region["image_path"]
    assert packet["student_answer_evidence"]["context_completeness_status"] == "unknown"
    assert packet["readiness_result"]["ready_for_grading"] is True
    assert packet["readiness_result"]["blockers"] == []
    assert "context completeness unknown" in packet["readiness_result"]["warnings"]


def test_grading_evidence_packet_blocks_when_active_rubric_is_missing(
    client: TestClient, tmp_path: Path
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path, create_rubric=False)

    packet_response = client.get(f"/answer-regions/{region['id']}/grading-evidence-packet")

    assert packet_response.status_code == 200
    packet = packet_response.json()
    assert packet["readiness_result"]["ready_for_grading"] is False
    assert "missing active rubric" in packet["readiness_result"]["blockers"]

    grade_response = client.post(f"/answer-regions/{region['id']}/grade")
    assert grade_response.status_code == 400
    assert "Evidence packet not ready for grading" in grade_response.text
    assert db_session_scalars_count(FinalGrade) == 0


def db_session_scalars_count(model: type[object]) -> int:
    db = SessionLocal()
    try:
        return len(db.scalars(select(model)).all())
    finally:
        db.close()


def test_batch_mock_grading_grades_ungraded_regions_only_and_skips_existing(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = create_assessment_with_answer_regions(client, tmp_path, region_count=3)
    assessment_id = data["assessment_id"]
    regions = data["regions"]
    assert isinstance(assessment_id, int)
    assert isinstance(regions, list)
    pregraded_region = regions[0]
    pregraded_response = client.post(f"/answer-regions/{pregraded_region['id']}/grade")
    assert pregraded_response.status_code == 201

    monkeypatch.setenv("BRAIN_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    response = client.post(f"/assessments/{assessment_id}/grade-all-mock")

    assert response.status_code == 201
    payload = response.json()
    assert payload["assessment_id"] == assessment_id
    assert payload["total_answer_regions"] == 3
    assert payload["graded_count"] == 2
    assert payload["skipped_count"] == 1
    assert payload["failed_count"] == 0
    assert len(payload["created_grade_suggestion_ids"]) == 2
    assert payload["errors"] == []
    assert "raw_response_json" not in str(payload)
    db_session.expire_all()
    suggestions = db_session.scalars(select(GradeSuggestion)).all()
    assert len(suggestions) == 3
    assert {suggestion.model_provider for suggestion in suggestions} == {"mock"}
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_grade_answer_region_failure_cases(client: TestClient, tmp_path: Path) -> None:
    missing_region = client.post("/answer-regions/999999/grade")
    assert missing_region.status_code == 404

    no_rubric_region = create_answer_region_with_optional_rubric(
        client, tmp_path, create_rubric=False
    )
    no_rubric = client.post(f"/answer-regions/{no_rubric_region['id']}/grade")
    assert no_rubric.status_code == 400
    assert "active rubric" in no_rubric.text


def test_batch_mock_grading_missing_assessment_returns_404(client: TestClient) -> None:
    response = client.post("/assessments/999999/grade-all-mock")

    assert response.status_code == 404


def test_grade_suggestion_and_job_read_endpoints(client: TestClient, tmp_path: Path) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    grade_response = client.post(f"/answer-regions/{region['id']}/grade")
    assert grade_response.status_code == 201
    created = grade_response.json()

    list_response = client.get(f"/answer-regions/{region['id']}/grade-suggestions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [created["suggestion"]["id"]]

    suggestion_response = client.get(f"/grade-suggestions/{created['suggestion']['id']}")
    assert suggestion_response.status_code == 200
    assert suggestion_response.json()["id"] == created["suggestion"]["id"]

    job_response = client.get(f"/grading-jobs/{created['job']['id']}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "succeeded"


def test_grade_answer_region_marks_job_failed_on_provider_error(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter:
        def grade_answer_region(self, **_: object) -> object:
            raise RuntimeError("provider failed with key sk-secret-value")

    class FailingBrainAdapterFactory:
        @classmethod
        def from_settings(cls, settings: object) -> FailingAdapter:
            return FailingAdapter()

    region = create_answer_region_with_optional_rubric(client, tmp_path)
    monkeypatch.setattr("app.services.grading_service.BrainAdapter", FailingBrainAdapterFactory)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 502
    assert "provider failed" in response.text
    assert "sk-secret-value" not in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert job.error is not None
    assert "sk-secret-value" not in job.error


def test_grade_answer_region_with_mocked_openai_image_input_creates_suggestion(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.brain.openai_provider import OpenAICompatibleProvider
    from tests.test_openai_provider import FakeOpenAIClient, valid_openai_payload

    requests: list[dict[str, object]] = []

    class CapturingClient(FakeOpenAIClient):
        def post(self, url: str, **kwargs: object):
            response = super().post(url, **kwargs)
            requests.extend(self.requests)
            return response

    def provider_factory(**kwargs: object) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            **kwargs,
            client=CapturingClient(valid_openai_payload()),
        )

    monkeypatch.setenv("BRAIN_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_IMAGE_INPUT_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("packages.brain.adapter.OpenAICompatibleProvider", provider_factory)
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 201
    suggestion = response.json()["suggestion"]
    assert suggestion["model_provider"] == "openai"
    raw = suggestion["raw_response_json"]
    assert "image_input_used" in raw["review_flags"]
    assert "data:image" not in str(raw)
    assert requests
    assert "data:image/png;base64," in str(requests[0]["json"])
    db_session.expire_all()
    stored = db_session.scalars(select(GradeSuggestion)).one()
    assert "data:image" not in str(stored.raw_response_json)


def test_grade_answer_region_missing_image_fails_before_provider_call(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAIN_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OPENAI_IMAGE_INPUT_ENABLED", "true")
    get_settings.cache_clear()
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    answer_region = db_session.get(AnswerRegion, region["id"])
    assert answer_region is not None
    Path(tmp_path / "storage" / answer_region.image_path).unlink()

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 400
    assert "image is missing" in response.text
    db_session.expire_all()
    assert db_session_scalars_count(GradingJob) == 0


def codex_api_output() -> GradeSuggestionOutput:
    return GradeSuggestionOutput(
        score=Decimal("3.00"),
        max_score=Decimal("5.00"),
        confidence=Decimal("0.25"),
        needs_review=True,
        rubric_breakdown=[
            RubricBreakdownItem(
                criterion_id="concept",
                criterion="Core concept",
                max_marks=Decimal("3.00"),
                awarded_marks=Decimal("2.00"),
                reason="Partial conceptual match in text-only context.",
                evidence=None,
                confidence=Decimal("0.25"),
            ),
            RubricBreakdownItem(
                criterion_id="clarity",
                criterion="Clarity",
                max_marks=Decimal("2.00"),
                awarded_marks=Decimal("1.00"),
                reason="Limited clarity in text-only context.",
                evidence=None,
                confidence=Decimal("0.25"),
            ),
        ],
        detected_answer_summary="Codex CLI mocked text-only suggestion.",
        major_errors=["Needs teacher review"],
        feedback_to_student="Add clearer explanation.",
        review_flags=[
            "teacher_review_required",
            "codex_cli_provider",
            "image_input_disabled",
        ],
        model_provider="codex_cli",
        model_name="codex-cli",
        prompt_version="codex_cli_grading_v1",
        cost_estimate=Decimal("0"),
    )


def test_codex_dev_route_requires_authenticated_owner(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = create_owned_answer_region(client, tmp_path, "codex-owner@example.com")
    intruder = register_auth_teacher(client, "codex-intruder@example.com")
    monkeypatch.setenv("CODEX_BROWSER_GRADING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        unauthenticated = client.post(f"/answer-regions/{owner['region']['id']}/grade-codex-dev")
        non_owner = client.post(
            f"/answer-regions/{owner['region']['id']}/grade-codex-dev",
            headers=auth_header(str(intruder["access_token"])),
        )
    finally:
        get_settings.cache_clear()

    assert unauthenticated.status_code == 401
    assert non_owner.status_code == 404


def test_unwritable_grading_context_blocks_before_provider_call(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("chmod-based unwritable-directory check cannot block the root user")
    class FakeCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"
        calls = 0

        def __init__(self, **kwargs: object) -> None:
            pass

        def grade(self, **kwargs: object) -> GradeSuggestionOutput:
            FakeCodexCliProvider.calls += 1
            return codex_api_output()

    monkeypatch.setenv("BRAIN_PROVIDER", "codex_cli")
    get_settings.cache_clear()
    monkeypatch.setattr("packages.brain.adapter.CodexCliProvider", FakeCodexCliProvider)
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    grading_context_root = tmp_path / "storage" / "artifacts" / "grading_context"
    grading_context_root.mkdir(parents=True, exist_ok=True)
    grading_context_root.chmod(0o500)
    try:
        response = client.post(f"/answer-regions/{region['id']}/grade")
    finally:
        grading_context_root.chmod(0o700)

    assert response.status_code == 400
    assert "Grading context preparation failed before provider call" in response.text
    assert FakeCodexCliProvider.calls == 0
    db_session.expire_all()
    assert db_session.scalars(select(GradingJob)).all() == []
    assert db_session.scalars(select(GradeSuggestion)).all() == []
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_grade_answer_region_with_codex_cli_mocked_subprocess_creates_suggestion(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def grade(self, **kwargs: object) -> GradeSuggestionOutput:
            assert kwargs["image_data_url"] is None
            assert kwargs["answer_image_path"]
            return codex_api_output()

    monkeypatch.setenv("BRAIN_PROVIDER", "codex_cli")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("packages.brain.adapter.CodexCliProvider", FakeCodexCliProvider)
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 201
    payload = response.json()
    assert payload["job"]["status"] == "succeeded"
    suggestion = payload["suggestion"]
    assert suggestion["model_provider"] == "codex_cli"
    assert suggestion["model_name"] == "codex-cli"
    assert suggestion["needs_review"] is True
    assert suggestion["raw_response_json"]["prompt_version"] == "codex_cli_grading_v1"
    db_session.expire_all()
    stored = db_session.scalars(select(GradeSuggestion)).one()
    assert stored.model_provider == "codex_cli"


def test_grade_answer_region_codex_cli_subprocess_failure_marks_job_failed(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"

        def __init__(self, **kwargs: object) -> None:
            pass

        def grade(self, **kwargs: object) -> GradeSuggestionOutput:
            raise RuntimeError("Codex CLI exited with status 2: failed with sk-secret-value")

    monkeypatch.setenv("BRAIN_PROVIDER", "codex_cli")
    get_settings.cache_clear()
    monkeypatch.setattr("packages.brain.adapter.CodexCliProvider", FailingCodexCliProvider)
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 502
    assert "Codex CLI exited with status 2" in response.text
    assert "sk-secret-value" not in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert job.error is not None
    assert "sk-secret-value" not in job.error


def test_grade_answer_region_codex_cli_image_enabled_unsupported_marks_job_failed(
    client: TestClient,
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ImageUnsupportedCodexCliProvider:
        provider_name = "codex_cli"
        model_name = "codex-cli"

        def __init__(self, **kwargs: object) -> None:
            pass

        def grade(self, **kwargs: object) -> GradeSuggestionOutput:
            raise RuntimeError("Codex CLI image input is not supported by this installed version.")

    monkeypatch.setenv("BRAIN_PROVIDER", "codex_cli")
    monkeypatch.setenv("CODEX_CLI_IMAGE_INPUT_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("packages.brain.adapter.CodexCliProvider", ImageUnsupportedCodexCliProvider)
    region = create_answer_region_with_optional_rubric(client, tmp_path)

    response = client.post(f"/answer-regions/{region['id']}/grade")

    assert response.status_code == 502
    assert "image input is not supported" in response.text
    db_session.expire_all()
    job = db_session.scalars(select(GradingJob)).one()
    assert job.status == "failed"
    assert job.error is not None
    assert "image input is not supported" in job.error


def test_evidence_packet_blocks_possible_continuation_near_page_bottom(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    answer_region = db_session.get(AnswerRegion, region["id"])
    assert answer_region is not None
    answer_region.y = Decimal("62.00")
    answer_region.height = Decimal("18.00")
    db_session.add(
        SubmissionPage(
            submission_id=answer_region.submission_id,
            page_no=2,
            image_path=answer_region.page.image_path,
        )
    )
    db_session.commit()

    packet_response = client.get(f"/answer-regions/{region['id']}/grading-evidence-packet")

    assert packet_response.status_code == 200
    packet = packet_response.json()
    student_evidence = packet["student_answer_evidence"]
    assert student_evidence["segment_count"] == 1
    assert student_evidence["pages_covered"] == [1]
    assert student_evidence["continuation_check_status"] == "possible_continuation"
    assert student_evidence["next_page_context_available"] is True
    assert student_evidence["teacher_founder_confirmed_full_answer"] is False
    assert "possible answer continuation not confirmed" in packet["readiness_result"]["blockers"]
    assert packet["readiness_result"]["ready_for_grading"] is False

    grade_response = client.post(f"/answer-regions/{region['id']}/grade")
    assert grade_response.status_code == 400
    assert "possible answer continuation not confirmed" in grade_response.text
    db_session.expire_all()
    assert db_session.scalars(select(GradingJob)).all() == []
    assert db_session.scalars(select(GradeSuggestion)).all() == []
    assert db_session.scalars(select(FinalGrade)).all() == []


def test_full_answer_confirmation_clears_continuation_blocker(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    region = create_answer_region_with_optional_rubric(client, tmp_path)
    answer_region = db_session.get(AnswerRegion, region["id"])
    assert answer_region is not None
    answer_region.y = Decimal("62.00")
    answer_region.height = Decimal("18.00")
    db_session.commit()

    confirm_response = client.patch(
        f"/answer-regions/{region['id']}/full-answer-confirmation",
        json={"full_answer_confirmed": True},
    )
    assert confirm_response.status_code == 200

    packet = client.get(f"/answer-regions/{region['id']}/grading-evidence-packet").json()
    assert (
        packet["student_answer_evidence"]["continuation_check_status"]
        == "continuation_confirmed_not_needed"
    )
    assert (
        "possible answer continuation not confirmed" not in packet["readiness_result"]["blockers"]
    )
    assert packet["readiness_result"]["ready_for_grading"] is True


def test_multisegment_grading_uses_composite_context_with_all_segments(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    from app.services.grading_service import GradingService

    region_payload = create_answer_region_with_optional_rubric(client, tmp_path)
    region = db_session.get(AnswerRegion, region_payload["id"])
    assert region is not None
    segment_response = client.post(
        f"/answer-regions/{region.id}/segments",
        json={
            "page_id": region.page_id,
            "x": 30,
            "y": 30,
            "width": 20,
            "height": 20,
            "order_index": 2,
            "source": "manual",
            "confirmed": True,
        },
    )
    assert segment_response.status_code == 201
    confirm_response = client.patch(
        f"/answer-regions/{region.id}/full-answer-confirmation",
        json={"full_answer_confirmed": True},
    )
    assert confirm_response.status_code == 200

    class RecordingAdapter:
        provider = type("Provider", (), {"provider_name": "mock"})()

        def __init__(self) -> None:
            self.answer_image_path: str | None = None

        def grade_answer_region(self, **kwargs: object) -> GradeSuggestionOutput:
            self.answer_image_path = str(kwargs["answer_image_path"])
            return GradeSuggestionOutput(
                model_provider="mock",
                model_name="mock-grader-v1",
                prompt_version="mock-grading-v1",
                score=Decimal("0.00"),
                max_score=Decimal("5.00"),
                confidence=Decimal("0.00"),
                feedback_to_student="mock",
                detected_answer_summary="mock summary",
                major_errors=[],
                rubric_breakdown=[
                    RubricBreakdownItem(
                        criterion_id="concept",
                        criterion="Core concept",
                        max_marks=Decimal("5.00"),
                        awarded_marks=Decimal("0.00"),
                        reason="mock",
                        confidence=Decimal("0.00"),
                    )
                ],
                needs_review=True,
                review_flags=["mock_provider", "teacher_review_required"],
            )

    service = GradingService(db_session, use_configured_adapter=False)
    recording_adapter = RecordingAdapter()
    service.adapter = recording_adapter  # type: ignore[assignment]

    service.grade_answer_region(region.id)

    assert recording_adapter.answer_image_path is not None
    assert "grading_context" in recording_adapter.answer_image_path
    composite_path = service.storage.resolve_relative(recording_adapter.answer_image_path)
    with Image.open(composite_path) as composite:
        assert composite.width >= 20
        assert composite.height > 40
    suggestion = db_session.scalars(select(GradeSuggestion)).one()
    raw = suggestion.raw_response_json
    assert "multi_segment_context" in raw["review_flags"]
    assert raw["grading_context"]["segment_count"] == 2
    assert len(raw["grading_context"]["segments"]) == 2


def test_prompt_construction_includes_manual_student_answer_text() -> None:
    from packages.brain.prompt_registry import build_grading_prompt

    messages = build_grading_prompt(
        question_text="What is the capital of Bangladesh?",
        rubric_json={
            "model_answer": "Dhaka is the capital of Bangladesh.",
            "criteria": [{"id": "capital", "max_marks": "6"}],
        },
        answer_image_path="artifacts/answer_regions/example.png",
        image_input_enabled=False,
        student_answer_text="Dhaka is the capital of Bangladesh.",
    )
    rendered = "\n".join(message["content"] for message in messages)
    assert "What is the capital of Bangladesh?" in rendered
    assert "Dhaka is the capital of Bangladesh." in rendered
    assert "Teacher-confirmed student answer text" in rendered
    assert "artifacts/answer_regions/example.png" in rendered


def test_prompt_construction_includes_dependent_rubric_instruction() -> None:
    from packages.brain.prompt_registry import build_grading_prompt

    messages = build_grading_prompt(
        question_text="What is the capital of Bangladesh? Give one identifying phrase.",
        rubric_json={
            "model_answer": (
                "Dhaka is the capital of Bangladesh. It is the country's main "
                "administrative and political centre."
            ),
            "criteria": [
                {"id": "capital", "name": "Capital identified correctly", "max_marks": "6"},
                {"id": "phrase", "name": "Valid identifying phrase", "max_marks": "4"},
            ],
        },
        answer_image_path="artifacts/answer_regions/example.png",
        image_input_enabled=False,
        student_answer_text="Chittagong is the capital of Bangladesh. It is a major port city.",
    )
    rendered = "\n".join(message["content"] for message in messages)
    assert "Evaluate rubric criteria in context, not as isolated keyword checks" in rendered
    assert (
        "Do not award marks for a dependent criterion when its prerequisite claim is incorrect"
        in rendered
    )
    assert (
        "Phrase, detail, justification, or identifying-description marks must refer to the"
        in rendered
    )
    assert "correct entity or answer required by the question and model answer" in rendered
    assert "do not award that detail" in rendered
    assert "the phrase must identify or describe Dhaka" in rendered


def test_codex_prompt_includes_manual_student_answer_text() -> None:
    from packages.brain.codex_cli_provider import CodexCliProvider

    provider = CodexCliProvider(command="codex", model_name="gpt-5.5")
    prompt = provider._build_prompt(  # noqa: SLF001
        question_text="What is the capital of Bangladesh?",
        question_total_marks=Decimal("10.00"),
        rubric_json={
            "model_answer": "Dhaka is the capital of Bangladesh.",
            "criteria": [{"id": "capital", "max_marks": "6"}],
        },
        messages=[],
        image_input_enabled=False,
        student_answer_text="Chittagong is the capital of Bangladesh.",
    )
    assert "What is the capital of Bangladesh?" in prompt
    assert "Dhaka is the capital of Bangladesh." in prompt
    assert "Teacher-confirmed student answer text" in prompt
    assert "Chittagong is the capital of Bangladesh." in prompt
