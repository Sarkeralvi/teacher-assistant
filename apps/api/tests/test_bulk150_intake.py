"""PD probes: ZIP intake, limits, identity derivation and route mapping (synthetic data only).

Everything here drives the REAL ``BulkEvaluationService`` intake (``create_from_zip`` and the
offline ``_inspect_archive``) and, for PD-2/PD-3, the REAL bulk-create route through a
``TestClient``. The only things replaced are provider construction (the harness fake brain),
authentication (a dependency override that returns the seeded teacher) and the RQ queue (a
recorder, so nothing ever reaches Redis).

Conventions (see ``tests/bulk150_harness.py``):

* a proven defect is ``xfail(strict=True, raises=AssertionError, reason="GAP <root-cause>: ...")``
  so the suite stays green and the xfail turns into a hard failure the day somebody fixes it;
* inside a GAP test every setup check goes through :func:`precondition` (``pytest.fail``, not an
  ``AssertionError``), so a broken scenario shows as a FAILURE instead of a wrong-reason XFAIL;
  only the genuine desired-behaviour assertion is a plain ``assert``;
* a product/policy choice is characterised by a passing test that pins what happens today;
* a suspected gap that does not exist is a normal passing regression test.

Probe ids: PD-1 order of checks, PD-2 route mapping, PD-3 re-upload, PD-4 identity derivation,
PD-5 wrong-file shapes, PD-6 offline seam, PD-7 stale staging.
"""

from __future__ import annotations

import errno
import hashlib
import json
import statistics
import struct
import threading
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi import Depends, HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.api.routes import bulk_evaluations as bulk_routes
from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, BulkEvaluationItem, BulkEvaluationRun, Submission, User
from app.services import bulk_evaluation_service as bulk_module
from app.services.bulk_evaluation_service import (
    ArchiveUnit,
    BulkEvaluationError,
    BulkEvaluationService,
)
from app.services.storage import LocalStorage
from app.services.submission_processing import extract_page_images as render_pdf_pages
from packages.brain.policy import brain_policy_from_settings
from tests.bulk150_harness import (  # noqa: F401  (fixtures are imported, not used by name)
    FakeBulkBrainProvider,
    HarnessStorage,
    ProcessKilled,
    Seeded,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    import_zip,
    install_fake_brain,
    make_settings,
    other_session,
    precondition,
    seed_assessment,
)
from tests.bulk150_poison import (
    PoisonedZip,
    bad_crc_zip,
    deflate64_zip,
    duplicate_member_zip,
    good_pdf_bytes,
    oversized_png_zip,
    password_protected_pdf_zip,
    wrapper_folder_zip,
    zero_byte_pdf_zip,
)

# =========================================================================== shared helpers


def _write_zip(
    path: Path,
    members: Sequence[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return path


def _blank_pdf(pages: int, size: tuple[int, int] = (10, 10)) -> bytes:
    """A valid PDF of ``pages`` blank pages; tiny on disk, as many pages as you like."""

    doc = pymupdf.open()
    try:
        for _ in range(pages):
            doc.new_page(width=size[0], height=size[1])
        return doc.tobytes()
    finally:
        doc.close()


def _offline_service(tmp_path: Path, **overrides: Any) -> BulkEvaluationService:
    """The intake service with NO database and no real storage (inspection needs neither)."""

    settings = make_settings(tmp_path / "offline-storage", **overrides)
    return BulkEvaluationService(None, settings=settings, storage=object())  # type: ignore[arg-type]


def _inspect(
    tmp_path: Path, members: Sequence[tuple[str, bytes]], **overrides: Any
) -> tuple[list[ArchiveUnit], str | None, list[dict[str, object]]]:
    archive_path = _write_zip(tmp_path / "inspect.zip", members)
    with zipfile.ZipFile(archive_path) as archive:
        return _offline_service(tmp_path, **overrides)._inspect_archive(archive)


def _try_inspect(
    tmp_path: Path, members: Sequence[tuple[str, bytes]], **overrides: Any
) -> tuple[list[ArchiveUnit] | None, BulkEvaluationError | None]:
    """``(units, None)`` or ``(None, refusal)``. Any other exception is a real failure."""

    try:
        units, _, _ = _inspect(tmp_path, members, **overrides)
    except BulkEvaluationError as exc:
        return None, exc
    return units, None


def _ids(units: Sequence[ArchiveUnit]) -> list[tuple[str, str | None]]:
    return [(unit.identifier, unit.student_name) for unit in units]


def _manifest(rows: Sequence[str], header: str = "source,student_identifier,student_name") -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def _clear_utf8_flag(path: Path) -> None:
    """Clear general-purpose bit 11 (UTF-8 names) in every local and central header.

    The name bytes stay UTF-8; the archive just no longer SAYS so, which is how a number of
    desktop zippers write names. ``zipfile`` then decodes them as cp437.
    """

    raw = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while (cursor := raw.find(signature, cursor)) != -1:
            flags = struct.unpack("<H", raw[cursor + flag_offset : cursor + flag_offset + 2])[0]
            raw[cursor + flag_offset : cursor + flag_offset + 2] = struct.pack("<H", flags & ~0x800)
            cursor += 4
    path.write_bytes(bytes(raw))


class CountingStorage(HarnessStorage):
    """HarnessStorage that records every page-image path the intake asks for.

    ``require_active_storage`` only compares roots, so this subclass is accepted by
    ``import_zip``. Every rasterised PDF page and every decoded image page goes through
    ``page_image_path``, so ``len(page_requests)`` is the number of pages the intake rendered.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.page_requests: list[tuple[int, int]] = []

    def page_image_path(self, submission_id: int, page_no: int) -> Any:
        self.page_requests.append((submission_id, page_no))
        return super().page_image_path(submission_id, page_no)


@dataclass
class Intake:
    run: BulkEvaluationRun | None
    refusal: BulkEvaluationError | None
    raw: BaseException | None
    identifiers: list[str]
    new_files: list[str]
    pages_rendered: int
    pdfs_rasterised: int
    staged_left: list[str]

    @property
    def failure(self) -> str:
        return repr(self.refusal or self.raw)


class IntakeBench:
    """Real ``create_from_zip`` on one seeded assessment, with the rasteriser instrumented.

    ``run`` may be called several times on the same assessment (re-import scenarios). Nothing
    is registered with the fake provider: no model call ever happens, only intake.
    """

    def __init__(
        self,
        db: Session,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        self.db = db
        self.settings = settings
        self.root = Path(settings.local_storage_root)
        self.seeded: Seeded = seed_assessment(db, questions=1)
        corpus = build_zip(tmp_path / "bench-dummy.zip", students=1, pages=1, questions=1)
        self.provider = FakeBulkBrainProvider(corpus)
        install_fake_brain(monkeypatch, self.provider, settings)
        self.storage = CountingStorage(settings)
        self.rasterised: list[int] = []
        real = bulk_module.extract_page_images

        def spy(**kwargs: Any) -> list[str]:
            self.rasterised.append(kwargs["submission_id"])
            return real(**kwargs)

        monkeypatch.setattr(bulk_module, "extract_page_images", spy)
        self.corpus = corpus

    def files(self) -> set[Path]:
        return {path for path in self.root.rglob("*") if path.is_file()}

    def staged(self) -> list[str]:
        staging = self.root / "uploads" / "bulk_staging"
        return sorted(path.name for path in staging.glob("*")) if staging.exists() else []

    def run(self, archive_path: Path, *, max_calls: int = 1500) -> Intake:
        before = self.files()
        pages_before = len(self.storage.page_requests)
        pdfs_before = len(self.rasterised)
        run = refusal = raw = None
        try:
            run = import_zip(
                self.db,
                seeded=self.seeded,
                corpus=self.corpus,
                provider=self.provider,
                settings=self.settings,
                storage=self.storage,
                archive_path=archive_path,
                register=False,
                maximum_provider_calls=max_calls,
            )
        except BulkEvaluationError as exc:
            self.db.rollback()
            refusal = exc
        except BaseException as exc:  # the exception TYPE is part of what is being probed
            self.db.rollback()
            raw = exc
        self.db.expire_all()
        return Intake(
            run=run,
            refusal=refusal,
            raw=raw,
            identifiers=self.identifiers(),
            new_files=sorted(str(path.relative_to(self.root)) for path in self.files() - before),
            pages_rendered=len(self.storage.page_requests) - pages_before,
            pdfs_rasterised=len(self.rasterised) - pdfs_before,
            staged_left=self.staged(),
        )

    def identifiers(self) -> list[str]:
        return [
            row.student_identifier
            for row in self.db.scalars(
                select(Submission)
                .where(Submission.assessment_id == self.seeded.assessment.id)
                .order_by(Submission.id)
            ).all()
        ]


@pytest.fixture(name="bench")
def _bench_fixture(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> IntakeBench:
    return IntakeBench(db_session, bulk_env, monkeypatch, tmp_path)


# =========================================================================== PD-4 identity
# Derivation lives in BulkEvaluationService._inspect_archive (bulk_evaluation_service.py:517-541).
# These tests call the REAL method with no database (see PD-6 for why that works).


@pytest.mark.parametrize("folder", ["S.001", "Dr. A. Rahman", "Md. Karim"])
def test_a_dotted_student_folder_keeps_its_full_name(tmp_path: Path, folder: str) -> None:
    units, refusal = _try_inspect(tmp_path, [(f"{folder}/script.pdf", b"x")])
    precondition(refusal is None, f"refused: {refusal}")
    precondition(units is not None and len(units) == 1 and units[0].kind == "pdf", "one pdf unit")
    assert units is not None
    assert units[0].identifier == folder, (
        f"folder {folder!r} became student {units[0].identifier!r}"
    )


def test_a_dotted_folder_is_stored_under_its_full_name(bench: IntakeBench, tmp_path: Path) -> None:
    archive = _write_zip(
        tmp_path / "dotted.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("Md. Karim/script.pdf", good_pdf_bytes("S002"))],
    )
    result = bench.run(archive)
    precondition(result.run is not None, f"intake failed: {result.failure}")
    assert "Md. Karim" in result.identifiers, f"stored identifiers: {result.identifiers}"


def test_two_dotted_folders_collapse_into_a_duplicate_refusal_not_a_merge(tmp_path: Path) -> None:
    """CONTROL (updated for F05): dotted folders are distinct students; only a REAL clash refuses.

    The old control pinned the stem defect ('Md. Karim' and 'Md. Rahim' both became 'Md' and were
    refused). Now those are two units, and the duplicate refusal (still a refusal, never a merge)
    needs identifiers that genuinely collide: 'Md. Karim' and 'md. karim' casefold to one name.
    """

    units, refusal = _try_inspect(
        tmp_path,
        [("Md. Karim/script.pdf", b"x"), ("Md. Rahim/script.pdf", b"x")],
    )
    assert refusal is None and units is not None, f"refused: {refusal}"
    assert _ids(units) == [("Md. Karim", None), ("Md. Rahim", None)]
    assert [len(unit.members) for unit in units] == [1, 1]

    units, refusal = _try_inspect(
        tmp_path,
        [("Md. Karim/script.pdf", b"x"), ("md. karim/script.pdf", b"x")],
    )
    assert units is None and refusal is not None
    assert "duplicate student identifiers" in str(refusal)


def test_identity_derivation_that_is_already_right(tmp_path: Path) -> None:
    """REFUTED: dotted ROOT pdfs, dotted IMAGE folders, case collisions, Bengali (UTF-8) names."""

    units, _, _ = _inspect(
        tmp_path,
        [("alice.final.pdf", b"x"), ("S.001/p1.png", b"x"), ("আলিম.pdf", b"x")],
    )
    by_source = {unit.source: unit.identifier for unit in units}
    assert by_source == {
        "alice.final.pdf": "alice.final",  # only the LAST suffix is dropped for a root pdf
        "S.001": "S.001",  # an image folder keeps its dots
        "আলিম.pdf": "আলিম",  # Bengali, UTF-8 flagged member name
    }
    units, refusal = _try_inspect(tmp_path, [("Alice.pdf", b"x"), ("alice.pdf", b"x")])
    assert units is None and refusal is not None
    assert "duplicate student identifiers" in str(refusal)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP identifier-not-unicode-normalised: identifiers are compared with casefold() only "
        "(bulk_evaluation_service.py:527 and :573), so 'Jose\\u0301' (NFD, how macOS names files) "
        "and 'Jos\\u00e9' (NFC, Windows) are two different students that LOOK identical."
    ),
)
def test_nfc_and_nfd_spellings_of_one_identifier_are_duplicates(tmp_path: Path) -> None:
    nfc = unicodedata.normalize("NFC", "José")
    nfd = unicodedata.normalize("NFD", "José")
    precondition(
        nfc != nfd and len(nfc) != len(nfd), "the two spellings must differ in code points"
    )
    units, refusal = _try_inspect(tmp_path, [(f"{nfc}.pdf", b"x"), (f"{nfd}.pdf", b"x")])
    assert refusal is not None, f"accepted as two students: {_ids(units or [])}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP identifier-not-unicode-normalised: _reject_existing_identifiers (bulk_evaluation_"
        "service.py:572-592) also compares casefolded, un-normalised strings, so re-importing a "
        "cohort zipped on another OS (NFC vs NFD) slips past the 'already exists' guard and "
        "creates a SECOND submission for the same student in the same assessment."
    ),
)
def test_a_reimport_in_another_unicode_form_is_refused_as_already_existing(
    bench: IntakeBench, tmp_path: Path
) -> None:
    nfc = unicodedata.normalize("NFC", "José")
    nfd = unicodedata.normalize("NFD", "José")
    first = bench.run(_write_zip(tmp_path / "a.zip", [(f"{nfc}.pdf", good_pdf_bytes("S001"))]))
    precondition(first.run is not None, f"the first import failed: {first.failure}")
    second = bench.run(_write_zip(tmp_path / "b.zip", [(f"{nfd}.pdf", good_pdf_bytes("S001"))]))
    precondition(second.raw is None, f"raw exception: {second.raw!r}")
    assert second.run is None, f"accepted; assessment now holds {len(second.identifiers)} 'José'"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP zip-member-name-encoding-guess-silent: a member whose name is UTF-8 but whose "
        "header does not carry the UTF-8 flag (several desktop zippers) is decoded by zipfile as "
        "cp437, so a Bengali or accented name becomes mojibake and is stored as the student's "
        "identifier without any warning."
    ),
)
def test_a_utf8_name_without_the_utf8_flag_is_not_stored_as_mojibake(tmp_path: Path) -> None:
    archive_path = _write_zip(tmp_path / "flagless.zip", [("আলিম.pdf", b"x")])
    _clear_utf8_flag(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        precondition(archive.infolist()[0].flag_bits & 0x800 == 0, "the UTF-8 flag must be clear")
        units, _, _ = _offline_service(tmp_path)._inspect_archive(archive)
    assert units[0].identifier == "আলিম", f"stored as {units[0].identifier!r}"


@pytest.mark.parametrize(
    ("header", "row", "want_identifier", "want_name"),
    [
        pytest.param(
            "source,student_name,student_identifier",
            "S001.pdf,Rahman, Abdul,ID-001",
            "ID-001",
            "Rahman, Abdul",
            id="name-before-id-silent-wrong-identifier",
        ),
        pytest.param(
            "source,student_identifier,student_name",
            "S001.pdf,ID-001,Rahman, Abdul",
            "ID-001",
            "Rahman, Abdul",
            id="standard-order-name-truncated",
        ),
    ],
)
def test_a_malformed_manifest_row_is_refused_not_silently_reinterpreted(
    tmp_path: Path, header: str, row: str, want_identifier: str, want_name: str
) -> None:
    units, refusal = _try_inspect(
        tmp_path, [("S001.pdf", b"x"), ("manifest.csv", _manifest([row], header))]
    )
    # Precondition: the archive is judged one way or the other (a raw exception would propagate).
    assert refusal is not None, (
        f"accepted: stored as identifier={units[0].identifier!r} name={units[0].student_name!r} "
        f"(wanted {want_identifier!r} / {want_name!r})"
    )


def test_a_malformed_manifest_row_refusal_names_the_line_and_the_cause(tmp_path: Path) -> None:
    """F05: the refusal says which row (line + source) and why, so it can be found in 150 rows."""

    manifest = _manifest(["S001.pdf,ID-001,One", "S002.pdf,ID-002,Rahman, Abdul"])
    units, refusal = _try_inspect(
        tmp_path, [("S001.pdf", b"x"), ("S002.pdf", b"x"), ("manifest.csv", manifest)]
    )
    assert units is None and refusal is not None
    assert "line 3" in str(refusal), f"refusal text: {refusal}"
    assert "S002.pdf" in str(refusal), f"refusal text: {refusal}"
    assert "more columns than the header" in str(refusal), f"refusal text: {refusal}"


@pytest.mark.parametrize("tail", [",", ",,", ", "], ids=["one-empty", "two-empty", "blank"])
def test_a_trailing_empty_manifest_cell_is_still_accepted(tmp_path: Path, tail: str) -> None:
    """F05 keeps the harmless case: a spreadsheet's trailing separator is not a malformed row."""

    manifest = _manifest([f"S001.pdf,ID-1,One{tail}"])
    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), ("manifest.csv", manifest)])
    assert refusal is None, f"refused: {refusal}"
    assert units is not None and _ids(units) == [("ID-1", "One")]


def test_a_duplicate_identifier_refusal_names_both_colliding_sources(tmp_path: Path) -> None:
    """F05: the two sources that produced the same identifier are both named."""

    units, refusal = _try_inspect(tmp_path, [("Alice.pdf", b"x"), ("alice.pdf", b"x")])
    assert units is None and refusal is not None
    assert "'Alice.pdf'" in str(refusal) and "'alice.pdf'" in str(refusal), str(refusal)


def test_an_unknown_manifest_source_refusal_names_every_offender_up_to_five(
    tmp_path: Path,
) -> None:
    """F05: several unknown sources are all listed (sorted); beyond five the rest are counted."""

    rows = [f"X{number}.pdf,ID-{number},N{number}" for number in range(1, 8)]
    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), ("manifest.csv", _manifest(rows))])
    assert units is None and refusal is not None
    text = str(refusal)
    assert all(f"'X{number}.pdf'" in text for number in range(1, 6)), text
    assert "'X6.pdf'" not in text and "and 2 more" in text, text


def test_quoted_manifest_cells_with_commas_and_quotes_survive(tmp_path: Path) -> None:
    """REFUTED: a properly quoted name/identifier is kept intact (comma, apostrophe, quotes)."""

    manifest = _manifest(['S001.pdf,"ID,1","O\'Brien ""Bob"", Jr."'])
    units, _, _ = _inspect(tmp_path, [("S001.pdf", b"x"), ("manifest.csv", manifest)])
    assert _ids(units) == [("ID,1", 'O\'Brien "Bob", Jr.')]


def test_a_duplicate_identifier_refusal_names_the_identifier(tmp_path: Path) -> None:
    units, refusal = _try_inspect(tmp_path, [("Alice.pdf", b"x"), ("alice.pdf", b"x")])
    precondition(units is None and refusal is not None, "the duplicate must be refused")
    assert "alice" in str(refusal).casefold(), f"refusal text: {refusal}"


def test_an_unknown_manifest_source_is_named_in_the_refusal(tmp_path: Path) -> None:
    manifest = _manifest(["S001/script.pdf,ID-001,One"])
    units, refusal = _try_inspect(tmp_path, [("S001/script.pdf", b"x"), ("manifest.csv", manifest)])
    precondition(units is None and refusal is not None, "the unknown source must be refused")
    assert "S001/script.pdf" in str(refusal), f"refusal text: {refusal}"


@pytest.mark.parametrize(
    "source",
    ["S001/script.pdf", "./S001.pdf", "s001.pdf", "S001", "scripts/S001.pdf"],
)
def test_manifest_source_written_in_another_style_is_refused_never_ignored(
    tmp_path: Path, source: str
) -> None:
    """REFUTED (silent part): a source that does not match a ZIP source EXACTLY is refused."""

    units, refusal = _try_inspect(
        tmp_path,
        [("S001.pdf", b"x"), ("manifest.csv", _manifest([f"{source},ID-001,One"]))],
    )
    assert units is None and refusal is not None
    assert "refers to a source that is not in the ZIP" in str(refusal)


@pytest.mark.parametrize(
    ("label", "raw", "message"),
    [
        pytest.param(
            "semicolon-delimited (Excel with a European list separator)",
            b"source;student_identifier;student_name\nS001.pdf;ID-1;One\n",
            "needs source, student_identifier, and student_name columns",
            id="semicolon",
        ),
        pytest.param(
            "capitalised header",
            b"Source,Student_Identifier,Student_Name\nS001.pdf,ID-1,One\n",
            "needs source, student_identifier, and student_name columns",
            id="capitalised-header",
        ),
        pytest.param(
            "space after the commas in the header",
            b"source, student_identifier, student_name\nS001.pdf,ID-1,One\n",
            "needs source, student_identifier, and student_name columns",
            id="spaced-header",
        ),
        pytest.param(
            "Windows-1252 file ('CSV' instead of 'CSV UTF-8') with an accented name",
            "source,student_identifier,student_name\nS001.pdf,ID-1,José\n".encode("cp1252"),
            "manifest.csv must be UTF-8",
            id="cp1252",
        ),
        pytest.param(
            "U+2028 inside a name (pasted from Word or a web page)",
            "source,student_identifier,student_name\nS001.pdf,ID-1,Abdul Karim\n".encode(),
            "refers to a source that is not in the ZIP",
            id="line-separator-in-name",
        ),
    ],
)
def test_manifest_dialects_that_spreadsheets_write_are_refused_never_half_read(
    tmp_path: Path, label: str, raw: bytes, message: str
) -> None:
    """REFUTED (silent part): every one of these is refused, none yields a wrong identity.

    The last row shows the cost of ``text.splitlines()`` (it splits on U+2028 and other
    separators ``csv`` would have kept inside a quoted cell): refused, but with a message that
    blames the wrong thing. Message quality is the already-proven intake-refusal-omits-offender
    gap; nothing here is accepted.
    """

    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), ("manifest.csv", raw)])
    assert units is None and refusal is not None, label
    assert message in str(refusal), f"{label}: {refusal}"


@pytest.mark.parametrize("spelling", ["S1/", "S1\\", "./S1"])
def test_manifest_sources_with_a_trailing_slash_or_backslash_match_the_folder(
    tmp_path: Path, spelling: str
) -> None:
    """REFUTED: Windows-style and trailing-slash spellings of a FOLDER source resolve correctly.

    ('./S1' does not: it is refused, as the unknown-source rule says, so the loop stops there.)
    """

    members = [
        ("S1/p1.png", b"x"),
        ("S2.pdf", b"x"),
        ("manifest.csv", _manifest([f"{spelling},ID-1,One"])),
    ]
    units, refusal = _try_inspect(tmp_path, members)
    if spelling.startswith("./"):
        assert units is None and refusal is not None
        return
    assert units is not None, refusal
    assert _ids(units) == [("ID-1", "One"), ("S2", None)]


def test_manifest_gaps_fall_back_to_the_file_name_silently(tmp_path: Path) -> None:
    """POLICY_QUESTION: blank identifier cell / unlisted source -> the raw file stem, no warning.

    With scan-named files (the case a manifest exists for) the fallback identity is 'scan_0002',
    which says nothing about the student. Nothing in the unit payload records that the
    identifier was a fallback.
    """

    members = [("scan_0001.pdf", b"x"), ("scan_0002.pdf", b"x"), ("scan_0003.pdf", b"x")]
    manifest = _manifest(["scan_0001.pdf,ID-ONE,One", "scan_0002.pdf,,Two"])
    units, _, payload = _inspect(tmp_path, [*members, ("manifest.csv", manifest)])
    assert _ids(units) == [("ID-ONE", "One"), ("scan_0002", "Two"), ("scan_0003", None)]
    assert all(
        set(entry) == {"source", "student_identifier", "student_name", "file_count", "kind"}
        for entry in payload
    )  # no 'identifier_source' / fallback flag anywhere


def test_an_appledouble_sidecar_is_not_a_student(tmp_path: Path) -> None:
    units, refusal = _try_inspect(
        tmp_path, [("S001.pdf", b"x"), ("._S001.pdf", b"\x00\x05\x16\x07")]
    )
    precondition(refusal is None, f"refused: {refusal}")
    assert units is not None
    assert [unit.identifier for unit in units] == ["S001"], f"students: {_ids(units)}"


# =========================================================================== PD-1 order of checks


def test_an_oversize_cohort_is_refused_before_any_page_is_rendered(
    bench: IntakeBench, tmp_path: Path
) -> None:
    one = _blank_pdf(6)
    members = [(f"S{n:03d}.pdf", one) for n in range(1, 151)]
    result = bench.run(_write_zip(tmp_path / "cohort.zip", members))
    precondition(result.raw is None, f"raw exception: {result.raw!r}")
    precondition(
        result.refusal is not None and "720-page bulk limit" in str(result.refusal),
        f"not refused for the page cap: {result.failure}",
    )
    assert result.pages_rendered == 0, (
        f"{result.pdfs_rasterised} PDFs / {result.pages_rendered} pages were rendered "
        "before the page cap fired"
    )


def test_a_single_huge_pdf_is_refused_without_rendering_its_pages(
    bench: IntakeBench, tmp_path: Path
) -> None:
    pdf = _blank_pdf(3000)
    result = bench.run(_write_zip(tmp_path / "huge.zip", [("S001.pdf", pdf)]))
    precondition(result.raw is None, f"raw exception: {result.raw!r}")
    precondition(
        result.refusal is not None and "720-page bulk limit" in str(result.refusal),
        f"not refused for the page cap: {result.failure}",
    )
    assert result.pages_rendered == 0, (
        f"a {len(pdf) // 1024} KB PDF caused {result.pages_rendered} page renders "
        "before the cap was enforced"
    )


def test_submission_count_cap_is_enforced_before_anything_is_rendered(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFUTED: the submission cap (and every central-directory limit) fires pre-render."""

    settings = make_settings(Path(bulk_env.local_storage_root), BULK_MAX_SUBMISSIONS=3)
    bench = IntakeBench(db_session, settings, monkeypatch, tmp_path)
    members = [(f"S{n:03d}.pdf", good_pdf_bytes(f"S{n:03d}")) for n in range(1, 5)]
    result = bench.run(_write_zip(tmp_path / "four.zip", members))
    assert result.refusal is not None and "3-submission limit" in str(result.refusal)
    assert result.pages_rendered == 0 and result.pdfs_rasterised == 0
    assert result.identifiers == [] and result.new_files == []


def test_central_directory_limits_refuse_before_any_page_is_rendered(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """REFUTED: entry-count, member-size-ratio and unsupported-type limits are pre-render."""

    flood = [(f"S{n:04d}.pdf", b"x") for n in range(1001)]
    ratio = [("S001.pdf", b"\x00" * (3 * 1024 * 1024))]
    cases = {
        "more than 1,000 entries": _write_zip(tmp_path / "flood.zip", flood),
        "compression ratio is unsafe": _write_zip(
            tmp_path / "ratio.zip", ratio, compression=zipfile.ZIP_DEFLATED
        ),
        "Unsupported ZIP entry: notes.txt": _write_zip(
            tmp_path / "txt.zip", [("S001.pdf", good_pdf_bytes()), ("notes.txt", b"x")]
        ),
    }
    for message, archive in cases.items():
        result = bench.run(archive)
        assert result.refusal is not None and message in str(result.refusal), result.failure
        assert result.pages_rendered == 0 and result.pdfs_rasterised == 0, message
        assert result.identifiers == [] and result.new_files == [], message


def test_the_page_cap_cannot_be_raised_above_720_by_configuration() -> None:
    """POLICY_QUESTION: BULK_MAX_PAGES is clamped to 720 by the Settings schema (le=720).

    720 pages is 4.8 pages per student at the 150-student target. A real cohort whose scripts
    average more than that is refused by design and no environment variable can change it
    (docs/BULK_SUPERVISED_RUNBOOK.md still says 50 submissions / 500 pages; code says 180 / 720).
    """

    assert make_settings(Path("unused"), BULK_MAX_PAGES=720).bulk_max_pages == 720
    with pytest.raises(ValidationError):
        make_settings(Path("unused"), BULK_MAX_PAGES=721)
    assert 720 / 150 == pytest.approx(4.8)


def _scanned_pdf(pages: int) -> bytes:
    """A4 pages that each hold a 200-dpi, high-entropy JPEG: about as expensive as a real scan."""

    doc = pymupdf.open()
    try:
        for _ in range(pages):
            buffer = BytesIO()
            Image.effect_noise((1654, 2339), 48).save(buffer, format="JPEG", quality=70)
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=buffer.getvalue())
        return doc.tobytes()
    finally:
        doc.close()


def test_what_rendering_a_cohort_before_refusing_it_costs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """MEASUREMENT for PD-1: seconds of rasterising one upload request may spend before a refusal.

    Real rendering cost per scanned A4 page (2x zoom, PNG) times the 720-page cap. This is the
    work the page-cap check throws away when it fires only after the unit that crosses the cap
    (and that every later fail-late member also throws away: see the next test).
    """

    storage = HarnessStorage(make_settings(tmp_path / "render-storage"))
    results: dict[str, float] = {}
    for label, payload in (
        ("noise-scan (worst case: incompressible)", _scanned_pdf(6)),
        ("synthetic-text-page (the corpus the other probes use)", good_pdf_bytes("S001", pages=6)),
    ):
        pdf = tmp_path / "cost.pdf"
        pdf.write_bytes(payload)
        start = time.perf_counter()
        pages = render_pdf_pages(storage=storage, submission_id=1, uploaded_path=pdf, kind="pdf")
        per_page = (time.perf_counter() - start) / len(pages)
        results[label] = per_page
        with capsys.disabled():
            print(
                f"\nRENDER-COST {label}: pdf={pdf.stat().st_size // 1024}KB pages={len(pages)} "
                f"per_page={per_page * 1000:.0f}ms -> 720 pages ~ {720 * per_page:.0f}s "
                "inside one synchronous HTTP request"
            )
        assert len(pages) == 6
    assert all(value > 0 for value in results.values())


def test_a_bad_last_member_is_found_before_any_student_is_rendered(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """Fail-fast preflight (RC-17/RC-31, B9): every PDF is opened, never rendered, first.

    20 good scripts then an empty 'S021.pdf': the refusal names S021.pdf and not one page of the
    20 good scripts is rasterised (before B9 all 20 were rendered and rolled back).
    """

    members = [(f"S{n:03d}.pdf", good_pdf_bytes(f"S{n:03d}")) for n in range(1, 21)]
    members.append(("S021.pdf", b""))
    result = bench.run(_write_zip(tmp_path / "late.zip", members))
    precondition(result.run is None and result.refusal is not None, f"expected a refusal: {result}")
    assert "S021.pdf" in str(result.refusal)
    assert result.pages_rendered == 0 and result.pdfs_rasterised == 0


def test_a_pdf_page_is_rasterised_at_whatever_size_it_declares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """POLICY_QUESTION: PDF pages have no pixel ceiling, image pages do (Pillow's bomb limit).

    A 520-byte PDF with one 4000 x 4000 pt page (1.4 m square) becomes an 8000 x 8000 px PNG
    (64 megapixels) at the fixed 2x zoom. The page-count cap does not look at size, and the
    PDF path never consults Pillow, which refuses a 196 MP PNG. PDF allows pages up to 14,400 pt:
    at 2x that is 829 MP, about 2.5 GB of RGB, in the API process. NOT executed here (it could
    exhaust the machine); only the arithmetic is asserted.
    """

    storage = HarnessStorage(make_settings(tmp_path / "pagesize-storage"))
    doc = pymupdf.open()
    doc.new_page(width=4000, height=4000)
    pdf = tmp_path / "huge-page.pdf"
    pdf.write_bytes(doc.tobytes())
    doc.close()
    start = time.perf_counter()
    pages = render_pdf_pages(storage=storage, submission_id=1, uploaded_path=pdf, kind="pdf")
    elapsed = time.perf_counter() - start
    with Image.open(storage.resolve_relative(pages[0])) as image:
        size = image.size
    with capsys.disabled():
        print(
            f"\nPAGE-SIZE pdf={pdf.stat().st_size}B declared=4000x4000pt -> {size[0]}x{size[1]}px "
            f"{size[0] * size[1] / 1e6:.0f}MP in {elapsed:.2f}s"
        )
    assert size == (8000, 8000)
    assert (14400 * 2) ** 2 * 3 / 2**30 == pytest.approx(2.31, abs=0.01)  # GiB of RGB at the limit


# =========================================================================== route harness


class _RecordingQueue:
    def __init__(self, sink: list[tuple[str, tuple[Any, ...], dict[str, Any]]]) -> None:
        self.sink = sink

    def enqueue(self, func: Any, *args: Any, **kwargs: Any) -> None:
        self.sink.append((getattr(func, "__name__", repr(func)), args, kwargs))


@dataclass
class RouteResponse:
    status: int
    body: Any

    @property
    def detail(self) -> str:
        return str(self.body.get("detail")) if isinstance(self.body, dict) else str(self.body)


class RouteBench:
    """The REAL ``POST /assessments/{id}/bulk-evaluation-runs``; provider, auth, queue faked."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        self.db = db
        self.settings = settings
        self.root = Path(settings.local_storage_root)
        self.seeded = seed_assessment(db, questions=1)
        corpus = build_zip(tmp_path / "route-dummy.zip", students=1, pages=1, questions=1)
        self.provider = FakeBulkBrainProvider(corpus)
        adapter = install_fake_brain(monkeypatch, self.provider, settings)

        def policy(settings_arg: Settings, profile_id: str, **_: Any) -> Any:
            return brain_policy_from_settings(
                settings_arg, adapter_override=adapter, profile_id=profile_id.strip().lower()
            )

        monkeypatch.setattr(bulk_routes, "brain_policy_for_profile", policy)
        self.enqueued: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        monkeypatch.setattr(
            bulk_routes, "get_default_queue", lambda: _RecordingQueue(self.enqueued)
        )
        teacher_id = self.seeded.teacher.id

        def current_user(route_db: Session = Depends(get_db)) -> User:  # noqa: B008
            user = route_db.get(User, teacher_id)
            assert user is not None
            return user

        monkeypatch.setitem(app.dependency_overrides, get_current_user, current_user)
        self.client = TestClient(app)

    def files(self) -> set[Path]:
        return {path for path in self.root.rglob("*") if path.is_file()}

    def send(
        self,
        archive: Path,
        *,
        client: TestClient | None = None,
        name: str = "scripts.zip",
        marking_policy: str = "general",
        maximum_provider_calls: int = 1500,
    ) -> RouteResponse:
        """One real POST. Never touches ``self.db``, so it is safe to call from another thread."""

        response = (client or self.client).post(
            f"/assessments/{self.seeded.assessment.id}/bulk-evaluation-runs",
            data={
                "grading_run_id": str(self.seeded.grading_run.id),
                "provider": self.provider.provider_name,
                "expected_model": self.provider.model_name,
                "marking_policy": marking_policy,
                "maximum_provider_calls": str(maximum_provider_calls),
                "local_only_confirmed": "true",
                "strict_auto_pass_confirmed": "true",
                "draft_only_confirmed": "true",
            },
            files={"file": (name, archive.read_bytes(), "application/zip")},
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return RouteResponse(response.status_code, body)

    def post(self, archive: Path, *, name: str = "scripts.zip", **form: Any) -> RouteResponse:
        response = self.send(archive, name=name, **form)
        self.db.expire_all()
        return response

    def submission_identifiers(self) -> list[str]:
        return [
            row.student_identifier
            for row in self.db.scalars(
                select(Submission)
                .where(Submission.assessment_id == self.seeded.assessment.id)
                .order_by(Submission.id)
            ).all()
        ]

    def runs(self) -> list[BulkEvaluationRun]:
        return list(
            self.db.scalars(
                select(BulkEvaluationRun)
                .where(BulkEvaluationRun.assessment_id == self.seeded.assessment.id)
                .order_by(BulkEvaluationRun.id)
            ).all()
        )

    def submission_count(self) -> int:
        return int(
            self.db.scalar(
                select(func.count(Submission.id)).where(
                    Submission.assessment_id == self.seeded.assessment.id
                )
            )
            or 0
        )


@pytest.fixture(name="route")
def _route_fixture(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> RouteBench:
    return RouteBench(db_session, bulk_env, monkeypatch, tmp_path)


def _good_cohort(path: Path, students: int = 2) -> Path:
    return _write_zip(
        path, [(f"S{n:03d}.pdf", good_pdf_bytes(f"S{n:03d}")) for n in range(1, students + 1)]
    )


def test_the_route_harness_is_sound_a_clean_cohort_is_accepted_and_enqueued_once(
    route: RouteBench, tmp_path: Path
) -> None:
    """Sanity for every route probe below: the happy path works, so a refusal means something."""

    response = route.post(_good_cohort(tmp_path / "good.zip"))
    assert response.status == 202, response.body
    run_id = response.body["id"]
    assert route.enqueued == [("run_bulk_evaluation_next_job", (run_id,), route.enqueued[0][2])]
    assert route.submission_count() == 2 and len(route.runs()) == 1


# =========================================================================== PD-2 route mapping


def _poison(kind: str, tmp_path: Path) -> PoisonedZip:
    path = tmp_path / f"{kind}.zip"
    return {
        "password_pdf": password_protected_pdf_zip,
        "zero_byte_pdf": zero_byte_pdf_zip,
        "bad_crc": bad_crc_zip,
        "deflate64": deflate64_zip,
        "png_196mp": lambda p: oversized_png_zip(p, width=14000, height=14000),
        "duplicate_member": duplicate_member_zip,
        "wrapper_folder": wrapper_folder_zip,
    }[kind](path)


# (status, substring of detail) the route returns for each poison: what the teacher sees on the
# wire. Every unusable member is a 409 that names the offending source (a PDF, or the student
# folder for image pages).
_ROUTE_TODAY = {
    "password_pdf": (409, "Could not import S002.pdf: password-protected PDF"),
    "zero_byte_pdf": (409, "Could not import S002.pdf: Uploaded PDF could not be decoded"),
    "deflate64": (409, "Could not import S002.pdf: unsupported ZIP compression method"),
    "png_196mp": (409, "Could not import S002: image too large to read safely"),
    "bad_crc": (409, "Could not import S002.pdf: damaged ZIP member"),
    "duplicate_member": (409, "ZIP contains the member S001.pdf twice"),
    "wrapper_folder": (409, "Student folder Scripts contains 2 PDFs"),
}


@pytest.mark.parametrize("kind", list(_ROUTE_TODAY))
def test_route_status_table_for_poisoned_archives(
    route: RouteBench, tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Characterisation (passing): the HTTP status and body each poison produces today.

    The unusable-member rows are 409s naming the source
    (test_bulk150_poison_fixtures::test_every_unusable_member_is_refused_with_a_teacher_readable_error
    pins the same at the service level); the bad-CRC row is no longer reported as an invalid ZIP.
    """

    poison = _poison(kind, tmp_path)
    response = route.post(poison.path)
    with capsys.disabled():
        print(f"\nROUTE-TABLE {kind:17s} -> {response.status} {response.detail[:110]!r}")
    want_status, want_detail = _ROUTE_TODAY[kind]
    assert response.status == want_status, response.body
    if want_detail is not None:
        assert want_detail in response.detail
    if response.status != 202:
        assert route.submission_count() == 0 and route.runs() == []


@pytest.mark.parametrize(
    ("kind", "source", "reason", "cause"),
    [
        ("password_pdf", "S002.pdf", "password-protected PDF", ValueError),
        ("zero_byte_pdf", "S002.pdf", "Uploaded PDF could not be decoded", HTTPException),
        ("deflate64", "S002.pdf", "unsupported ZIP compression method", NotImplementedError),
        ("png_196mp", "S002", "image too large to read safely", Image.DecompressionBombError),
        ("bad_crc", "S002.pdf", "damaged ZIP member", zipfile.BadZipFile),
    ],
)
def test_an_unusable_member_is_refused_naming_it_and_keeping_the_original_error(
    bench: IntakeBench, tmp_path: Path, kind: str, source: str, reason: str, cause: type
) -> None:
    """Every unusable member is a named refusal (not an opaque 503) with the original as cause."""

    result = bench.run(_poison(kind, tmp_path).path)
    assert result.run is None and result.raw is None, result.failure
    assert result.refusal is not None
    message = str(result.refusal)
    assert f"Could not import {source}: " in message and reason in message, message
    assert message.endswith("Nothing was imported."), message
    assert "not a valid ZIP archive" not in message
    assert isinstance(result.refusal.__cause__, cause), repr(result.refusal.__cause__)
    assert result.identifiers == [] and result.staged_left == []


def _zlib_damaged_zip(path: Path) -> Path:
    """S002.pdf is deflated and one byte of its stream is flipped so ``zlib`` rejects it."""

    payload = b"".join(b"line %d of a synthetic script page\n" % number for number in range(4000))
    _write_zip(
        path,
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", payload)],
        compression=zipfile.ZIP_DEFLATED,
    )
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("S002.pdf")
    raw = path.read_bytes()
    name_len, extra_len = struct.unpack(
        "<HH", raw[info.header_offset + 26 : info.header_offset + 30]
    )
    start = info.header_offset + 30 + name_len + extra_len
    for position in range(start, start + info.compress_size):
        damaged = bytearray(raw)
        damaged[position] ^= 0xFF
        try:
            with zipfile.ZipFile(BytesIO(bytes(damaged))) as archive:
                archive.read("S002.pdf")
        except zlib.error:
            path.write_bytes(bytes(damaged))
            return path
        except zipfile.BadZipFile:
            continue
    pytest.fail("PRECONDITION BROKEN: no single-byte flip produced a zlib.error")


def test_a_member_with_a_damaged_compressed_stream_is_named_not_an_opaque_503(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """``zlib.error`` is how most real bit-rot in a deflated member shows up (not BadZipFile)."""

    result = bench.run(_zlib_damaged_zip(tmp_path / "zlib.zip"))
    assert result.run is None and result.raw is None, result.failure
    assert result.refusal is not None
    assert "Could not import S002.pdf: damaged ZIP member" in str(result.refusal)
    assert isinstance(result.refusal.__cause__, zlib.error)


def test_a_damaged_manifest_is_named_as_the_manifest_not_as_an_invalid_zip(
    bench: IntakeBench, tmp_path: Path
) -> None:
    archive_path = _write_zip(
        tmp_path / "bad-manifest.zip",
        [
            ("S001.pdf", good_pdf_bytes("S001")),
            ("S002.pdf", good_pdf_bytes("S002")),
            ("manifest.csv", _manifest(["S001.pdf,ID-ONE,Student One"])),
        ],
    )
    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo("manifest.csv")
    raw = bytearray(archive_path.read_bytes())
    name_len, extra_len = struct.unpack(
        "<HH", raw[info.header_offset + 26 : info.header_offset + 30]
    )
    raw[info.header_offset + 30 + name_len + extra_len] ^= 0xFF  # stored data, so a CRC mismatch
    archive_path.write_bytes(bytes(raw))
    result = bench.run(archive_path)
    assert result.run is None and result.raw is None, result.failure
    assert result.refusal is not None
    assert "Could not import manifest.csv: damaged ZIP member" in str(result.refusal)
    assert "not a valid ZIP archive" not in str(result.refusal)
    assert isinstance(result.refusal.__cause__, zipfile.BadZipFile)
    assert result.identifiers == []


def test_an_archive_that_is_not_a_zip_is_still_reported_as_such(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """The 'not a valid ZIP archive' message stays for the archive-open failure only."""

    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"this is not a zip archive at all" * 8)
    result = bench.run(garbage)
    assert result.raw is None and result.refusal is not None
    assert "Uploaded file is not a valid ZIP archive" in str(result.refusal)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom"),
        ValueError("something that is not about encryption"),
        NotImplementedError("an abstract hook that was never overridden"),
        HTTPException(status_code=503, detail="not a client error, so not translated"),
    ],
    ids=["runtime", "value", "not_implemented", "http_503"],
)
def test_an_unrecognised_failure_while_importing_a_member_still_surfaces_as_itself(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    """Only the named member failures are translated; a genuine bug must stay visible."""

    archive_path = _write_zip(
        tmp_path / "two.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
    )

    def fail(**kwargs: Any) -> list[str]:
        raise error

    monkeypatch.setattr(bulk_module, "extract_page_images", fail)
    result = bench.run(archive_path)
    assert result.refusal is None and result.run is None
    assert result.raw is error
    assert result.identifiers == [] and result.staged_left == []


def test_a_wrapper_folder_is_refused_409_naming_the_folder(
    route: RouteBench, tmp_path: Path
) -> None:
    """REFUTED: the best-handled case. 409, names the folder, explains both remedies."""

    response = route.post(wrapper_folder_zip(tmp_path / "w.zip").path)
    assert response.status == 409
    assert "Scripts" in response.detail and "top level of the ZIP" in response.detail
    assert route.enqueued == []


def test_a_corrupt_member_is_reported_as_that_member_not_as_an_invalid_zip(
    route: RouteBench, tmp_path: Path
) -> None:
    poison = bad_crc_zip(tmp_path / "crc.zip")
    with zipfile.ZipFile(poison.path) as archive:  # the ARCHIVE itself is fine
        precondition(archive.testzip() == "S002.pdf" and archive.namelist(), "bad member only")
    response = route.post(poison.path)
    precondition(response.status == 409, f"unexpected status {response.status}: {response.body}")
    assert "S002.pdf" in response.detail, f"409 detail: {response.detail!r}"


# =========================================================================== PD-3 re-upload


def test_identical_reupload_while_the_run_is_active_returns_the_same_run_and_enqueues_again(
    route: RouteBench, tmp_path: Path
) -> None:
    """POLICY_QUESTION (documented: 'Re-uploading the same active archive returns the run').

    Only the first upload, which creates the run, enqueues a ``run_bulk_evaluation_next_job``.
    A repeat upload returns the same run (202) without a second job: each job re-enqueues its
    own successor, so an extra one would start a second chain advancing the same run. (The test
    name is historical: it pinned the old behaviour of enqueueing again.)
    """

    archive = _good_cohort(tmp_path / "cohort.zip")
    first = route.post(archive)
    second = route.post(archive)
    third = route.post(archive)
    assert (first.status, second.status, third.status) == (202, 202, 202)
    assert first.body["id"] == second.body["id"] == third.body["id"]
    assert len(route.runs()) == 1 and route.submission_count() == 2
    assert [call[1] for call in route.enqueued] == [(first.body["id"],)]
    assert first.body["status"] == "queued"


@pytest.mark.parametrize("status", ["completed", "completed_with_exceptions", "stopped", "failed"])
def test_reupload_of_the_same_students_after_a_settled_run_is_refused_naming_them(
    route: RouteBench, tmp_path: Path, status: str
) -> None:
    """POLICY_QUESTION/characterisation: the status is forced in the DB (labelled, not run).

    Once a run has left the active set the same students can never be imported again into this
    assessment: 409, 'existing scripts were preserved', 'import it into a separate assessment'.
    The refusal DOES name the colliding identifiers (casefolded: 's001', not 'S001').
    The same wall applies to a STOPPED or FAILED run, i.e. a teacher who stops a run to fix the
    reference material cannot re-upload the corrected cohort without recreating the assessment.
    """

    archive = _good_cohort(tmp_path / "cohort.zip")
    first = route.post(archive)
    precondition(first.status == 202, f"first upload failed: {first.body}")
    route.db.execute(
        update(BulkEvaluationRun)
        .where(BulkEvaluationRun.id == first.body["id"])
        .values(status=status)
    )
    route.db.commit()
    again = route.post(archive)
    assert again.status == 409
    assert "2 student identifier(s) already exist in this assessment" in again.detail
    assert "s001, s002" in again.detail  # casefolded, not as uploaded
    assert "separate assessment" in again.detail
    assert len(route.enqueued) == 1 and route.submission_count() == 2


def test_a_refused_intake_does_not_block_the_corrected_reupload(
    route: RouteBench, tmp_path: Path
) -> None:
    """REFUTED: a refused (nothing-committed) intake leaves no rows, so a fixed ZIP goes through."""

    refused = route.post(wrapper_folder_zip(tmp_path / "w.zip").path)
    assert refused.status == 409 and route.submission_count() == 0
    accepted = route.post(_good_cohort(tmp_path / "fixed.zip"))
    assert accepted.status == 202 and route.submission_count() == 2
    assert len(route.runs()) == 1 and len(route.enqueued) == 1


def _three_page_cohort(path: Path) -> Path:
    """2 scripts x 3 pages, one question: the cohort needs 6 page reads + 2 gradings = 8 calls."""

    return _write_zip(
        path, [(f"S{n:03d}.pdf", good_pdf_bytes(f"S{n:03d}", pages=3)) for n in (1, 2)]
    )


def test_an_authorisation_below_pages_plus_items_is_refused_with_409_and_nothing_is_kept(
    route: RouteBench, tmp_path: Path
) -> None:
    """F16: a call limit under pages + items can only end exhausted, so intake refuses it.

    The refusal is a 409 naming the minimum and the requested limit, says that the whole-
    transcript assignment calls are extra, and leaves no run, submission, file, or queued job.
    """

    archive = _three_page_cohort(tmp_path / "cohort.zip")
    before = route.files()
    refused = route.post(archive, maximum_provider_calls=7)
    assert refused.status == 409, refused.body
    assert "Authorized provider calls (7) are below the minimum" in refused.detail
    assert "(8: 6 page reads + 2 gradings)" in refused.detail
    assert "Whole-transcript assignment calls" in refused.detail
    assert route.submission_count() == 0 and route.runs() == [] and route.enqueued == []
    assert route.files() == before


def test_an_authorisation_of_exactly_pages_plus_items_is_accepted(
    route: RouteBench, tmp_path: Path
) -> None:
    """F16 boundary: the minimum itself is accepted, and the limit is stored as asked."""

    accepted = route.post(_three_page_cohort(tmp_path / "cohort.zip"), maximum_provider_calls=8)
    assert accepted.status == 202, accepted.body
    assert accepted.body["authorized_call_limit"] == 8
    assert (accepted.body["total_pages"], accepted.body["total_items"]) == (6, 2)
    assert route.submission_count() == 2 and len(route.runs()) == 1 and len(route.enqueued) == 1


def test_a_repeat_upload_with_different_settings_silently_returns_the_original_run(
    route: RouteBench, tmp_path: Path
) -> None:
    """POLICY_QUESTION: the active-archive shortcut ignores every form field except the file.

    A teacher who re-uploads the same ZIP after changing the marking policy and the provider-call
    limit gets 202 and the ORIGINAL run (policy 'general', limit 1500) and no extra queued job.
    Nothing in the response says the new settings were not applied; only a client that compares
    the returned run with what it asked for can notice. (The lookup keys on assessment, archive
    hash and reference-bundle hash only: bulk_evaluation_service.py:168-177.)
    """

    archive = _good_cohort(tmp_path / "cohort.zip")
    first = route.post(archive, marking_policy="general", maximum_provider_calls=1500)
    second = route.post(archive, marking_policy="tough", maximum_provider_calls=50)
    assert (first.status, second.status) == (202, 202)
    assert second.body["id"] == first.body["id"]
    assert (second.body["marking_policy"], second.body["authorized_call_limit"]) == (
        "general",
        1500,
    )
    assert len(route.runs()) == 1 and len(route.enqueued) == 1


class OverlappingUpload:
    """Fire a SECOND real upload while the FIRST one is still inside the rasteriser.

    Intake is one synchronous request: it flushes the run and the submission rows, renders
    every page and commits at the very end, so for minutes of a 150-student upload nothing is
    visible to any other session. That is the window a second tab, a reload or a retry lands in.

    ``extract_page_images`` is wrapped; on its first call the second request is started on
    another thread (its own ``TestClient``, so its own connection and transaction) and the
    first intake waits until that request is either BLOCKED on a database lock the first
    transaction holds or has already finished. Only then does the first intake carry on.
    ``overlapped`` is False when neither happened, i.e. the setup did not do its job.
    """

    def __init__(
        self,
        route: RouteBench,
        second_archive: Path,
        monkeypatch: pytest.MonkeyPatch,
        **second_form: Any,
    ) -> None:
        self.route = route
        self.second_archive = second_archive
        self.second_form = second_form
        self.fired = False
        self.blocked_on_lock = False
        self.finished_early = False
        self.snapshot: list[tuple[Any, ...]] = []
        self.second: RouteResponse | None = None
        self.second_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        real = bulk_module.extract_page_images

        def watch(**kwargs: Any) -> list[str]:
            if not self.fired:
                self.fired = True
                self._start_second_request()
            return real(**kwargs)

        monkeypatch.setattr(bulk_module, "extract_page_images", watch)

    def _second_request(self) -> None:
        try:
            self.second = self.route.send(
                self.second_archive, client=TestClient(app), **self.second_form
            )
        except BaseException as exc:  # reported through precondition() by finish()
            self.second_error = exc

    def _start_second_request(self) -> None:
        self._thread = threading.Thread(target=self._second_request, name="second-upload")
        self._thread.start()
        deadline = time.monotonic() + 20
        with other_session() as probe:
            while time.monotonic() < deadline:
                if not self._thread.is_alive():
                    self.finished_early = True
                    return
                # pg_stat_activity is cached for the whole transaction: without clearing the
                # snapshot every poll would replay the first one, taken before the second
                # request had even connected.
                probe.execute(text("select pg_stat_clear_snapshot()"))
                blocked = probe.execute(
                    text(
                        "select count(*) from pg_stat_activity "
                        "where datname = current_database() and pid <> pg_backend_pid() "
                        "and cardinality(pg_blocking_pids(pid)) > 0"
                    )
                ).scalar_one()
                if blocked:
                    self.blocked_on_lock = True
                    return
                time.sleep(0.05)
            probe.execute(text("select pg_stat_clear_snapshot()"))
            self.snapshot = [
                tuple(row)
                for row in probe.execute(
                    text(
                        "select pid, state, wait_event_type, wait_event, left(query, 50) "
                        "from pg_stat_activity where datname = current_database()"
                    )
                ).all()
            ]

    @property
    def overlapped(self) -> bool:
        return self.blocked_on_lock or self.finished_early

    def finish(self) -> RouteResponse:
        precondition(self.fired and self._thread is not None, "the first intake never rendered")
        assert self._thread is not None
        self._thread.join(60)
        precondition(not self._thread.is_alive(), "the second request never returned")
        precondition(self.second_error is None, f"second request crashed: {self.second_error!r}")
        precondition(
            self.overlapped,
            f"the second request was not in flight during the first; backends: {self.snapshot}",
        )
        assert self.second is not None
        self.route.db.expire_all()
        return self.second


def test_an_identical_upload_that_overlaps_the_first_returns_that_run_not_a_503(
    route: RouteBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _good_cohort(tmp_path / "cohort.zip")
    overlap = OverlappingUpload(route, archive, monkeypatch)
    first = route.post(archive)
    second = overlap.finish()
    precondition(first.status == 202, f"the first upload failed: {first.status} {first.body}")
    runs = route.runs()
    # Collateral damage check: the second request's failure must not have touched the first run.
    precondition(
        len(runs) == 1 and runs[0].status == "queued" and runs[0].error is None,
        f"the first run was disturbed: {[(run.id, run.status, run.error) for run in runs]}",
    )
    same_run = second.status == 202 and second.body["id"] == first.body["id"]
    told_why = second.status == 409 and "could not be started" not in second.detail
    assert same_run or told_why, (
        f"second upload -> {second.status} {second.detail!r} "
        f"(blocked on a lock while the first was open: {overlap.blocked_on_lock}; "
        f"runs={[run.id for run in runs]} enqueued={len(route.enqueued)})"
    )


def test_two_overlapping_uploads_of_the_same_students_never_create_a_student_twice(
    route: RouteBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    names = ("S001", "S002")
    first_zip = _write_zip(
        tmp_path / "v1.zip", [(f"{name}.pdf", good_pdf_bytes(name)) for name in names]
    )
    corrected_zip = _write_zip(
        tmp_path / "v2.zip", [(f"{name}.pdf", good_pdf_bytes(name, pages=2)) for name in names]
    )
    precondition(
        first_zip.read_bytes() != corrected_zip.read_bytes(), "the two archives must differ"
    )
    overlap = OverlappingUpload(route, corrected_zip, monkeypatch)
    first = route.post(first_zip)
    second = overlap.finish()
    precondition(first.status == 202, f"the first upload failed: {first.status} {first.body}")
    identifiers = [value.casefold() for value in route.submission_identifiers()]
    assert len(identifiers) == len(set(identifiers)), (
        f"assessment holds {sorted(identifiers)} (first {first.status}, second {second.status}, "
        f"runs={[run.id for run in route.runs()]}, enqueued={len(route.enqueued)})"
    )


# =========================================================================== PD-5 wrong files


def _run_trace(db: Session, run: BulkEvaluationRun) -> str:
    """Everything intake recorded about a run, as one searchable string."""

    audit = db.scalars(select(AuditLog).where(AuditLog.entity_id == run.id)).all()
    warnings = db.scalars(
        select(BulkEvaluationItem.warnings).where(BulkEvaluationItem.run_id == run.id)
    ).all()
    return json.dumps(
        {
            "manifest": run.import_manifest,
            "audit": [entry.payload_json for entry in audit],
            "item_warnings": list(warnings),
            "error": run.error,
        },
        default=str,
    ).casefold()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "GAP duplicate-script-content-accepted-silently: two students whose PDFs are byte-"
        "identical (same sha256: the same file dropped in twice under two names) are imported "
        "as two independent scripts and graded twice. Nothing is hashed per member, so neither a "
        "refusal nor a flag is recorded anywhere (import_manifest, audit payload, item warnings)."
    ),
)
def test_byte_identical_scripts_under_two_names_are_refused_or_flagged(
    bench: IntakeBench, tmp_path: Path
) -> None:
    same = good_pdf_bytes("S001")
    result = bench.run(_write_zip(tmp_path / "twins.zip", [("S001.pdf", same), ("S002.pdf", same)]))
    precondition(result.raw is None, f"raw exception: {result.raw!r}")
    if result.run is None:
        return  # refused outright: also an acceptable fix
    digest = hashlib.sha256(same).hexdigest()
    trace = _run_trace(bench.db, result.run)
    flagged = digest in trace or "duplicate" in trace or "identical" in trace
    assert flagged, "two students hold byte-identical scripts and nothing says so"


def test_a_script_made_of_another_students_pages_is_accepted_intake_is_content_blind(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """POLICY_QUESTION / INCONCLUSIVE at intake: 'S001.pdf' that holds S002's pages.

    Intake never looks at page content, so it cannot notice. Detecting it needs a CONTENT-level
    check outside intake: an ID/name cover-page read compared with the manifest identifier, or
    the teacher transcript-review gate showing which student the text claims to be. This test
    only pins that intake accepts it under the file's name.
    """

    archive = _write_zip(
        tmp_path / "swapped.zip",
        [("S001.pdf", good_pdf_bytes("S002")), ("S002.pdf", good_pdf_bytes("S002"))],
    )
    result = bench.run(archive)
    assert result.run is not None and result.refusal is None
    assert result.identifiers == ["S001", "S002"]


def test_multi_file_shapes_are_refused_with_actionable_messages(tmp_path: Path) -> None:
    """REFUTED: the already-covered shapes (cited from test_bulk_evaluation_service.py)."""

    cases = {
        "two pdfs in a folder": (
            [("Scripts/a.pdf", b"x"), ("Scripts/b.pdf", b"x")],
            "Student folder Scripts contains 2 PDFs",
        ),
        "pdf + images": (
            [("S1/a.pdf", b"x"), ("S1/p1.png", b"x")],
            "Student folder S1 mixes PDF and image pages",
        ),
        "root image": ([("p1.png", b"x")], "Root-level images are ambiguous"),
        "nested folder": ([("S1/p/1.png", b"x")], "no nested folders"),
    }
    for label, (members, message) in cases.items():
        units, refusal = _try_inspect(tmp_path, members)
        assert units is None and refusal is not None, label
        assert message in str(refusal), f"{label}: {refusal}"


# =========================================================================== PD-6 offline seam


def test_inspect_archive_runs_without_a_database_or_storage(tmp_path: Path) -> None:
    """REFUTED: the seam exists: ``BulkEvaluationService(None, settings=..., storage=...)``.

    ``_inspect_archive`` reads only the central directory and ``manifest.csv`` and touches only
    ``settings.bulk_max_submissions``. Nothing else on ``self`` is used.
    """

    units, manifest_hash, payload = _inspect(
        tmp_path,
        [
            ("S001.pdf", b"x"),
            ("S002/p1.png", b"x"),
            ("manifest.csv", _manifest(["S001.pdf,ID-1,One"])),
        ],
    )
    assert [unit.identifier for unit in units] == ["ID-1", "S002"]
    assert manifest_hash is not None and len(payload) == 2


def test_the_default_storage_ignores_the_settings_it_was_given(
    bulk_env: Settings, tmp_path: Path
) -> None:
    """HAZARD: ``storage=None`` builds ``LocalStorage()`` from ``get_settings()``, not ``settings``.

    A preflight CLI that passes its own Settings but forgets ``storage=`` would silently create
    (and later write to) the process-environment data directories. Under ``bulk_env`` those are
    the test's tmp dirs, so this is safe to demonstrate here.
    """

    elsewhere = tmp_path / "somewhere-else"
    settings = make_settings(elsewhere)
    service = BulkEvaluationService(None, settings=settings)  # type: ignore[arg-type]
    assert isinstance(service.storage, LocalStorage)
    assert Path(service.storage.uploads_dir) == Path(get_settings().uploads_dir).resolve()
    assert Path(service.storage.uploads_dir) != (elsewhere / "uploads").resolve()
    assert not elsewhere.exists()


def test_inspection_alone_would_green_light_every_poisoned_member(tmp_path: Path) -> None:
    """HAZARD for a preflight built on ``_inspect_archive`` only: it never opens a member.

    An encrypted PDF, a zero-byte PDF, a damaged payload, an unsupported compression method and a
    196-megapixel PNG all pass inspection, because every one of those is only discovered when a
    member is read (and the page count is only known after rasterising, see PD-1). A preflight
    needs its own member pass: pymupdf open + needs_pass + page_count + is_repaired, PIL header
    size, and a CRC/decompress check.
    """

    builders = {
        "password_pdf": password_protected_pdf_zip,
        "zero_byte_pdf": zero_byte_pdf_zip,
        "bad_crc": bad_crc_zip,
        "deflate64": deflate64_zip,
        "png_196mp": lambda path: oversized_png_zip(path, width=14000, height=14000),
    }
    for label, builder in builders.items():
        poison = builder(tmp_path / f"{label}.zip")
        with zipfile.ZipFile(poison.path) as archive:
            units, _, _ = _offline_service(tmp_path)._inspect_archive(archive)
        assert len(units) == 2, label


def test_inspection_time_on_a_150_student_600_member_archive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    members = [
        (f"S{student:03d}/page{page}.png", b"\x89PNG-placeholder")
        for student in range(1, 151)
        for page in range(1, 5)
    ]
    manifest = _manifest(
        [f"S{student:03d},ID-{student:03d},Student {student}" for student in range(1, 151)]
    )
    archive_path = _write_zip(tmp_path / "big.zip", [*members, ("manifest.csv", manifest)])
    service = _offline_service(tmp_path)
    timings = []
    for _ in range(20):
        start = time.perf_counter()
        with zipfile.ZipFile(archive_path) as archive:
            units, _, _ = service._inspect_archive(archive)
        timings.append(time.perf_counter() - start)
    with capsys.disabled():
        print(
            f"\nINSPECT-TIMING members=601 students={len(units)} "
            f"median={statistics.median(timings) * 1000:.1f}ms max={max(timings) * 1000:.1f}ms"
        )
    assert len(units) == 150
    assert statistics.median(timings) < 1.0  # generous guard; the point is the printed number


# =========================================================================== PD-7 stale staging


class _FailingUpload(BytesIO):
    """An upload body that dies part-way, like a full disk or a dropped connection."""

    def __init__(self, data: bytes, *, fail_on_read: int = 2) -> None:
        super().__init__(data)
        self.reads = 0
        self.fail_on_read = fail_on_read

    def read(self, size: int | None = -1) -> bytes:
        self.reads += 1
        if self.reads >= self.fail_on_read:
            raise OSError(errno.ENOSPC, "No space left on device")
        return super().read(size)


@pytest.mark.parametrize(
    "exit_path",
    ["refused", "not_a_zip", "raw_exception", "process_killed"],
)
def test_the_staged_archive_is_removed_on_every_in_process_exit_of_create_from_zip(
    bench: IntakeBench,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_path: str,
) -> None:
    """REFUTED: ``finally: staged_path.unlink`` runs for BulkEvaluationError, BadZipFile, any
    Exception and a BaseException (the simulated kill), so no cohort ZIP is left staged."""

    if exit_path == "refused":
        archive = wrapper_folder_zip(tmp_path / "w.zip").path
    elif exit_path == "not_a_zip":
        archive = tmp_path / "garbage.zip"
        archive.write_bytes(b"this is not a zip archive at all" * 8)
    elif exit_path == "raw_exception":
        archive = password_protected_pdf_zip(tmp_path / "pw.zip").path
    else:
        archive = _write_zip(
            tmp_path / "kill.zip",
            [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
        )
        killed: list[int] = []

        def die(**kwargs: Any) -> list[str]:
            killed.append(kwargs["submission_id"])
            raise ProcessKilled("simulated kill inside the rasteriser")

        monkeypatch.setattr(bulk_module, "extract_page_images", die)
    result = bench.run(archive)
    if exit_path == "process_killed":
        precondition(isinstance(result.raw, ProcessKilled), f"kill did not fire: {result.raw!r}")
    else:
        precondition(result.run is None, "the intake must have failed")
    assert result.staged_left == []


@pytest.mark.parametrize("shape", ["oversize", "empty", "not_a_zip_name"])
def test_the_staged_archive_is_removed_when_staging_itself_refuses(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    shape: str,
) -> None:
    """REFUTED: the three refusals inside ``_stage_archive`` leave no partial file behind."""

    settings = make_settings(Path(bulk_env.local_storage_root), BULK_MAX_ARCHIVE_BYTES=1_048_576)
    bench = IntakeBench(db_session, settings, monkeypatch, tmp_path)
    if shape == "oversize":
        archive = tmp_path / "big.zip"
        archive.write_bytes(b"0" * (1_048_576 + 5))
        message = "configured bulk archive limit"
    elif shape == "empty":
        archive = tmp_path / "empty.zip"
        archive.write_bytes(b"")
        message = "Uploaded ZIP is empty"
    else:
        archive = tmp_path / "cohort.rar"
        archive.write_bytes(b"Rar!" + b"0" * 64)
        message = "Upload a ZIP archive"
    result = bench.run(archive)
    assert result.refusal is not None and message in str(result.refusal), result.failure
    assert result.staged_left == [] and result.new_files == []


def test_nothing_in_the_application_ever_sweeps_the_staging_folder() -> None:
    """INCONCLUSIVE in-process (a SIGKILL cannot be simulated), pinned from the source.

    ``finally: staged_path.unlink`` is the ONLY removal. A hard kill (power loss, Task Manager,
    OOM) between staging and that ``finally`` leaves a cohort ZIP of up to BULK_MAX_ARCHIVE_BYTES
    (default 1 GiB) in uploads/bulk_staging for good: no startup sweep, no age-based cleanup, no
    other reader. This test fails the day somebody adds one (then re-probe the kill path).
    """

    app_root = Path(bulk_module.__file__).resolve().parents[1]
    mentions = {
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if "bulk_staging" in path.read_text(encoding="utf-8")
    }
    assert mentions == {"services/bulk_evaluation_service.py"}, mentions


def test_an_interrupted_intake_leaves_no_student_file_on_disk(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _write_zip(
        tmp_path / "kill.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
    )
    real = bulk_module.extract_page_images
    calls: list[int] = []

    def die_on_second(**kwargs: Any) -> list[str]:
        calls.append(kwargs["submission_id"])
        if len(calls) == 2:
            raise ProcessKilled("simulated kill while rasterising the second script")
        return real(**kwargs)

    monkeypatch.setattr(bulk_module, "extract_page_images", die_on_second)
    result = bench.run(archive)
    precondition(isinstance(result.raw, ProcessKilled), f"kill did not fire: {result.raw!r}")
    precondition(len(calls) == 2, f"expected two rasterise calls, saw {calls}")
    precondition(result.identifiers == [], f"rows survived the rollback: {result.identifiers}")
    assert result.new_files == [], f"orphaned student files: {result.new_files}"


def test_an_undecodable_image_page_leaves_no_student_file_on_disk(
    bench: IntakeBench, tmp_path: Path
) -> None:
    """The image branch of ``_import_unit``: page 1's PNG is already written when page 2 fails."""

    png = BytesIO()
    Image.new("RGB", (8, 8), "white").save(png, format="PNG")
    archive = _write_zip(
        tmp_path / "images.zip",
        [("S001/page1.png", png.getvalue()), ("S001/page2.png", b"not an image at all")],
    )
    result = bench.run(archive)
    precondition(
        result.refusal is not None and "could not be decoded" in str(result.refusal),
        f"the second page was not refused as undecodable: {result.failure}",
    )
    precondition(result.pages_rendered == 2, f"page 1 was never written: {result.pages_rendered}")
    precondition(result.identifiers == [], f"rows survived the rollback: {result.identifiers}")
    assert result.new_files == [], f"orphaned student files: {result.new_files}"
    assert result.staged_left == []


def _student_files(bench: IntakeBench, submission_id: int) -> list[Path]:
    """Every file the intake wrote for one submission: its original upload and its page images."""

    directories = (
        bench.storage.uploads_dir / "submissions" / str(submission_id),
        bench.storage.artifacts_dir / "pages" / f"submission_{submission_id}",
    )
    return sorted(
        path for directory in directories for path in directory.rglob("*") if path.is_file()
    )


@pytest.mark.parametrize("failure", ["exception", "process_killed"])
def test_a_failure_after_the_commit_keeps_the_committed_runs_student_files(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    """W07 (F03b hardening): ``create_from_zip`` commits and only THEN reloads the run to return.

    A failure in that reload (a database blip, a kill, an interrupt) arrives after the rows are
    durable. The cleanup handlers must not delete the files of a committed run: the teacher
    would be left with a queued run whose students have no pages to read.
    """

    archive = _write_zip(
        tmp_path / "committed.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
    )
    error: BaseException = (
        ProcessKilled("simulated kill after the commit")
        if failure == "process_killed"
        else RuntimeError("simulated database blip while reloading the committed run")
    )

    def reload_fails(self: BulkEvaluationService, run_id: int) -> BulkEvaluationRun:
        raise error

    monkeypatch.setattr(BulkEvaluationService, "get_run", reload_fails)
    result = bench.run(archive)
    precondition(result.raw is error, f"the injected failure did not surface: {result.failure}")
    # bench.run rolled the session back after the failure, so what is read here is what committed.
    assessment_id = bench.seeded.assessment.id
    runs = bench.db.scalars(
        select(BulkEvaluationRun).where(BulkEvaluationRun.assessment_id == assessment_id)
    ).all()
    precondition(
        len(runs) == 1 and runs[0].status == "queued",
        f"the run did not commit before the failure: {[run.status for run in runs]}",
    )
    submission_ids = list(
        bench.db.scalars(
            select(Submission.id)
            .where(Submission.assessment_id == assessment_id)
            .order_by(Submission.id)
        )
    )
    precondition(len(submission_ids) == 2, f"committed submissions: {submission_ids}")
    for submission_id in submission_ids:
        assert _student_files(bench, submission_id), (
            f"files of committed submission {submission_id} were deleted"
        )


def test_an_interrupted_intake_rolls_the_session_back_before_it_cleans_up(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W07: the kill/interrupt branch used to leave the flushed run and rows pending in the session.

    A caller that reuses the session and commits next would persist a half-built run whose
    student files were just deleted. The branch must roll the session back like the others do.
    """

    archive = _write_zip(
        tmp_path / "kill.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
    )
    real = bulk_module.extract_page_images
    calls: list[int] = []

    def die_on_second(**kwargs: Any) -> list[str]:
        calls.append(kwargs["submission_id"])
        if len(calls) == 2:
            raise ProcessKilled("simulated kill while rasterising the second script")
        return real(**kwargs)

    monkeypatch.setattr(bulk_module, "extract_page_images", die_on_second)
    with pytest.raises(ProcessKilled):
        import_zip(
            bench.db,
            seeded=bench.seeded,
            corpus=bench.corpus,
            provider=bench.provider,
            settings=bench.settings,
            storage=bench.storage,
            archive_path=archive,
            register=False,
            maximum_provider_calls=1500,
        )
    precondition(len(calls) == 2, f"expected two rasterise calls, saw {calls}")
    bench.db.commit()  # what a caller that reuses the session would do next
    bench.db.expire_all()
    assessment_id = bench.seeded.assessment.id
    half_built = bench.db.scalar(
        select(func.count())
        .select_from(BulkEvaluationRun)
        .where(BulkEvaluationRun.assessment_id == assessment_id)
    )
    assert bench.identifiers() == [] and half_built == 0, (
        f"a half-built run was committed: {bench.identifiers()}, {half_built} run row(s)"
    )


def test_a_failing_rollback_does_not_mask_the_interrupt_or_skip_the_file_cleanup(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W07: the rollback added to the kill/interrupt branch is guarded, so it cannot replace the
    original exception, and the student files are still deleted when it fails."""

    archive = _write_zip(
        tmp_path / "kill.zip",
        [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
    )
    real = bulk_module.extract_page_images
    calls: list[int] = []
    rollbacks: list[int] = []

    def die_on_second(**kwargs: Any) -> list[str]:
        calls.append(kwargs["submission_id"])
        if len(calls) == 2:
            raise ProcessKilled("simulated kill while rasterising the second script")
        return real(**kwargs)

    def rollback_fails() -> None:
        rollbacks.append(1)
        raise RuntimeError("connection already gone")

    monkeypatch.setattr(bulk_module, "extract_page_images", die_on_second)
    before = bench.files()
    with monkeypatch.context() as patch:
        patch.setattr(bench.db, "rollback", rollback_fails)
        with pytest.raises(ProcessKilled):
            import_zip(
                bench.db,
                seeded=bench.seeded,
                corpus=bench.corpus,
                provider=bench.provider,
                settings=bench.settings,
                storage=bench.storage,
                archive_path=archive,
                register=False,
                maximum_provider_calls=1500,
            )
    precondition(len(calls) == 2, f"expected two rasterise calls, saw {calls}")
    precondition(rollbacks, "the interrupt branch never tried to roll the session back")
    leftovers = sorted(str(path.relative_to(bench.root)) for path in bench.files() - before)
    assert leftovers == [], f"orphaned student files: {leftovers}"


def test_a_failed_staging_write_leaves_no_partial_archive(tmp_path: Path) -> None:
    storage = HarnessStorage(make_settings(tmp_path / "stage-storage"))
    service = BulkEvaluationService(
        None, settings=make_settings(tmp_path / "stage-storage"), storage=storage
    )  # type: ignore[arg-type]
    upload = UploadFile(
        filename="cohort.zip", file=_FailingUpload(b"PK\x03\x04" + b"0" * (2 * 1024 * 1024))
    )
    with pytest.raises(OSError, match="No space left"):
        service._stage_archive(upload)
    staging = storage.uploads_dir / "bulk_staging"
    leftovers = sorted(path.name for path in staging.glob("*"))
    precondition(upload.file.reads >= 2, "the failure must come after the first chunk was written")  # type: ignore[attr-defined]
    assert leftovers == [], f"partial staged archives: {leftovers}"


# =========================================================================== archive hygiene (F04)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_a_duplicated_member_is_refused_naming_it(tmp_path: Path) -> None:
    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), ("S001.pdf", b"y")])
    assert units is None and refusal is not None
    assert "S001.pdf" in str(refusal)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_a_duplicated_page_inside_a_student_folder_is_refused(tmp_path: Path) -> None:
    units, refusal = _try_inspect(tmp_path, [("S1/p1.png", b"x"), ("S1/p1.png", b"y")])
    assert units is None and refusal is not None
    assert "S1/p1.png" in str(refusal)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_a_duplicated_manifest_is_refused_not_last_one_wins(tmp_path: Path) -> None:
    manifest = _manifest(["S001.pdf,ID-1,One"])
    units, refusal = _try_inspect(
        tmp_path, [("S001.pdf", b"x"), ("manifest.csv", manifest), ("manifest.csv", manifest)]
    )
    assert units is None and refusal is not None
    assert "manifest.csv" in str(refusal)


def test_names_differing_only_in_case_are_not_a_duplicate_member(tmp_path: Path) -> None:
    """The member check is case-sensitive; the student-identifier check keeps its own refusal."""

    units, refusal = _try_inspect(tmp_path, [("Alice.pdf", b"x"), ("alice.pdf", b"y")])
    assert units is None and refusal is not None
    assert "duplicate student identifiers" in str(refusal)
    assert "twice" not in str(refusal)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_duplicated_ignorable_metadata_is_not_a_duplicate_member(tmp_path: Path) -> None:
    members = [
        ("S001.pdf", b"x"),
        (".DS_Store", b"a"),
        (".DS_Store", b"b"),
        ("__MACOSX/._S001.pdf", b"a"),
        ("__MACOSX/._S001.pdf", b"b"),
        ("._S001.pdf", b"a"),
        ("._S001.pdf", b"b"),
    ]
    units, refusal = _try_inspect(tmp_path, members)
    assert refusal is None and units is not None
    assert [unit.identifier for unit in units] == ["S001"]


def test_the_entry_cap_counts_only_entries_that_are_not_ignorable_metadata(tmp_path: Path) -> None:
    pages = [(f"S1/p{n:04d}.png", b"x") for n in range(1000)]
    sidecars = [(f"S1/._p{n:04d}.png", b"x") for n in range(50)]
    units, refusal = _try_inspect(tmp_path, [*pages, *sidecars])
    assert refusal is None and units is not None
    assert [unit.identifier for unit in units] == ["S1"]
    assert len(units[0].members) == 1000

    one_too_many = [*pages, ("S1/p1000.png", b"x"), *sidecars]
    units, refusal = _try_inspect(tmp_path, one_too_many)
    assert units is None and "more than 1,000 entries" in str(refusal)


def test_a_file_that_merely_contains_a_dot_underscore_is_not_ignored(tmp_path: Path) -> None:
    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), ("S_._002.pdf", b"x")])
    assert refusal is None and units is not None
    assert [unit.identifier for unit in units] == ["S001", "S_._002"]


# =========================================================================== intake micro-hardening


@pytest.mark.parametrize("variant_first", [True, False], ids=["variant-first", "variant-last"])
def test_a_case_variant_of_manifest_csv_is_refused_not_last_one_wins(
    tmp_path: Path, variant_first: bool
) -> None:
    """'manifest.csv' is recognised case-insensitively, so two spellings are two manifests."""

    spellings = ["Manifest.csv", "manifest.csv"]
    if not variant_first:
        spellings.reverse()
    manifests = [
        (spellings[0], _manifest(["S001.pdf,ID-FIRST,First"])),
        (spellings[1], _manifest(["S001.pdf,ID-SECOND,Second"])),
    ]
    units, refusal = _try_inspect(tmp_path, [("S001.pdf", b"x"), *manifests])
    assert units is None and refusal is not None, "a second manifest silently replaced the first"
    assert "more than one manifest.csv" in str(refusal), str(refusal)


def test_a_root_file_and_a_folder_of_the_same_name_are_refused_naming_both(tmp_path: Path) -> None:
    """'A.pdf' and 'A.pdf/p1.png' share one source key: the folder must not replace the PDF."""

    units, refusal = _try_inspect(tmp_path, [("A.pdf", b"x"), ("A.pdf/p1.png", b"x")])
    assert units is None and refusal is not None, "the folder silently replaced the root PDF"
    assert "file 'A.pdf'" in str(refusal) and "folder 'A.pdf/'" in str(refusal), str(refusal)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_an_overlong_name_is_capped_in_the_member_and_folder_refusals(tmp_path: Path) -> None:
    """A hostile 300-character member name is echoed at most 200 characters long."""

    name = "n" * 296 + ".pdf"
    _, twice = _try_inspect(tmp_path, [(name, b"x"), (name, b"y")])
    assert twice is not None and "twice" in str(twice)
    assert "n" * 200 in str(twice) and "n" * 201 not in str(twice), str(twice)

    _, both = _try_inspect(tmp_path, [(name, b"x"), (f"{name}/p1.png", b"x")])
    assert both is not None and "folder" in str(both)
    assert "n" * 200 in str(both) and "n" * 201 not in str(both), str(both)

    with pytest.raises(BulkEvaluationError) as named:
        bulk_module._raise_if_named_member_failure(name, zipfile.BadZipFile("bad CRC"))
    assert str(named.value).startswith(f"Could not import {'n' * 200}: damaged ZIP member")
    assert "n" * 201 not in str(named.value)


@pytest.mark.parametrize("outcome", ["committed", "refused"])
def test_a_locked_staged_archive_never_replaces_the_intake_outcome(
    bench: IntakeBench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcome: str
) -> None:
    """On Windows an antivirus can hold the staged ZIP when ``finally`` unlinks it.

    That ``PermissionError`` must not replace a committed run's return value (the route would
    answer 503 for a run that exists) nor a refusal. The leftover file is the operator's to sweep.
    """

    if outcome == "committed":
        archive = _write_zip(
            tmp_path / "two.zip",
            [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))],
        )
    else:
        archive = wrapper_folder_zip(tmp_path / "w.zip").path
    real_unlink = Path.unlink
    hits: list[str] = []

    def locked_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.parent.name == "bulk_staging" and self.name.startswith("bulk-"):
            hits.append(self.name)
            raise PermissionError(13, "The process cannot access the file: in use")
        real_unlink(self, missing_ok=missing_ok)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked_unlink)
        result = bench.run(archive)
    precondition(hits, "the staged archive was never unlinked, so the lock never fired")
    assert result.raw is None, f"the lock replaced the outcome: {result.failure}"
    if outcome == "committed":
        assert result.refusal is None and result.run is not None, result.failure
        assert result.run.status == "queued" and len(result.identifiers) == 2
    else:
        assert result.run is None and result.refusal is not None
    assert len(result.staged_left) == 1, result.staged_left  # left for the operator, not hidden
    for leftover in (bench.root / "uploads" / "bulk_staging").glob("*"):
        leftover.unlink()
