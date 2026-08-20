"""Decide, deterministically, when a page must be re-read by the vision model.

Pure functions over a recorded reading: same inputs, same decision, no I/O and
no model involved. That is what makes a fixed threshold defensible in an audit
and what lets the whole policy be unit-tested without an engine installed.

Two independent triggers, either sufficient:

**A - recognition uncertainty.** A CTC recognizer's per-line score is a property
of its own decoding, computed identically on every crop, so a numeric threshold
against it means the same thing everywhere. A vision model's self-reported
confidence is a *generated token* and is deliberately not used here: gating on
it would let the model decide when to escalate to itself.

**B - structural / out-of-distribution.** Confidence detects ambiguous ink. It
does not detect content the recognizer has no vocabulary for. Given a display
equation, a line recognizer emits a short plausible string with a *high* score
and ~100% error. A first probe of the real solution page did exactly this:
isolated digits "7", "7", "5" at ~0.99999 with the fraction structure gone. A
confidence-only gate would have accepted all of it. Trigger B never consults
the score.

Escalation is a pre-authorized budget, not a hidden fallback: the caller sets
explicit maxima and exceeding them is a hard failure, so nothing degrades
silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from packages.ocr.types import BoundingBox, OcrLine, OcrPageReading

# Reason codes are recorded per page so a teacher and an auditor can see which
# trigger fired, not merely that something did.
REASON_LOW_LINE_CONFIDENCE = "low_line_confidence"
REASON_UNCOVERED_INK = "uncovered_ink"
REASON_TALL_BOX_MATH = "tall_box_math"
REASON_SPLIT_BOX_FRACTION = "split_box_fraction"
REASON_SPARSE_DECODE = "sparse_decode"
REASON_DOCUMENT_ROLE_HANDWRITTEN = "document_role_handwritten"
REASON_NO_LINES_DETECTED = "no_lines_detected"
REASON_AREA_ROLLUP = "escalated_area_rollup"
REASON_REGION_COUNT_ROLLUP = "escalated_region_count_rollup"

DECISION_ACCEPTED = "tier1_accepted"
DECISION_ESCALATED_REGIONS = "escalated_regions"
DECISION_ESCALATED_PAGE = "escalated_page"


@dataclass(frozen=True)
class EscalationPolicy:
    """Thresholds governing escalation.

    PROVISIONAL: every default below is a placeholder until the bake-off's
    reliability table and escalation ROC are computed against teacher-labelled
    fixtures. Shipping these as if they were measured would repeat the mistake
    the reference-bundle token budget made.
    """

    line_confidence_escalate_below: Decimal = Decimal("0.80")
    uncovered_ink_escalate_above: Decimal = Decimal("0.20")
    tall_box_median_ratio: float = 1.8
    min_decoded_chars_per_100px: float = 1.0
    page_escalation_area_fraction: Decimal = Decimal("0.40")
    max_regions_before_page_escalation: int = 4
    region_padding_px: float = 8.0
    # Merge flagged neighbours within this multiple of the median line height.
    region_merge_gap_ratio: float = 1.5
    # A teacher may declare a document handwritten. A human lowering the bar for
    # a known-hard document is auditable; a model doing it is not.
    handwritten_confidence_bonus: Decimal = Decimal("0.05")


@dataclass(frozen=True)
class EscalationDecision:
    decision: str
    reason_codes: list[str]
    regions: list[BoundingBox] = field(default_factory=list)
    flagged_line_indexes: list[int] = field(default_factory=list)

    @property
    def escalated(self) -> bool:
        return self.decision != DECISION_ACCEPTED


def effective_confidence_threshold(
    policy: EscalationPolicy, *, expect_handwritten: bool
) -> Decimal:
    if not expect_handwritten:
        return policy.line_confidence_escalate_below
    return min(
        Decimal("1"),
        policy.line_confidence_escalate_below + policy.handwritten_confidence_bonus,
    )


def _median_line_height(lines: list[OcrLine]) -> float:
    heights = [line.bbox.height for line in lines if line.bbox is not None and line.bbox.height > 0]
    if not heights:
        return 0.0
    return float(median(heights))


def _is_tall_box(line: OcrLine, *, median_height: float, policy: EscalationPolicy) -> bool:
    """A box much taller than the page's typical line is usually stacked math."""
    if line.bbox is None or median_height <= 0:
        return False
    return line.bbox.height > median_height * policy.tall_box_median_ratio


def _is_sparse_decode(line: OcrLine, *, policy: EscalationPolicy) -> bool:
    """Very little text decoded from a wide box means content was dropped."""
    if line.bbox is None or line.bbox.width <= 0:
        return False
    decoded = len(line.text.strip())
    per_100px = decoded / (line.bbox.width / 100.0)
    return per_100px < policy.min_decoded_chars_per_100px


def _split_box_partners(lines: list[OcrLine], *, median_height: float) -> set[int]:
    """Indexes of boxes that look like the halves of one split fraction.

    Two boxes stacked directly above one another with overlapping x-range and a
    gap far smaller than a line height are usually a numerator and denominator
    the recognizer read as separate lines, losing the division entirely.
    """
    flagged: set[int] = set()
    if median_height <= 0:
        return flagged
    for i, first in enumerate(lines):
        if first.bbox is None:
            continue
        for j in range(i + 1, len(lines)):
            second = lines[j]
            if second.bbox is None:
                continue
            if not first.bbox.overlaps_horizontally(second.bbox):
                continue
            if first.bbox.vertical_gap_to(second.bbox) < median_height * 0.5:
                flagged.add(i)
                flagged.add(j)
    return flagged


def merge_regions(
    boxes: list[BoundingBox], *, median_height: float, policy: EscalationPolicy
) -> list[BoundingBox]:
    """Coalesce flagged boxes into as few crops as possible.

    Each escalated region costs a vision call, so neighbours are merged rather
    than sent one by one.
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda box: (box.y1, box.x1))
    gap_limit = median_height * policy.region_merge_gap_ratio if median_height > 0 else 0.0
    merged: list[BoundingBox] = [ordered[0]]
    for box in ordered[1:]:
        current = merged[-1]
        touching = current.overlaps_horizontally(box) and current.vertical_gap_to(box) <= gap_limit
        if touching:
            merged[-1] = current.merged_with(box)
        else:
            merged.append(box)
    return [box.padded(policy.region_padding_px) for box in merged]


def evaluate_page(
    reading: OcrPageReading,
    *,
    policy: EscalationPolicy | None = None,
    expect_handwritten: bool = False,
) -> EscalationDecision:
    """Decide whether this page's reading can be trusted as-is."""
    policy = policy or EscalationPolicy()
    reasons: list[str] = []

    if expect_handwritten:
        reasons.append(REASON_DOCUMENT_ROLE_HANDWRITTEN)

    # No lines at all on a page that plainly has content is a total miss, and
    # there is no per-line signal to catch it.
    if not reading.lines:
        return EscalationDecision(
            decision=DECISION_ESCALATED_PAGE,
            reason_codes=[*reasons, REASON_NO_LINES_DETECTED],
        )

    if (
        reading.uncovered_ink_ratio is not None
        and reading.uncovered_ink_ratio > policy.uncovered_ink_escalate_above
    ):
        return EscalationDecision(
            decision=DECISION_ESCALATED_PAGE,
            reason_codes=[*reasons, REASON_UNCOVERED_INK],
        )

    threshold = effective_confidence_threshold(policy, expect_handwritten=expect_handwritten)
    median_height = _median_line_height(reading.lines)
    split_partners = _split_box_partners(reading.lines, median_height=median_height)

    flagged_indexes: list[int] = []
    for index, line in enumerate(reading.lines):
        line_reasons: list[str] = []
        # Trigger A. A line with no reported confidence is not treated as
        # suspicious on that basis alone; the structural checks still apply.
        if line.confidence is not None and line.confidence < threshold:
            line_reasons.append(REASON_LOW_LINE_CONFIDENCE)
        # Trigger B, which never consults the score.
        if _is_tall_box(line, median_height=median_height, policy=policy):
            line_reasons.append(REASON_TALL_BOX_MATH)
        if index in split_partners:
            line_reasons.append(REASON_SPLIT_BOX_FRACTION)
        if _is_sparse_decode(line, policy=policy):
            line_reasons.append(REASON_SPARSE_DECODE)
        if line_reasons:
            flagged_indexes.append(index)
            for reason in line_reasons:
                if reason not in reasons:
                    reasons.append(reason)

    if not flagged_indexes:
        return EscalationDecision(
            decision=DECISION_ACCEPTED,
            reason_codes=reasons if expect_handwritten else [],
        )

    flagged_boxes = [
        reading.lines[index].bbox
        for index in flagged_indexes
        if reading.lines[index].bbox is not None
    ]
    # Without geometry there is nothing to crop, so the whole page must go.
    if not flagged_boxes:
        return EscalationDecision(
            decision=DECISION_ESCALATED_PAGE,
            reason_codes=reasons,
            flagged_line_indexes=flagged_indexes,
        )

    present_boxes = [box for box in flagged_boxes if box is not None]
    regions = merge_regions(present_boxes, median_height=median_height, policy=policy)

    # Compare unpadded flagged area against unpadded total. Measuring the
    # padded crops instead would inflate one short flagged line into most of
    # the page and roll up to a full-page call that was never warranted.
    total_text_area = sum(line.bbox.area for line in reading.lines if line.bbox is not None)
    flagged_area = sum(box.area for box in present_boxes)
    area_fraction = (
        Decimal(str(flagged_area)) / Decimal(str(total_text_area))
        if total_text_area > 0
        else Decimal("1")
    )

    # One call for the page beats several for most of it.
    if area_fraction >= policy.page_escalation_area_fraction:
        return EscalationDecision(
            decision=DECISION_ESCALATED_PAGE,
            reason_codes=[*reasons, REASON_AREA_ROLLUP],
            flagged_line_indexes=flagged_indexes,
        )
    if len(regions) > policy.max_regions_before_page_escalation:
        return EscalationDecision(
            decision=DECISION_ESCALATED_PAGE,
            reason_codes=[*reasons, REASON_REGION_COUNT_ROLLUP],
            flagged_line_indexes=flagged_indexes,
        )

    return EscalationDecision(
        decision=DECISION_ESCALATED_REGIONS,
        reason_codes=reasons,
        regions=regions,
        flagged_line_indexes=flagged_indexes,
    )
