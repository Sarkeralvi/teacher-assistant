from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import GradingRun
from packages.brain.adapter import (
    BrainAdapter,
    BrainProviderConfigurationError,
    registered_brain_profiles,
)
from packages.brain.capabilities import BRAIN_CAPABILITY_METHODS, BrainCapability
from packages.brain.policy import brain_policy_for_profile
from packages.brain.profiles import BUILTIN_BRAIN_PROFILES
from packages.brain.provider_base import BrainProvider
from tests.test_grading_runs_api import (
    CLEANUP_MODELS,
    create_assessment_for_teacher,
    register_teacher,
)

CAPABILITY_CONTRACT_EXERCISES = {
    BrainCapability.GRADING: "grade_answer_region",
    BrainCapability.QUESTION_PDF_EXTRACTION: "extract_questions_from_document",
    BrainCapability.RUBRIC_PDF_EXTRACTION: "extract_rubric_from_document",
    BrainCapability.OCR_REFERENCE_EXTRACTION: (
        "extract_reference_bundle_from_ocr_documents"
    ),
    BrainCapability.OCR_ANSWER_MAPPING: "map_submission_answers_from_ocr_pages",
    BrainCapability.OCR_ANSWER_PREPARATION: (
        "prepare_student_answers_from_ocr_candidates"
    ),
    BrainCapability.VISUAL_REFERENCE_EXTRACTION: (
        "extract_reference_bundle_from_images"
    ),
    BrainCapability.VISUAL_MAPPING: "map_page_answer_regions",
    BrainCapability.VISUAL_PAGE_READ: "read_page",
    BrainCapability.VISUAL_TRANSCRIPTION: "transcribe_images",
    BrainCapability.TRANSCRIPTION_REPAIR: "repair_transcription_images",
}


@pytest.fixture()
def harness_db() -> Iterator[Session]:
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
def harness_client(
    harness_db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    del harness_db
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    get_settings.cache_clear()
    try:
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def test_every_registered_profile_capability_has_a_concrete_adapter_contract() -> None:
    settings = Settings(BRAIN_IMAGE_INPUT_ENABLED=True)
    definitions = {definition.profile_id: definition for definition in BUILTIN_BRAIN_PROFILES}

    assert set(registered_brain_profiles()) == set(definitions)
    for profile_id, definition in definitions.items():
        configuration = definition.resolve(settings)
        for capability in configuration.capabilities:
            assert capability in CAPABILITY_CONTRACT_EXERCISES, (
                f"Profile {profile_id} advertises {capability.value} without a "
                "verification-harness contract exercise"
            )
            adapter_method = CAPABILITY_CONTRACT_EXERCISES[capability]
            assert callable(getattr(BrainAdapter, adapter_method, None))
            method_name = BRAIN_CAPABILITY_METHODS[capability]
            provider_method = getattr(definition.provider_constructor, method_name, None)
            canonical_method = getattr(BrainProvider, method_name, None)
            assert callable(provider_method)
            assert provider_method is not canonical_method


def test_mock_profile_web_action_reaches_policy_adapter_and_persistence(
    harness_client: TestClient,
    harness_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = BrainAdapter.for_profile.__func__

    def recording_for_profile(
        cls: type[BrainAdapter], settings: Settings, profile_id: str
    ) -> BrainAdapter:
        calls.append(profile_id)
        return original(cls, settings, profile_id)

    monkeypatch.setattr(BrainAdapter, "for_profile", classmethod(recording_for_profile))
    teacher, token = register_teacher(harness_client, email_prefix="brain-harness")
    assessment = create_assessment_for_teacher(
        harness_client,
        int(teacher["id"]),
        token,
    )
    headers = {"Authorization": f"Bearer {token}"}
    grading_run = harness_client.post(
        f"/assessments/{assessment['id']}/grading-runs/custom",
        headers=headers,
    ).json()

    response = harness_client.put(
        f"/grading-runs/{grading_run['id']}/brain-profile",
        headers=headers,
        json={
            "profile_id": "mock",
            "required_capability": "grading",
            "provider_data_boundary_confirmed": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["brain_profile_id"] == "mock"
    assert calls == ["mock"]
    harness_db.expire_all()
    stored = harness_db.get(GradingRun, int(grading_run["id"]))
    assert stored is not None
    assert stored.brain_profile_id == "mock"


def test_disabled_local_profile_fails_construction_without_a_provider_call() -> None:
    settings = Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN38_ENABLED=False,
    )

    with pytest.raises(
        BrainProviderConfigurationError,
        match="LOCAL_QWEN38_ENABLED must be true",
    ):
        BrainAdapter.for_profile(settings, "llama_cpp_qwen38")


def test_cloud_profile_without_consent_is_refused_before_selection() -> None:
    settings = Settings(BRAIN_ALLOW_REAL_PROVIDERS=True)
    policy = brain_policy_for_profile(settings, "codex_cli")

    with pytest.raises(
        BrainProviderConfigurationError,
        match="Cloud provider data transfer must be explicitly confirmed",
    ):
        policy.validate_profile_request(
            profile_id="codex_cli",
            capability=BrainCapability.GRADING,
            provider_data_boundary_confirmed=False,
        )
