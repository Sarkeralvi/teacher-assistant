"""Tier-1 OCR stage of script preparation, without a database or an engine.

``_ocr_pages`` touches neither, so it is tested directly. What it produces is
the geometry every later stage depends on: Qwen3.6 selects block identifiers,
and the crop the teacher confirms is the union of the boxes behind them. A block
whose box is wrong sends the teacher a picture of the wrong part of the page, so
these are correctness tests, not smoke tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.core.config import Settings
from app.services.local_script_preparation import (
    LocalScriptPreparationError,
    LocalScriptPreparationService,
)
from packages.ocr.escalation import REASON_NO_LINES_DETECTED, REASON_UNCOVERED_INK
from packages.ocr.types import BoundingBox, OcrLine, OcrPageReading


@dataclass
class FakePage:
    id: int
    page_no: int
    image_path: str


class FakeStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve_relative(self, relative: str) -> Path:
        return self.root / relative


class FakeEngine:
    """Returns a scripted reading per page and records how it was called."""

    def __init__(self, readings: list[OcrPageReading]) -> None:
        self._readings = list(readings)
        self.calls: list[dict[str, Any]] = []

    def read_page(
        self,
        image_bytes: bytes,
        *,
        render_dpi: int,
        page_width: int,
        page_height: int,
    ) -> OcrPageReading:
        self.calls.append(
            {
                "bytes": len(image_bytes),
                "render_dpi": render_dpi,
                "page_width": page_width,
                "page_height": page_height,
            }
        )
        return self._readings.pop(0)


class ExplodingEngine:
    def read_page(self, *_args: Any, **_kwargs: Any) -> OcrPageReading:
        raise RuntimeError("onnxruntime session failed")


def _reading(lines: list[OcrLine], **kwargs: Any) -> OcrPageReading:
    defaults: dict[str, Any] = {
        "engine": "rapidocr",
        "lines": lines,
        "render_dpi": 300,
        "page_image_sha256": "b" * 64,
        "page_width": 400,
        "page_height": 600,
    }
    defaults.update(kwargs)
    return OcrPageReading(**defaults)


def _line(text: str, box: tuple[float, float, float, float] | None, confidence: str | None = None):
    return OcrLine(
        text=text,
        confidence=Decimal(confidence) if confidence is not None else None,
        bbox=BoundingBox(*box) if box is not None else None,
    )


def _service(
    tmp_path: Path,
    engine: Any,
    *,
    ocr_enabled: bool = True,
    settings: Settings | None = None,
) -> LocalScriptPreparationService:
    resolved = settings or Settings(
        LOCAL_OCR_ENABLED=ocr_enabled,
        LOCAL_OCR_RENDER_DPI=300,
    )
    return LocalScriptPreparationService(
        db=object(),  # type: ignore[arg-type]  # _ocr_pages never touches the session
        settings=resolved,
        storage=FakeStorage(tmp_path),  # type: ignore[arg-type]
        ocr_engine=engine,
    )


def _page(tmp_path: Path, page_no: int, size: tuple[int, int] = (400, 600)) -> FakePage:
    name = f"page_{page_no}.png"
    Image.new("RGB", size, color="white").save(tmp_path / name, format="PNG")
    return FakePage(id=page_no * 10, page_no=page_no, image_path=name)


def test_blocks_are_numbered_in_reading_order_with_pixel_boxes(tmp_path: Path) -> None:
    engine = FakeEngine(
        [
            _reading(
                [
                    _line("1(a)(i)", (10, 10, 120, 40), "0.88"),
                    _line("P(D) = 0.3", (10, 50, 300, 80), "0.42"),
                ]
            )
        ]
    )
    service = _service(tmp_path, engine)

    readings = service._ocr_pages([_page(tmp_path, 1)])

    assert [block["order"] for block in readings[0].blocks] == [1, 2]
    assert readings[0].blocks[0]["text"] == "1(a)(i)"
    # Absolute page pixels: _union_box compares these against image width/height.
    assert readings[0].blocks[1]["bbox"] == [10.0, 50.0, 300.0, 80.0]
    assert readings[0].blocks[1]["confidence"] == "0.42"


def test_the_engine_is_told_the_real_page_size_and_configured_dpi(tmp_path: Path) -> None:
    engine = FakeEngine([_reading([_line("x", (0, 0, 10, 10))])])
    service = _service(tmp_path, engine)

    service._ocr_pages([_page(tmp_path, 1, size=(1240, 1754))])

    assert engine.calls[0]["page_width"] == 1240
    assert engine.calls[0]["page_height"] == 1754
    assert engine.calls[0]["render_dpi"] == 300


def test_lines_without_text_or_geometry_are_dropped_not_renumbered_around(
    tmp_path: Path,
) -> None:
    """A block the crop step cannot honour must not get an order number.

    Qwen3.6 selects blocks by (page, order). Handing it an identifier with no
    box would let it map an answer that cannot then be cropped, which surfaces
    much later as an invalid region rather than here as a dropped line.
    """
    engine = FakeEngine(
        [
            _reading(
                [
                    _line("real", (0, 0, 100, 20), "0.9"),
                    _line("   ", (0, 30, 100, 50), "0.9"),
                    _line("no box", None, "0.9"),
                    _line("also real", (0, 60, 100, 80), "0.9"),
                ]
            )
        ]
    )
    service = _service(tmp_path, engine)

    blocks = service._ocr_pages([_page(tmp_path, 1)])[0].blocks

    assert [block["order"] for block in blocks] == [1, 2]
    assert [block["text"] for block in blocks] == ["real", "also real"]


def test_a_confidenceless_engine_produces_usable_blocks(tmp_path: Path) -> None:
    """Unlimited-OCR reports no per-line score; that must not break the stage.

    OcrLine.confidence is genuinely optional, and the detection-only escalation
    policy never consults it, so a vision-language reader is a valid tier-1
    engine here.
    """
    engine = FakeEngine([_reading([_line("handwriting", (0, 0, 200, 30), None)])])
    service = _service(tmp_path, engine)

    readings = service._ocr_pages([_page(tmp_path, 1)])

    assert readings[0].blocks[0]["confidence"] is None
    assert readings[0].escalated is False


def test_a_misread_page_whose_ink_was_found_is_not_escalated(tmp_path: Path) -> None:
    # The whole point of the tiered script path: bad text, good boxes, no vision call.
    engine = FakeEngine(
        [
            _reading(
                [_line("P(D)=03", (0, 0, 300, 30), "0.31")],
                uncovered_ink_ratio=Decimal("0.04"),
            )
        ]
    )
    service = _service(tmp_path, engine)

    assert service._ocr_pages([_page(tmp_path, 1)])[0].escalated is False


def test_pages_are_escalated_when_detection_failed(tmp_path: Path) -> None:
    engine = FakeEngine(
        [
            _reading([]),
            _reading([_line("x", (0, 0, 10, 10))], uncovered_ink_ratio=Decimal("0.90")),
            _reading([_line("fine", (0, 0, 300, 30))], uncovered_ink_ratio=Decimal("0.01")),
        ]
    )
    service = _service(tmp_path, engine)

    readings = service._ocr_pages(
        [_page(tmp_path, 1), _page(tmp_path, 2), _page(tmp_path, 3)]
    )

    assert [item.escalated for item in readings] == [True, True, False]
    assert readings[0].decision.reason_codes == [REASON_NO_LINES_DETECTED]
    assert readings[1].decision.reason_codes == [REASON_UNCOVERED_INK]


def test_the_configured_ink_threshold_is_passed_through(tmp_path: Path) -> None:
    engine = FakeEngine(
        [_reading([_line("x", (0, 0, 10, 10))], uncovered_ink_ratio=Decimal("0.3"))]
    )
    settings = Settings(
        LOCAL_OCR_ENABLED=True,
        LOCAL_OCR_UNCOVERED_INK_ESCALATE_ABOVE=Decimal("0.50"),
    )
    service = _service(tmp_path, engine, settings=settings)

    assert service._ocr_pages([_page(tmp_path, 1)])[0].escalated is False


def test_disabled_tier1_ocr_refuses_rather_than_reading_nothing(tmp_path: Path) -> None:
    service = _service(tmp_path, FakeEngine([]), ocr_enabled=False)

    with pytest.raises(LocalScriptPreparationError, match="LOCAL_OCR_ENABLED"):
        service._ocr_pages([_page(tmp_path, 1)])


def test_an_engine_failure_surfaces_as_a_safe_preparation_error(tmp_path: Path) -> None:
    service = _service(tmp_path, ExplodingEngine())

    with pytest.raises(LocalScriptPreparationError, match="Tier-1 OCR failed safely"):
        service._ocr_pages([_page(tmp_path, 1)])
