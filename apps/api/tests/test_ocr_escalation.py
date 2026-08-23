from __future__ import annotations

from decimal import Decimal

from packages.ocr.escalation import (
    DECISION_ACCEPTED,
    DECISION_ESCALATED_PAGE,
    DECISION_ESCALATED_REGIONS,
    REASON_DOCUMENT_ROLE_HANDWRITTEN,
    REASON_LOW_LINE_CONFIDENCE,
    REASON_NO_LINES_DETECTED,
    REASON_SPARSE_DECODE,
    REASON_SPLIT_BOX_FRACTION,  # noqa: F401 - used by the prose/fraction tests
    REASON_TALL_BOX_MATH,
    REASON_UNCOVERED_INK,
    EscalationPolicy,
    effective_confidence_threshold,
    evaluate_page,
    merge_regions,
)
from packages.ocr.types import BoundingBox, OcrLine, OcrPageReading


def _line(
    text: str = "P(X) = 7/12",
    confidence: str | None = "0.99",
    box: tuple[float, float, float, float] = (0, 0, 400, 20),
) -> OcrLine:
    return OcrLine(
        text=text,
        confidence=Decimal(confidence) if confidence is not None else None,
        bbox=BoundingBox(*box),
    )


def _reading(lines: list[OcrLine], **kwargs: object) -> OcrPageReading:
    defaults: dict[str, object] = {
        "engine": "rapidocr",
        "lines": lines,
        "render_dpi": 300,
        "page_image_sha256": "a" * 64,
        "page_width": 2480,
        "page_height": 3508,
    }
    defaults.update(kwargs)
    return OcrPageReading(**defaults)  # type: ignore[arg-type]


def test_a_confident_well_formed_page_is_accepted() -> None:
    reading = _reading(
        [
            _line(box=(0, 0, 400, 20)),
            _line(box=(0, 30, 400, 50)),
            _line(box=(0, 60, 400, 80)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.decision == DECISION_ACCEPTED
    assert decision.escalated is False


def test_a_low_confidence_line_escalates_its_region() -> None:
    reading = _reading(
        [
            _line(box=(0, 0, 400, 20)),
            _line(text="Ssuution", confidence="0.42", box=(0, 200, 400, 220)),
            _line(box=(0, 300, 400, 320)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.decision == DECISION_ESCALATED_REGIONS
    assert REASON_LOW_LINE_CONFIDENCE in decision.reason_codes
    assert decision.flagged_line_indexes == [1]
    assert len(decision.regions) == 1


def test_confidently_shredded_math_still_escalates() -> None:
    """The failure a confidence-only gate would miss.

    Modelled on the real solution page: a fraction read as isolated digits in
    stacked boxes, every one at ~0.99999. Trigger A sees nothing wrong. Only
    the structural checks catch it.
    """
    reading = _reading(
        [
            _line(text="Question 1(a)", confidence="0.999", box=(0, 0, 400, 20)),
            _line(text="7", confidence="0.99999", box=(100, 100, 130, 120)),
            _line(text="12", confidence="0.99999", box=(100, 124, 130, 144)),
            _line(text="normal prose line here", confidence="0.995", box=(0, 300, 400, 320)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.escalated is True
    assert REASON_SPLIT_BOX_FRACTION in decision.reason_codes
    assert REASON_LOW_LINE_CONFIDENCE not in decision.reason_codes


def test_ordinary_prose_lines_are_not_mistaken_for_split_fractions() -> None:
    """Regression from a real run: a perfect printed page escalated anyway.

    The question paper was read with CER 0.000 and mean confidence 0.986, yet
    every line tripped the split-fraction rule -- consecutive prose lines are
    also "overlapping in x with a small vertical gap". Width and centring are
    what separate a stacked fraction from a paragraph.
    """
    reading = _reading(
        [
            # Full-width lines at normal tight spacing, sharing a left margin.
            _line(text="In a chemical engineering laboratory, two", box=(0, 0, 400, 20)),
            _line(text="engineers X and Y are independently", box=(0, 24, 400, 44)),
            _line(text="attempting to complete the process", box=(0, 48, 400, 68)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.decision == DECISION_ACCEPTED
    assert REASON_SPLIT_BOX_FRACTION not in decision.reason_codes


def test_a_narrow_centred_stack_is_still_caught_as_a_fraction() -> None:
    # The rule must still fire on what it exists for: short components centred
    # over one another, among otherwise full-width lines.
    reading = _reading(
        [
            _line(text="Given the following values,", box=(0, 0, 400, 20)),
            _line(text="another full width line here", box=(0, 200, 400, 220)),
            _line(text="7", box=(180, 100, 210, 118)),
            _line(text="12", box=(178, 122, 212, 140)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.escalated is True
    assert REASON_SPLIT_BOX_FRACTION in decision.reason_codes


def test_a_tall_box_escalates_without_consulting_confidence() -> None:
    reading = _reading(
        [
            _line(box=(0, 0, 400, 20)),
            _line(box=(0, 30, 400, 50)),
            # A stacked display equation, read confidently.
            _line(text="x", confidence="1.0", box=(0, 100, 400, 220)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.escalated is True
    assert REASON_TALL_BOX_MATH in decision.reason_codes


def test_a_wide_box_yielding_almost_no_text_escalates() -> None:
    reading = _reading(
        [
            _line(box=(0, 0, 400, 20)),
            _line(box=(0, 30, 400, 50)),
            _line(text="-", confidence="0.99", box=(0, 100, 900, 120)),
        ]
    )

    decision = evaluate_page(reading)

    assert decision.escalated is True
    assert REASON_SPARSE_DECODE in decision.reason_codes


def test_uncovered_ink_escalates_the_whole_page() -> None:
    # Content the detector never boxed has no line to flag, so only a
    # page-level signal can catch it.
    reading = _reading([_line()], uncovered_ink_ratio=Decimal("0.35"))

    decision = evaluate_page(reading)

    assert decision.decision == DECISION_ESCALATED_PAGE
    assert REASON_UNCOVERED_INK in decision.reason_codes


def test_a_page_with_no_detected_lines_escalates() -> None:
    decision = evaluate_page(_reading([]))

    assert decision.decision == DECISION_ESCALATED_PAGE
    assert REASON_NO_LINES_DETECTED in decision.reason_codes


def test_mostly_bad_pages_roll_up_to_one_page_call() -> None:
    # Five separate crops cost five vision calls; the page costs one.
    reading = _reading(
        [
            _line(text="bad", confidence="0.10", box=(0, index * 100, 400, index * 100 + 20))
            for index in range(6)
        ]
    )

    decision = evaluate_page(reading)

    assert decision.decision == DECISION_ESCALATED_PAGE


def test_regions_are_merged_and_padded_rather_than_sent_individually() -> None:
    policy = EscalationPolicy()
    boxes = [
        BoundingBox(0, 0, 100, 20),
        BoundingBox(0, 25, 100, 45),
        BoundingBox(0, 400, 100, 420),
    ]

    merged = merge_regions(boxes, median_height=20.0, policy=policy)

    assert len(merged) == 2
    assert merged[0].y1 < 0  # padded outward
    assert merged[0].y2 > 45


def test_a_declared_handwritten_document_escalates_regardless_of_confidence() -> None:
    """Handwriting bypasses the confidence gate entirely.

    Measured on teacher-verified fixtures: 94.7% of handwritten lines are wrong,
    and 82.4% are still wrong in the highest confidence bin. No threshold
    separates them, so triaging line by line would send most of the page anyway
    while trusting the few confidently-wrong lines that happened to score well.
    """
    policy = EscalationPolicy()
    # Every line maximally confident, which per-line triage would accept.
    reading = _reading(
        [
            _line(confidence="1.0", box=(0, 0, 400, 20)),
            _line(confidence="1.0", box=(0, 30, 400, 50)),
            _line(confidence="1.0", box=(0, 60, 400, 80)),
        ]
    )

    assert evaluate_page(reading, policy=policy).decision == DECISION_ACCEPTED
    handwritten = evaluate_page(reading, policy=policy, expect_handwritten=True)
    assert handwritten.decision == DECISION_ESCALATED_PAGE
    assert REASON_DOCUMENT_ROLE_HANDWRITTEN in handwritten.reason_codes


def test_the_confidence_threshold_does_not_escalate_a_good_printed_page() -> None:
    # The observed minimum on a perfectly-read printed page was 0.79; the
    # threshold sits below it so a correct page is not escalated over one
    # merely-lower-scoring line.
    policy = EscalationPolicy()

    assert effective_confidence_threshold(policy, expect_handwritten=False) < Decimal("0.79")


def test_lines_without_reported_confidence_are_not_assumed_bad() -> None:
    # Some engines report no score. Treating that as zero would escalate
    # everything; the structural checks still apply to them.
    reading = _reading(
        [
            _line(confidence=None, box=(0, 0, 400, 20)),
            _line(confidence=None, box=(0, 30, 400, 50)),
            _line(confidence=None, box=(0, 60, 400, 80)),
        ]
    )

    assert evaluate_page(reading).decision == DECISION_ACCEPTED


def test_the_decision_is_deterministic() -> None:
    reading = _reading(
        [
            _line(box=(0, 0, 400, 20)),
            _line(text="Ssuution", confidence="0.42", box=(0, 200, 400, 220)),
        ]
    )

    first = evaluate_page(reading)
    second = evaluate_page(reading)

    assert first == second
