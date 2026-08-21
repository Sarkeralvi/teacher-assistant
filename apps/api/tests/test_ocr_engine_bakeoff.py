from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from packages.evaluation.ocr_engine_bakeoff import (
    EngineReading,
    Fixture,
    OcrBakeoffError,
    OcrLine,
    ProviderCallBudget,
    build_engine_adapters,
    escalation_roc,
    load_fixtures,
    reliability_table,
    run_bakeoff,
    score_reading,
    write_fixture_template,
)


def _png(path: Path) -> Path:
    # A real 1x1 PNG so adapters that check magic bytes see a valid image.
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c6300010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
    )
    return path


def _fixture(tmp_path: Path, ground_truth: str = "P(B|L) = 7/12") -> Fixture:
    return Fixture(
        fixture_id="rubric_p1",
        image_path=_png(tmp_path / "rubric_p1.png"),
        ground_truth=ground_truth,
        critical_tokens=["7/12"],
        kind="handwriting",
    )


def test_scoring_separates_math_fidelity_from_character_error(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    # Fluent prose, wrong fraction: CER stays low while the mark-changing token
    # is lost. Reporting only CER would hide exactly the failure that matters.
    reading = EngineReading(
        engine="fake",
        text="P(B|L) = 1/12",
        lines=[OcrLine(text="P(B|L) = 1/12", confidence=Decimal("0.95"))],
        latency_ms=12,
    )

    row = score_reading(fixture, reading)

    assert Decimal(row["cer"]) < Decimal("0.2")
    assert Decimal(row["critical_token_recall"]) < Decimal("1")


def test_reliability_table_reports_error_per_confidence_bin() -> None:
    observations = [
        (Decimal("0.95"), Decimal("0.01")),
        (Decimal("0.92"), Decimal("0.03")),
        (Decimal("0.55"), Decimal("0.40")),
        (Decimal("0.52"), Decimal("0.60")),
    ]

    rows = reliability_table(observations)

    by_bin = {row["confidence_bin"]: row for row in rows}
    assert Decimal(by_bin["0.9-1.0"]["mean_cer"]) < Decimal(by_bin["0.5-0.6"]["mean_cer"])
    assert Decimal(by_bin["0.5-0.6"]["bad_line_rate"]) == Decimal("1")


def test_reliability_table_exposes_an_uninformative_confidence_signal() -> None:
    # The kill criterion: if error does not vary with confidence, no threshold
    # drawn from it is defensible and the confidence gate must be abandoned.
    flat = [
        (Decimal("0.95"), Decimal("0.30")),
        (Decimal("0.55"), Decimal("0.30")),
    ]

    rows = reliability_table(flat)

    means = {Decimal(row["mean_cer"]) for row in rows}
    assert means == {Decimal("0.30")}


def test_escalation_roc_trades_recall_against_cost() -> None:
    observations = [
        (Decimal("0.95"), Decimal("0.01")),
        (Decimal("0.40"), Decimal("0.90")),
    ]

    rows = escalation_roc(observations)

    at_zero = next(row for row in rows if row["threshold"] == "0")
    at_one = next(row for row in rows if row["threshold"] == "1")
    assert at_zero["escalation_cost"] == "0"
    assert at_one["escalation_cost"] == "1"
    assert Decimal(at_one["bad_line_recall"]) == Decimal("1")


def test_provider_arms_refuse_without_explicit_authorization(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    budget = ProviderCallBudget(authorized=False, maximum=6)
    adapters = build_engine_adapters(budget)

    report = run_bakeoff(fixtures=[fixture], engines={"qwen38_vision": adapters["qwen38_vision"]})

    # Refusal must be recorded as skipped, never as a zero-error result.
    assert report["readings"] == []
    assert "qwen38_vision" in report["skipped_engines"]
    assert budget.used == 0


def test_provider_budget_stops_at_its_ceiling() -> None:
    budget = ProviderCallBudget(authorized=True, maximum=2)

    budget.spend()
    budget.spend()

    with pytest.raises(OcrBakeoffError, match="budget"):
        budget.spend()


def test_missing_engine_dependency_skips_its_arm_rather_than_failing(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    def unavailable(_image: bytes, _mime: str) -> EngineReading:
        raise OcrBakeoffError("rapidocr is not installed; install it to run this arm")

    report = run_bakeoff(fixtures=[fixture], engines={"rapidocr_ppocrv5": unavailable})

    assert report["readings"] == []
    assert "not installed" in report["skipped_engines"]["rapidocr_ppocrv5"]


def test_unlabelled_fixtures_are_refused(tmp_path: Path) -> None:
    _png(tmp_path / "a.png")
    (tmp_path / "fixtures.json").write_text(
        json.dumps({"fixtures": [{"id": "a", "image": "a.png", "ground_truth": "  "}]}),
        encoding="utf-8",
    )

    # Scoring against an empty ground truth would silently report a perfect or
    # meaningless rate, which is worse than refusing.
    with pytest.raises(OcrBakeoffError, match="no ground_truth"):
        load_fixtures(tmp_path)


def test_an_unverified_ocr_draft_is_refused_as_an_answer_key(tmp_path: Path) -> None:
    """The trap that makes seeding ground_truth from OCR safe.

    Seeding saves the teacher typing, but an unchecked draft is the engine's own
    reading. Scoring against it would report a flawless result for an engine
    that misread every line, so it must be refused until a human confirms it.
    """
    _png(tmp_path / "a.png")
    (tmp_path / "fixtures.json").write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "id": "a",
                        "image": "a.png",
                        "ground_truth": "P(D)=03",
                        "verified": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(OcrBakeoffError, match="not verified"):
        load_fixtures(tmp_path)


def test_a_verified_fixture_loads(tmp_path: Path) -> None:
    _png(tmp_path / "a.png")
    (tmp_path / "fixtures.json").write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "id": "a",
                        "image": "a.png",
                        "ground_truth": "P(D) = 0.3",
                        "verified": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_fixtures(tmp_path)[0].ground_truth == "P(D) = 0.3"


def test_fixtures_written_with_a_windows_bom_still_load(tmp_path: Path) -> None:
    # Notepad and PowerShell's Out-File both add a BOM. A teacher editing this
    # file by hand must not be met with a JSON syntax error they did not cause.
    _png(tmp_path / "a.png")
    (tmp_path / "fixtures.json").write_text(
        json.dumps(
            {
                "fixtures": [
                    {"id": "a", "image": "a.png", "ground_truth": "7/12", "verified": True}
                ]
            }
        ),
        encoding="utf-8-sig",
    )

    fixtures = load_fixtures(tmp_path)

    assert fixtures[0].ground_truth == "7/12"


def test_fixture_template_round_trips_once_labelled(tmp_path: Path) -> None:
    image = _png(tmp_path / "solution_p1.png")
    manifest = write_fixture_template(tmp_path, [image])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["fixtures"][0]["ground_truth"] = "P(X) = 7/12"
    payload["fixtures"][0]["dataset"] = "holdout"
    payload["fixtures"][0]["verified"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    fixtures = load_fixtures(tmp_path)

    assert fixtures[0].fixture_id == "solution_p1"
    assert fixtures[0].dataset == "holdout"

    with pytest.raises(OcrBakeoffError, match="Refusing to overwrite"):
        write_fixture_template(tmp_path, [image])


def test_line_scoring_matches_a_single_line_not_the_whole_page() -> None:
    """Regression: the reliability table once measured nothing.

    _closest_line_cer normalized before splitting on newlines, but
    normalize_text collapses all whitespace including newlines, so the whole
    page became one candidate "line". Every line then scored ~0.97 against the
    full document, error looked flat across confidence bins, and the confidence
    gate would have been abandoned on the strength of a measurement artefact.
    """
    from packages.evaluation.ocr_engine_bakeoff import _closest_line_cer

    ground_truth = "P(D) = 0.3\nP(W) = 0.3\nP(B) = 0.4"

    # A line that exactly matches one ground-truth line must score ~0.
    assert _closest_line_cer(ground_truth, "P(W) = 0.3") < Decimal("0.01")
    # A line matching nothing must score high, so the two are distinguishable.
    assert _closest_line_cer(ground_truth, "completely different text") > Decimal("0.5")


def test_harness_imports_no_application_services() -> None:
    # It must never be able to touch product state.
    source = Path(
        Path(__file__).resolve().parents[1] / "packages" / "evaluation" / "ocr_engine_bakeoff.py"
    ).read_text(encoding="utf-8")

    assert "from app.services" not in source
    assert "SessionLocal" not in source
