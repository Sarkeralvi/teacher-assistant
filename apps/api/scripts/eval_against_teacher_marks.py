"""Measure Claude's draft grades against a teacher's own marks (v2 Phase 1 smoke eval).

Runs the REAL Bulk Supervised pipeline in-process with the real Claude provider:

    ZIP intake -> page read (Claude) -> whole-transcript assignment (Claude)
    -> transcript review (confirmed here, labelled eval-only) -> draft grading (Claude)

against a disposable ``*_test`` PostgreSQL database, then compares every draft grade
with the teacher's mark for the same student and question part.

Two steps:

1. ``extract`` drafts the exam blueprint (questions, marks, model answers, rubric
   criteria) from the Question, Solution and Rubric PDFs and writes
   ``blueprint.draft.json``. The teacher checks it, corrects it, and saves it as
   ``blueprint.confirmed.json``. The number of corrections is the blueprint accuracy.
2. ``run`` loads the confirmed blueprint, runs the scripts ZIP through the pipeline
   and writes the comparison.

Safety:

* Paid calls happen only after a printed cost estimate and ``--yes``.
* The Anthropic key is taken from ``ANTHROPIC_EVAL_API_KEY`` (the dev-evals workspace),
  never the app key. ``--env-file`` loads only the ``ANTHROPIC_*`` names listed below
  and never prints a value.
* The database must be a disposable ``*_test`` database: ``--scratch-postgres`` (the
  default) creates and destroys one with the bundled PostgreSQL runtime.
* All outputs go to ``--out``, which must be outside the repository. Nothing prints
  student text: the console shows only counts, marks and costs.
* Transcript review is confirmed in code. That is labelled eval-only in the outputs and
  mirrors the v2 combined-review decision; it is not a teacher confirmation.
* No final grade is ever created; the run asserts that.

Example (run from apps/api; PowerShell). The first run only prints the estimate; add
``--yes`` (and optionally ``--max-cost-usd``) to approve and send:

    ..\\..\\.venv\\Scripts\\python.exe scripts\\eval_against_teacher_marks.py extract `
        --exam-dir "E:\\Question, solution, rubric and scripts" `
        --out "E:\\Question, solution, rubric and scripts\\eval-runs\\blueprint" `
        --env-file <path to your local environment file>
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
PG_BIN = REPO_ROOT / ".local-ai" / "runtime" / "postgresql-17.10" / "bin"
EVAL_DATABASE_NAME = "ta_eval_test"
PROFILE = "anthropic"

# Only these names are ever read from --env-file. Values are never printed.
ENV_FILE_KEYS = (
    "ANTHROPIC_EVAL_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_TASK_EFFORT",
    "ANTHROPIC_MAX_OUTPUT_TOKENS",
    "ANTHROPIC_TIMEOUT_SECONDS",
)

# Rough output-token assumptions for the pre-run estimate only. Real usage is measured.
EST_PAGE_READ_OUTPUT = 3500
EST_ASSIGNMENT_OUTPUT = 2500
EST_GRADE_OUTPUT = 3500
EST_GRADE_INPUT = 3500
EST_BLUEPRINT_OUTPUT = 9000
EST_TEXT_PROMPT_TOKENS = 1600
IMAGE_TOKEN_PATCH_PX = 28  # ~one token per 28x28 px patch (Claude vision)
MAX_IMAGE_LONG_EDGE_PX = 2576
MAX_IMAGE_PIXELS = 3_750_000

# Kept in sync with packages/brain/grade_contract.py and anthropic_provider.py (a test pins it).
CHANGE_FLAGS = {
    "unsupported_criterion_evidence_removed",
    "dependent_criterion_credit_removed",
    "not_met_criterion_credit_removed",
    "question_maximum_changed_by_model",
    "rubric_criteria_changed_by_model",
}
MODEL_SCORE_PREFIX = "model_score_before_checks:"
TOLERANCE = Decimal("0.005")
BIG_MISS = Decimal("1.0")


class EvalError(RuntimeError):
    """A precondition failed; nothing paid was attempted after it."""


# ---------------------------------------------------------------------------
# Environment and safety guards
# ---------------------------------------------------------------------------


def _load_env_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.is_file():
        raise EvalError(f"--env-file does not exist: {path}")
    loaded: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in ENV_FILE_KEYS:
            os.environ[key] = value.strip().strip('"').strip("'")
            loaded.append(key)
    return loaded


def _configure_claude_environment() -> str:
    eval_key = os.environ.get("ANTHROPIC_EVAL_API_KEY", "").strip()
    if not eval_key:
        raise EvalError(
            "ANTHROPIC_EVAL_API_KEY is not set. Evals use the dev-evals workspace key, never "
            "the app key. Put it in your local environment file and pass --env-file."
        )
    os.environ["ANTHROPIC_API_KEY"] = eval_key
    os.environ["ANTHROPIC_ENABLED"] = "true"
    os.environ["BRAIN_ALLOW_REAL_PROVIDERS"] = "true"
    os.environ["BRAIN_PROVIDER"] = PROFILE
    # The SDK must not read any other credential source by accident.
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
    return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")


def _require_outside_repo(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise EvalError(f"--out must be outside the repository: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _confirm_spend(
    low_usd: Decimal, high_usd: Decimal, *, approved: bool, cap_usd: Decimal | None = None
) -> Decimal:
    """Print the estimate range and return the hard spending cap for this run."""

    cap = cap_usd if cap_usd is not None else Decimal(math.ceil(high_usd * 2 + 1))
    print(
        f"Estimated cost: ${low_usd:.2f} to ${high_usd:.2f} (thinking tokens make output "
        f"uncertain; the real cost is measured). Hard cap for this run: ${cap:.2f}."
    )
    if not approved:
        raise EvalError(
            "Nothing was sent. Re-run with --yes to approve (and --max-cost-usd to change the cap)."
        )
    return cap


class SpendTracker:
    """Adds up real call costs and refuses the next call once the cap is reached."""

    def __init__(self, cap_usd: Decimal) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = Decimal("0")
        self.calls: list[dict[str, Any]] = []

    def observe(self, record: dict[str, Any]) -> None:
        self.calls.append(record)
        self.spent_usd += Decimal(str(record.get("cost_usd", "0")))

    def guard(self, task: str) -> None:
        if self.spent_usd >= self.cap_usd:
            from packages.brain.anthropic_provider import SpendLimitReached

            raise SpendLimitReached(
                f"Eval spending cap ${self.cap_usd:.2f} reached (spent ${self.spent_usd:.4f}); "
                f"the {task} call was not sent"
            )


def _require_disposable_url(database_url: str) -> str:
    name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not name.endswith("_test"):
        raise EvalError(f"--database-url must name a disposable *_test database, not {name!r}")
    return database_url


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def scratch_postgres(*, keep: bool = False) -> Iterator[str]:
    """Create, start, and finally stop and delete a throwaway PostgreSQL cluster.

    The cluster holds student identifiers, transcripts and draft grades, so its
    files are removed afterwards (also after a failure) unless ``keep`` is set.
    """

    for tool in ("initdb.exe", "pg_ctl.exe", "createdb.exe"):
        if not (PG_BIN / tool).is_file():
            raise EvalError(f"Bundled PostgreSQL tool is missing: {PG_BIN / tool}")
    workdir = Path(tempfile.mkdtemp(prefix="ta-eval-pg-"))
    data_dir = workdir / "pgdata"
    log_file = workdir / "postgres.log"
    port = _free_port()
    quiet: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }
    started = False
    try:
        subprocess.run(
            [str(PG_BIN / "initdb.exe"), "-D", str(data_dir), "-U", "postgres", "-A", "trust",
             "-E", "UTF8", "--no-locale"],
            check=True, timeout=180, **quiet,
        )
        subprocess.run(
            [str(PG_BIN / "pg_ctl.exe"), "-D", str(data_dir), "-o",
             f"-p {port} -c listen_addresses=127.0.0.1", "-l", str(log_file), "-w", "-t", "60",
             "start"],
            check=True, timeout=120, **quiet,
        )
        started = True
        subprocess.run(
            [str(PG_BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres",
             EVAL_DATABASE_NAME],
            check=True, timeout=60, **quiet,
        )
        yield f"postgresql+psycopg://postgres@127.0.0.1:{port}/{EVAL_DATABASE_NAME}"
    finally:
        if started:
            subprocess.run(
                [str(PG_BIN / "pg_ctl.exe"), "-D", str(data_dir), "-m", "fast", "stop"],
                check=False, timeout=120, **quiet,
            )
        if keep:
            print(f"Scratch database kept at {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def _prepare_imports(out_dir: Path) -> None:
    # No local environment file may be picked up implicitly: run from the output folder.
    os.chdir(out_dir)
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExamFiles:
    question: Path
    solution: Path
    rubric: Path
    scripts_zip: Path


def _find_exam_files(exam_dir: Path) -> ExamFiles:
    if not exam_dir.is_dir():
        raise EvalError(f"--exam-dir does not exist: {exam_dir}")
    by_name = {path.name.casefold(): path for path in exam_dir.iterdir() if path.is_file()}

    def pick(*names: str) -> Path:
        for name in names:
            if name.casefold() in by_name:
                return by_name[name.casefold()]
        raise EvalError(f"{exam_dir} needs one of: {', '.join(names)}")

    zips = sorted(path for path in exam_dir.glob("*.zip") if path.is_file())
    if len(zips) != 1:
        raise EvalError(f"{exam_dir} must contain exactly one scripts ZIP (found {len(zips)})")
    return ExamFiles(
        question=pick("Question.pdf", "Questions.pdf", "question_paper.pdf"),
        solution=pick("Solution.pdf", "Solutions.pdf", "model_answer.pdf"),
        rubric=pick("rubric.pdf", "Rubric.pdf", "marking_scheme.pdf"),
        scripts_zip=zips[0],
    )


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise EvalError(f"{field} is not a number: {value!r}") from exc


def normalize_label(label: str) -> str:
    """Compare part labels loosely: 'Q1(a)', '1 (a)', '1.a' and '1a' are the same part."""

    text = str(label).strip().casefold()
    text = re.sub(r"^(?:question|q)\s*", "", text)
    return re.sub(r"[\s().\[\]_-]", "", text)


def load_blueprint(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvalError(f"--blueprint does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise EvalError("The blueprint has no questions")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(questions, start=1):
        number = str(item.get("question_number") or "").strip()
        if not number:
            raise EvalError(f"Blueprint question {index} has no question_number")
        if normalize_label(number) in seen:
            raise EvalError(f"Blueprint question number {number} appears twice")
        seen.add(normalize_label(number))
        model_answer = str(item.get("model_answer") or "").strip()
        if not model_answer:
            raise EvalError(f"Blueprint question {number} has no model_answer")
        marks = _decimal(item.get("marks"), field=f"{number} marks")
        criteria = item.get("criteria") or []
        if not criteria:
            raise EvalError(f"Blueprint question {number} has no rubric criteria")
        rows = []
        for position, criterion in enumerate(criteria, start=1):
            label = str(criterion.get("criterion_label") or "").strip()
            if not label:
                raise EvalError(f"{number} criterion {position} has no criterion_label")
            rows.append(
                {
                    "criterion_label": label,
                    "description": str(criterion.get("description") or label).strip(),
                    "max_marks": _decimal(
                        criterion.get("max_marks"), field=f"{number} criterion {position}"
                    ),
                }
            )
        total = sum((row["max_marks"] for row in rows), Decimal("0"))
        if total != marks:
            raise EvalError(f"{number}: criterion marks sum to {total}, not {marks}")
        cleaned.append(
            {
                "question_number": number,
                "question_text": str(item.get("question_text") or number).strip(),
                "model_answer": model_answer,
                "marks": marks,
                "criteria": rows,
            }
        )
    return cleaned


def load_marks(
    path: Path, label_map: dict[str, str], blueprint_labels: list[str]
) -> dict[tuple[str, str], Decimal]:
    """Map (student key, normalized blueprint label) -> teacher mark."""

    if not path.is_file():
        raise EvalError(f"--marks does not exist: {path}")
    canonical = {normalize_label(label): label for label in blueprint_labels}
    mapped = {normalize_label(key): value for key, value in label_map.items()}
    marks: dict[tuple[str, str], Decimal] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"script_file", "student_id", "part_label", "mark"}
        if not required <= set(reader.fieldnames or []):
            raise EvalError(f"--marks needs columns {sorted(required)}")
        for line_no, row in enumerate(reader, start=2):
            teacher_label = normalize_label(row["part_label"])
            target = normalize_label(mapped.get(teacher_label, teacher_label))
            if target not in canonical:
                raise EvalError(
                    f"marks line {line_no}: part {row['part_label']!r} matches no blueprint "
                    "question; add it to --label-map"
                )
            mark = _decimal(row["mark"], field=f"marks line {line_no}")
            for student_key in _student_keys(row["student_id"], row["script_file"]):
                marks[(student_key, target)] = mark
    if not marks:
        raise EvalError("--marks has no rows")
    return marks


def _student_keys(*values: str) -> set[str]:
    keys: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text:
            keys.add(text.casefold())
            keys.add(Path(text).stem.casefold())
    return keys


def _zip_page_count(path: Path) -> tuple[int, int]:
    import fitz

    pages = 0
    scripts = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.casefold()
            if name.endswith(".pdf"):
                scripts += 1
                with fitz.open(stream=archive.read(info), filetype="pdf") as document:
                    pages += document.page_count
            elif name.endswith((".png", ".jpg", ".jpeg")):
                pages += 1
    return scripts, pages


def _page_image_tokens(width_pt: float, height_pt: float, dpi: int) -> int:
    width = width_pt * dpi / 72.0
    height = height_pt * dpi / 72.0
    scale = min(1.0, MAX_IMAGE_LONG_EDGE_PX / max(width, height),
                (MAX_IMAGE_PIXELS / (width * height)) ** 0.5)
    width, height = width * scale, height * scale
    return int((width / IMAGE_TOKEN_PATCH_PX) * (height / IMAGE_TOKEN_PATCH_PX))


def _price(input_tokens: int, output_tokens: int) -> Decimal:
    rate_in = Decimal(os.environ.get("ANTHROPIC_INPUT_USD_PER_MTOK", "4.00"))
    rate_out = Decimal(os.environ.get("ANTHROPIC_OUTPUT_USD_PER_MTOK", "20.00"))
    return (Decimal(input_tokens) * rate_in + Decimal(output_tokens) * rate_out) / Decimal(
        1_000_000
    )


# ---------------------------------------------------------------------------
# Step 1: blueprint draft
# ---------------------------------------------------------------------------


def _absolute(value: str | None) -> Path | None:
    # Resolve before _prepare_imports changes the working directory.
    return Path(value).expanduser().resolve() if value else None


def _cap_arg(args: argparse.Namespace) -> Decimal | None:
    return _decimal(args.max_cost_usd, field="--max-cost-usd") if args.max_cost_usd else None


def cmd_extract(args: argparse.Namespace) -> int:
    exam = _find_exam_files(_absolute(args.exam_dir) or Path())
    out_dir = _require_outside_repo(Path(args.out))
    loaded = _load_env_file(_absolute(args.env_file))
    model = _configure_claude_environment()
    print(f"Loaded from env file: {', '.join(loaded) or '(nothing)'}; model {model}")

    import fitz

    reference_pages = 0
    image_tokens = 0
    for pdf in (exam.question, exam.solution, exam.rubric):
        with fitz.open(pdf) as document:
            for page in document:
                reference_pages += 1
                image_tokens += _page_image_tokens(page.rect.width, page.rect.height, 300)
    input_tokens = image_tokens + EST_TEXT_PROMPT_TOKENS
    cap = _confirm_spend(
        _price(input_tokens, EST_BLUEPRINT_OUTPUT),
        _price(input_tokens, EST_BLUEPRINT_OUTPUT * 3),
        approved=args.yes,
        cap_usd=_cap_arg(args),
    )

    _prepare_imports(out_dir)
    from app.core.config import get_settings
    from app.services.local_reference_extraction import LocalReferenceExtractor
    from packages.brain.adapter import BrainAdapter
    from packages.brain.anthropic_provider import register_call_observer, register_spend_guard

    get_settings.cache_clear()
    settings = get_settings()
    extractor = LocalReferenceExtractor(settings=settings)
    documents: dict[str, list[tuple[bytes, str, int]]] = {}
    for name, pdf in (("QUESTION", exam.question), ("SOLUTION", exam.solution),
                      ("RUBRIC", exam.rubric)):
        rendered = extractor.render_pages(
            pdf, "application/pdf", target_dpi=settings.local_ocr_render_dpi
        )
        documents[name] = [(image, mime, page_no) for page_no, image, mime in rendered]
    adapter = BrainAdapter.for_profile(settings, PROFILE)
    tracker = SpendTracker(cap)
    unregister_observer = register_call_observer(tracker.observe)
    unregister_guard = register_spend_guard(tracker.guard)
    started = time.perf_counter()
    try:
        bundle = adapter.extract_reference_bundle_from_images(documents=documents)
    finally:
        unregister_guard()
        unregister_observer()
    calls = tracker.calls
    draft = {
        "questions": bundle.get("questions", []),
        "warnings": bundle.get("warnings", []),
        "_eval": {
            "step": "extract",
            "created_at": datetime.now(UTC).isoformat(),
            "model": settings.anthropic_model,
            "reference_pages": reference_pages,
            "seconds": round(time.perf_counter() - started, 1),
            "calls": calls,
            "note": (
                "Draft only. Check every question, mark, model answer and criterion "
                "against the PDFs, correct this file, and save it as "
                "blueprint.confirmed.json."
            ),
        },
    }
    target = out_dir / "blueprint.draft.json"
    target.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    cost = sum((Decimal(call["cost_usd"]) for call in calls), Decimal("0"))
    print(f"Blueprint draft: {target}")
    print(f"Questions: {len(draft['questions'])}; Claude calls: {len(calls)}; "
          f"cost ${cost:.4f}; {draft['_eval']['seconds']} s")
    for item in draft["questions"]:
        criteria = item.get("criteria") or []
        print(f"  {item.get('question_number')}: marks={item.get('marks')} "
              f"criteria={len(criteria)} blockers={len(item.get('blockers') or [])}")
    return 0


# ---------------------------------------------------------------------------
# Step 2: run and compare
# ---------------------------------------------------------------------------


def _blueprint_corrections(draft_path: Path | None, confirmed: list[dict[str, Any]]) -> dict:
    if draft_path is None or not draft_path.is_file():
        return {"available": False}
    draft = json.loads(draft_path.read_text(encoding="utf-8")).get("questions") or []
    draft_by = {normalize_label(item.get("question_number", "")): item for item in draft}
    confirmed_by = {normalize_label(item["question_number"]): item for item in confirmed}
    changed_marks = 0
    changed_criteria = 0
    for key, item in confirmed_by.items():
        source = draft_by.get(key)
        if source is None:
            continue
        try:
            if Decimal(str(source.get("marks"))) != item["marks"]:
                changed_marks += 1
        except (InvalidOperation, ValueError):
            changed_marks += 1
        draft_criteria = [
            (str(row.get("criterion_label", "")).strip(), str(row.get("max_marks")))
            for row in (source.get("criteria") or [])
        ]
        confirmed_criteria = [
            (row["criterion_label"], str(row["max_marks"])) for row in item["criteria"]
        ]
        if draft_criteria != confirmed_criteria:
            changed_criteria += 1
    return {
        "available": True,
        "draft_questions": len(draft_by),
        "confirmed_questions": len(confirmed_by),
        "questions_added": len(set(confirmed_by) - set(draft_by)),
        "questions_removed": len(set(draft_by) - set(confirmed_by)),
        "questions_with_changed_marks": changed_marks,
        "questions_with_changed_criteria": changed_criteria,
    }


def _seed_from_blueprint(db: Any, blueprint: list[dict[str, Any]]) -> Any:
    from uuid import uuid4

    from app.models import (
        Assessment,
        Course,
        ExtractionRun,
        GradingRun,
        Question,
        QuestionNode,
        Rubric,
        User,
    )
    from tests.bulk150_harness import Seeded

    teacher = User(
        name="Eval Teacher",
        email=f"eval-{uuid4().hex}@example.invalid",
        password_hash="eval-only",
        role="teacher",
    )
    db.add(teacher)
    db.flush()
    course = Course(teacher_id=teacher.id, code=f"EVAL{uuid4().hex[:6]}", title="Eval")
    db.add(course)
    db.flush()
    assessment = Assessment(
        course_id=course.id,
        title="Claude smoke eval",
        assessment_type="eval",
        total_marks=sum((item["marks"] for item in blueprint), Decimal("0")),
        status="ready",
    )
    db.add(assessment)
    db.flush()
    now = datetime.now(UTC)
    grading_run = GradingRun(
        assessment_id=assessment.id,
        created_by_teacher_id=teacher.id,
        mode="bulk_supervised",
        status="grading_ready",
        marking_policy="general",
        questions_confirmed_at=now,
        rubrics_confirmed_at=now,
    )
    extraction = ExtractionRun(
        assessment_id=assessment.id,
        artifact_file_path="artifacts/eval-blueprint.json",
        original_filename="blueprint.confirmed.json",
        content_type="application/json",
        extraction_type="question_paper",
        provider=PROFILE,
        status="succeeded",
        blockers=[],
    )
    db.add_all([grading_run, extraction])
    db.flush()
    questions: dict[str, Any] = {}
    nodes: dict[str, Any] = {}
    for item in blueprint:
        label = item["question_number"]
        question = Question(
            assessment_id=assessment.id,
            question_no=label,
            question_text=item["question_text"],
            model_answer=item["model_answer"],
            total_marks=item["marks"],
        )
        db.add(question)
        db.flush()
        # Same rubric shape as ReferenceExtractionService.confirm.
        db.add(
            Rubric(
                question_id=question.id,
                version=1,
                rubric_json={
                    "total_marks": str(item["marks"]),
                    "criteria": [
                        {
                            "id": f"criterion-{index}",
                            "name": row["criterion_label"],
                            "description": row["description"],
                            "max_marks": str(row["max_marks"]),
                        }
                        for index, row in enumerate(item["criteria"], start=1)
                    ],
                },
                is_active=True,
            )
        )
        node = QuestionNode(
            assessment_id=assessment.id,
            extraction_run_id=extraction.id,
            question_number=label,
            label=label,
            text=item["question_text"],
            node_type="question",
            teacher_confirmed=True,
        )
        db.add(node)
        questions[label] = question
        nodes[label] = node
    db.commit()
    return Seeded(
        teacher=teacher,
        course=course,
        assessment=assessment,
        grading_run=grading_run,
        labels=tuple(questions),
        questions=questions,
        nodes=nodes,
    )


@dataclass(frozen=True)
class RunPlan:
    exam: ExamFiles
    out_dir: Path
    blueprint: list[dict[str, Any]]
    teacher_marks: dict[tuple[str, str], Decimal]
    scripts: int
    pages: int
    items: int
    cap_usd: Decimal
    blueprint_draft: Path | None


def _estimate_run(scripts: int, pages: int, items: int, render_dpi: int) -> tuple[Decimal, Decimal]:
    page_tokens = _page_image_tokens(595, 842, render_dpi)
    read_in = pages * (page_tokens + EST_TEXT_PROMPT_TOKENS)
    assign_in = pages * 800 + scripts * EST_TEXT_PROMPT_TOKENS
    grade_in = items * EST_GRADE_INPUT
    output = (
        pages * EST_PAGE_READ_OUTPUT
        + scripts * EST_ASSIGNMENT_OUTPUT
        + items * EST_GRADE_OUTPUT
    )
    total_in = read_in + assign_in + grade_in
    return _price(total_in, output), _price(total_in, output * 3)


def cmd_run(args: argparse.Namespace) -> int:
    exam = _find_exam_files(_absolute(args.exam_dir) or Path())
    out_dir = _require_outside_repo(Path(args.out))
    blueprint = load_blueprint(_absolute(args.blueprint) or Path())
    label_map_path = _absolute(args.label_map)
    label_map = json.loads(label_map_path.read_text(encoding="utf-8")) if label_map_path else {}
    teacher_marks = load_marks(
        _absolute(args.marks) or Path(), label_map, [item["question_number"] for item in blueprint]
    )
    if args.database_url:
        _require_disposable_url(args.database_url)
    loaded = _load_env_file(_absolute(args.env_file))
    model = _configure_claude_environment()
    os.environ["SCRIPT_PAGE_RENDER_DPI"] = str(args.render_dpi)
    print(f"Loaded from env file: {', '.join(loaded) or '(nothing)'}; model {model}; "
          f"render {args.render_dpi} DPI")

    scripts, pages = _zip_page_count(exam.scripts_zip)
    items = scripts * len(blueprint)
    print(f"Scripts: {scripts}; pages: {pages}; question parts: {len(blueprint)}; "
          f"draft grades: {items}")
    low, high = _estimate_run(scripts, pages, items, args.render_dpi)
    cap = _confirm_spend(low, high, approved=args.yes, cap_usd=_cap_arg(args))
    plan = RunPlan(
        exam=exam,
        out_dir=out_dir,
        blueprint=blueprint,
        teacher_marks=teacher_marks,
        scripts=scripts,
        pages=pages,
        items=items,
        cap_usd=cap,
        blueprint_draft=_absolute(args.blueprint_draft),
    )
    database_context = (
        contextlib.nullcontext(args.database_url)
        if args.database_url
        else scratch_postgres(keep=args.keep_db)
    )
    with database_context as database_url:
        os.environ["DATABASE_URL"] = database_url
        _prepare_imports(out_dir)
        return _run_pipeline(args, plan)


def _run_pipeline(args: argparse.Namespace, plan: RunPlan) -> int:
    exam, out_dir, blueprint = plan.exam, plan.out_dir, plan.blueprint
    teacher_marks = plan.teacher_marks
    from alembic.config import Config
    from fastapi import UploadFile
    from sqlalchemy import delete, select

    from alembic import command
    from app.db.session import SessionLocal, engine
    from app.models import BulkEvaluationItem, GradeSuggestion, Question, Submission
    from app.services.bulk_evaluation_service import BulkEvaluationService
    from packages.brain.anthropic_provider import register_call_observer, register_spend_guard
    from tests.bulk150_harness import (
        CLEANUP_MODELS,
        assert_disposable_database,
        assert_no_final_grades,
        bulk_environment,
        drain,
        harness_storage,
        resume_all_items,
        review_all_transcripts,
    )

    assert_disposable_database(engine.url.database)
    command.upgrade(Config(str(API_ROOT / "alembic.ini")), "head")
    tracker = SpendTracker(plan.cap_usd)
    calls = tracker.calls
    started = time.perf_counter()
    with bulk_environment(out_dir / "storage") as settings:
        db = SessionLocal()
        try:
            for model_class in CLEANUP_MODELS:
                db.execute(delete(model_class))
            db.commit()
            seeded = _seed_from_blueprint(db, blueprint)
            service = BulkEvaluationService(db, settings=settings,
                                            storage=harness_storage(settings))
            unregister_observer = register_call_observer(tracker.observe)
            unregister_guard = register_spend_guard(tracker.guard)
            try:
                upload = UploadFile(
                    filename=exam.scripts_zip.name,
                    file=BytesIO(exam.scripts_zip.read_bytes()),
                )
                # One read per page, up to two assignment calls per script and one grade
                # per item, doubled for resumed work. The dollar cap is the real limit.
                call_budget = 2 * (plan.pages + 2 * plan.scripts + plan.items) + 10
                run = service.create_from_zip(
                    assessment_id=seeded.assessment.id,
                    grading_run=seeded.grading_run,
                    teacher=seeded.teacher,
                    upload=upload,
                    expected_model=settings.anthropic_model,
                    marking_policy="general",
                    maximum_provider_calls=min(settings.bulk_max_provider_calls, call_budget),
                    provider=PROFILE,
                )
                read_result = drain(run.id, settings=settings)
                # EVAL-ONLY: confirms each transcript in code (pages classified by the
                # model's blank flag, ownership accepted as assigned). Mirrors the v2
                # combined-review decision; it is not a teacher confirmation.
                review = review_all_transcripts(db, run.id, seeded.teacher)
                resumed = resume_all_items(run.id, seeded.teacher, settings=settings)
                grade_result = drain(run.id, settings=settings)
            finally:
                unregister_guard()
                unregister_observer()
            db.expire_all()
            assert_no_final_grades(db, run.id)
            rows = []
            for item in db.scalars(
                select(BulkEvaluationItem).where(BulkEvaluationItem.run_id == run.id)
            ).all():
                submission = db.get(Submission, item.submission_id)
                question = db.get(Question, item.question_id)
                suggestion = (
                    db.get(GradeSuggestion, item.grade_suggestion_id)
                    if item.grade_suggestion_id
                    else None
                )
                rows.append((submission, question, item, suggestion))
        finally:
            db.close()

    report = _compare(
        rows, teacher_marks, settings_threshold=settings.bulk_grading_clean_min_confidence
    )
    elapsed = round(time.perf_counter() - started, 1)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "model": settings.anthropic_model,
        "render_dpi": args.render_dpi,
        "eval_only_transcript_confirmation": True,
        "seconds": elapsed,
        "pipeline": {
            "read_stage": {"status": read_result.status, "units": read_result.units},
            "transcripts_confirmed": len(review.confirmed),
            "transcripts_refused": len(review.refused),
            "items_resumed": len(resumed.resumed),
            "grading_stage": {"status": grade_result.status, "units": grade_result.units,
                              "calls_used": grade_result.calls_used},
        },
        "agreement": report["aggregate"],
        "blueprint_corrections": _blueprint_corrections(plan.blueprint_draft, blueprint),
        "spending": {
            "cap_usd": str(plan.cap_usd),
            "spent_usd": str(tracker.spent_usd),
            "cap_reached": tracker.spent_usd >= plan.cap_usd,
        },
        "calls": _call_stats(calls),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                          encoding="utf-8")
    with (out_dir / "per_part.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["rows"][0]) if report["rows"]
                                else ["student", "part"])
        writer.writeheader()
        writer.writerows(report["rows"])
    with (out_dir / "calls.jsonl").open("w", encoding="utf-8") as handle:
        for call in calls:
            handle.write(json.dumps(call) + "\n")
    _print_summary(summary, out_dir)
    return 0


def _compare(
    rows: list[tuple[Any, Any, Any, Any]],
    teacher_marks: dict[tuple[str, str], Decimal],
    *,
    settings_threshold: Decimal,
) -> dict[str, Any]:
    detail: list[dict[str, Any]] = []
    deltas: list[Decimal] = []
    over: list[Decimal] = []
    under: list[Decimal] = []
    unscored = 0
    missing_teacher = 0
    big_misses = 0
    big_misses_flagged = 0
    contract_flag_counts: dict[str, int] = {flag: 0 for flag in sorted(CHANGE_FLAGS)}
    parts_with_credit_removed = 0
    marks_removed = Decimal("0")
    for submission, question, item, suggestion in rows:
        keys = _student_keys(submission.student_identifier or "",
                             getattr(submission, "original_filename", "") or "")
        part = normalize_label(question.question_no)
        teacher = next((teacher_marks[(key, part)] for key in keys
                        if (key, part) in teacher_marks), None)
        if teacher is None:
            missing_teacher += 1
        ai = suggestion.score if suggestion is not None else None
        flags = list((suggestion.raw_response_json or {}).get("review_flags") or []) \
            if suggestion is not None else []
        confidence = suggestion.confidence if suggestion is not None else None
        flagged = (
            suggestion is None
            or item.status != "graded"
            or (confidence is not None and confidence < settings_threshold)
            or bool(CHANGE_FLAGS & set(flags))
            or any(flag.startswith("served_by_fallback_model:") for flag in flags)
        )
        for flag in CHANGE_FLAGS & set(flags):
            contract_flag_counts[flag] += 1
        before = next(
            (
                flag[len(MODEL_SCORE_PREFIX):]
                for flag in flags
                if flag.startswith(MODEL_SCORE_PREFIX)
            ),
            None,
        )
        if before is not None and ai is not None:
            parts_with_credit_removed += 1
            marks_removed += max(Decimal(before) - Decimal(ai), Decimal("0"))
        delta = None
        if ai is None:
            unscored += 1
        elif teacher is not None:
            delta = Decimal(ai) - teacher
            deltas.append(delta)
            if delta > TOLERANCE:
                over.append(delta)
            elif delta < -TOLERANCE:
                under.append(-delta)
            if abs(delta) >= BIG_MISS:
                big_misses += 1
                big_misses_flagged += int(flagged)
        detail.append(
            {
                "student": submission.student_identifier,
                "part": question.question_no,
                "teacher_mark": str(teacher) if teacher is not None else "",
                "ai_mark": str(ai) if ai is not None else "",
                "model_score_before_checks": before or "",
                "max_marks": str(question.total_marks),
                "delta": str(delta) if delta is not None else "",
                "ai_confidence": str(confidence) if confidence is not None else "",
                "item_status": item.status,
                "exception_codes": ";".join(item.exception_codes or []),
                "flagged_for_review": flagged,
                "review_flags": ";".join(flags),
            }
        )
    compared = len(deltas)
    aggregate = {
        "parts_total": len(rows),
        "parts_compared": compared,
        "parts_unscored_by_ai": unscored,
        "parts_without_teacher_mark": missing_teacher,
        "exact_matches": sum(1 for delta in deltas if abs(delta) <= TOLERANCE),
        "within_half_mark": sum(1 for delta in deltas if abs(delta) <= Decimal("0.5")),
        "mean_absolute_error": str(
            (sum((abs(delta) for delta in deltas), Decimal("0")) / compared).quantize(
                Decimal("0.01")
            )
        ) if compared else None,
        "over_scored_parts": len(over),
        "over_score_total_marks": str(sum(over, Decimal("0"))),
        "largest_over_score": str(max(over)) if over else "0",
        "under_scored_parts": len(under),
        "under_score_total_marks": str(sum(under, Decimal("0"))),
        "misses_of_one_mark_or_more": big_misses,
        "those_misses_flagged_for_review": big_misses_flagged,
        # The checks below run after Claude: marks they remove are not Claude's grading.
        "grade_contract": {
            "parts_with_credit_removed": parts_with_credit_removed,
            "marks_removed": str(marks_removed),
            "flag_counts": contract_flag_counts,
        },
    }
    return {"aggregate": aggregate, "rows": detail}


def _call_stats(calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, Any]] = {}
    for call in calls:
        bucket = by_task.setdefault(
            call["task"],
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": Decimal("0"),
             "latency_ms_total": 0, "latency_ms_max": 0, "served_models": set()},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += int(call["input_tokens"]) + int(
            call["cache_creation_input_tokens"]
        ) + int(call["cache_read_input_tokens"])
        bucket["output_tokens"] += int(call["output_tokens"])
        bucket["cost_usd"] += Decimal(call["cost_usd"])
        bucket["latency_ms_total"] += int(call["latency_ms"])
        bucket["latency_ms_max"] = max(bucket["latency_ms_max"], int(call["latency_ms"]))
        bucket["served_models"].add(call["model_served"])
    total = Decimal("0")
    result: dict[str, Any] = {}
    for task, bucket in by_task.items():
        total += bucket["cost_usd"]
        result[task] = {
            "calls": bucket["calls"],
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "cost_usd": str(bucket["cost_usd"]),
            "avg_latency_s": round(bucket["latency_ms_total"] / bucket["calls"] / 1000, 1),
            "max_latency_s": round(bucket["latency_ms_max"] / 1000, 1),
            "served_models": sorted(bucket["served_models"]),
        }
    return {"by_task": result, "total_calls": len(calls), "total_cost_usd": str(total)}


def _print_summary(summary: dict[str, Any], out_dir: Path) -> None:
    agreement = summary["agreement"]
    calls = summary["calls"]
    print("")
    print(f"Pipeline: read={summary['pipeline']['read_stage']['status']} "
          f"grading={summary['pipeline']['grading_stage']['status']} "
          f"({summary['seconds']} s)")
    print(f"Parts compared: {agreement['parts_compared']} of {agreement['parts_total']} "
          f"(unscored by AI: {agreement['parts_unscored_by_ai']})")
    print(f"Exact: {agreement['exact_matches']}  within 0.5: {agreement['within_half_mark']}  "
          f"MAE: {agreement['mean_absolute_error']}")
    print(f"Over-scored: {agreement['over_scored_parts']} parts "
          f"(+{agreement['over_score_total_marks']} marks, largest "
          f"+{agreement['largest_over_score']})  under-scored: "
          f"{agreement['under_scored_parts']} parts (-{agreement['under_score_total_marks']})")
    print(f"Misses >= 1 mark: {agreement['misses_of_one_mark_or_more']}, flagged: "
          f"{agreement['those_misses_flagged_for_review']}")
    contract = agreement["grade_contract"]
    print(f"Grade checks removed {contract['marks_removed']} marks on "
          f"{contract['parts_with_credit_removed']} parts (not Claude's own grading)")
    print(f"Claude calls: {calls['total_calls']}, cost ${Decimal(calls['total_cost_usd']):.4f}")
    for task, stats in calls["by_task"].items():
        print(f"  {task}: {stats['calls']} calls, in {stats['input_tokens']} / out "
              f"{stats['output_tokens']} tokens, ${Decimal(stats['cost_usd']):.4f}, "
              f"avg {stats['avg_latency_s']} s, served by {', '.join(stats['served_models'])}")
    print(f"Outputs: {out_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--exam-dir", required=True,
                             help="Folder with Question/Solution/rubric PDFs and one scripts ZIP")
        command.add_argument("--out", required=True, help="Output folder outside the repository")
        command.add_argument("--env-file", help="Local environment file holding ANTHROPIC_* keys")
        command.add_argument("--yes", action="store_true", help="Approve the estimated spend")
        command.add_argument(
            "--max-cost-usd",
            help="Hard spending cap; no call is sent once reached (default: 2x high estimate)",
        )

    extract = sub.add_parser("extract", help="Draft the exam blueprint with Claude")
    common(extract)
    extract.set_defaults(handler=cmd_extract)

    run = sub.add_parser("run", help="Run the scripts and compare with teacher marks")
    common(run)
    run.add_argument("--blueprint", required=True, help="Teacher-confirmed blueprint JSON")
    run.add_argument("--blueprint-draft", help="The draft JSON, to count corrections")
    run.add_argument("--marks", required=True,
                     help="CSV with script_file, student_id, part_label, mark")
    run.add_argument("--label-map", help="JSON mapping teacher part labels to blueprint labels")
    run.add_argument("--render-dpi", type=int, default=144, choices=range(72, 301),
                     metavar="72-300", help="Script page render DPI (v1 used 144)")
    run.add_argument("--database-url",
                     help="Existing disposable *_test database (default: scratch PostgreSQL)")
    run.add_argument("--keep-db", action="store_true",
                     help="Keep the scratch database files (they hold student data) for inspection")
    run.set_defaults(handler=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except EvalError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
