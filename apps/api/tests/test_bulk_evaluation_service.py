from __future__ import annotations

import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings
from app.models import BulkEvaluationItem, BulkEvaluationRun
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
            "contains multiple PDFs",
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
    source = Path(
        "apps/api/app/services/bulk_evaluation_service.py"
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
