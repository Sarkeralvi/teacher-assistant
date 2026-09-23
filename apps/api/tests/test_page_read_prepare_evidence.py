"""The transcript and assignment layers are reached by the real preparation path.

``LocalScriptPageReadService.prepare`` is exercised end to end against the real
database and real local storage: finalized questions, confirmed question nodes,
active rubrics, page images on disk, crop writing, mapping creation and the
transcription artifact. Only ``_validate_authorization`` is replaced, because
provider authorization is covered by its own tests and needs live provider
settings that this check is not about.

Without these, the transcript and assignment tables would be tested classes that
nothing in the product calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import (
    AnswerEvidenceAssignment,
    AnswerEvidenceSpan,
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    Assessment,
    AuditLog,
    Course,
    ExtractionRun,
    Question,
    QuestionNode,
    Rubric,
    ScriptPageTranscript,
    ScriptTranscript,
    ScriptTranscriptBlock,
    Submission,
    SubmissionPage,
    User,
)
from app.services.answer_evidence_assignment import (
    ANSWER_PRESENT,
    NO_ANSWER_FOUND,
    AnswerEvidenceAssignmentService,
    CanonicalQuestion,
)
from app.services.local_script_page_read import LocalScriptPageReadService
from app.services.storage import LocalStorage
from packages.brain.schemas_qwen38 import VisualPageBlock, VisualPageTranscriptOutput

CLEANUP_MODELS = (
    AuditLog,
    AnswerEvidenceSpan,
    AnswerEvidenceAssignment,
    ScriptTranscriptBlock,
    ScriptPageTranscript,
    ScriptTranscript,
    AnswerRegionOcrRun,
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
    User,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    api_root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(api_root / "alembic.ini")), "head")
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


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LocalStorage]:
    get_settings.cache_clear()
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "storage" / "artifacts"))
    try:
        yield LocalStorage()
    finally:
        get_settings.cache_clear()


class _Adapter:
    def __init__(
        self,
        outputs: list[VisualPageTranscriptOutput],
        *,
        mapping_output: dict[str, Any] | None = None,
    ) -> None:
        self._outputs = outputs
        self.calls = 0
        self.mapping_output = mapping_output
        self.mapping_calls = 0
        self.runtime = SimpleNamespace(managed_local_phase=None)

    def read_page(self, **_kwargs: Any) -> VisualPageTranscriptOutput:
        result = self._outputs[self.calls]
        self.calls += 1
        return result

    def map_submission_answers_from_ocr_pages(self, **_kwargs: Any) -> dict[str, Any]:
        self.mapping_calls += 1
        if self.mapping_output is None:
            raise AssertionError("whole-transcript assignment was not expected")
        return self.mapping_output


def _seed(db: Session, storage: LocalStorage, labels: list[str]) -> Submission:
    teacher = User(
        name="Teacher",
        email=f"prepare-{uuid4().hex}@example.com",
        password_hash="x",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code=f"C{uuid4().hex[:6]}", title="Course")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Midterm",
        assessment_type="exam",
        total_marks=Decimal("50.00"),
    )
    db.add(assessment)
    db.flush()
    run = ExtractionRun(
        assessment_id=assessment.id,
        artifact_file_path="artifacts/paper.pdf",
        original_filename="paper.pdf",
        content_type="application/pdf",
        extraction_type="question_paper",
        provider="mock",
        status="succeeded",
        blockers=[],
    )
    db.add(run)
    db.flush()
    for label in labels:
        question = Question(
            assessment_id=assessment.id,
            question_no=label,
            question_text=f"Explain {label}",
            model_answer=f"Model answer {label}",
            total_marks=Decimal("5.00"),
        )
        db.add(question)
        db.flush()
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                rubric_json={
                    "total_marks": "5.00",
                    "criteria": [
                        {
                            "id": "accuracy",
                            "name": "Accuracy",
                            "description": "Accurate",
                            "max_marks": "5.00",
                        }
                    ],
                },
                is_active=True,
            )
        )
        db.add(
            QuestionNode(
                assessment_id=assessment.id,
                extraction_run_id=run.id,
                question_number=label,
                label=label,
                text=f"Explain {label}",
                node_type="question",
                teacher_confirmed=True,
            )
        )
    submission = Submission(
        assessment_id=assessment.id,
        student_identifier="S-001",
        status="ready",
    )
    db.add(submission)
    db.flush()

    page_dir = storage.root / "uploads" / f"submission-{submission.id}"
    page_dir.mkdir(parents=True, exist_ok=True)
    path = page_dir / "page-1.png"
    image = Image.new("RGB", (1000, 1000), "white")
    # Ink confined to the band the returned block declares, so the coverage
    # control has nothing legitimately uncovered to block on.
    ImageDraw.Draw(image).rectangle((120, 160, 880, 380), fill="black")
    image.save(path)
    db.add(
        SubmissionPage(
            submission_id=submission.id,
            page_no=1,
            image_path=storage.relative_to_root(path),
        )
    )
    db.commit()
    db.refresh(submission)
    return submission


def _page_output() -> VisualPageTranscriptOutput:
    return VisualPageTranscriptOutput(
        blocks=[
            VisualPageBlock(
                question_label="Q1",
                bbox=[100, 140, 900, 400],
                text="the answer to one",
                continues_from_previous=False,
                label_source="heading",
                confidence=Decimal("0.95"),
            )
        ],
        is_blank_page=False,
    )


def _service(
    db: Session,
    storage: LocalStorage,
    adapter: _Adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> LocalScriptPageReadService:
    service = LocalScriptPageReadService(
        db,
        settings=Settings(_env_file=None, LOCAL_SCRIPT_UNASSIGNED_INK_WARN_ABOVE=Decimal("0.35")),
        storage=storage,
        qwen_adapter=adapter,
    )
    monkeypatch.setattr(
        service,
        "_validate_authorization",
        lambda *_args, **_kwargs: SimpleNamespace(
            provider="mock",
            model="mock-vision-1",
            adapter=adapter,
            model_asset_sha256=None,
            auxiliary_model_asset_sha256=None,
        ),
    )
    return service


def test_prepare_persists_the_transcript_and_the_evidence_assignment(
    db_session: Session,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _seed(db_session, storage, ["Q1", "Q2"])
    adapter = _Adapter([_page_output()])

    result = _service(db_session, storage, adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=True,
        maximum_page_read_calls=5,
    )

    assert adapter.calls == 1
    assert result.calls_used == 1
    assert result.script_transcript_id is not None

    # The source transcript exists on the product path, not only in its own test.
    transcript = db_session.get(ScriptTranscript, result.script_transcript_id)
    assert transcript is not None
    assert transcript.status == "complete"
    assert [block.text for page in transcript.pages for block in page.blocks] == [
        "the answer to one"
    ]

    # So does the separately versioned assignment, with distinct states.
    assignments = db_session.scalars(
        select(AnswerEvidenceAssignment).where(
            AnswerEvidenceAssignment.script_transcript_id == transcript.id
        )
    ).all()
    states = {row.question.question_no: row.state for row in assignments}
    assert states == {"Q1": ANSWER_PRESENT, "Q2": NO_ANSWER_FOUND}
    assert result.evidence_states[ANSWER_PRESENT] == 1
    assert result.evidence_states[NO_ANSWER_FOUND] == 1

    # And the state reaches the record a reviewer reads.
    by_label = {
        mapping.question.question_no: mapping.source_reference["page_read"]
        for mapping in result.mappings
    }
    assert by_label["Q1"]["evidence_state"] == ANSWER_PRESENT
    assert by_label["Q2"]["evidence_state"] == NO_ANSWER_FOUND
    assert by_label["Q2"]["source_coverage_complete"] is True
    assert by_label["Q1"]["script_transcript_id"] == transcript.id

    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.event_type == "submission_script_page_read_prepared")
    ).one()
    assert audit.payload_json["visual_page_read_call_count"] == 1
    assert audit.payload_json["reused_page_transcript_count"] == 0
    assert audit.payload_json["evidence_states"][ANSWER_PRESENT] == 1


def test_transcript_only_prepare_creates_no_mapping_crop_or_region_ocr(
    db_session: Session,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _seed(db_session, storage, ["Q1", "Q2"])
    adapter = _Adapter([_page_output()])

    result = _service(db_session, storage, adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=False,
        maximum_page_read_calls=5,
        persist_legacy_artifacts=False,
    )

    assert result.script_transcript_id is not None
    assert result.mappings == []
    assert result.transcription_runs_by_question == {}
    assert db_session.scalars(select(AnswerRegionMapping)).all() == []
    assert db_session.scalars(select(AnswerRegionOcrRun)).all() == []
    assert db_session.scalars(select(AnswerRegion)).all() == []
    assert result.evidence_states[ANSWER_PRESENT] == 1
    assert result.evidence_states[NO_ANSWER_FOUND] == 1
    assert sum(result.evidence_states.values()) == 2


def test_preparing_again_reuses_the_transcript_and_versions_the_assignment(
    db_session: Session,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submission = _seed(db_session, storage, ["Q1", "Q2"])
    first_adapter = _Adapter([_page_output()])
    first = _service(db_session, storage, first_adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=True,
        maximum_page_read_calls=5,
    )
    assert first.calls_used == 1

    # This is the case the whole change exists for: re-preparing after a remap
    # or a rubric change must not pay to read the same unchanged pages again.
    second_adapter = _Adapter([])
    second = _service(db_session, storage, second_adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=True,
        maximum_page_read_calls=5,
    )

    assert second_adapter.calls == 0
    assert second.calls_used == 0
    assert second.reused_page_count == 1
    assert second.script_transcript_id == first.script_transcript_id

    versions = db_session.scalars(
        select(AnswerEvidenceAssignment)
        .where(AnswerEvidenceAssignment.script_transcript_id == first.script_transcript_id)
        .order_by(
            AnswerEvidenceAssignment.question_node_id,
            AnswerEvidenceAssignment.assignment_version,
        )
    ).all()
    assert [row.assignment_version for row in versions] == [1, 2, 1, 2]
    assert sum(1 for row in versions if row.is_current) == 2


def test_complete_saved_transcript_is_assigned_globally_when_page_labels_are_missing(
    db_session: Session,
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for real run 5: every page was read, but all packets became
    ``unassigned_ink`` because the second stage only carried page labels forward.

    The full saved transcript must be interpreted once as a document. The model
    selects immutable page/block identifiers; it cannot rewrite transcript text.
    """

    submission = _seed(db_session, storage, ["Q1", "Q2"])
    seeded_questions = db_session.scalars(
        select(Question).order_by(Question.question_no)
    ).all()
    page_output = VisualPageTranscriptOutput(
        blocks=[
            VisualPageBlock(
                question_label=None,
                bbox=[100, 140, 900, 260],
                text="(i) first answer work",
                continues_from_previous=False,
                label_source="continuation",
                confidence=Decimal("0.90"),
            ),
            VisualPageBlock(
                question_label=None,
                bbox=[100, 300, 900, 430],
                text="(ii) second answer work",
                continues_from_previous=False,
                label_source="continuation",
                confidence=Decimal("0.90"),
            ),
            VisualPageBlock(
                question_label="Q1",
                bbox=[100, 460, 900, 560],
                text="unclaimed margin note",
                continues_from_previous=False,
                label_source="heading",
                confidence=Decimal("0.90"),
            ),
            VisualPageBlock(
                question_label=None,
                bbox=[100, 580, 900, 640],
                text="Answer no: 01",
                continues_from_previous=False,
                label_source="continuation",
                confidence=Decimal("0.90"),
            ),
        ],
        is_blank_page=False,
    )
    adapter = _Adapter(
        [page_output],
        mapping_output={
            "mappings": [
                {
                    "question_id": seeded_questions[0].id,
                    "question_no": "Q1",
                    "status": "mapped",
                    "block_references": [{"page_no": 1, "block_orders": [1]}],
                    "confidence": "0.95",
                    "warnings": [],
                    "needs_review": True,
                },
                {
                    "question_id": seeded_questions[1].id,
                    "question_no": "Q2",
                    "status": "mapped",
                    "block_references": [{"page_no": 1, "block_orders": [2]}],
                    "confidence": "0.95",
                    "warnings": [],
                    "needs_review": True,
                },
            ],
            "unassigned_block_references": [{"page_no": 1, "block_orders": [3]}],
            "non_answer_block_references": [{"page_no": 1, "block_orders": [4]}],
            "warnings": [],
        },
    )

    result = _service(db_session, storage, adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=False,
        maximum_page_read_calls=5,
        persist_legacy_artifacts=False,
    )

    transcript = db_session.get(ScriptTranscript, result.script_transcript_id)
    assert transcript is not None
    assignments = db_session.scalars(
        select(AnswerEvidenceAssignment)
        .where(
            AnswerEvidenceAssignment.script_transcript_id == transcript.id,
            AnswerEvidenceAssignment.is_current.is_(True),
        )
        .order_by(AnswerEvidenceAssignment.question_id)
    ).all()

    assert adapter.calls == 1
    assert adapter.mapping_calls == 1
    assert result.calls_used == 2
    assert [len(item.spans) for item in assignments] == [1, 1]
    assert {span.assignment_basis for item in assignments for span in item.spans} == {
        "full_transcript_model"
    }
    # Even an explicit page-local label cannot survive as hidden fallback when
    # the authoritative full-transcript pass leaves that block unclaimed.
    assert all(item.unassigned_block_count == 1 for item in assignments)
    # Model-selected ownership is useful but remains explicitly review-gated.
    assert all(item.state == "ambiguous" for item in assignments)

    cached_adapter = _Adapter([])
    cached = _service(db_session, storage, cached_adapter, monkeypatch).prepare(
        submission=submission,
        teacher=db_session.scalars(select(User)).one(),
        expected_model="mock-vision-1",
        replace_existing=False,
        maximum_page_read_calls=5,
        persist_legacy_artifacts=False,
    )
    assert cached.calls_used == 0
    assert cached.reused_page_count == 1
    assert cached_adapter.calls == 0
    assert cached_adapter.mapping_calls == 0

    nodes = {
        node.question_number: node
        for node in db_session.scalars(select(QuestionNode)).all()
    }
    rederived = AnswerEvidenceAssignmentService(db_session).assign(
        submission_id=submission.id,
        transcript=AnswerEvidenceAssignmentService(db_session).load_transcript(
            result.script_transcript_id
        ),
        questions=[
            CanonicalQuestion(
                question_id=question.id,
                question_node_id=nodes[question.question_no].id,
                question_no=question.question_no,
            )
            for question in seeded_questions
        ],
    )
    assert [len(item.spans) for item in rederived] == [1, 1]
    assert {span.assignment_basis for item in rederived for span in item.spans} == {
        "full_transcript_model"
    }
