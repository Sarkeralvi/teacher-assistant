"""Poisoned-archive builders (tests.bulk150_poison) and what production intake does with them.

Two kinds of test live here. The first group checks that each builder really produces the
poison it claims (so a probe is not silently testing a clean file). The second feeds the
poisons to the REAL ``BulkEvaluationService.create_from_zip`` and asserts the behaviour a
teacher needs: a clean refusal, nothing left behind, nothing silently altered. Where
production falls short the test is ``xfail(strict=True, reason="GAP: ...")``.

A GAP test is ``xfail(raises=AssertionError)``, so a bare ``assert`` in its SETUP would be
absorbed as the gap (the wrong-reason XFAIL). Setup checks therefore use
:func:`tests.bulk150_harness.precondition`; only the desired-behaviour assertion is a plain
``assert``.

This module also proves the shared helpers import cleanly from a second test file.
"""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import BulkEvaluationRun, Submission, SubmissionPage
from app.services.bulk_evaluation_service import BulkEvaluationError
from tests.bulk150_harness import (  # noqa: F401
    FakeBulkBrainProvider,
    build_zip,
    bulk150_db_session,
    bulk150_env,
    import_zip,
    install_fake_brain,
    precondition,
    seed_assessment,
)
from tests.bulk150_poison import (
    MANIFEST_VARIANTS,
    PoisonedZip,
    all_poisons,
    bad_crc_zip,
    deflate64_zip,
    duplicate_member_zip,
    exif_rotated_jpeg_zip,
    good_pdf_bytes,
    macosx_flood_zip,
    manifest_zip,
    oversized_png_zip,
    password_protected_pdf_zip,
    truncated_pdf_zip,
    wrapper_folder_zip,
    zero_byte_pdf_zip,
)

# --------------------------------------------------------------------------- builders


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_every_builder_names_a_member_that_is_really_in_its_archive(tmp_path: Path) -> None:
    poisons = all_poisons(tmp_path / "all")
    assert len(poisons) == 9 + len(MANIFEST_VARIANTS)
    for kind, poison in poisons.items():
        assert poison.path.is_file() and poison.kind == kind
        with zipfile.ZipFile(poison.path) as archive:
            names = archive.namelist()
        if poison.member and not poison.member.endswith("/"):
            assert poison.member in names, kind
        assert any("S001" in name for name in names) or kind == "macosx_flood"


def test_pdf_poisons_are_what_they_claim(tmp_path: Path) -> None:
    password = password_protected_pdf_zip(tmp_path / "pw.zip")
    with zipfile.ZipFile(password.path) as archive:
        encrypted = archive.read(password.member)
        good = archive.read("S001.pdf")
    with pymupdf.open(stream=encrypted, filetype="pdf") as doc:
        assert doc.needs_pass and not doc.authenticate("wrong")
        assert doc.authenticate("synthetic-user-pw")
    with pymupdf.open(stream=good, filetype="pdf") as doc:
        assert not doc.needs_pass and doc.page_count == 1

    zero = zero_byte_pdf_zip(tmp_path / "zero.zip")
    with zipfile.ZipFile(zero.path) as archive:
        assert archive.getinfo(zero.member).file_size == 0

    cut = truncated_pdf_zip(tmp_path / "cut.zip")
    assert cut.meta["kept_bytes"] < cut.meta["full_bytes"]
    with zipfile.ZipFile(cut.path) as archive:
        assert archive.getinfo(cut.member).file_size == cut.meta["kept_bytes"]


def test_zip_structure_poisons_are_what_they_claim(tmp_path: Path) -> None:
    crc = bad_crc_zip(tmp_path / "crc.zip")
    with zipfile.ZipFile(crc.path) as archive:
        assert archive.testzip() == crc.member  # structure fine, payload no longer matches CRC
        assert archive.read("S001.pdf")

    d64 = deflate64_zip(tmp_path / "d64.zip")
    with zipfile.ZipFile(d64.path) as archive:
        assert archive.getinfo(d64.member).compress_type == 9
        assert archive.read("S001.pdf")
        with pytest.raises(NotImplementedError):
            archive.read(d64.member)

    dup = duplicate_member_zip(tmp_path / "dup.zip")
    with zipfile.ZipFile(dup.path) as archive:
        assert archive.namelist() == ["S001.pdf", "S001.pdf"]

    wrapped = wrapper_folder_zip(tmp_path / "wrap.zip")
    with zipfile.ZipFile(wrapped.path) as archive:
        assert all(name.startswith("Scripts/") for name in archive.namelist())

    flood = macosx_flood_zip(tmp_path / "flood.zip", images=600)
    with zipfile.ZipFile(flood.path) as archive:
        names = archive.namelist()
    assert len(names) == flood.meta["total_members"] == 1200
    assert sum(name.startswith("__MACOSX/") for name in names) == 600
    assert sum(name.endswith(".png") and "MACOSX" not in name for name in names) == 600


def test_image_poisons_are_what_they_claim(tmp_path: Path) -> None:
    huge = oversized_png_zip(tmp_path / "huge.zip", width=14000, height=14000)
    medium = oversized_png_zip(tmp_path / "medium.zip", width=12000, height=12000)
    for poison, side in ((huge, 14000), (medium, 12000)):
        with zipfile.ZipFile(poison.path) as archive:
            info = archive.getinfo(poison.member)
            assert _png_size(archive.read(poison.member)) == (side, side)
            assert info.file_size / max(info.compress_size, 1) < 100  # not a ratio-guard case
        assert poison.meta["megapixels"] == side * side / 1_000_000
        assert poison.path.stat().st_size < 2_000_000
    assert huge.meta["megapixels"] > 178.96 > medium.meta["megapixels"] > 89.5

    rotated = exif_rotated_jpeg_zip(tmp_path / "exif.zip")
    with zipfile.ZipFile(rotated.path) as archive:
        image = Image.open(BytesIO(archive.read(rotated.member)))
    assert image.size == (200, 100) and image.getexif()[0x0112] == 6


def test_manifest_poisons_carry_their_defect(tmp_path: Path) -> None:
    bom = manifest_zip(tmp_path / "bom.zip", "bom_crlf")
    with zipfile.ZipFile(bom.path) as archive:
        raw = archive.read("manifest.csv")
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    blank = manifest_zip(tmp_path / "blank.zip", "blank_identifier")
    with zipfile.ZipFile(blank.path) as archive:
        assert b"S002.pdf,,Student Two" in archive.read("manifest.csv")
    assert set(MANIFEST_VARIANTS) == {
        "blank_identifier",
        "partial_rows",
        "bom_crlf",
        "unknown_source",
        "duplicate_source",
        "missing_column",
        "header_only",
        "blank_source",
    }
    with pytest.raises(Exception, match="unknown manifest variant"):
        manifest_zip(tmp_path / "x.zip", "nope")


# --------------------------------------------------------------------------- production


@dataclass
class Attempt:
    run: BulkEvaluationRun | None
    refusal: BulkEvaluationError | None
    raw: BaseException | None
    new_files: list[str]
    identifiers: list[str]
    storage: Path
    db: Session


def _attempt(
    db: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    poison: PoisonedZip,
) -> Attempt:
    """Run the REAL create_from_zip on a poison ZIP and record everything it leaves behind."""

    seeded = seed_assessment(db, questions=1)
    corpus = build_zip(tmp_path / "dummy.zip", students=1, pages=1, questions=1)
    provider = FakeBulkBrainProvider(corpus)
    install_fake_brain(monkeypatch, provider, settings)
    root = Path(settings.local_storage_root)
    before = {path for path in root.rglob("*") if path.is_file()}
    run = refusal = raw = None
    try:
        run = import_zip(
            db,
            seeded=seeded,
            corpus=corpus,
            provider=provider,
            settings=settings,
            archive_path=poison.path,
            register=False,
            maximum_provider_calls=1500,
        )
    except BulkEvaluationError as exc:
        db.rollback()
        refusal = exc
    except BaseException as exc:  # recording the exception TYPE is the point
        db.rollback()
        raw = exc
    db.expire_all()
    after = {path for path in root.rglob("*") if path.is_file()}
    identifiers = [
        row.student_identifier
        for row in db.scalars(
            select(Submission)
            .where(Submission.assessment_id == seeded.assessment.id)
            .order_by(Submission.id)
        ).all()
    ]
    return Attempt(
        run=run,
        refusal=refusal,
        raw=raw,
        new_files=sorted(str(path.relative_to(root)) for path in after - before),
        identifiers=identifiers,
        storage=root,
        db=db,
    )


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("wrapper_folder", "Student folder Scripts contains 2 PDFs"),
        ("manifest_unknown_source", "refers to a source that is not in the ZIP"),
        ("manifest_duplicate_source", "blank or duplicate source"),
        ("manifest_blank_source", "blank or duplicate source"),
        ("manifest_missing_column", "needs source, student_identifier, and student_name"),
    ],
)
def test_structural_poisons_are_refused_cleanly_and_leave_nothing_behind(
    kind: str,
    message: str,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = all_poisons(tmp_path / "poisons")[kind]
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    assert result.raw is None and result.run is None
    assert result.refusal is not None and message in str(result.refusal)
    assert result.identifiers == [] and result.new_files == []


@pytest.mark.parametrize(
    ("variant", "identifiers"),
    [
        ("blank_identifier", ["S001", "S002"]),  # blank cell falls back to the file name
        ("partial_rows", ["ID-ONE", "S002"]),  # unlisted source keeps its file name
        ("bom_crlf", ["ID-ONE", "ID-TWO"]),  # BOM and CRLF are tolerated
        ("header_only", ["S001", "S002"]),
    ],
)
def test_tolerated_manifest_variants_resolve_identifiers_as_documented(
    variant: str,
    identifiers: list[str],
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = manifest_zip(tmp_path / f"{variant}.zip", variant)
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    assert result.refusal is None and result.raw is None and result.run is not None
    assert result.identifiers == identifiers


def test_sidecars_under_the_entry_cap_are_ignored_not_imported(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CONTROL for the xfail below: 450 images + 450 sidecars = 900 entries is accepted."""

    poison = macosx_flood_zip(tmp_path / "flood450.zip", images=450)
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    assert result.refusal is None and result.raw is None and result.run is not None
    assert (result.run.total_submissions, result.run.total_pages) == (75, 450)
    pages = result.db.scalar(select(func.count(SubmissionPage.id)))
    assert pages == 450  # the __MACOSX sidecars never became pages


def test_sidecars_do_not_count_toward_the_entry_cap(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = macosx_flood_zip(tmp_path / "flood600.zip", images=600)
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    # A refusal for any OTHER reason (or a raw exception) is not the gap this test documents.
    precondition(result.raw is None, f"raw exception: {result.raw!r}")
    precondition(
        result.refusal is None or "more than 1,000 entries" in str(result.refusal),
        f"refused for another reason than the entry cap: {result.refusal!r}",
    )
    assert result.run is not None, f"refused: {result.refusal or result.raw!r}"
    assert result.run.total_pages == 600


@pytest.mark.parametrize(
    "builder",
    [
        password_protected_pdf_zip,
        zero_byte_pdf_zip,
        deflate64_zip,
        pytest.param(
            lambda path: oversized_png_zip(path, width=14000, height=14000), id="png_196mp"
        ),
    ],
)
def test_every_unusable_member_is_refused_with_a_teacher_readable_error(
    builder: object,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = builder(tmp_path / "poison.zip")  # type: ignore[operator]
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    # The poison must actually have been rejected: an accepted archive is a different finding.
    precondition(result.run is None, f"the poisoned archive was accepted as {result.identifiers}")
    assert result.raw is None, f"raw {type(result.raw).__name__}: {result.raw}"
    assert result.refusal is not None


@pytest.mark.parametrize("builder", [password_protected_pdf_zip, zero_byte_pdf_zip, bad_crc_zip])
def test_a_failed_intake_leaves_no_student_file_on_disk(
    builder: object,
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = builder(tmp_path / "poison.zip")  # type: ignore[operator]
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    # The intake must have failed and been rolled back for "orphaned files" to mean anything.
    precondition(result.run is None, "the poisoned archive was accepted")
    precondition(result.identifiers == [], f"submission rows survived: {result.identifiers}")
    assert result.new_files == [], f"orphaned files: {result.new_files}"


def test_duplicate_member_names_are_not_silently_replaced(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _attempt(
        db_session, bulk_env, monkeypatch, tmp_path, duplicate_member_zip(tmp_path / "dup.zip")
    )
    precondition(result.raw is None, f"raw exception: {result.raw!r}")  # not the silent collapse
    assert result.refusal is not None or len(result.identifiers) == 2, (
        f"accepted a ZIP with two 'S001.pdf' entries as {result.identifiers}"
    )


def test_exif_orientation_is_applied_to_the_stored_page(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    poison = exif_rotated_jpeg_zip(tmp_path / "exif.zip")
    result = _attempt(db_session, bulk_env, monkeypatch, tmp_path, poison)
    precondition(result.run is not None, f"the import failed: {result.refusal or result.raw!r}")
    page = result.db.scalar(
        select(SubmissionPage)
        .join(Submission, Submission.id == SubmissionPage.submission_id)
        .where(Submission.student_identifier == "S002")
    )
    if page is None:  # a setup check, so not an assert (see the module docstring)
        pytest.fail("PRECONDITION BROKEN (the scenario never reached the gap): no page for S002")
    with Image.open(result.storage / page.image_path) as stored:
        assert stored.size == (100, 200), f"stored sideways at {stored.size}"


@pytest.mark.parametrize("orientation", [None, 1])
def test_an_upright_photo_is_stored_pixel_for_pixel_unchanged(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    orientation: int | None,
) -> None:
    """EXIF handling must not touch a photo that has no tag or the identity tag (1)."""

    image = Image.new("RGB", (200, 100), "white")
    for x in range(0, 200, 10):
        image.putpixel((x, 5), (0, 0, 0))
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    archive = tmp_path / "upright.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("S001.pdf", good_pdf_bytes("S001"))
        writer.writestr("S002/page1.jpg", buffer.getvalue())
    result = _attempt(
        db_session,
        bulk_env,
        monkeypatch,
        tmp_path,
        PoisonedZip(archive, "S002/page1.jpg", "upright_jpeg", "no rotation"),
    )
    precondition(result.run is not None, f"the import failed: {result.refusal or result.raw!r}")
    page = result.db.scalar(
        select(SubmissionPage)
        .join(Submission, Submission.id == SubmissionPage.submission_id)
        .where(Submission.student_identifier == "S002")
    )
    if page is None:
        pytest.fail("PRECONDITION BROKEN (the scenario never reached the check): no page for S002")
    with (
        Image.open(BytesIO(buffer.getvalue())) as source,
        Image.open(result.storage / page.image_path) as stored,
    ):
        assert stored.size == (200, 100)
        assert stored.tobytes() == source.convert("RGB").tobytes()


def test_a_truncated_pdf_is_not_accepted_as_blank_pages(
    db_session: Session,
    bulk_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _attempt(
        db_session, bulk_env, monkeypatch, tmp_path, truncated_pdf_zip(tmp_path / "cut.zip")
    )
    assert result.refusal is not None or result.raw is not None, f"accepted as {result.identifiers}"
