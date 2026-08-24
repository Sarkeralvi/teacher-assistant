from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from packages.evaluation.ocr_engine_bakeoff import (
    UNLIMITED_OCR_ENV_VAR,
    EngineReading,
    Fixture,
    OcrBakeoffError,
    OcrLine,
    ProviderCallBudget,
    _unlimited_ocr_lines,
    _unlimited_ocr_text,
    build_engine_adapters,
    build_parser,
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


def test_qwen38_bakeoff_arm_uses_the_same_fail_closed_lease_as_production() -> None:
    # Offline arms remain DB-free.  The optional real Qwen arm must use the
    # single model slot rather than bypassing the application's scheduler.
    source = Path(
        Path(__file__).resolve().parents[1] / "packages" / "evaluation" / "ocr_engine_bakeoff.py"
    ).read_text(encoding="utf-8")

    assert "LocalModelLeaseService" in source
    assert "LocalAiPhaseManager" in source
    assert 'lease_holder_id=holder_id' in source


# ── Unlimited-OCR arm ──────────────────────────────────────────────────────


def test_unlimited_ocr_reads_grounded_spans_as_lines_with_no_confidence() -> None:
    """It is a generative VLM, so there is no per-line decoding statistic.

    Lines must carry confidence=None rather than a substituted number the
    engine never produced; the escalation policy already handles None.
    """
    payload = {
        "markdown": "1(a)(i)\n\nP(D) = 0.3",
        "layout": [
            {"label": "1(a)(i)", "boxes": [[10, 20, 110, 60]]},
            {"label": "P(D) = 0.3", "boxes": [[10, 70, 300, 110]]},
        ],
    }

    lines = _unlimited_ocr_lines(payload)

    assert [line.text for line in lines] == ["1(a)(i)", "P(D) = 0.3"]
    assert all(line.confidence is None for line in lines)
    assert lines[1].bbox == (10.0, 70.0, 300.0, 110.0)


def test_unlimited_ocr_prefers_the_models_own_markdown_over_rejoined_spans() -> None:
    payload = {"markdown": "# Heading\n\n$P(D)=0.3$", "layout": [{"label": "x", "boxes": []}]}

    assert _unlimited_ocr_text(payload, _unlimited_ocr_lines(payload)) == "# Heading\n\n$P(D)=0.3$"


def test_unlimited_ocr_falls_back_to_span_text_when_no_markdown_is_present() -> None:
    payload = {"layout": [{"label": "one", "boxes": []}, {"label": "two", "boxes": []}]}

    assert _unlimited_ocr_text(payload, _unlimited_ocr_lines(payload)) == "one\ntwo"


def test_unlimited_ocr_expands_a_span_carrying_several_boxes() -> None:
    payload = {"layout": [{"label": "continued", "boxes": [[0, 0, 10, 10], [0, 20, 10, 30]]}]}

    lines = _unlimited_ocr_lines(payload)

    assert len(lines) == 2
    assert {line.text for line in lines} == {"continued"}


def test_unlimited_ocr_degrades_to_no_geometry_on_an_unexpected_shape() -> None:
    """A 0.x third-party CLI may change its JSON; that must not crash the run.

    An arm reporting no boxes is visible in the report, which is the intended
    failure mode. Raising here would take down the other arms with it.
    """
    for payload in ({"layout": "not a list"}, {"layout": [42, None]}, [], "text", None):
        assert _unlimited_ocr_lines(payload) == []


def test_unlimited_ocr_arm_is_offered_without_a_provider_budget() -> None:
    # It runs as a local CPU subprocess, so it must not consume provider calls.
    adapters = build_engine_adapters(ProviderCallBudget(authorized=False, maximum=0))

    assert "unlimited_ocr" in adapters


def test_the_cli_default_engine_list_names_only_real_arms() -> None:
    """The previous default named arms build_engine_adapters does not provide,
    so the CLI exited with "Unknown engine arms" on its own defaults."""
    available = build_engine_adapters(ProviderCallBudget(authorized=False, maximum=0))
    default = build_parser().get_default("engines")

    requested = [name.strip() for name in default.split(",") if name.strip()]
    assert requested
    assert [name for name in requested if name not in available] == []
    # The default must not make real provider calls.
    assert "qwen38_vision" not in requested


def test_a_missing_focr_binary_reports_how_to_enable_the_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(UNLIMITED_OCR_ENV_VAR, str(tmp_path / "definitely-absent.exe"))
    adapters = build_engine_adapters(ProviderCallBudget(authorized=False, maximum=0))

    with pytest.raises(OcrBakeoffError, match="focr CLI is not installed"):
        adapters["unlimited_ocr"](b"\x89PNG\r\n\x1a\n", "image/png")
