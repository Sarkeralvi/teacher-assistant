# Repository Overview and Project Status

Written at: 2026-08-31. Baseline commit: `9f37e80`. Branch: `rescue/paddle-qwen36-hybrid`.

This document is the single orientation page for the repository: what the product
is, how the code is arranged, what is actually built, what is proven, and what
comes next. It contains no credentials, model paths, private artifacts, or
student data.

For the binding safety contract read `AGENTS.md` and root `CLAUDE.md` first. For
the current working state read the newest `docs/CLAUDE_HANDOFF_*.md`.

---

## 1. What the product is

Teacher Assistant implements the **Answer Evidence Extraction Machine (AEEM)**: a
teacher-controlled workflow for grading handwritten mathematics scripts.

The governing principle is that AI proposes and the teacher governs. No
`FinalGrade` row can exist without an explicit teacher approval action, in any
mode, under any configuration.

The distinguishing design decision is that this is **not** an OCR-then-grade
pipeline. It is an evidence machine. Before any grading claim is permitted, the
system must separately confirm:

1. question text;
2. solution / model answer;
3. rubric and criterion marks;
4. canonical grading unit label and max marks;
5. student script page order;
6. answer-region boundaries;
7. multi-page continuation grouping;
8. evidence packet completeness.

The project rule, recorded after a real failure in which a `1(b)(i)` answer was
graded `4/6` because the crop ended at the bottom of page 3 while the answer
continued onto page 4, is: **grading quality cannot be interpreted until evidence
quality is confirmed.** An incomplete crop, a missed continuation, a wrong label,
or an ambiguous max mark invalidates a grading-quality conclusion regardless of
how plausible the mark looks.

---

## 2. Repository layout

```text
teacher-assistant/
├── AGENTS.md                  binding agent operating rules
├── CLAUDE.md                  entry instructions and non-negotiable constraints
├── ARCHITECTURE.md            component and module boundaries
├── PROJECT_CONSTITUTION.md    product principles
├── BACKLOG.md                 task ledger, newest entries first
├── TECH_STACK_DECISION.md     locked stack
├── BRAIN_ADAPTER_SPEC.md      LLM boundary contract
├── GRADING_ENGINE_SPEC.md     grading input/output contract
├── apps/
│   ├── api/                   FastAPI backend
│   │   ├── app/
│   │   │   ├── api/routes/    19 routers
│   │   │   ├── services/      23 domain services
│   │   │   ├── core/          config, auth, ownership, logging
│   │   │   ├── db/            SQLAlchemy session and base
│   │   │   ├── worker/        RQ jobs and worker entrypoint
│   │   │   ├── models.py      32 ORM classes
│   │   │   └── schemas.py     Pydantic contracts
│   │   ├── packages/
│   │   │   ├── brain/         the ONLY module allowed to call a model
│   │   │   ├── ocr/           engine-agnostic OCR types and escalation policy
│   │   │   ├── evaluation/    benchmark and bake-off harnesses
│   │   │   └── local_ocr_sidecar/  retired PaddleOCR sidecar (rollback asset)
│   │   ├── alembic/versions/  26 migrations, head 0026
│   │   ├── scripts/           bounded operator/smoke scripts
│   │   └── tests/             61 test modules
│   └── web/                   Next.js App Router frontend
│       ├── app/               14 routes
│       ├── components/        12 client components
│       ├── lib/api.ts         the only backend call surface
│       ├── tests/             static workflow guard
│       └── e2e/               Playwright specs
├── docs/                      46 documents (runbooks, protocols, policies, logs)
├── scripts/
│   ├── pilot/                 supported Windows pilot stack launcher/status/stop
│   ├── local-ai/              model preflight, download, start/stop, smoke
│   └── evaluation/            curated evaluation and bake-off launchers
└── .local-ai/  data/  tmp/    ignored runtime, storage, and scratch
```

Ignored and never committed: `.env.local-ai`, `.local-ai/`, `data/`, uploaded
PDFs and images, crops, exports, model files, evaluation artifacts, and any
student artifact.

### Where the weight sits

The largest modules are the ones carrying the evidence logic. They are listed
here because they are where correctness bugs are most likely to hide.

| Module | Size | Responsibility |
|---|---:|---|
| `apps/web/components/AssessmentDetailClient.tsx` | 166 KB | the entire teacher workflow surface |
| `apps/api/app/services/local_script_preparation.py` | 115 KB | script mapping, boundaries, continuations |
| `apps/api/packages/brain/llama_cpp_qwen38_vision_provider.py` | 94 KB | Qwen3.8 vision provider |
| `apps/api/app/api/routes/answer_regions.py` | 72 KB | answer-region and evidence endpoints |
| `apps/api/app/services/bulk_evaluation_service.py` | 70 KB | Bulk Supervised cohort orchestration |
| `apps/api/app/models.py` | 65 KB | persistence and CHECK constraints |

---

## 3. Runtime architecture

```text
Teacher browser
  → Next.js App Router frontend
  → FastAPI backend
      → domain services
      → PostgreSQL via SQLAlchemy 2.x (Alembic migrations)
      → storage adapter → local filesystem
      → Redis queue
          → RQ worker
              → document processing (PyMuPDF, Pillow, OpenCV)
              → grading engine
              → export engine (openpyxl)
              → Brain Adapter → model providers
```

The frontend must never call a model provider directly. The backend must never
embed provider-specific calls. Both rules are enforced by tests, not convention:
`tests/test_no_direct_llm_imports.py` fails the build if any module outside
`packages/brain` imports a provider, and `apps/web/tests/workflow-ui.test.mjs`
guards the frontend against direct LLM or Codex calls.

### Supported Windows pilot runtime

The repository ships its own dependencies under ignored `.local-ai/runtime/`:
PostgreSQL, Memurai (Redis-compatible), Node.js, a Python virtual environment,
and the llama.cpp Qwen3.8 server. Do not assume system `node`, Docker,
PostgreSQL, or Redis exists on `PATH`.

Six services must be healthy: PostgreSQL, Redis/RQ, backend, RQ worker,
frontend, and loopback-only Qwen3.8. Use the supported launcher only. A manually
started Uvicorn previously used a different storage root from the pilot runtime
and produced database records for reference PDFs that the worker could not find.

---

## 4. Domain model

32 ORM classes. Beyond the expected `Course`, `Assessment`, `Question`,
`QuestionNode`, `Rubric`, `Submission`, `SubmissionPage`, `User`, the
evidence-integrity records are the interesting ones:

| Record | Purpose |
|---|---|
| `AnswerRegion`, `AnswerRegionSegment` | answer geometry, including multi-page continuation segments |
| `AnswerRegionMapping` | draft region-to-grading-unit mapping awaiting confirmation |
| `AnswerRegionOcrRun` / `Band` / `Candidate` | image-grounded OCR rescue evidence |
| `ReferencePageOcrRun` | per-page reference extraction provenance |
| `ExtractionRun` | reference-bundle extraction runs |
| `LocalModelLease` | single-holder, fail-closed GPU lease |
| `BatchEvidencePrepRun` | readiness and quarantine accounting across a cohort |
| `GradingQueueRun` / `GradingQueueItem` | readiness snapshots with staleness hashes |
| `GradingDispatchRun` / `Item` | capped, sequential cohort dispatch |
| `BulkEvaluationRun` / `BulkEvaluationItem` | Bulk Supervised cohort state |
| `GradeSuggestion` | draft mark; always `needs_review = true` |
| `FinalGrade` | created only by an explicit teacher approval action |
| `AuditLog` | append-only; never contains raw student text |

---

## 5. The safety architecture

This is the part that has absorbed most of the engineering effort, and it is the
project's actual differentiator.

**Everything is off by default.** Over 100 configuration flags; every local-model
capability defaults to `false`. `COHORT_MODEL_GRADING_ENABLED=false` is a
standing requirement. Application startup and page loads never load a model.

**Fail-closed GPU lease.** The host has one model slot. Every Qwen call must hold
a durable database lease plus a process-local call guard. A missing, expired,
busy, or wrong-phase lease fails *before* inference HTTP is sent.

**No retries, no fallback, no cloud escape hatch.** A failed provider call stops
the run. This is deliberate: a silent retry or a cloud fallback would hide a real
failure and would break the loopback-only privacy guarantee.

**Separate, non-transitive gates.** Confirming region geometry does not confirm
transcript text. Confirming transcript text does not confirm that the image
contains the whole answer. Each is its own teacher action, and grading stays
blocked until all of them pass.

**Staleness hashes.** A queued item is a historical readiness snapshot, not a
grade and not permission to run a model. If validation returns `stale`,
`evidence_missing`, or `blocked_now`, execution must refuse the item and require
a rebuild or teacher correction.

**Privacy in audit and export.** Raw student text never enters audit logs or
aggregate exports. Student images are never sent to the grading call; grading
receives only server-assembled, teacher-confirmed text.

**Bounded call ceilings.** Granular cohort dispatch is capped at 25 sequential
provider calls with zero automatic retries and stop-on-first-failure.

---

## 6. Workflow modes and current gating

| Mode | Automation | State |
|---|---|---|
| **Custom Controlled** | lowest — teacher supplies question, solution, rubric; confirms every gate | implemented; supported path |
| **Bulk Supervised** | exception-first cohort surface over the same pipeline | implemented 2026-08-29/30; unverified |
| **Semi-Automated** | system drafts questions/rubrics, teacher confirms, then batch | experimental, blocked by default |
| **Fully Automated** | question PDF + ZIP end to end | unreleased, out of scope |

### Custom Controlled sequence

1. Qwen3.8 vision drafts references from the three teacher-uploaded PDFs, with
   thinking disabled.
2. Teacher compares every extracted question, mark, and rubric criterion against
   the source and confirms only accurate canonical references.
3. A fresh Qwen3.8 vision task maps complete answer regions from full pages.
4. Teacher confirms region geometry and every continuation segment.
5. A fresh thinking-disabled Qwen3.8 task classifies visible
   cancellation/replacement marks, then transcribes only the student's surviving
   final work.
6. Teacher confirms transcript fidelity and full-answer coverage separately.
7. A fresh text-only Qwen3.8 task grades the confirmed transcript, producing one
   pending draft suggestion.
8. Teacher approves, edits, or rejects. Approved-only XLSX export.

An explicit, separately authorized **one-call thinking repair** exists for step 5
when the teacher judges the cancellation interpretation unfaithful. It receives
the answer images and the rejected transcript but deliberately receives no
question, solution, rubric, marks, or grading context, so it cannot rationalize a
reading from what the answer "should" be. Ambiguous overwrites remain
`[unclear correction]`; mathematical context is explicitly forbidden from
repairing them.

### Bulk Supervised sequence

ZIP intake of one root PDF per student or one top-level folder of naturally
ordered images per student, with an optional `manifest.csv`. Mapping,
transcription, verification, and draft grading run as durable one-call RQ jobs;
the browser may be closed. The teacher works an exception inbox, inspects only
ambiguous, incomplete, unreadable, or interrupted items, then approves the exact
clean-draft snapshot. A student with any unresolved item exports as `INCOMPLETE`
rather than receiving a misleading total.

Limits: 50 submissions, 500 pages, 1 GiB archive, 1,000 entries. Root images,
nested student folders, mixed PDF/image folders, duplicate identifiers,
encrypted entries, unsafe paths, and unsafe compression ratios are rejected
before any submission is created.

---

## 7. Providers and models

All providers live behind the Brain Adapter. Real providers are off unless
explicitly configured.

| Provider | Role | State |
|---|---|---|
| `mock` | deterministic default | active default |
| `llama_cpp_qwen38` | Qwen3.8-27B vision, loopback port 8085 | **the only model in the supervised workflow** |
| `llama_cpp_qwen` | Qwen3.6-35B-A3B text | disabled rollback asset |
| PaddleOCR-VL / PP-DocLayoutV3 sidecar | retired recognition stack | disabled rollback asset |
| RapidOCR | tier-1 CPU OCR | behind `LOCAL_OCR_ENABLED`, default false |
| `codex_cli`, `gemini`, `openai` | historical/dev paths | disabled |

Qwen3.8 runtime is pinned by publisher SHA-256 for both the main GGUF and the
vision projector, and the server must serve the exact model alias. Runtime
b10622 with speculative decoding (MTP draft length 3) is the promoted
configuration; b10249 is retained for immediate rollback.

---

## 8. Evaluation harnesses

Seven benchmark suites exist under `apps/api/packages/evaluation/`. They were
built deliberately *before* real providers, on the reasoning that real providers
are not self-validating: without benchmarks the project cannot answer whether a
provider found the full answer, attached it to the right grading unit, missed a
continuation, invented a false continuation warning, or merely moved errors into
the review queue.

- reference extraction evaluator
- answer mapping evaluator
- script processing evaluator
- grading evaluation
- grading model bake-off
- OCR engine bake-off
- marking policy calibration
- local curated evaluation (the 20-case gate)

The OCR bake-off includes a **Tesseract control arm added specifically to prove
the harness discriminates rather than flattering whatever it measures**. That
control is the reason the bake-off results can be trusted as comparisons.

---

## 9. Where the project stands

### Verified engineering state (measured 2026-08-31)

| Check | Result |
|---|---|
| Backend tests | 594 passed, 3 skipped |
| Ruff | clean |
| Frontend static workflow test | passed |
| Migration head | `0026_bulk_supervised_evaluation` |
| Working tree | clean apart from one untracked local helper script |

### What is built

Course/assessment/question/rubric workflows; submission upload and page
rendering; reference extraction from teacher PDFs; Qwen3.8 answer-region mapping
with continuation handling; final-intent visual transcription with cancellation
classification and an authorized thinking-repair path; text-only draft grading;
evidence readiness and quarantine accounting; a confirmed-packet-only grading
queue with staleness validation; capped sequential cohort dispatch; teacher
review, approval, and approved-only XLSX export; Bulk Supervised ZIP cohort
evaluation with an exception inbox and snapshot approval; a tiered OCR pipeline
with vision escalation; seven evaluation harnesses; and the full Windows pilot
runtime with preflight, lease, and phase management.

### What is NOT proven

Engineering readiness is not quality evidence, and the project has very little of
the latter. This section must not be softened in any status report.

- **No teacher-signed 20-case curated quality `PASS` exists.** `BACKLOG.md`
  records the gate as *not runnable* because its OCR stage was never rewired
  after the pipeline changed to Qwen3.8-only. Nothing recorded since states that
  it has been rewired, so as documented the gate is unrunnable, not merely unrun.
- **No end-to-end supervised rehearsal has ever completed.**
  `docs/FOUNDER_PILOT_REHEARSAL.md` is a 12-step protocol that has never been
  executed to the end.
- **Gate I4 has exactly one teacher-reviewed image**, on one crop from one
  submission. It is explicitly insufficient evidence for cohort or batch use.
- **Escalation thresholds are PROVISIONAL.** Only 6 unique handwriting images
  exist, too few for a dev/holdout split.
- **The grading-model bake-off has never run.**
- **Bulk Supervised has no recorded verification.** It has unit and API tests and
  a bounded live-smoke script, but no `BACKLOG.md` entry and no
  `docs/VALIDATION_LOG.md` record.

### Known quality limitations

- Tier-1 OCR drops decimal points on some handwriting (`03` for `0.3`), a 10x
  error in a value a mark depends on. Handwriting therefore escalates often, and
  the speed benefit is concentrated on reference extraction rather than script
  checking.
- Historical grading accuracy (Codex era, May–June 2026) showed a clear
  asymmetry: 8/8 exact on full-score correct answers, but the one real
  partial-credit case was **over-scored by 2.5 marks at 0.82 confidence**.
  Reliable on clean correct work, unreliable on partial credit. This has not been
  re-measured on the current Qwen3.8 pipeline.
- Marking policy (Tough/General/Easy) is recorded end to end, but a calibration
  smoke found all three policies produced **identical scores**. Policy metadata
  reaches the provider; policy does not yet influence marks.

---

## 10. Development history

The project moved through three eras.

**Foundation (May – June 2026).** Stack lock, domain model, teacher review and
approval flow, XLSX export, evidence-packet readiness gate, and the AEEM pivot
after the `1(b)(i)` continuation failure. Grading experiments used Codex CLI and
established the safety invariants that still hold.

**Local-first pivot (July – mid August 2026).** Everything moved onto the
Windows host: local llama.cpp providers, a PaddleOCR sidecar, the model lease,
capped cohort dispatch, and the evaluation harnesses. Qwen3.8 vision replaced
local OCR for transcription in TA-LOCAL-003.

**Consolidation (20 – 30 August 2026, 82 commits).** In order: fixed the
reference-extraction JSON truncation, page-count, and timeout failures; built and
ran the OCR bake-off and rejected Unlimited-OCR, GOT-OCR2, and PaddleOCR-VL-1.6,
keeping RapidOCR as tier-1; fixed the `--n-cpu-moe` offload split, taking Qwen3.6
from 17.9 to over 60 tok/s; attempted a Paddle + Qwen3.6 hybrid and then
abandoned it in favour of a Qwen3.8-only supervised workflow; designed and built
final-intent transcription and the bounded thinking repair; hardened boundary and
continuation mapping; promoted llama.cpp b10622 with MTP speculative decoding for
a 93% decode improvement (5.44 to 10.52 tok/s); and built Bulk Supervised.

The branch name `rescue/paddle-qwen36-hybrid` is a fossil of the abandoned hybrid
and no longer describes the work on it.

---

## 11. Where it is going

**Immediately blocking the pilot**, in order:

1. Make the 20-case curated quality gate runnable against the Qwen3.8 pipeline,
   then run it to a teacher-signed `PASS`.
2. Execute one complete founder-supervised rehearsal end to end, per
   `docs/FOUNDER_PILOT_REHEARSAL.md`.

Neither can be substituted by more engineering. Both are named in every status
document as the pilot blockers.

**Then:** `TA-PILOT-014`, one real teacher, observed, synthetic data only, using
the protocol in `docs/REAL_TEACHER_OBSERVED_SYNTHETIC_PILOT_PROTOCOL.md`.

**Then, in risk order:** marking policy calibration so policy actually affects
borderline marks; Semi-Automated mode; Fully Automated mode only after
extraction, mapping, and grading quality are proven on mixed teacher-marked
originals. A voice-command assistant is a stated future extension, not scheduled.

### The strategic inflection point

Bulk Supervised is a genuine change in the safety envelope and should be treated
as such. Every earlier mode required a teacher confirmation at each evidence
gate. Bulk Supervised replaces per-item teacher confirmation with **policy
thresholds** — mapping and transcription auto-pass at confidence `0.90`, grading
counts as clean at `0.80` — and collapses the teacher's role to an exception
inbox plus one snapshot approval. The provider-call ceiling rises from 25 to
2,000.

The implementation is careful about the distinction: policy verification is
recorded as `bulk_policy` and never impersonates teacher confirmation, blank,
unreadable, truncated, low-confidence, contradictory, and interrupted evidence
receive no silent score, and final grades still require exact-snapshot teacher
approval. But the honest framing is that clean items now reach a grade having
been checked by a confidence number rather than by a person, and those thresholds
were chosen rather than calibrated.

The one real over-score in the project's recorded history occurred at **0.82
confidence**, which clears the `0.80` clean-grading threshold. Threshold
calibration against teacher-marked partial-credit cases should therefore be
treated as a prerequisite for relying on Bulk Supervised, not as a follow-up.

---

## 12. Validating locally

Backend tests need a repository-local base temp directory on this host because
the default Windows pytest temp directory can deny access:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest -q --basetemp ..\..\tmp\pytest-claude
..\..\.venv\Scripts\python.exe -m ruff check .
Pop-Location
```

CI runs pytest with `working-directory: apps/api`, so any test that reads a
repository file must resolve it from `Path(__file__)`, never from a
repository-root-relative literal.

Frontend checks use the bundled Node installation rather than assuming `npm` is
on `PATH`:

```powershell
$env:Path = "$PWD\.local-ai\runtime\node-v22.14.0;$env:Path"
Push-Location apps\web
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run lint
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run build
Pop-Location
```

Starting, stopping, or rebuilding the stack is an operational action and requires
explicit user authorization. So does any provider or model call.

---

## 13. Document map

| Purpose | Document |
|---|---|
| Binding agent rules | `AGENTS.md`, root `CLAUDE.md` |
| Current working state | newest `docs/CLAUDE_HANDOFF_*.md` |
| Component boundaries | `ARCHITECTURE.md` |
| Task ledger | `BACKLOG.md` (newest first) |
| Verification records | `docs/VALIDATION_LOG.md` |
| Grading quality findings | `docs/GRADING_QUALITY_NOTES.md` |
| Windows runtime | `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md` |
| Local model operation | `docs/LOCAL_AI_RUNBOOK.md` |
| Rehearsal protocol | `docs/FOUNDER_PILOT_REHEARSAL.md` |
| Bulk Supervised | `docs/BULK_SUPERVISED_RUNBOOK.md` |
| Product direction | `docs/PRODUCT_ROADMAP.md`, `docs/GRADING_WORKFLOW_MODES.md` |
| AEEM layer mapping | `docs/AEEM_IMPLEMENTATION_ROADMAP.md` |
| Provider rules | `docs/PROVIDER_USAGE_POLICY.md` |
| Privacy | `docs/PRIVACY_BASELINE.md`, `docs/STUDENT_SCRIPT_PRIVACY_AND_RETENTION.md` |
