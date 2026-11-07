"""Poisoned-archive builders for Bulk Supervised intake probes (test only, all synthetic).

Every builder writes ONE small ZIP containing a good script (``S001``) next to exactly one
offending member, and returns a :class:`PoisonedZip` naming that member. Nothing is
asserted about how production reacts: these only build the inputs. Feed the ZIP to
``BulkEvaluationService.create_from_zip`` (``tests.bulk150_harness.import_zip`` with
``register=False``) and look at the exception type, the rows left behind and the files left
on disk.

Large inputs (``oversized_png_zip``) are written with a streaming PNG encoder, so even a
14000 x 14000 image costs a few hundred KB of disk and almost no memory.
"""

from __future__ import annotations

import struct
import warnings
import zipfile
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from tests.bulk150_harness import (
    BlockSpec,
    HarnessError,
    PageSpec,
    pdf_from_pngs,
    render_page_png,
)

__all__ = [
    "MANIFEST_VARIANTS",
    "PoisonedZip",
    "all_poisons",
    "bad_crc_zip",
    "deflate64_zip",
    "duplicate_member_zip",
    "exif_rotated_jpeg_zip",
    "good_pdf_bytes",
    "macosx_flood_zip",
    "manifest_zip",
    "oversized_png_zip",
    "password_protected_pdf_zip",
    "solid_gray_png",
    "truncated_pdf_zip",
    "wrapper_folder_zip",
    "zero_byte_pdf_zip",
]

PAGE_SIZE = (240, 320)


@dataclass(frozen=True)
class PoisonedZip:
    path: Path
    member: str  # the offending member / folder ("" when the whole archive is the problem)
    kind: str
    note: str
    meta: dict[str, Any] = field(default_factory=dict)


def good_pdf_bytes(student: str = "S001", pages: int = 1) -> bytes:
    """A small, valid, un-poisoned one-student PDF whose page text carries a token."""

    pngs = []
    for page_no in range(1, pages + 1):
        block = BlockSpec(
            page_no=page_no,
            block_no=1,
            owner=student,
            question="Q1",
            reported_label="Q1",
            label_source="heading",
            continues_from_previous=False,
            bbox=(100, 100, 900, 300),
            text=f"SYN150|{student}|Q1|p{page_no}|b1 poison fixture good page",
        )
        pngs.append(render_page_png(PageSpec(blocks=(block,)), PAGE_SIZE))
    return pdf_from_pngs(pngs, PAGE_SIZE)


def _write(
    path: Path, members: list[tuple[str, bytes]], *, compression: int = zipfile.ZIP_STORED
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate names are the point of one builder
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, content in members:
                archive.writestr(name, content)


# ------------------------------------------------------------------ PDF poisons


def password_protected_pdf_zip(path: Path) -> PoisonedZip:
    """S002.pdf is AES-256 encrypted with a USER password (cannot be opened without it)."""

    doc = pymupdf.open(stream=good_pdf_bytes("S002"), filetype="pdf")
    try:
        encrypted = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="synthetic-user-pw",
            owner_pw="synthetic-owner-pw",
        )
    finally:
        doc.close()
    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", encrypted)])
    return PoisonedZip(
        path,
        "S002.pdf",
        "password_protected_pdf",
        "AES-256 user-password PDF",
        {"needs_pass": True},
    )


def zero_byte_pdf_zip(path: Path) -> PoisonedZip:
    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", b"")])
    return PoisonedZip(path, "S002.pdf", "zero_byte_pdf", "empty file named .pdf")


def truncated_pdf_zip(path: Path, *, keep: float = 0.4) -> PoisonedZip:
    """S002.pdf is a real PDF with its tail (xref, trailer) cut off."""

    full = good_pdf_bytes("S002", pages=2)
    cut = full[: max(64, int(len(full) * keep))]
    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", cut)])
    meta: dict[str, Any] = {"full_bytes": len(full), "kept_bytes": len(cut)}
    try:
        with pymupdf.open(stream=cut, filetype="pdf") as doc:
            meta["pymupdf_repairs"] = True
            meta["pymupdf_pages"] = doc.page_count
    except Exception as exc:  # recording what the library does is the point
        meta["pymupdf_repairs"] = False
        meta["pymupdf_error"] = type(exc).__name__
    return PoisonedZip(path, "S002.pdf", "truncated_pdf", "PDF cut before its xref", meta)


# ------------------------------------------------------------------ ZIP-structure poisons


def _data_offset(path: Path, name: str) -> tuple[int, zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(name)
    raw = path.read_bytes()
    offset = info.header_offset
    name_len, extra_len = struct.unpack("<HH", raw[offset + 26 : offset + 30])
    return offset + 30 + name_len + extra_len, info


def bad_crc_zip(path: Path) -> PoisonedZip:
    """Structurally valid ZIP whose S002.pdf data no longer matches its stored CRC-32."""

    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))])
    start, info = _data_offset(path, "S002.pdf")
    raw = bytearray(path.read_bytes())
    raw[start + 16] ^= 0xFF  # flip one payload byte, leave both headers untouched
    path.write_bytes(bytes(raw))
    return PoisonedZip(
        path,
        "S002.pdf",
        "bad_crc",
        "payload byte flipped after the CRC was written",
        {"crc32": info.CRC, "size": info.file_size},
    )


def deflate64_zip(path: Path) -> PoisonedZip:
    """S002.pdf is declared compression method 9 (deflate64), which Python cannot open."""

    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))])
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("S002.pdf")
    raw[info.header_offset + 8 : info.header_offset + 10] = struct.pack("<H", 9)
    encoded = b"S002.pdf"
    cursor = 0
    patched_central = 0
    while (cursor := bytes(raw).find(b"PK\x01\x02", cursor)) != -1:
        name_len = struct.unpack("<H", raw[cursor + 28 : cursor + 30])[0]
        if bytes(raw[cursor + 46 : cursor + 46 + name_len]) == encoded:
            raw[cursor + 10 : cursor + 12] = struct.pack("<H", 9)
            patched_central += 1
        cursor += 4
    if patched_central != 1:
        raise HarnessError("could not patch the central directory entry")
    path.write_bytes(bytes(raw))
    return PoisonedZip(path, "S002.pdf", "deflate64", "compression method 9", {"method": 9})


def duplicate_member_zip(path: Path) -> PoisonedZip:
    """Two different S001.pdf entries at the ZIP root (the second is the 'other' student)."""

    first = good_pdf_bytes("S001")
    second = good_pdf_bytes("S900")
    _write(path, [("S001.pdf", first), ("S001.pdf", second)])
    return PoisonedZip(
        path,
        "S001.pdf",
        "duplicate_member",
        "same member name twice with different content",
        {"first_bytes": len(first), "second_bytes": len(second)},
    )


def wrapper_folder_zip(path: Path, *, layout: str = "pdf", wrapper: str = "Scripts") -> PoisonedZip:
    """Every student sits under one top-level folder (how many desktop zippers pack a folder)."""

    members: list[tuple[str, bytes]] = []
    for student in ("S001", "S002"):
        if layout == "pdf":
            members.append((f"{wrapper}/{student}.pdf", good_pdf_bytes(student)))
        elif layout == "images":
            png = render_page_png(
                PageSpec(
                    blocks=(
                        BlockSpec(
                            1,
                            1,
                            student,
                            "Q1",
                            "Q1",
                            "heading",
                            False,
                            (100, 100, 900, 300),
                            f"SYN150|{student}|Q1|p1|b1 wrapped",
                        ),
                    )
                ),
                PAGE_SIZE,
            )
            members.append((f"{wrapper}/{student}/page1.png", png))
        else:
            raise HarnessError(f"unknown layout {layout!r}")
    _write(path, members)
    return PoisonedZip(
        path, f"{wrapper}/", "wrapper_folder", f"all students under {wrapper}/", {"layout": layout}
    )


def macosx_flood_zip(path: Path, *, images: int = 600, per_student: int = 6) -> PoisonedZip:
    """``images`` real page images plus one ``__MACOSX/._`` sidecar for each of them."""

    tiny = BytesIO()
    Image.new("RGB", (8, 8), "white").save(tiny, format="PNG")
    png = tiny.getvalue()
    members: list[tuple[str, bytes]] = []
    students = images // per_student
    for student_index in range(1, students + 1):
        folder = f"S{student_index:03d}"
        for page_no in range(1, per_student + 1):
            members.append((f"{folder}/page{page_no}.png", png))
            members.append((f"__MACOSX/{folder}/._page{page_no}.png", b"\x00\x05\x16\x07"))
    _write(path, members)
    return PoisonedZip(
        path,
        "__MACOSX/",
        "macosx_flood",
        f"{images} images + {images} __MACOSX entries",
        {
            "real_members": students * per_student,
            "metadata_members": students * per_student,
            "total_members": len(members),
            "students": students,
        },
    )


# ------------------------------------------------------------------ image poisons


def solid_gray_png(width: int, height: int, value: int = 255) -> bytes:
    """Valid 8-bit grayscale PNG encoded row by row, so huge sizes stay cheap."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    row = b"\x00" + bytes([value]) * width
    compressor = zlib.compressobj(9)
    parts = [compressor.compress(row) for _ in range(height)]
    parts.append(compressor.flush())
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", b"".join(parts))
        + chunk(b"IEND", b"")
    )


def oversized_png_zip(path: Path, *, width: int = 14000, height: int = 14000) -> PoisonedZip:
    """S002/page1.png has ``width * height`` pixels (14000x14000 = 196 MP, 12000x12000 = 144 MP)."""

    png = solid_gray_png(width, height)
    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002/page1.png", png)])
    return PoisonedZip(
        path,
        "S002/page1.png",
        "oversized_png",
        f"{width}x{height} grayscale PNG",
        {
            "width": width,
            "height": height,
            "megapixels": width * height / 1_000_000,
            "png_bytes": len(png),
        },
    )


def exif_rotated_jpeg_zip(path: Path) -> PoisonedZip:
    """A 200x100 JPEG tagged EXIF orientation 6 (viewers show it as 100x200, rotated)."""

    image = Image.new("RGB", (200, 100), "white")
    for x in range(0, 200, 10):  # asymmetric marks so a rotation is detectable
        image.putpixel((x, 5), (0, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    _write(path, [("S001.pdf", good_pdf_bytes("S001")), ("S002/page1.jpg", buffer.getvalue())])
    return PoisonedZip(
        path,
        "S002/page1.jpg",
        "exif_rotated_jpeg",
        "stored 200x100, EXIF orientation 6",
        {"stored_size": (200, 100), "displayed_size": (100, 200), "orientation": 6},
    )


# ------------------------------------------------------------------ manifest poisons

MANIFEST_VARIANTS = (
    "blank_identifier",
    "partial_rows",
    "bom_crlf",
    "unknown_source",
    "duplicate_source",
    "missing_column",
    "header_only",
    "blank_source",
)


def manifest_zip(path: Path, variant: str) -> PoisonedZip:
    """Two valid PDFs plus a ``manifest.csv`` that is wrong in exactly one way."""

    members = [("S001.pdf", good_pdf_bytes("S001")), ("S002.pdf", good_pdf_bytes("S002"))]
    header = "source,student_identifier,student_name"
    rows = {
        "blank_identifier": [header, "S001.pdf,S001,Student One", "S002.pdf,,Student Two"],
        "partial_rows": [header, "S001.pdf,ID-ONE,Student One"],
        "bom_crlf": [header, "S001.pdf,ID-ONE,Student One", "S002.pdf,ID-TWO,Student Two"],
        "unknown_source": [header, "S001.pdf,ID-ONE,One", "S003.pdf,ID-THREE,Three"],
        "duplicate_source": [header, "S001.pdf,ID-ONE,One", "S001.pdf,ID-TWO,Two"],
        "missing_column": ["source,student_identifier", "S001.pdf,ID-ONE"],
        "header_only": [header],
        "blank_source": [header, ",ID-ONE,One"],
    }
    if variant not in rows:
        raise HarnessError(f"unknown manifest variant {variant!r}")
    newline = "\r\n" if variant == "bom_crlf" else "\n"
    text = newline.join(rows[variant]) + newline
    payload = (b"\xef\xbb\xbf" if variant == "bom_crlf" else b"") + text.encode("utf-8")
    members.append(("manifest.csv", payload))
    _write(path, members)
    return PoisonedZip(path, "manifest.csv", f"manifest_{variant}", variant, {"variant": variant})


def all_poisons(directory: Path, *, include_huge: bool = False) -> dict[str, PoisonedZip]:
    """Every poison above, one ZIP each, keyed by ``kind``.

    ``include_huge`` adds the 196 MP and 144 MP PNG variants.
    """

    directory.mkdir(parents=True, exist_ok=True)
    built: dict[str, PoisonedZip] = {}
    builders = {
        "password_protected_pdf": password_protected_pdf_zip,
        "zero_byte_pdf": zero_byte_pdf_zip,
        "truncated_pdf": truncated_pdf_zip,
        "bad_crc": bad_crc_zip,
        "deflate64": deflate64_zip,
        "duplicate_member": duplicate_member_zip,
        "wrapper_folder": wrapper_folder_zip,
        "macosx_flood": macosx_flood_zip,
        "exif_rotated_jpeg": exif_rotated_jpeg_zip,
    }
    for kind, builder in builders.items():
        built[kind] = builder(directory / f"{kind}.zip")
    for variant in MANIFEST_VARIANTS:
        built[f"manifest_{variant}"] = manifest_zip(directory / f"manifest_{variant}.zip", variant)
    if include_huge:
        built["png_196mp"] = oversized_png_zip(
            directory / "png_196mp.zip", width=14000, height=14000
        )
        built["png_144mp"] = oversized_png_zip(
            directory / "png_144mp.zip", width=12000, height=12000
        )
    return built
