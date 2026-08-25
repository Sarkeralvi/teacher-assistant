"""The staged tiered script pipeline, with fake models and a real database.

Asserts the properties that make the design worth having, none of which a
single happy-path test would catch:

* the vision model is not called when tier-1 read every page;
* each model is loaded at most once, because interleaving costs a 60-90 s reload;
* the two mappers never both claim one answer;
* an unmapped finalized question becomes a visible blocker, never a silent drop;
* exceeding the authorized vision budget stops the run instead of reading less.

No real model, no engine installed, no provider call.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    LocalModelLease,
    Question,
    QuestionNode,
    Rubric,
    Submission,
    SubmissionPage,
    User,
)
from app.services.local_ocr_client import LocalOcrResult
from app.services.local_script_preparation import (
    LocalScriptPreparationError,
    LocalScriptPreparationService,
)
from app.services.storage import LocalStorage
from packages.brain.schemas_qwen38 import VisualPageMappingOutput, VisualPageRegion
from packages.ocr.types import BoundingBox, OcrLine, OcrPageReading

CLEANUP_MODELS = (
    AuditLog,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    AnswerRegionMapping,
    AnswerRegionSegment,
    AnswerRegion,
    SubmissionPage,
    Submission,
    Rubric,
    QuestionNode,
    Question,
    ExtractionRun,
    Assessment,
    Course,
    LocalModelLease,
    User,
)

LABELS = ("1(a)(i)", "1(a)(ii)")


@pytest.fixture()
def db_session() -> Iterator[Session]:
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


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeEngine:
    def __init__(self, readings: list[OcrPageReading]) -> None:
        self._readings = list(readings)
        self.call_count = 0

    def read_page(self, image_bytes: bytes, **_kwargs: Any) -> OcrPageReading:
        del image_bytes
        self.call_count += 1
        return self._readings.pop(0)


@dataclass
class SwitchLog:
    phases: list[str]


class FakePhaseManager:
    def __init__(self, log: SwitchLog) -> None:
        self.log = log

    def switch(self, phase: str, *, lease_holder_id: str | None = None) -> None:
        del lease_holder_id
        self.log.phases.append(phase)


class FakeTextProvider:
    provider_name = "llama_cpp_qwen"

    def __init__(self, mappings: list[dict[str, Any]]) -> None:
        self._mappings = mappings
        self.calls: list[dict[str, Any]] = []

    def map_submission_answers_from_ocr_pages(
        self, *, pages: list[dict[str, Any]], questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"pages": pages, "questions": questions})
        return {"mappings": self._mappings}


class SequencedFakeTextProvider(FakeTextProvider):
    def __init__(self, mapping_passes: list[list[dict[str, Any]]]) -> None:
        super().__init__([])
        self._mapping_passes = list(mapping_passes)

    def map_submission_answers_from_ocr_pages(
        self, *, pages: list[dict[str, Any]], questions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.calls.append({"pages": pages, "questions": questions})
        return {"mappings": self._mapping_passes.pop(0)}


class FakeVisionProvider:
    provider_name = "llama_cpp_qwen38"

    def __init__(self, regions_per_call: list[list[VisualPageRegion]]) -> None:
        self._regions = list(regions_per_call)
        self.calls = 0

    def map_page_answer_regions(self, **_kwargs: Any) -> VisualPageMappingOutput:
        self.calls += 1
        return VisualPageMappingOutput(regions=self._regions.pop(0), needs_review=True)


class FakePaddleClient:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self._pages = list(pages)
        self.calls = 0
        self.health_calls = 0

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        return {"status": "ready"}

    def ocr_image(self, **kwargs: Any) -> LocalOcrResult:
        self.calls += 1
        blocks = self._pages.pop(0)
        text = "\n".join(block["text"] for block in blocks)
        return LocalOcrResult.model_validate(
            {
                "request_id": kwargs["request_id"],
                "mode": kwargs["mode"],
                "text": text,
                "normalized_text": text,
                "markdown": text,
                "blocks": [
                    {
                        "page": 1,
                        "order": block["order"],
                        "label": "text",
                        "text": block["text"],
                        "bbox": block["bbox"],
                    }
                    for block in blocks
                ],
                "warnings": [],
                "provider": "local_paddle_qwen",
                "model": "PaddleOCR-VL-1.6",
                "layout_model": "PP-DocLayoutV3",
                "version": "3.7.0",
                "device": "gpu:0",
                "latency_ms": 10,
            }
        )


class FakeAdapter:
    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.verified = 0

    def verify_available_model(self) -> None:
        self.verified += 1


# ── Fixture construction ───────────────────────────────────────────────────


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalStorage]:
    """The real LocalStorage under tmp_path.

    Not a fake: cropping a confirmed answer region writes a real PNG through
    ``answer_region_image_path``, and a stub that skips that step would not
    exercise the geometry these tests exist to check.
    """
    root = tmp_path / "storage"
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(root))
    monkeypatch.setenv("UPLOADS_DIR", str(root / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(root / "artifacts"))
    get_settings.cache_clear()
    try:
        yield LocalStorage()
    finally:
        get_settings.cache_clear()


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    root = tmp_path / "storage"
    values: dict[str, Any] = {
        "BRAIN_ALLOW_REAL_PROVIDERS": True,
        "LOCAL_OCR_ENABLED": True,
        "LOCAL_PADDLE_OCR_ENABLED": True,
        "LOCAL_PADDLE_OCR_MODEL": "PaddleOCR-VL-1.6",
        "LOCAL_PADDLE_OCR_LAYOUT_MODEL": "PP-DocLayoutV3",
        "LOCAL_SCRIPT_PREPARATION_ENABLED": True,
        "LOCAL_QWEN_ENABLED": True,
        "LOCAL_QWEN_MODEL": "qwen3.6-35b-a3b-q4km",
        "LOCAL_QWEN38_ENABLED": True,
        "LOCAL_QWEN38_MODEL": "qwen3.8-27b-q4km",
        "LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED": True,
        "LOCAL_AI_PHASE_SWITCH_ENABLED": True,
        "LOCAL_STORAGE_ROOT": str(root),
        "UPLOADS_DIR": str(root / "uploads"),
        "ARTIFACTS_DIR": str(root / "artifacts"),
    }
    values.update(overrides)
    return Settings(**values)


def _seed(db: Session, tmp_path: Path, page_count: int = 2) -> tuple[Submission, User]:
    suffix = uuid4().hex[:8]
    teacher = User(
        name="Teacher",
        email=f"tiered-{suffix}@example.com",
        password_hash="x",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(code=f"TIER-{suffix}", title="Tiered", teacher_id=teacher.id)
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Exam",
        assessment_type="exam",
        total_marks=Decimal("10.00"),
    )
    db.add(assessment)
    db.flush()
    # question_nodes.extraction_run_id is NOT NULL: a confirmed node always
    # traces back to the run that extracted it.
    extraction_run = ExtractionRun(
        assessment_id=assessment.id,
        artifact_file_path="references/question.pdf",
        original_filename="question.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="llama_cpp_qwen38",
        status="succeeded",
        blockers=[],
    )
    db.add(extraction_run)
    db.flush()
    for label in LABELS:
        question = Question(
            assessment_id=assessment.id,
            question_no=label,
            question_text=f"Question {label}",
            model_answer=f"Model answer for {label}",
            total_marks=Decimal("5.00"),
        )
        db.add(question)
        db.flush()
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                is_active=True,
                rubric_json={"criteria": [{"criterion_label": "c1", "max_marks": "5.00"}]},
            )
        )
        db.add(
            QuestionNode(
                assessment_id=assessment.id,
                extraction_run_id=extraction_run.id,
                label=label,
                question_number=label,
                text=f"Question {label}",
                marks=Decimal("5.00"),
                node_type="subquestion",
                teacher_confirmed=True,
            )
        )
    submission = Submission(
        assessment_id=assessment.id,
        student_identifier="S-1",
        status="uploaded",
    )
    db.add(submission)
    db.flush()
    storage_root = tmp_path / "storage"
    (storage_root / "pages").mkdir(parents=True, exist_ok=True)
    for page_no in range(1, page_count + 1):
        name = f"pages/page_{page_no}.png"
        Image.new("RGB", (600, 800), color="white").save(storage_root / name, format="PNG")
        db.add(
            SubmissionPage(
                submission_id=submission.id,
                page_no=page_no,
                image_path=name,
            )
        )
    db.commit()
    db.refresh(submission)
    return submission, teacher


def _reading(lines: list[OcrLine], **kwargs: Any) -> OcrPageReading:
    defaults: dict[str, Any] = {
        "engine": "rapidocr",
        "lines": lines,
        "render_dpi": 300,
        "page_image_sha256": "c" * 64,
        "page_width": 600,
        "page_height": 800,
        "uncovered_ink_ratio": Decimal("0.02"),
    }
    defaults.update(kwargs)
    return OcrPageReading(**defaults)


def _line(text: str, box: tuple[float, float, float, float]) -> OcrLine:
    return OcrLine(text=text, confidence=Decimal("0.55"), bbox=BoundingBox(*box))


def _good_page(label: str, top: float) -> OcrPageReading:
    return _reading(
        [
            _line(label, (40, top, 200, top + 30)),
            _line("working here", (40, top + 40, 420, top + 70)),
        ]
    )


def _service(
    db: Session,
    tmp_path: Path,
    storage: LocalStorage,
    *,
    engine: FakeEngine,
    text_provider: FakeTextProvider | None = None,
    vision_provider: FakeVisionProvider | None = None,
    switches: SwitchLog | None = None,
    settings: Settings | None = None,
) -> LocalScriptPreparationService:
    return LocalScriptPreparationService(
        db,
        settings=settings or _settings(tmp_path),
        storage=storage,
        ocr_engine=engine,
        qwen_adapter=FakeAdapter(vision_provider) if vision_provider else None,  # type: ignore[arg-type]
        text_adapter=FakeAdapter(text_provider) if text_provider else None,  # type: ignore[arg-type]
        phase_manager=FakePhaseManager(switches or SwitchLog([])),  # type: ignore[arg-type]
    )


def _draft(question_id: int, label: str, page_no: int, orders: list[int]) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_no": label,
        "status": "mapped",
        "confidence": "0.80",
        "warnings": [],
        "block_references": [{"page_no": page_no, "block_orders": orders}],
    }


# ── Tests ──────────────────────────────────────────────────────────────────


def test_hybrid_path_batches_paddle_then_qwen36_and_never_calls_qwen38(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    paddle = FakePaddleClient(
        [
            [
                {"order": 1, "text": LABELS[0], "bbox": [40, 40, 200, 70]},
                {"order": 2, "text": "working one", "bbox": [40, 80, 420, 120]},
            ],
            [
                {"order": 1, "text": LABELS[1], "bbox": [40, 40, 200, 70]},
                {"order": 2, "text": "working two", "bbox": [40, 80, 420, 120]},
            ],
        ]
    )
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1, 2]),
            _draft(questions[1].id, LABELS[1], 2, [1, 2]),
        ]
    )
    vision = FakeVisionProvider([])
    switches = SwitchLog([])
    service = LocalScriptPreparationService(
        db_session,
        settings=_settings(tmp_path),
        storage=storage,
        qwen_adapter=FakeAdapter(vision),  # type: ignore[arg-type]
        text_adapter=FakeAdapter(text_provider),  # type: ignore[arg-type]
        paddle_client_factory=lambda: paddle,
        phase_manager=FakePhaseManager(switches),  # type: ignore[arg-type]
    )

    mappings = service.prepare_from_paddle_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_ocr_model="PaddleOCR-VL-1.6",
        expected_layout_model="PP-DocLayoutV3",
        replace_existing=True,
        maximum_ocr_calls=2,
    )

    assert paddle.health_calls == 1
    assert paddle.calls == 2
    assert len(text_provider.calls) == 1
    assert vision.calls == 0
    assert switches.phases == ["PaddleOcr", "Qwen"]
    assert {item.provider for item in mappings} == {"local_paddle_qwen"}
    assert {item.mapping_status for item in mappings} == {"mapped"}
    audit = db_session.query(AuditLog).filter(
        AuditLog.event_type == "submission_script_draft_prepared"
    ).one()
    assert audit.payload_json["paddle_ocr_call_count"] == 2
    assert audit.payload_json["qwen38_call_count"] == 0


def test_hybrid_path_refuses_page_count_above_explicit_paddle_budget(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path, page_count=2)
    paddle = FakePaddleClient([])
    service = LocalScriptPreparationService(
        db_session,
        settings=_settings(tmp_path),
        storage=storage,
        paddle_client_factory=lambda: paddle,
    )

    with pytest.raises(LocalScriptPreparationError, match="authorized OCR call limit"):
        service.prepare_from_paddle_ocr(
            submission=submission,
            teacher=teacher,
            expected_text_model="qwen3.6-35b-a3b-q4km",
            expected_ocr_model="PaddleOCR-VL-1.6",
            expected_layout_model="PP-DocLayoutV3",
            replace_existing=True,
            maximum_ocr_calls=1,
        )

    assert paddle.calls == 0


def test_hybrid_coverage_pass_adds_bottom_continuation_and_unmapped_question(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    """One bounded second pass repairs only blocks the initial map left behind."""
    submission, teacher = _seed(db_session, tmp_path, page_count=2)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    paddle = FakePaddleClient(
        [
            [
                {"order": 1, "text": LABELS[0], "bbox": [40, 40, 200, 70]},
                {"order": 2, "text": "continues", "bbox": [40, 720, 420, 790]},
            ],
            [
                {"order": 1, "text": "final line", "bbox": [40, 40, 420, 85]},
                {"order": 2, "text": LABELS[1], "bbox": [40, 200, 200, 230]},
                {"order": 3, "text": "working two", "bbox": [40, 240, 420, 290]},
            ],
        ]
    )
    provider = SequencedFakeTextProvider(
        [
            [
                _draft(questions[0].id, LABELS[0], 1, [1, 2]),
                {
                    "question_id": questions[1].id,
                    "question_no": LABELS[1],
                    "status": "not_found",
                    "confidence": "0.10",
                    "warnings": [],
                    "block_references": [],
                },
            ],
            [
                _draft(questions[0].id, LABELS[0], 2, [1]),
                _draft(questions[1].id, LABELS[1], 2, [2, 3]),
            ],
        ]
    )
    service = LocalScriptPreparationService(
        db_session,
        settings=_settings(tmp_path),
        storage=storage,
        text_adapter=FakeAdapter(provider),  # type: ignore[arg-type]
        paddle_client_factory=lambda: paddle,
        phase_manager=FakePhaseManager(SwitchLog([])),  # type: ignore[arg-type]
    )

    mappings = service.prepare_from_paddle_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_ocr_model="PaddleOCR-VL-1.6",
        expected_layout_model="PP-DocLayoutV3",
        replace_existing=True,
        maximum_ocr_calls=2,
        maximum_text_mapping_calls=2,
    )

    assert len(provider.calls) == 2
    assert {question["question_id"] for question in provider.calls[1]["questions"]} == {
        questions[0].id,
        questions[1].id,
    }
    first = next(mapping for mapping in mappings if mapping.question_id == questions[0].id)
    second = next(mapping for mapping in mappings if mapping.question_id == questions[1].id)
    assert [segment.submission_page_id for segment in first.answer_region.segments] == [
        submission.pages[0].id,
        submission.pages[1].id,
    ]
    assert second.answer_region is not None
    audit = db_session.query(AuditLog).filter(
        AuditLog.event_type == "submission_script_draft_prepared"
    ).one()
    assert audit.payload_json["text_mapping_call_count"] == 2
    assert audit.payload_json["text_mapping_call_limit"] == 2


def test_hybrid_repair_preserves_confirmed_mapping_and_replaces_only_unresolved(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )

    def paddle() -> FakePaddleClient:
        return FakePaddleClient(
            [
                [
                    {"order": 1, "text": LABELS[0], "bbox": [40, 40, 200, 70]},
                    {"order": 2, "text": "working one", "bbox": [40, 80, 420, 120]},
                ],
                [
                    {"order": 1, "text": LABELS[1], "bbox": [40, 40, 200, 70]},
                    {"order": 2, "text": "working two", "bbox": [40, 80, 420, 120]},
                ],
            ]
        )

    first = LocalScriptPreparationService(
        db_session,
        settings=_settings(tmp_path),
        storage=storage,
        text_adapter=FakeAdapter(
            FakeTextProvider(
                [
                    _draft(questions[0].id, LABELS[0], 1, [1, 2]),
                    _draft(questions[1].id, LABELS[1], 2, [1, 2]),
                ]
            )
        ),  # type: ignore[arg-type]
        paddle_client_factory=paddle,
        phase_manager=FakePhaseManager(SwitchLog([])),  # type: ignore[arg-type]
    )
    initial = first.prepare_from_paddle_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_ocr_model="PaddleOCR-VL-1.6",
        expected_layout_model="PP-DocLayoutV3",
        replace_existing=True,
        maximum_ocr_calls=2,
    )
    confirmed = next(item for item in initial if item.question_id == questions[0].id)
    confirmed_id = confirmed.id
    confirmed.teacher_confirmed = True
    for segment in confirmed.answer_region.segments:
        segment.confirmed = True
    db_session.commit()

    repair = LocalScriptPreparationService(
        db_session,
        settings=_settings(tmp_path),
        storage=storage,
        text_adapter=FakeAdapter(
            FakeTextProvider(
                [
                    _draft(questions[0].id, LABELS[0], 1, [1, 2]),
                    _draft(questions[1].id, LABELS[1], 2, [1, 2]),
                ]
            )
        ),  # type: ignore[arg-type]
        paddle_client_factory=paddle,
        phase_manager=FakePhaseManager(SwitchLog([])),  # type: ignore[arg-type]
    )
    repaired = repair.prepare_from_paddle_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_ocr_model="PaddleOCR-VL-1.6",
        expected_layout_model="PP-DocLayoutV3",
        replace_existing=False,
        repair_unconfirmed_only=True,
        maximum_ocr_calls=2,
    )

    preserved = next(item for item in repaired if item.question_id == questions[0].id)
    assert preserved.id == confirmed_id
    assert preserved.teacher_confirmed is True
    assert any(item.question_id == questions[1].id for item in repaired)


def test_no_vision_call_when_tier1_read_every_page(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    """The whole economic argument: readable pages must cost zero vision calls."""
    submission, teacher = _seed(db_session, tmp_path)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    engine = FakeEngine([_good_page(LABELS[0], 40), _good_page(LABELS[1], 40)])
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1, 2]),
            _draft(questions[1].id, LABELS[1], 2, [1, 2]),
        ]
    )
    vision = FakeVisionProvider([])
    switches = SwitchLog([])
    service = _service(
        db_session,
        tmp_path,
        storage,
        engine=engine,
        text_provider=text_provider,
        vision_provider=vision,
        switches=switches,
    )

    mappings = service.prepare_from_tier1_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_vision_model="qwen3.8-27b-q4km",
        replace_existing=True,
        maximum_visual_calls=5,
    )

    assert vision.calls == 0
    assert len(text_provider.calls) == 1
    # One switch, to the text model only. Every extra costs a 60-90 s reload.
    assert switches.phases == ["Qwen"]
    assert engine.call_count == 2
    assert {item.mapping_status for item in mappings} == {"mapped"}
    assert all(item.provider == "llama_cpp_qwen" for item in mappings)
    assert all(item.teacher_confirmed is False for item in mappings)


def test_geometry_comes_from_the_ocr_boxes_not_from_the_model(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    """Qwen3.6 selects block ids; the crop must come from the detected boxes."""
    submission, teacher = _seed(db_session, tmp_path, page_count=1)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    engine = FakeEngine(
        [_reading([_line(LABELS[0], (100, 200, 300, 240)), _line("x", (100, 250, 280, 290))])]
    )
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1, 2]),
            {
                "question_id": questions[1].id,
                "question_no": LABELS[1],
                "status": "not_found",
                "confidence": "0.10",
                "warnings": [],
                "block_references": [],
            },
        ]
    )
    service = _service(
        db_session, tmp_path, storage, engine=engine, text_provider=text_provider
    )

    mappings = service.prepare_from_tier1_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_vision_model="qwen3.8-27b-q4km",
        replace_existing=True,
        maximum_visual_calls=5,
    )

    mapped = next(item for item in mappings if item.question_id == questions[0].id)
    region = mapped.answer_region
    assert region is not None
    # Union of the two boxes, widened by _union_box; must enclose both.
    assert float(region.x) <= 100
    assert float(region.y) <= 200
    assert float(region.x) + float(region.width) >= 300
    assert float(region.y) + float(region.height) >= 290


def test_an_unmapped_question_becomes_a_visible_blocker(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path, page_count=1)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    engine = FakeEngine([_good_page(LABELS[0], 40)])
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1, 2]),
            {
                "question_id": questions[1].id,
                "question_no": LABELS[1],
                "status": "not_found",
                "confidence": "0",
                "warnings": [],
                "block_references": [],
            },
        ]
    )
    service = _service(db_session, tmp_path, storage, engine=engine, text_provider=text_provider)

    mappings = service.prepare_from_tier1_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_vision_model="qwen3.8-27b-q4km",
        replace_existing=True,
        maximum_visual_calls=5,
    )

    missing = next(item for item in mappings if item.question_id == questions[1].id)
    assert missing.mapping_status == "blocked"
    assert missing.answer_region_id is None
    assert missing.blocker_reason


def test_only_the_unreadable_page_goes_to_the_vision_model(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    """Page 1 is readable, page 2 is not; the mappers must split the work."""
    submission, teacher = _seed(db_session, tmp_path, page_count=2)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    engine = FakeEngine([_good_page(LABELS[0], 40), _reading([])])
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1, 2]),
            {
                "question_id": questions[1].id,
                "question_no": LABELS[1],
                "status": "not_found",
                "confidence": "0",
                "warnings": [],
                "block_references": [],
            },
        ]
    )
    vision = FakeVisionProvider(
        [
            [
                VisualPageRegion(
                    question_label=LABELS[1],
                    bbox=[100, 100, 800, 600],
                    continues_from_previous=False,
                    continues_to_next=False,
                    confidence=Decimal("0.70"),
                    warnings=[],
                )
            ]
        ]
    )
    switches = SwitchLog([])
    service = _service(
        db_session,
        tmp_path,
        storage,
        engine=engine,
        text_provider=text_provider,
        vision_provider=vision,
        switches=switches,
    )

    mappings = service.prepare_from_tier1_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_vision_model="qwen3.8-27b-q4km",
        replace_existing=True,
        maximum_visual_calls=5,
    )

    assert vision.calls == 1
    assert len(text_provider.calls) == 1
    # Vision first, then text: each model loads exactly once.
    assert switches.phases == ["Qwen38", "Qwen"]
    # The text mapper only ever saw the readable page.
    assert [page["page"] for page in text_provider.calls[0]["pages"]] == [1]
    assert {item.mapping_status for item in mappings} == {"mapped"}
    vision_mapped = next(item for item in mappings if item.question_id == questions[1].id)
    assert any(
        "located by the vision model" in warning
        for warning in (vision_mapped.source_reference or {}).get("warnings", [])
    )


def test_the_two_mappers_never_both_claim_one_answer(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    """Vision placed 1(a)(ii); the text mapper claiming it too must not add a second region."""
    submission, teacher = _seed(db_session, tmp_path, page_count=2)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    engine = FakeEngine([_good_page(LABELS[0], 40), _reading([])])
    text_provider = FakeTextProvider(
        [
            _draft(questions[0].id, LABELS[0], 1, [1]),
            _draft(questions[1].id, LABELS[1], 1, [2]),
        ]
    )
    vision = FakeVisionProvider(
        [
            [
                VisualPageRegion(
                    question_label=LABELS[1],
                    bbox=[100, 100, 800, 600],
                    continues_from_previous=False,
                    continues_to_next=False,
                    confidence=Decimal("0.70"),
                    warnings=[],
                )
            ]
        ]
    )
    service = _service(
        db_session,
        tmp_path,
        storage,
        engine=engine,
        text_provider=text_provider,
        vision_provider=vision,
    )

    mappings = service.prepare_from_tier1_ocr(
        submission=submission,
        teacher=teacher,
        expected_text_model="qwen3.6-35b-a3b-q4km",
        expected_vision_model="qwen3.8-27b-q4km",
        replace_existing=True,
        maximum_visual_calls=5,
    )

    claimed = next(item for item in mappings if item.question_id == questions[1].id)
    region = claimed.answer_region
    assert region is not None
    assert len(region.segments) == 1
    assert region.segments[0].submission_page_id == submission.pages[1].id


def test_exceeding_the_authorized_vision_budget_stops_the_run(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path, page_count=2)
    engine = FakeEngine([_reading([]), _reading([])])
    vision = FakeVisionProvider([])
    service = _service(db_session, tmp_path, storage, engine=engine, vision_provider=vision)

    with pytest.raises(LocalScriptPreparationError, match="only 1 vision call"):
        service.prepare_from_tier1_ocr(
            submission=submission,
            teacher=teacher,
            expected_text_model="qwen3.6-35b-a3b-q4km",
            expected_vision_model="qwen3.8-27b-q4km",
            replace_existing=True,
            maximum_visual_calls=1,
        )

    assert vision.calls == 0
    assert db_session.query(AnswerRegionMapping).count() == 0


def test_a_wrong_model_alias_is_refused_before_any_page_is_read(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path, page_count=1)
    engine = FakeEngine([_good_page(LABELS[0], 40)])
    service = _service(db_session, tmp_path, storage, engine=engine)

    with pytest.raises(LocalScriptPreparationError, match="Qwen3.6 model alias"):
        service.prepare_from_tier1_ocr(
            submission=submission,
            teacher=teacher,
            expected_text_model="wrong-model",
            expected_vision_model="qwen3.8-27b-q4km",
            replace_existing=True,
            maximum_visual_calls=5,
        )

    assert engine.call_count == 0


def test_confirmed_mappings_are_never_replaced_automatically(
    db_session: Session, tmp_path: Path, storage: LocalStorage
) -> None:
    submission, teacher = _seed(db_session, tmp_path, page_count=1)
    questions = sorted(
        db_session.query(Question).filter(Question.assessment_id == submission.assessment_id),
        key=lambda item: item.question_no,
    )
    node = db_session.query(QuestionNode).filter(QuestionNode.label == LABELS[0]).one()
    region = AnswerRegion(
        submission_id=submission.id,
        question_id=questions[0].id,
        question_node_id=node.id,
        page_id=submission.pages[0].id,
        x=Decimal("0"),
        y=Decimal("0"),
        width=Decimal("10"),
        height=Decimal("10"),
        image_path="pages/page_1.png",
        manual_answer_text="teacher confirmed this text",
    )
    db_session.add(region)
    db_session.flush()
    db_session.add(
        AnswerRegionMapping(
            assessment_id=submission.assessment_id,
            submission_id=submission.id,
            question_node_id=node.id,
            question_id=questions[0].id,
            answer_region=region,
            source_reference={"warnings": []},
            confidence=Decimal("0.9"),
            mapping_status="teacher_confirmed",
            provider="llama_cpp_qwen38",
            teacher_confirmed=True,
        )
    )
    db_session.commit()
    engine = FakeEngine([_good_page(LABELS[0], 40)])
    service = _service(db_session, tmp_path, storage, engine=engine)

    with pytest.raises(LocalScriptPreparationError, match="cannot be replaced"):
        service.prepare_from_tier1_ocr(
            submission=submission,
            teacher=teacher,
            expected_text_model="qwen3.6-35b-a3b-q4km",
            expected_vision_model="qwen3.8-27b-q4km",
            replace_existing=True,
            maximum_visual_calls=5,
        )
