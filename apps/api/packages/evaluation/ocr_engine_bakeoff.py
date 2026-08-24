"""Offline bake-off for candidate tier-1 OCR engines.

Chooses the tier-1 engine from measurements rather than assertion. Neither
PaddleOCR nor Qwen3.8 has real accuracy evidence on this material: no teacher
ever confirmed a PaddleOCR reading, and Qwen3.8 has exactly one confirmed
transcription.

The deliverable is not "which engine has the lowest error rate". It is the
**confidence calibration**: whether a reported confidence predicts actual
error well enough to gate escalation on it. If error is flat across confidence
bins, the confidence-gate premise fails and the tiered design must be
re-planned around structural triggers only. That is a result worth having
before writing pipeline code, not after.

Deliberate constraints:

* Imports nothing from ``app.services`` and touches no database, so it can
  never alter product state.
* Every engine dependency is imported lazily inside its adapter, so a missing
  package skips that arm instead of breaking collection of the whole test suite.
* Provider-backed arms are off unless explicitly authorized and capped.
* Fixtures and results live under gitignored ``data/evaluation/``. Nothing here
  writes an image, a transcription, or a per-page result into the repository.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from packages.evaluation.local_curated_evaluation import (
    character_error_rate,
    critical_token_recall,
    sha256_bytes,
    word_error_rate,
)

# A line is "bad" when it is wrong enough that a teacher would have to correct
# it. The escalation ROC measures how well confidence separates these.
BAD_LINE_CER = Decimal("0.15")
CONFIDENCE_BINS = (
    Decimal("0.0"),
    Decimal("0.5"),
    Decimal("0.6"),
    Decimal("0.7"),
    Decimal("0.8"),
    Decimal("0.9"),
    Decimal("1.0"),
)


class OcrBakeoffError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: Decimal | None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class EngineReading:
    """One engine's reading of one image. Engine-agnostic on purpose."""

    engine: str
    text: str
    lines: list[OcrLine]
    latency_ms: int
    model_load_ms: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def confidences(self) -> list[Decimal]:
        return [line.confidence for line in self.lines if line.confidence is not None]


@dataclass(frozen=True)
class Fixture:
    """One labelled image.

    ``critical_tokens`` are the symbols whose loss changes the mark - fraction
    bars, complement bars, intersections, digits. Raw CER punishes harmless
    formatting differences equally, which would make every engine look the same
    on exactly the content that matters for grading.
    """

    fixture_id: str
    image_path: Path
    ground_truth: str
    critical_tokens: list[str] = field(default_factory=list)
    kind: str = "unknown"
    dataset: str = "dev"


EngineAdapter = Callable[[bytes, str], EngineReading]


# ── Engine adapters (lazily imported) ─────────────────────────────────────


def _sequence_or_empty(value: Any) -> list[Any]:
    """Coerce an optional result field to a list.

    Not ``value or []``: RapidOCR returns numpy arrays, and their truthiness
    raises "the truth value of an array with more than one element is
    ambiguous" rather than being falsy when empty.
    """
    if value is None:
        return []
    return list(value)


def _rapidocr_adapter() -> EngineAdapter:
    def run(image_bytes: bytes, _mime: str) -> EngineReading:
        try:
            from rapidocr import RapidOCR  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise OcrBakeoffError(
                "rapidocr is not installed; install it to run this arm"
            ) from exc
        load_start = time.perf_counter()
        engine = RapidOCR()
        model_load_ms = int((time.perf_counter() - load_start) * 1000)

        # RapidOCR takes raw bytes; handing it a PIL Image raises.
        start = time.perf_counter()
        result = engine(image_bytes)
        latency_ms = int((time.perf_counter() - start) * 1000)

        lines: list[OcrLine] = []
        texts = _sequence_or_empty(getattr(result, "txts", None))
        scores = _sequence_or_empty(getattr(result, "scores", None))
        boxes = _sequence_or_empty(getattr(result, "boxes", None))
        for index, text in enumerate(texts):
            score = scores[index] if index < len(scores) else None
            box = boxes[index] if index < len(boxes) else None
            lines.append(
                OcrLine(
                    text=str(text),
                    confidence=Decimal(str(round(float(score), 6))) if score is not None else None,
                    bbox=_normalize_bbox(box),
                )
            )
        return EngineReading(
            engine="rapidocr",
            text="\n".join(line.text for line in lines),
            lines=lines,
            latency_ms=latency_ms,
            model_load_ms=model_load_ms,
        )

    return run


def _tesseract_adapter() -> EngineAdapter:
    def run(image_bytes: bytes, _mime: str) -> EngineReading:
        try:
            import pytesseract  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise OcrBakeoffError(
                "pytesseract is not installed; install it to run this arm"
            ) from exc
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
        start = time.perf_counter()
        data = pytesseract.image_to_data(
            image, config="--psm 6", output_type=pytesseract.Output.DICT
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Tesseract reports per-word; group into lines so confidence is
        # comparable with the line-level scores other engines emit.
        grouped: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
        for index, word in enumerate(data.get("text", [])):
            if not str(word).strip():
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            grouped.setdefault(key, []).append((str(word), float(data["conf"][index])))

        lines = []
        for key in sorted(grouped):
            words = grouped[key]
            mean_conf = sum(score for _text, score in words) / len(words) / 100.0
            lines.append(
                OcrLine(
                    text=" ".join(text for text, _score in words),
                    confidence=Decimal(str(round(max(mean_conf, 0.0), 6))),
                )
            )
        return EngineReading(
            engine="tesseract",
            text="\n".join(line.text for line in lines),
            lines=lines,
            latency_ms=latency_ms,
        )

    return run


UNLIMITED_OCR_ENV_VAR = "FOCR_BINARY"
_UNLIMITED_OCR_TIMEOUT_SECONDS = 900


def _unlimited_ocr_binary() -> str | None:
    """Locate the focr CLI without importing anything or assuming a PATH entry.

    Its Windows installer adds itself to the user PATH, which an already-running
    process does not see, so the default install location is checked directly.
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    override = os.environ.get(UNLIMITED_OCR_ENV_VAR, "").strip()
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which("focr")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "focr" / "focr.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _run_focr(
    binary: str, image_bytes: bytes, mime: str, extra_args: list[str]
) -> tuple[Any, int]:
    """Shell out to the focr CLI and return its parsed JSON payload plus latency.

    Shared by every focr-backed arm (unlimited-ocr, got-ocr2, ...) so the
    subprocess/tempfile/error-handling shape is written once. ``extra_args``
    carries what differs between them: got-ocr2 needs ``--model`` and
    ``--task``, the default unlimited-ocr run needs nothing extra.

    A resident warm-model daemon (focr's own, not this bake-off's) keeps
    weights loaded between invocations, so only the first call per model pays
    load time; that is a property of the real deployment shape, not a
    measurement artefact to correct for.
    """
    import json as _json  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    suffix = ".png" if "png" in mime else ".jpg"
    with tempfile.TemporaryDirectory(prefix="focr-bakeoff-") as directory:
        image_path = Path(directory) / f"page{suffix}"
        image_path.write_bytes(image_bytes)
        start = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603
                [binary, "ocr", str(image_path), *extra_args, "--json"],
                capture_output=True,
                timeout=_UNLIMITED_OCR_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrBakeoffError(
                f"focr did not finish within {_UNLIMITED_OCR_TIMEOUT_SECONDS}s"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()[:400]
        raise OcrBakeoffError(f"focr exited {completed.returncode}: {detail}")
    raw = completed.stdout.decode("utf-8", "replace").strip()
    if not raw:
        raise OcrBakeoffError("focr produced no output")
    try:
        payload = _json.loads(raw)
    except ValueError as exc:
        raise OcrBakeoffError(f"focr output was not JSON: {raw[:200]!r}") from exc
    return payload, latency_ms


def _unlimited_ocr_adapter() -> EngineAdapter:
    """Baidu Unlimited-OCR via the franken_ocr CPU-only Rust CLI.

    A candidate tier-1 engine, run as a subprocess rather than an import: there
    is no Python package, and the official runtimes are CUDA/vLLM, which would
    contend for the single GPU model slot the lease exists to protect.

    It is a generative VLM, so it reports no per-line decoding statistic. Lines
    therefore carry ``confidence=None``, which the escalation policy already
    handles: the detection-only script policy never consults confidence, and the
    reference-phase policy treats a missing score as "not suspicious on that
    basis alone" rather than substituting a number the engine never produced.

    Its published OmniDocBench score explicitly excludes handwriting, so nothing
    here may be inferred from it. This arm exists to measure handwriting on the
    local teacher-verified fixtures, which is the only evidence that counts.
    """

    def run(image_bytes: bytes, mime: str) -> EngineReading:
        binary = _unlimited_ocr_binary()
        if binary is None:
            raise OcrBakeoffError(
                "the focr CLI is not installed; install franken_ocr or set "
                f"{UNLIMITED_OCR_ENV_VAR} to run this arm"
            )
        payload, latency_ms = _run_focr(binary, image_bytes, mime, [])
        lines = _unlimited_ocr_lines(payload)
        return EngineReading(
            engine="unlimited_ocr",
            text=_unlimited_ocr_text(payload, lines),
            lines=lines,
            latency_ms=latency_ms,
            warnings=["engine_reports_no_per_line_confidence"],
        )

    return run


def _got_ocr2_formula_adapter() -> EngineAdapter:
    """GOT-OCR2.0 in formula mode: math/formulas -> LaTeX, via the same CLI.

    A second tier-1 candidate, specifically for the failure Unlimited-OCR's
    "FAST plain-text OCR" framing does not claim to solve: typeset and
    handwritten mathematics shredded into confident fragments, which is
    RapidOCR's own measured weak point (0.215 CER, 0.771 math-token recall on
    typeset math; worse on handwriting). ``--task formula`` routes to
    got-ocr2's structured "OCR with format" mode, which emits inline LaTeX
    rather than plain text, so a correctly-read fraction survives as
    ``\\frac{...}{...}`` instead of being flattened into digits.

    Needs ``focr pull got-ocr2`` in addition to the default model. Apache-2.0,
    so no licence blocker if it is ever adopted for the reference phase's
    typeset-math pages specifically, distinct from the tier-1 decision here.
    """

    def run(image_bytes: bytes, mime: str) -> EngineReading:
        binary = _unlimited_ocr_binary()
        if binary is None:
            raise OcrBakeoffError(
                "the focr CLI is not installed; install franken_ocr or set "
                f"{UNLIMITED_OCR_ENV_VAR} to run this arm"
            )
        payload, latency_ms = _run_focr(
            binary,
            image_bytes,
            mime,
            ["--model", "got-ocr2.int8.focrq", "--task", "formula"],
        )
        lines = _unlimited_ocr_lines(payload)
        return EngineReading(
            engine="got_ocr2_formula",
            text=_unlimited_ocr_text(payload, lines),
            lines=lines,
            latency_ms=latency_ms,
            warnings=["engine_reports_no_per_line_confidence"],
        )

    return run


def _unlimited_ocr_lines(payload: Any) -> list[OcrLine]:
    """Read grounded spans out of the focr JSON.

    Tolerant by design: this is a third-party CLI at 0.x, so an unexpected shape
    must degrade to "no geometry" rather than crash the whole bake-off. A shape
    change shows up as an arm with no boxes, which is visible in the report.
    """
    if not isinstance(payload, dict):
        return []
    layout = payload.get("layout")
    if not isinstance(layout, list):
        return []
    lines: list[OcrLine] = []
    for entry in layout:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("label") or entry.get("text") or "").strip()
        boxes = entry.get("boxes") or entry.get("bbox")
        if isinstance(boxes, list) and boxes and isinstance(boxes[0], (list, tuple)):
            candidates = boxes
        elif isinstance(boxes, list) and boxes:
            candidates = [boxes]
        else:
            candidates = [None]
        for box in candidates:
            if not text and box is None:
                continue
            lines.append(OcrLine(text=text, confidence=None, bbox=_focr_bbox(box)))
    return lines


def _focr_bbox(box: Any) -> tuple[float, float, float, float] | None:
    """Convert a focr box to (x1, y1, x2, y2) in source-image pixels.

    focr reports a flat ``[x1, y1, x2, y2]``, where RapidOCR reports a polygon
    of corner points. ``_normalize_bbox`` handles the polygon form and returns
    None for the flat one, so this is a separate converter rather than a change
    to the shared helper. A polygon is still accepted in case the CLI's shape
    changes.
    """
    if box is None:
        return None
    try:
        values = list(box)
    except TypeError:
        return None
    if len(values) == 4 and all(isinstance(item, (int, float)) for item in values):
        x1, y1, x2, y2 = (float(item) for item in values)
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    return _normalize_bbox(box)


def _unlimited_ocr_text(payload: Any, lines: list[OcrLine]) -> str:
    """Prefer the model's own rendered markdown over re-joining spans.

    The spans exist to give geometry; the markdown is what the model actually
    read, and joining spans would drop structure it encoded there.
    """
    if isinstance(payload, dict):
        for key in ("markdown", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return "\n".join(line.text for line in lines if line.text)


def _qwen38_vision_adapter(*, budget: ProviderCallBudget) -> EngineAdapter:
    """The incumbent, as an accuracy ceiling and latency baseline.

    Without this arm the new pipeline can be claimed faster but not as good.
    Its self-reported confidence is recorded but must NOT be used as an
    escalation gate: it is a generated token, not a decoding statistic, so
    gating on it would let the model decide when to escalate to itself.
    """

    def run(image_bytes: bytes, mime: str) -> EngineReading:
        from uuid import uuid4  # noqa: PLC0415

        from app.core.config import get_settings  # noqa: PLC0415
        from app.db.session import SessionLocal  # noqa: PLC0415
        from app.services.local_ai_phase_manager import LocalAiPhaseManager  # noqa: PLC0415
        from app.services.local_model_lease_service import (  # noqa: PLC0415
            LocalModelLeaseError,
            LocalModelLeaseService,
        )
        from packages.brain.llama_cpp_qwen38_vision_provider import (  # noqa: PLC0415
            LlamaCppQwen38VisionProvider,
        )

        settings = get_settings()
        budget.ensure_allowed()
        db = SessionLocal()
        holder_id = f"ocr_bakeoff:{uuid4().hex}"
        try:
            lease = LocalModelLeaseService(db)
            with lease.hold(
                model_phase="Qwen38",
                holder_kind="ocr_bakeoff",
                holder_id=holder_id,
            ):
                LocalAiPhaseManager(settings=settings, db=db).switch(
                    "Qwen38", lease_holder_id=holder_id
                )
                provider = LlamaCppQwen38VisionProvider(
                    api_key=settings.local_qwen38_api_key,
                    model_name=settings.local_qwen38_model,
                    base_url=settings.local_qwen38_base_url,
                    timeout_seconds=settings.local_qwen38_timeout_seconds,
                    context_tokens=settings.local_qwen38_context_tokens,
                )
                provider.verify_available_model()
                lease.heartbeat(holder_id=holder_id)
                budget.spend()
                start = time.perf_counter()
                output = provider.transcribe_image(image_bytes=image_bytes, mime_type=mime)
                latency_ms = int((time.perf_counter() - start) * 1000)
                lease.heartbeat(holder_id=holder_id)
        except LocalModelLeaseError as exc:
            raise OcrBakeoffError(
                "The local model slot is busy; no Qwen3.8 bake-off call was made"
            ) from exc
        finally:
            db.close()
        return EngineReading(
            engine="qwen38_vision",
            text=output.draft_text,
            lines=[OcrLine(text=output.draft_text, confidence=None)],
            latency_ms=latency_ms,
            warnings=["self_reported_confidence_is_not_a_gate"],
        )

    return run


@dataclass
class ProviderCallBudget:
    """A hard ceiling on real provider calls, spent before the call is made."""

    authorized: bool
    maximum: int
    used: int = 0

    def ensure_allowed(self) -> None:
        if not self.authorized:
            raise OcrBakeoffError(
                "This arm makes real provider calls; re-run with "
                "--i-authorize-provider-calls to allow them."
            )
        if self.used >= self.maximum:
            raise OcrBakeoffError(
                f"Provider call budget of {self.maximum} is exhausted; stopping rather "
                "than making an unauthorized call."
            )

    def spend(self) -> None:
        self.ensure_allowed()
        self.used += 1


def build_engine_adapters(budget: ProviderCallBudget) -> dict[str, EngineAdapter]:
    # One rapidocr arm, not two: rapidocr 3.9.2 ships PP-OCRv6 det/rec/cls as
    # its defaults, so naming separate v5 and v6 arms would have labelled the
    # same models twice. Model files are reported by the engine at load time.
    return {
        "rapidocr": _rapidocr_adapter(),
        "tesseract": _tesseract_adapter(),
        # Candidate tier-1 replacements. Local CPU subprocess, so neither needs
        # a provider budget and neither touches the GPU model slot.
        "unlimited_ocr": _unlimited_ocr_adapter(),
        "got_ocr2_formula": _got_ocr2_formula_adapter(),
        "qwen38_vision": _qwen38_vision_adapter(budget=budget),
    }


# ── Metrics ───────────────────────────────────────────────────────────────


def _normalize_bbox(box: Any) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    try:
        points = [(float(point[0]), float(point[1])) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _bin_label(value: Decimal) -> str:
    for lower, upper in zip(CONFIDENCE_BINS, CONFIDENCE_BINS[1:], strict=False):
        if lower <= value < upper:
            return f"{lower}-{upper}"
    return f"{CONFIDENCE_BINS[-2]}-{CONFIDENCE_BINS[-1]}"


def score_reading(fixture: Fixture, reading: EngineReading) -> dict[str, Any]:
    return {
        "fixture_id": fixture.fixture_id,
        "kind": fixture.kind,
        "dataset": fixture.dataset,
        "engine": reading.engine,
        "cer": str(character_error_rate(fixture.ground_truth, reading.text)),
        "wer": str(word_error_rate(fixture.ground_truth, reading.text)),
        # Scored apart from CER: a fluent sentence with a mangled fraction is a
        # grading failure even though its character error rate looks acceptable.
        "critical_token_recall": str(
            critical_token_recall(fixture.critical_tokens, reading.text)
        ),
        "latency_ms": reading.latency_ms,
        "model_load_ms": reading.model_load_ms,
        "line_count": len(reading.lines),
        "reported_confidence_lines": len(reading.confidences),
        "warnings": list(reading.warnings),
    }


def reliability_table(line_observations: Iterable[tuple[Decimal, Decimal]]) -> list[dict[str, Any]]:
    """Mean line error per confidence bin.

    This is the result that decides whether the confidence gate is viable at
    all. Flat error across bins means the score carries no information about
    correctness, and no threshold chosen from it would be defensible.
    """
    buckets: dict[str, list[Decimal]] = {}
    for confidence, cer in line_observations:
        buckets.setdefault(_bin_label(confidence), []).append(cer)
    rows = []
    for label in sorted(buckets):
        errors = buckets[label]
        rows.append(
            {
                "confidence_bin": label,
                "lines": len(errors),
                "mean_cer": str(sum(errors) / Decimal(len(errors))),
                "bad_line_rate": str(
                    Decimal(sum(1 for value in errors if value > BAD_LINE_CER))
                    / Decimal(len(errors))
                ),
            }
        )
    return rows


def escalation_roc(
    line_observations: Iterable[tuple[Decimal, Decimal]],
) -> list[dict[str, Any]]:
    """Recall of bad lines against escalation cost, per candidate threshold.

    The knee of this curve is the only honest way to choose
    OCR_LINE_CONFIDENCE_ESCALATE_BELOW. Picking a round number instead would be
    the same guess the token-budget constant was.
    """
    observations = list(line_observations)
    if not observations:
        return []
    total = Decimal(len(observations))
    bad_total = Decimal(sum(1 for _conf, cer in observations if cer > BAD_LINE_CER))
    rows = []
    for step in range(0, 21):
        threshold = Decimal(step) / Decimal(20)
        escalated = [item for item in observations if item[0] < threshold]
        caught = sum(1 for _conf, cer in escalated if cer > BAD_LINE_CER)
        rows.append(
            {
                "threshold": str(threshold),
                "escalation_cost": str(Decimal(len(escalated)) / total),
                "bad_line_recall": (
                    str(Decimal(caught) / bad_total) if bad_total else "1"
                ),
            }
        )
    return rows


# ── Fixtures ──────────────────────────────────────────────────────────────


def load_fixtures(fixtures_dir: Path) -> list[Fixture]:
    """Load ``fixtures.json`` from a gitignored evaluation directory.

    Ground truth is the one part only a teacher can supply. Without it the
    harness produces impressions, not error rates, so a missing or unlabelled
    entry is refused rather than silently scored against an empty string.
    """
    manifest_path = fixtures_dir / "fixtures.json"
    if not manifest_path.is_file():
        raise OcrBakeoffError(
            f"No fixtures.json in {fixtures_dir}. Create it with one entry per "
            "labelled image; see write_fixture_template()."
        )
    # utf-8-sig, not utf-8: this file is edited by hand on Windows, where
    # Notepad and PowerShell's Out-File both write a BOM. Rejecting that with a
    # raw JSON decode error would send a teacher hunting a syntax mistake they
    # did not make.
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    fixtures: list[Fixture] = []
    for entry in payload.get("fixtures", []):
        image_path = (fixtures_dir / str(entry["image"])).resolve()
        if not image_path.is_file():
            raise OcrBakeoffError(f"Fixture image is missing: {image_path}")
        ground_truth = str(entry.get("ground_truth") or "").strip()
        if not ground_truth:
            raise OcrBakeoffError(
                f"Fixture '{entry.get('id')}' has no ground_truth. Every fixture must "
                "be labelled, or its scores are meaningless."
            )
        # ground_truth may be seeded from an engine's own output to save the
        # teacher typing. Until a human has checked it against the image it is
        # NOT an answer key: scoring an engine against its own reading would
        # report a flawless result for an engine that misread every line.
        if not bool(entry.get("verified", False)):
            raise OcrBakeoffError(
                f"Fixture '{entry.get('id')}' is not verified. Its ground_truth is an "
                "unchecked OCR draft; correct it against the image and set "
                '"verified": true. Delete the fixture to skip it instead.'
            )
        fixtures.append(
            Fixture(
                fixture_id=str(entry["id"]),
                image_path=image_path,
                ground_truth=ground_truth,
                critical_tokens=[str(token) for token in entry.get("critical_tokens", [])],
                kind=str(entry.get("kind", "unknown")),
                dataset=str(entry.get("dataset", "dev")),
            )
        )
    if not fixtures:
        raise OcrBakeoffError("fixtures.json contains no fixtures")
    return fixtures


def write_fixture_template(fixtures_dir: Path, images: list[Path]) -> Path:
    """Write a blank labelling template for the teacher to fill in."""
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = fixtures_dir / "fixtures.json"
    if manifest_path.exists():
        raise OcrBakeoffError(f"Refusing to overwrite existing fixtures at {manifest_path}")
    payload = {
        "note": (
            "Fill ground_truth with exactly what is written on the image, including "
            "mistakes. critical_tokens are the symbols whose loss would change the "
            "mark. dataset: 'dev' to tune thresholds, 'holdout' to validate them - "
            "never tune on holdout."
        ),
        "fixtures": [
            {
                "id": image.stem,
                "image": image.name,
                "kind": "unknown",
                "dataset": "dev",
                "ground_truth": "",
                "verified": False,
                "critical_tokens": [],
            }
            for image in images
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


# ── Runner ────────────────────────────────────────────────────────────────


def run_bakeoff(
    *,
    fixtures: list[Fixture],
    engines: dict[str, EngineAdapter],
) -> dict[str, Any]:
    per_reading: list[dict[str, Any]] = []
    line_observations: dict[str, list[tuple[Decimal, Decimal]]] = {}
    skipped: dict[str, str] = {}

    for engine_name, adapter in engines.items():
        for fixture in fixtures:
            image_bytes = fixture.image_path.read_bytes()
            mime = "image/png" if fixture.image_path.suffix.lower() == ".png" else "image/jpeg"
            try:
                reading = adapter(image_bytes, mime)
            except OcrBakeoffError as exc:
                # A missing optional dependency or an exhausted budget skips the
                # arm; it must not look like a zero-error result.
                skipped[engine_name] = str(exc)
                break
            row = score_reading(fixture, reading)
            row["image_sha256"] = sha256_bytes(image_bytes)
            per_reading.append(row)
            for line in reading.lines:
                if line.confidence is None:
                    continue
                line_observations.setdefault(engine_name, []).append(
                    (line.confidence, _closest_line_cer(fixture.ground_truth, line.text))
                )

    return {
        "readings": per_reading,
        "skipped_engines": skipped,
        "reliability": {
            engine: reliability_table(observations)
            for engine, observations in line_observations.items()
        },
        "escalation_roc": {
            engine: escalation_roc(observations)
            for engine, observations in line_observations.items()
        },
    }


def _closest_line_cer(ground_truth: str, line_text: str) -> Decimal:
    """Score a line against its best-matching ground-truth line.

    Engines split lines differently, so comparing line N to line N would
    measure segmentation disagreement rather than recognition error.

    Split on raw newlines BEFORE normalizing: normalize_text collapses all
    whitespace including newlines, so normalizing first yields a single
    "line" containing the whole page. Every line then scored ~0.97 against
    the full document, which made confidence look uninformative in the
    reliability table and would have killed the confidence gate on the
    strength of a measurement artefact.
    """
    candidates = [item for item in ground_truth.split("\n") if item.strip()]
    if not candidates:
        candidates = [ground_truth]
    return min(character_error_rate(candidate, line_text) for candidate in candidates)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument(
        "--engines",
        # Defaults to every arm that runs locally and makes no provider call.
        # The previous default named rapidocr_ppocrv5/v6, which
        # build_engine_adapters does not provide, so the CLI exited on its own
        # defaults with "Unknown engine arms".
        default="rapidocr,tesseract,unlimited_ocr,got_ocr2_formula",
        help="Comma-separated arms. qwen38_vision makes real provider calls.",
    )
    parser.add_argument("--i-authorize-provider-calls", action="store_true")
    parser.add_argument("--max-provider-calls", type=int, default=6)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    budget = ProviderCallBudget(
        authorized=args.i_authorize_provider_calls,
        maximum=args.max_provider_calls,
    )
    available = build_engine_adapters(budget)
    requested = [name.strip() for name in str(args.engines).split(",") if name.strip()]
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise SystemExit(f"Unknown engine arms: {', '.join(unknown)}")

    fixtures = load_fixtures(args.fixtures)
    report = run_bakeoff(
        fixtures=fixtures,
        engines={name: available[name] for name in requested},
    )
    report["provider_calls_used"] = budget.used
    rendered = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
