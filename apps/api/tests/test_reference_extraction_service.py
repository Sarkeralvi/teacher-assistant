from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import SessionLocal
from app.models import (
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingRun,
    Question,
    QuestionNode,
    Rubric,
    RubricExtractionCriterion,
    User,
)
from app.services.local_model_lease_service import LocalModelLeaseService
from app.services.reference_extraction_service import (
    ReferenceExtractionError,
    ReferenceExtractionService,
)


class FakePaddleBlock:
    def __init__(self, text: str) -> None:
        self.page = 1
        self.order = 1
        self.label = "text"
        self.text = text
        self.bbox = [10.0, 10.0, 200.0, 80.0]

    def model_dump(self, **_kwargs):
        return {
            "page": self.page,
            "order": self.order,
            "label": self.label,
            "text": self.text,
            "bbox": self.bbox,
        }


class FakePaddleClient:
    def __init__(self) -> None:
        self.calls = 0

    def health(self):
        return {"status": "ready"}

    def ocr_image(self, **kwargs):
        self.calls += 1
        text = f"OCR {kwargs['request_id']}"
        return SimpleNamespace(
            normalized_text=text,
            markdown=text,
            blocks=[FakePaddleBlock(text)],
            warnings=[],
            version="3.7.0",
            latency_ms=10,
        )


class FakeTextProvider:
    def __init__(self) -> None:
        self.calls = 0

    def extract_reference_bundle_from_images(self, *, documents):
        self.calls += 1
        assert set(documents) == {"QUESTION", "SOLUTION", "RUBRIC"}
        return FakeExtractor().extract_reference_bundle(documents)

    def extract_reference_bundle_from_ocr_documents(self, *, documents):
        assert set(documents) == {"question_paper", "solution", "rubric"}
        return FakeExtractor().extract_reference_bundle(
            {"QUESTION": [], "SOLUTION": [], "RUBRIC": []}
        )


@pytest.fixture(autouse=True)
def fake_local_hybrid_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.reference_extraction_service as module

    paddle = FakePaddleClient()
    monkeypatch.setattr(
        module.LocalOcrClient,
        "from_settings",
        classmethod(lambda cls, settings=None: paddle),
    )
    adapter = SimpleNamespace(provider=FakeTextProvider(), verify_available_model=lambda: None)
    monkeypatch.setattr(
        module.BrainAdapter,
        "for_provider",
        classmethod(lambda cls, settings, provider: adapter),
    )


class FakePhaseManager:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def switch(self, phase: str, *, lease_holder_id: str) -> None:
        assert lease_holder_id
        self.phases.append(phase)


class FakeExtractor:
    def __init__(self) -> None:
        self.qwen_calls = 0
        self.qwen_adapter = FakeReferenceAdapter()

    def render_pages(self, file_path: Path, _content_type: str, **_kwargs):
        # **_kwargs absorbs target_dpi, which the tiered path passes.
        return [(1, f"rendered {file_path.stem}".encode(), "image/png")]

    def extract_reference_bundle(self, documents):
        self.qwen_calls += 1
        assert set(documents) == {"QUESTION", "SOLUTION", "RUBRIC"}
        return {
            "questions": [
                {
                    "question_number": "1(a)",
                    "parent_question_number": "1",
                    "node_type": "subquestion",
                    "question_text": "Calculate the probability.",
                    "model_answer": "Private worked answer from the solution.",
                    "marks": "5.00",
                    "source_question_pages": [1],
                    "source_solution_pages": [1],
                    "source_text_excerpt": "Calculate the probability.",
                    "confidence": "0.90",
                    "criteria": [
                        {
                            "criterion_label": "Method",
                            "description": "Uses the correct probability method.",
                            "max_marks": "3.00",
                            "confidence": "0.90",
                            "source_rubric_pages": [1],
                            "blocker": None,
                        },
                        {
                            "criterion_label": "Answer",
                            "description": "Obtains the correct answer.",
                            "max_marks": "2.00",
                            "confidence": "0.90",
                            "source_rubric_pages": [1],
                            "blocker": None,
                        },
                    ],
                    "blockers": [],
                    "needs_review": True,
                }
            ],
            "warnings": [],
            "usage": {"total_tokens": 100},
        }


class FakeReferenceAdapter:
    def verify_available_model(self) -> None:
        return None


@pytest.fixture()
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    cleanup = (
        AuditLog,
        FinalGrade,
        GradeSuggestion,
        Rubric,
        Question,
        RubricExtractionCriterion,
        QuestionNode,
        GradingRun,
        ExtractionRun,
        Assessment,
        Course,
        User,
    )
    try:
        for model in cleanup:
            db.execute(delete(model))
        db.commit()
        yield db
    finally:
        for model in cleanup:
            db.execute(delete(model))
        db.commit()
        db.close()


def seed_run(db: Session, storage_root: Path) -> GradingRun:
    teacher = User(
        name="Teacher",
        email="reference-service@example.test",
        password_hash="not-used",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code="MATH", title="Math")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Assessment",
        assessment_type="exam",
        total_marks="5.00",
        status="draft",
    )
    db.add(assessment)
    db.flush()
    material_dir = storage_root / "uploads" / "grading_runs" / "1"
    material_dir.mkdir(parents=True)
    paths = {}
    for name in ("question", "solution", "rubric"):
        path = material_dir / f"{name}.pdf"
        path.write_bytes(f"%PDF-1.4 {name}".encode())
        paths[name] = path.relative_to(storage_root).as_posix()
    run = GradingRun(
        assessment_id=assessment.id,
        created_by_teacher_id=teacher.id,
        mode="custom_controlled",
        status="materials_uploaded",
        marking_policy="general",
        question_pdf_path=paths["question"],
        solution_pdf_path=paths["solution"],
        rubric_pdf_path=paths["rubric"],
        question_pdf_name="question.pdf",
        solution_pdf_name="solution.pdf",
        rubric_pdf_name="rubric.pdf",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def enabled_settings(storage_root: Path) -> Settings:
    return Settings(
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        LOCAL_QWEN38_ENABLED=True,
        LOCAL_QWEN38_API_KEY="key-local-test",
        LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=True,
        LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
        LOCAL_AI_PHASE_SWITCH_ENABLED=True,
        LOCAL_STORAGE_ROOT=str(storage_root),
        UPLOADS_DIR=str(storage_root / "uploads"),
        ARTIFACTS_DIR=str(storage_root / "artifacts"),
    )


def test_reference_bundle_runs_with_qwen38_vision_only(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    extractor = FakeExtractor()
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=phases,
        extractor_factory=lambda: extractor,
    )

    queued = service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )
    assert queued["status"] == "queued"
    service.run(run.id)

    db_session.expire_all()
    run = db_session.get(GradingRun, run.id)
    assert run is not None
    assert run.reference_extraction_status == "succeeded"
    assert run.reference_ocr_call_count == 3
    assert run.reference_qwen_call_count == 1
    assert phases.phases == ["Qwen38"]


def test_reference_bundle_fails_before_switching_or_calling_when_model_slot_is_busy(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    extractor = FakeExtractor()
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=phases,
        extractor_factory=lambda: extractor,
    )
    service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )
    lease = LocalModelLeaseService(db_session)
    lease.acquire(
        model_phase="Qwen38",
        holder_kind="other_operation",
        holder_id="already-running",
    )
    try:
        service.run(run.id)

        db_session.expire_all()
        refreshed = db_session.get(GradingRun, run.id)
        assert refreshed is not None
        assert refreshed.reference_extraction_status == "failed"
        assert "held by" in (refreshed.reference_extraction_error or "")
        assert extractor.qwen_calls == 0
        assert phases.phases == []
        assert lease.read().holder_id == "already-running"
    finally:
        lease.release(holder_id="already-running")


def test_reference_bundle_detects_material_tampering_before_any_model_call(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    extractor = FakeExtractor()
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=phases,
        extractor_factory=lambda: extractor,
    )
    service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )
    (storage_root / run.question_pdf_path).write_bytes(b"changed")

    service.run(run.id)

    db_session.expire_all()
    run = db_session.get(GradingRun, run.id)
    assert run is not None
    assert run.reference_extraction_status == "failed"
    assert "changed after teacher authorization" in (run.reference_extraction_error or "")
    assert run.reference_ocr_call_count == 0
    assert run.reference_qwen_call_count == 0
    assert phases.phases == []
    assert extractor.qwen_calls == 0


def test_qwen38_schema_failure_records_the_provider_attempt(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.reference_extraction_service as module

    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=FakePhaseManager(),
        extractor_factory=FakeExtractor,
    )
    service.create(
        run,
        teacher_id=run.created_by_teacher_id,
        expected_model="qwen3.8-27b-q4km",
    )

    def fail_after_provider_attempt(*, documents):
        assert set(documents) == {"QUESTION", "SOLUTION", "RUBRIC"}
        raise ValueError("response schema mismatch")

    provider = SimpleNamespace(extract_reference_bundle_from_images=fail_after_provider_attempt)
    adapter = SimpleNamespace(provider=provider, verify_available_model=lambda: None)
    monkeypatch.setattr(
        module.BrainAdapter,
        "for_provider",
        classmethod(lambda cls, settings, provider_name: adapter),
    )

    service.run(run.id)

    db_session.expire_all()
    refreshed = db_session.get(GradingRun, run.id)
    assert refreshed is not None
    assert refreshed.reference_extraction_status == "failed"
    assert refreshed.reference_qwen_call_count == 1
    assert "schema mismatch" in (refreshed.reference_extraction_error or "")


def test_reference_bundle_kill_switch_and_model_alias_are_enforced(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    settings = enabled_settings(storage_root)
    settings.local_reference_extraction_enabled = False
    service = ReferenceExtractionService(
        db_session,
        settings=settings,
        phase_manager=FakePhaseManager(),
        extractor_factory=FakeExtractor,
    )

    with pytest.raises(ReferenceExtractionError, match="disabled"):
        service.create(
            run,
            teacher_id=run.created_by_teacher_id,
            expected_model="qwen3.8-27b-q4km",
        )

    settings.local_reference_extraction_enabled = True
    with pytest.raises(ReferenceExtractionError, match="model alias"):
        service.create(
            run,
            teacher_id=run.created_by_teacher_id,
            expected_model="wrong-model",
        )


def test_exceeding_the_visual_page_budget_is_a_hard_failure(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    settings = enabled_settings(storage_root)
    settings.local_reference_max_ocr_calls = 1
    phases = FakePhaseManager()
    service = ReferenceExtractionService(
        db_session,
        settings=settings,
        phase_manager=phases,
        extractor_factory=lambda: FakeExtractor(),
    )
    service.create(
        run, teacher_id=run.created_by_teacher_id, expected_model="qwen3.8-27b-q4km"
    )
    service.run(run.id)
    db_session.expire_all()
    refreshed = db_session.get(GradingRun, run.id)
    assert refreshed is not None
    assert refreshed.reference_extraction_status == "failed"
    assert refreshed.reference_qwen_call_count == 0
    assert phases.phases == []


def test_teacher_is_told_qwen38_visual_draft_needs_confirmation(
    db_session: Session, tmp_path: Path
) -> None:
    storage_root = tmp_path / "storage"
    run = seed_run(db_session, storage_root)
    service = ReferenceExtractionService(
        db_session,
        settings=enabled_settings(storage_root),
        phase_manager=FakePhaseManager(),
        extractor_factory=lambda: FakeExtractor(),
    )
    service.create(
        run, teacher_id=run.created_by_teacher_id, expected_model="qwen3.8-27b-q4km"
    )
    service.run(run.id)
    db_session.expire_all()
    refreshed = db_session.get(GradingRun, run.id)
    assert refreshed is not None
    warnings = " ".join(refreshed.reference_extraction_warnings or [])
    assert "Qwen3.8 vision" in warnings
    assert "thinking disabled" in warnings
    assert "teacher confirmation" in warnings
