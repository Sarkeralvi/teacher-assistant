from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings
from app.models import (
    AnswerRegion,
    AnswerRegionMapping,
    AnswerRegionOcrRun,
    AnswerRegionSegment,
    BulkEvaluationItem,
    BulkEvaluationRun,
    Submission,
    User,
)
from app.services.bulk_evaluation_service import (
    BulkEvaluationError,
    BulkEvaluationService,
    _safe_member,
)


def _service() -> BulkEvaluationService:
    return BulkEvaluationService(
        MagicMock(), settings=get_settings(), storage=MagicMock()
    )


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_bulk_zip_groups_root_pdfs_and_naturally_orders_folder_images(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "scripts.zip"
    _write_zip(
        archive_path,
        {
            "student-a.pdf": b"pdf",
            "student-b/page10.png": b"ten",
            "student-b/page2.png": b"two",
            "student-b/page1.png": b"one",
            "manifest.csv": (
                b"source,student_identifier,student_name\n"
                b"student-a.pdf,A-001,Student A\n"
                b"student-b,B-002,Student B\n"
            ),
            "__MACOSX/._student-a.pdf": b"metadata",
        },
    )

    with zipfile.ZipFile(archive_path) as archive:
        units, manifest_hash, payload = _service()._inspect_archive(archive)

    assert [unit.identifier for unit in units] == ["A-001", "B-002"]
    assert [member.filename for member in units[1].members] == [
        "student-b/page1.png",
        "student-b/page2.png",
        "student-b/page10.png",
    ]
    assert manifest_hash is not None
    assert payload[1]["kind"] == "images"


@pytest.mark.parametrize(
    "member",
    ["../script.pdf", "/script.pdf", "C:/script.pdf", "student/../script.pdf"],
)
def test_bulk_zip_rejects_unsafe_paths(member: str) -> None:
    with pytest.raises(BulkEvaluationError, match="unsafe member path"):
        _safe_member(member)


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"page1.png": b"image"}, "Root-level images are ambiguous"),
        (
            {"student/script.pdf": b"pdf", "student/page1.png": b"image"},
            "mixes PDF and image pages",
        ),
        (
            {"student/a.pdf": b"a", "student/b.pdf": b"b"},
            "unclear whether this is one student or several",
        ),
        ({"student/nested/page.png": b"image"}, "no nested folders"),
        ({"student/notes.txt": b"text"}, "Unsupported ZIP entry"),
    ],
)
def test_bulk_zip_rejects_ambiguous_or_unsupported_layouts(
    tmp_path: Path, members: dict[str, bytes], message: str
) -> None:
    archive_path = tmp_path / "bad.zip"
    _write_zip(archive_path, members)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(BulkEvaluationError, match=message):
            _service()._inspect_archive(archive)


def test_multiple_pdfs_in_one_folder_explains_both_valid_layouts(tmp_path: Path) -> None:
    """A real teacher hit this with Scripts/a.pdf + Scripts/b.pdf -- a container
    folder holding one PDF per student. The old message stated the rule but not
    the remedy, so it did not say which of the two supported layouts to produce.
    Refusing stays correct (guessing would merge or split students); the message
    has to carry the fix."""
    archive_path = tmp_path / "container.zip"
    _write_zip(archive_path, {"Scripts/a.pdf": b"a", "Scripts/b.pdf": b"b"})
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(BulkEvaluationError) as caught:
            _service()._inspect_archive(archive)

    message = str(caught.value)
    assert "Scripts" in message
    # Names the separate-students remedy...
    assert "top level" in message
    # ...and the one-student remedy, so neither reading is left unaddressed.
    assert "single PDF" in message
    assert "numbered images" in message


def test_manifest_rejects_duplicate_identifiers(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.zip"
    _write_zip(
        archive_path,
        {
            "a.pdf": b"a",
            "b.pdf": b"b",
            "manifest.csv": (
                b"source,student_identifier,student_name\n"
                b"a.pdf,SAME,A\n"
                b"b.pdf,same,B\n"
            ),
        },
    )
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(BulkEvaluationError, match="duplicate student identifiers"):
            _service()._inspect_archive(archive)


def test_mapping_policy_fails_closed_on_low_confidence_and_continuation() -> None:
    mapping = SimpleNamespace(
        question_id=11,
        answer_region=object(),
        blocker_reason=None,
        confidence=Decimal("0.89"),
        source_reference={"warnings": ["Possible continuation on next page"]},
    )

    codes = _service()._mapping_exception_codes(mapping, set())

    assert codes == ["possible_continuation", "incomplete_region"]


def test_critical_math_tokens_preserve_decimal_fraction_and_complement_signals() -> None:
    tokens = _service()._critical_tokens(
        r"P(\bar X)=5/12, P(Y\mid\bar X)=0.500 and 7/10"
    )

    assert tokens == [
        r"\bar",
        "=",
        "5",
        "/",
        "12",
        r"\bar",
        "=",
        "0.500",
        "7",
        "/",
        "10",
    ]


def test_workbook_contract_never_includes_raw_transcript_sheet() -> None:
    # The export contract is intentionally explicit: only these aggregate sheets
    # are created by build_results_workbook.
    source = (
        Path(__file__).resolve().parents[1] / "app/services/bulk_evaluation_service.py"
    ).read_text(encoding="utf-8")
    for sheet_name in ("Approved Scores", "Student Totals", "Exceptions", "Run Summary"):
        assert sheet_name in source
    assert 'create_sheet("Transcripts")' not in source


def test_provider_call_budget_is_hard_and_never_overruns() -> None:
    run = BulkEvaluationRun(authorized_call_limit=4, calls_used=3)
    service = _service()

    with pytest.raises(BulkEvaluationError, match="budget would be exceeded"):
        service._consume_calls(run, 2)

    assert run.calls_used == 3


def test_grading_is_drained_question_major_so_the_prompt_prefix_stays_cacheable() -> None:
    # Items are created student-major, so ordering by id alone would swap the
    # question, model answer and rubric on every consecutive grading call. The
    # host serves one slot; a stable header is what makes prefix reuse possible.
    db = MagicMock()
    db.scalar.return_value = None
    service = _service()
    service.db = db

    service._next_grading_item(BulkEvaluationRun(id=3, created_by_teacher_id=1))

    statement = str(db.scalar.call_args[0][0])
    assert (
        "ORDER BY bulk_evaluation_items.question_id, bulk_evaluation_items.id"
        in statement
    )


def test_bulk_items_are_created_student_major() -> None:
    # The pairing that makes the grading order above load-bearing: if item
    # creation ever became question-major, _next_grading_item's ordering would be
    # a no-op rather than a correction, and this test should be revisited.
    source = (
        Path(__file__).resolve().parents[1] / "app/services/bulk_evaluation_service.py"
    ).read_text(encoding="utf-8")
    nested_loop = "for submission in submissions:\n                    for question in questions:"
    assert nested_loop in source


def _png(tmp_path: Path, name: str, *, inked: bool) -> Path:
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("L", (40, 40), color=255)
    if inked:
        ImageDraw.Draw(image).rectangle((10, 10, 20, 20), fill=0)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    target = tmp_path / name
    target.write_bytes(buffer.getvalue())
    return target


def test_blank_region_is_refused_before_the_provider_call(tmp_path: Path) -> None:
    blank = _png(tmp_path, "blank.png", inked=False)
    service = _service()
    service.storage.resolve_relative = MagicMock(return_value=blank)
    region = AnswerRegion(
        id=101, segments=[AnswerRegionSegment(image_path="blank.png", order_index=1)]
    )

    assert service._region_has_no_ink(region) is True


def test_region_with_any_ink_still_goes_to_the_provider(tmp_path: Path) -> None:
    inked = _png(tmp_path, "inked.png", inked=True)
    service = _service()
    service.storage.resolve_relative = MagicMock(return_value=inked)
    region = AnswerRegion(
        id=102, segments=[AnswerRegionSegment(image_path="inked.png", order_index=1)]
    )

    assert service._region_has_no_ink(region) is False


def test_unreadable_segment_falls_through_to_the_provider(tmp_path: Path) -> None:
    # Fail open. "Unknown" must never be treated as "blank", because the cost of
    # a wrong blank is a student's answer presented to the teacher as empty.
    service = _service()
    service.storage.resolve_relative = MagicMock(return_value=tmp_path / "missing.png")
    region = AnswerRegion(
        id=103, segments=[AnswerRegionSegment(image_path="missing.png", order_index=1)]
    )

    assert service._region_has_no_ink(region) is False


def test_region_without_segments_is_not_treated_as_blank() -> None:
    assert _service()._region_has_no_ink(AnswerRegion(id=104, segments=[])) is False


def test_blank_short_circuit_consumes_no_provider_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blank = _png(tmp_path, "blank.png", inked=False)
    db = MagicMock()
    run = BulkEvaluationRun(
        id=4,
        authorized_call_limit=20,
        calls_used=0,
        created_by_teacher_id=1,
        model_name="qwen3.8-27b-q4km",
    )
    item = BulkEvaluationItem(
        id=21, run_id=4, submission_id=62, question_id=72, stage="transcription",
        status="pending", provider_call_count=0, exception_codes=[], warnings=[],
    )
    region = AnswerRegion(
        id=105, segments=[AnswerRegionSegment(image_path="blank.png", order_index=1)]
    )

    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service.storage.resolve_relative = MagicMock(return_value=blank)
    service._next_transcription_item = MagicMock(return_value=item)
    service._refresh_counts = MagicMock()
    db.get.side_effect = lambda model, _id: region if model is AnswerRegion else User(id=1)

    transcription = MagicMock()
    monkeypatch.setattr(
        "app.services.bulk_evaluation_service.Qwen38VisualTranscriptionService",
        transcription,
    )

    service._process_transcription(run)

    transcription.return_value.create.assert_not_called()
    transcription.return_value.run.assert_not_called()
    assert run.calls_used == 0
    assert item.provider_call_count == 0
    assert item.status == "exception"
    assert item.exception_codes == ["probable_blank"]


def test_confirmed_transcription_of_identical_images_is_reused_without_a_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inked = _png(tmp_path, "inked.png", inked=True)
    db = MagicMock()
    run = BulkEvaluationRun(
        id=9,
        authorized_call_limit=20,
        calls_used=0,
        created_by_teacher_id=1,
        model_name="qwen3.8-27b-q4km",
    )
    item = BulkEvaluationItem(
        id=31, run_id=9, submission_id=62, question_id=72, stage="transcription",
        status="pending", provider_call_count=0, exception_codes=[], warnings=[],
    )
    region = AnswerRegion(
        id=106, segments=[AnswerRegionSegment(image_path="inked.png", order_index=1)]
    )
    reused = AnswerRegionOcrRun(
        id=555,
        answer_region_id=106,
        profile="qwen38_verbatim_visual",
        status="confirmed",
        draft_text="x = 4",
        bulk_verification_run_id=8,
        normalized_result={"confidence": "0.97"},
    )

    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service.storage.resolve_relative = MagicMock(return_value=inked)
    service._next_transcription_item = MagicMock(return_value=item)
    service._refresh_counts = MagicMock()
    service._audit_run = MagicMock()
    db.get.side_effect = lambda model, _id: region if model is AnswerRegion else User(id=1)
    db.scalar.return_value = reused

    transcription = MagicMock()
    monkeypatch.setattr(
        "app.services.bulk_evaluation_service.Qwen38VisualTranscriptionService",
        transcription,
    )

    service._process_transcription(run)

    transcription.return_value.create.assert_not_called()
    assert run.calls_used == 0
    assert item.provider_call_count == 0
    assert item.transcription_run_id == 555
    assert item.stage == "grading"
    assert region.manual_answer_text == "x = 4"
    assert service._audit_run.call_args[0][1] == "bulk_evaluation_transcription_reused"
    # The reuse audit keeps the link to the run that actually paid for the call.
    assert service._audit_run.call_args[0][3]["originating_bulk_run_id"] == 8


def test_reuse_never_accepts_a_merely_succeeded_transcription() -> None:
    # A run can succeed and still have been quarantined afterwards for low
    # confidence, an ambiguous symbol, or a formula disagreement. Only
    # _accept_or_quarantine_transcription promotes one to "confirmed", so that
    # is the status the reuse query is allowed to match.
    db = MagicMock()
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())

    service._reusable_transcription(AnswerRegion(id=107, segments=[]), "abc123")

    statement = str(db.scalar.call_args[0][0])
    assert "answer_region_ocr_runs.status = " in statement
    assert "answer_region_ocr_runs.prompt_version = " in statement
    assert "answer_region_ocr_runs.model_asset_sha256" in statement
    assert "answer_region_ocr_runs.mmproj_asset_sha256" in statement
    params = db.scalar.call_args[0][0].compile().params
    assert "confirmed" in params.values()


def test_interrupted_running_items_become_uncertain_without_retry() -> None:
    db = MagicMock()
    item = BulkEvaluationItem(
        id=7,
        run_id=3,
        submission_id=2,
        question_id=5,
        status="running",
        stage="transcription",
        exception_codes=[],
        warnings=[],
    )
    db.scalars.return_value.all.return_value = [item]
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._refresh_counts = MagicMock()

    service._mark_running_uncertain(
        BulkEvaluationRun(id=3), "Interrupted call; explicit retry required"
    )

    assert item.status == "uncertain"
    assert item.exception_codes == ["provider_contract_failure"]
    assert "explicit retry" in item.warnings[0]
    service._refresh_counts.assert_called_once()

def test_interrupted_run_also_closes_the_transcription_row_it_was_waiting_on() -> None:
    """Reclaiming the item alone leaves the provider ledger lying.

    A real interrupted run left AnswerRegionOcrRun 88 with status "running" and
    completed_at NULL from one day to the next, because recovery only ever
    touched BulkEvaluationItem. Anything reading the ledger then believes a
    provider call is still in flight for a process that no longer exists."""
    db = MagicMock()
    item = BulkEvaluationItem(
        id=7,
        run_id=3,
        submission_id=2,
        question_id=5,
        status="running",
        stage="transcription",
        exception_codes=[],
        warnings=[],
        transcription_run_id=88,
    )
    orphan = AnswerRegionOcrRun(id=88, status="running", warnings=[])
    db.scalars.return_value.all.return_value = [item]
    db.get.return_value = orphan
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._refresh_counts = MagicMock()

    service._mark_running_uncertain(
        BulkEvaluationRun(id=3), "Interrupted call; explicit retry required"
    )

    assert orphan.status == "failed"
    assert orphan.completed_at is not None
    assert "interrupted_run_reclaimed" in orphan.warnings
    assert orphan.error


def test_recovery_heals_an_orphan_whose_item_was_already_reclaimed() -> None:
    """The exact shape seen in production.

    The pause had already flipped item 1 to "uncertain", so a recovery that
    reconciles only *currently running* items found nothing to do and left
    AnswerRegionOcrRun 88 running overnight. Reconciliation keys off ledger
    state so the orphan is still closed."""
    db = MagicMock()
    already_reclaimed = BulkEvaluationItem(
        id=1,
        run_id=3,
        submission_id=2,
        question_id=5,
        status="uncertain",
        stage="transcription",
        exception_codes=["provider_contract_failure"],
        warnings=[],
        transcription_run_id=88,
    )
    orphan = AnswerRegionOcrRun(id=88, status="running", warnings=[])
    # No item is "running" any more; the sweep must still find the orphan.
    db.scalars.return_value.all.return_value = [already_reclaimed]
    db.get.return_value = orphan
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._refresh_counts = MagicMock()

    service._release_orphaned_transcriptions(
        BulkEvaluationRun(id=3), "Interrupted run closed", datetime.now(UTC)
    )

    assert orphan.status == "failed"
    assert orphan.completed_at is not None
    assert "interrupted_run_reclaimed" in orphan.warnings


def test_interrupted_run_does_not_rewrite_a_finished_transcription() -> None:
    """Only in-flight rows are reclaimed; a succeeded transcript is evidence
    and must not be restamped as failed by a later recovery."""
    db = MagicMock()
    item = BulkEvaluationItem(
        id=8,
        run_id=3,
        submission_id=2,
        question_id=5,
        status="running",
        stage="transcription",
        exception_codes=[],
        warnings=[],
        transcription_run_id=90,
    )
    finished = AnswerRegionOcrRun(id=90, status="succeeded", warnings=[])
    db.scalars.return_value.all.return_value = [item]
    db.get.return_value = finished
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._refresh_counts = MagicMock()

    service._mark_running_uncertain(BulkEvaluationRun(id=3), "Interrupted call")

    assert finished.status == "succeeded"
    assert finished.error is None


def test_bulk_audit_payload_records_hashes_and_counts_not_raw_answer_text() -> None:
    db = MagicMock()
    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    run = BulkEvaluationRun(
        id=9,
        status="grading",
        stage="grading",
        calls_used=12,
    )

    service._audit_run(
        run,
        "bulk_test_event",
        1,
        {"evidence_sha256": "a" * 64, "item_count": 3},
    )

    audit = db.add.call_args.args[0]
    assert audit.payload_json["calls_used"] == 12
    assert audit.payload_json["evidence_sha256"] == "a" * 64
    assert "answer" not in " ".join(audit.payload_json).casefold()


def test_process_mapping_reuses_existing_mappings_without_calling_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    run = BulkEvaluationRun(
        id=2,
        authorized_call_limit=20,
        calls_used=4,
        created_by_teacher_id=1,
        model_name="qwen3.8-27b-q4km",
    )
    submission = Submission(id=62)
    teacher = User(id=1)
    region = AnswerRegion(id=101, segments=[])
    mapping = AnswerRegionMapping(
        id=201,
        submission_id=62,
        question_id=72,
        answer_region_id=101,
        confidence=Decimal("0.95"),
        answer_region=region,
        blocker_reason=None,
    )
    item = BulkEvaluationItem(
        id=15,
        run_id=2,
        submission_id=62,
        question_id=72,
        stage="mapping",
        status="pending",
        provider_call_count=0,
    )

    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._next_mapping_submission = MagicMock(return_value=62)
    db.scalar.return_value = submission
    db.get.return_value = teacher
    db.scalars.side_effect = [
        MagicMock(all=MagicMock(return_value=[item])),  # items
        MagicMock(all=MagicMock(return_value=[mapping])),  # existing mappings
    ]
    service._refresh_counts = MagicMock()
    service._audit_run = MagicMock()

    mock_prep = MagicMock()
    monkeypatch.setattr(
        "app.services.bulk_evaluation_service.LocalScriptPreparationService",
        mock_prep,
    )

    service._process_mapping(run)

    mock_prep.assert_not_called()
    assert item.status == "pending"
    assert item.stage == "transcription"
    assert item.mapping_id == 201
    assert item.answer_region_id == 101
    assert mapping.bulk_policy_verified is True
    assert mapping.bulk_verification_run_id == 2
    service._audit_run.assert_called_once()
    assert service._audit_run.call_args[0][1] == "bulk_evaluation_mapping_reused"


def test_failed_thinking_repair_quarantines_item_as_ambiguous_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    run = BulkEvaluationRun(
        id=2,
        authorized_call_limit=20,
        calls_used=4,
        created_by_teacher_id=1,
        model_name="qwen3.8-27b-q4km",
    )
    region = AnswerRegion(id=101, question_id=72)
    teacher = User(id=1)
    ocr_run = AnswerRegionOcrRun(
        id=102,
        profile="qwen38_thinking_repair",
        call_limit=3,
        calls_used=3,
        status="failed",
        error=(
            "The surviving pixels remain visually unresolved after bounded reasoning. "
            "No transcript was accepted."
        ),
        warnings=["teacher_review_required", "thinking_repair_visual_resolution_unresolved"],
    )
    item = BulkEvaluationItem(
        id=15,
        run_id=2,
        submission_id=62,
        question_id=72,
        stage="transcription",
        status="running",
        answer_region_id=101,
        transcription_run_id=102,
        provider_call_count=1,
        exception_codes=[],
        warnings=[],
    )

    service = BulkEvaluationService(db, settings=get_settings(), storage=MagicMock())
    service._next_transcription_item = MagicMock(return_value=item)
    service._refresh_counts = MagicMock()

    db.get.side_effect = lambda model, pk: {
        (AnswerRegion, 101): region,
        (User, 1): teacher,
        (AnswerRegionOcrRun, 102): ocr_run,
    }.get((model, pk))

    mock_qwen_service = MagicMock()
    monkeypatch.setattr(
        "app.services.bulk_evaluation_service.Qwen38VisualTranscriptionService",
        lambda _db: mock_qwen_service,
    )

    service._process_transcription(run)

    mock_qwen_service.run_thinking_repair.assert_called_once_with(102)
    assert item.status == "exception"
    assert "ambiguous_symbol" in item.exception_codes
    assert "The surviving pixels remain visually unresolved" in item.warnings[0]
    assert run.calls_used == 7  # 4 + 3 consumed
    assert item.provider_call_count == 4  # 1 + 3
    service._refresh_counts.assert_called_once()
