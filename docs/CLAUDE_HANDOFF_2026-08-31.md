# Claude Handoff - 2026-08-31

## Purpose

This is the current operating handoff for ongoing development of Teacher
Assistant / AEEM. It supersedes `docs/CLAUDE_HANDOFF_2026-08-20.md`, which was 82
commits out of date. It contains no credentials, private artifacts, uploaded
PDFs, or model paths.

Read `AGENTS.md` and root `CLAUDE.md` before acting. They are the binding safety
contract. For full orientation read `docs/REPOSITORY_OVERVIEW.md`.

## Current baseline

- Repository root: `E:\teacher-assistant`
- Branch: `rescue/paddle-qwen36-hybrid`
- Handoff baseline: `9f37e80` plus the commit carrying this document
- Backend migration head: `0026_bulk_supervised_evaluation`
- Supported workflows: Custom Controlled and Bulk Supervised. Semi- and
  fully-automated modes are out of scope and disabled.
- Cohort model grading must remain disabled.

### Branch state requires attention

`rescue/paddle-qwen36-hybrid` is **97 commits ahead of `origin/master` and
nothing has been pushed.** Local `master` is 46 commits behind this branch. All
work from the OCR bake-off, the Qwen3.8 pivot, the transcription design, the
runtime optimization, and the whole of Bulk Supervised exists only on this
machine, which has a documented hardware stability fault. Pushing the branch is
the highest-value low-cost action available and requires user authorization
because it is outward-facing.

The branch name is a fossil. It refers to a Paddle + Qwen3.6 hybrid that was
attempted and then abandoned in favour of the Qwen3.8-only supervised workflow.
It no longer describes the work on the branch.

## Supported Windows runtime

The repository ships its own Windows pilot dependencies under ignored
`.local-ai/runtime/`: PostgreSQL, Memurai (Redis-compatible queue), Node.js, a
Python virtual environment, and the local llama.cpp Qwen3.8 server.

Do not assume system `node`, Docker, PostgreSQL, or Redis exists on `PATH`.

Use the supported launcher from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1 -StartLocalAi -LocalAiMode Qwen38
```

Check the stack with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll
```

The expected ready services are PostgreSQL, Redis/RQ, backend, RQ worker,
frontend, and loopback-only Qwen3.8. The frontend is `http://localhost:3000`.

Do not manually run Uvicorn. A manually started API previously used a different
storage root (`E:\data`) from the pilot runtime
(`E:\teacher-assistant\data`), which produced database records for reference
PDFs that the worker could not find.

## What changed since the 2026-08-20 handoff

**The reference-extraction latency failure described in the previous handoff is
resolved and is no longer the current issue.** It was fixed by a measured
throughput/timeout correction plus JSON-truncation and page-count robustness
work.

Subsequent changes, in order:

- **OCR bake-off run and decided.** Six engines against ten fixtures, with a
  Tesseract control arm proving the harness discriminates. Unlimited-OCR,
  GOT-OCR2, and PaddleOCR-VL-1.6 were evaluated and rejected. RapidOCR remains
  tier-1.
- **Qwen3.6 offload split fixed**, 17.9 to over 60 tok/s.
- **Paddle + Qwen3.6 hybrid attempted, then abandoned.** The supervised workflow
  is now **Qwen3.8-only**. PaddleOCR and Qwen3.6 are disabled rollback assets.
- **Final-intent transcription built.** Qwen3.8 classifies visible
  cancellation/replacement marks first, then transcribes only surviving work. A
  separately authorized one-call thinking repair may adjudicate visible edits; it
  receives no question, solution, rubric, marks, or grading context and stays
  review-only. Ambiguous overwrites remain `[unclear correction]`.
- **Boundary and continuation mapping hardened**, including ambiguous cross-page
  splits and omitted subpart boundary recovery.
- **Runtime promoted to llama.cpp b10622 with MTP speculative decoding**, draft
  length 3: decode 5.44 to 10.52 tok/s, +93%. b10249 retained for rollback.
  Context is now operator-configurable between `12288` and `32768`; the previous
  handoff's fixed `12288` figure is superseded.
- **Bulk Supervised built** (migration `0026`, ~4,100 lines): ZIP cohort intake,
  durable RQ jobs, exception inbox, snapshot-exact bulk approval, and an XLSX
  export that marks any student with an unresolved item `INCOMPLETE`. See
  `docs/BULK_SUPERVISED_RUNBOOK.md`.

## Current state and open items

### Engineering health, measured 2026-08-31

| Check | Result |
|---|---|
| Backend tests | 594 passed, 3 skipped |
| Ruff | clean |
| Frontend static workflow test | passed |
| Migration head | `0026` |

A CI-breaking test was found and fixed in this handoff commit.
`tests/test_bulk_evaluation_service.py` read its source file through a
repository-root-relative literal, which failed under CI's
`working-directory: apps/api`. It now resolves from `Path(__file__)`, matching
the convention used by every other file-reading test in the suite. **Any new test
that reads a repository file must do the same.**

### Open items, in priority order

1. **Push the branch.** See branch state above.
2. **The 20-case curated quality gate is recorded as not runnable**, because its
   OCR stage was never rewired after the pipeline changed to Qwen3.8-only.
   Nothing since records it as rewired. Confirm its real state before citing any
   result from it. No result may be cited from a gate that cannot run.
3. **Bulk Supervised has no `BACKLOG.md` entry and no `docs/VALIDATION_LOG.md`
   record.** It is the newest, largest, and most safety-significant feature and
   the least documented. `AGENTS.md` requires both. This gap should be closed
   before the feature is exercised further.
4. **Bulk Supervised confidence thresholds are chosen, not calibrated.** Mapping
   and transcription auto-pass at `0.90`; grading counts as clean at `0.80`. The
   one real over-score in the project's recorded history occurred at `0.82`
   confidence, which clears the clean-grading threshold. Calibrate against
   teacher-marked partial-credit cases before relying on the mode.
5. **Escalation thresholds remain PROVISIONAL.** Only 6 unique handwriting
   images exist, too few for a dev/holdout split.
6. Untracked local helper `scripts/local-ai/Get-Qwen38ApiKey.ps1` copies the
   loopback API key to the clipboard. It reads ignored configuration so it leaks
   nothing if committed, but decide deliberately whether it belongs in the
   repository.

## Immediate next step

No provider call, upload, batch run, or stack operation may happen without the
user's explicit authorization of its exact bounded scope.

The two gates blocking any teacher pilot are unchanged and cannot be substituted
by more engineering:

1. Make the 20-case curated quality gate runnable against the current Qwen3.8
   pipeline, then run it to a teacher-signed `PASS`.
2. Execute one complete founder-supervised rehearsal end to end, per
   `docs/FOUNDER_PILOT_REHEARSAL.md`.

If the user authorizes one fresh bounded local provider call:

1. Confirm all six pilot services are healthy.
2. Confirm the target run uses files in `E:\teacher-assistant\data` through the
   managed API.
3. Ask the teacher/founder to confirm the displayed inputs and deliberately start
   the action.
4. Watch the single worker job and the Qwen log. Do not add a retry and do not
   run another provider request yourself.
5. On success, stop at teacher draft review. Do not confirm materials, map
   answers, grade, finalize, or export without the corresponding authorization.
6. On failure, capture the sanitized run state, response timing, server token
   counts, and error. Do not broaden provider permissions and do not use a cloud
   fallback.

## Safety and workflow state

- Qwen3.8 visual preparation, transcription, thinking repair, single-answer
  grading, and Bulk Supervised are locally enabled for rehearsal.
- Provider use remains explicit and teacher-controlled.
- `COHORT_MODEL_GRADING_ENABLED=false` is required.
- AI cannot finalize grades. A grade stays a review-required suggestion until an
  explicit teacher approval action.
- One Gate I4 visual-transcription smoke was teacher-reviewed and signed off on a
  single image. That is insufficient evidence for cohort or batch use.
- **The founder-supervised rehearsal has still not been completed.**
- Use only synthetic or founder-authorized data.

Canonical workflow documents: `docs/REPOSITORY_OVERVIEW.md`,
`docs/FOUNDER_PILOT_REHEARSAL.md`, `docs/LOCAL_AI_RUNBOOK.md`,
`docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`, `docs/BULK_SUPERVISED_RUNBOOK.md`,
`docs/PROVIDER_USAGE_POLICY.md`, `BACKLOG.md`.

## Validation commands

Backend tests need a repository-local base temp directory on this machine
because the default Windows pytest temp directory can deny access:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest -q --basetemp ..\..\tmp\pytest-claude
..\..\.venv\Scripts\python.exe -m ruff check .
Pop-Location
```

Run from `apps\api`, which is the working directory CI uses. A test that passes
only from the repository root will fail in CI.

For frontend checks, use the bundled Node installation rather than assuming
`npm` is on `PATH`:

```powershell
$env:Path = "$PWD\.local-ai\runtime\node-v22.14.0;$env:Path"
Push-Location apps\web
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run lint
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run build
Pop-Location
```

The frontend static workflow guard can be run directly:

```powershell
& ".\.local-ai\runtime\node-v22.14.0\node.exe" apps\web\tests\workflow-ui.test.mjs
```

## Handoff discipline

- Preserve existing user changes if the working tree is dirty; do not reset or
  discard them.
- Prefer focused diagnostics and tests before code changes.
- Treat model calls, uploads, pushes, deletions, approvals, and exports as
  external state changes requiring user authorization.
- Keep source changes small, test them, and commit them with an explanatory
  message.
- Record completed work in `BACKLOG.md` and verification in
  `docs/VALIDATION_LOG.md`. The repository's documentation discipline is its
  safety argument; a gap in it is a safety gap.
- In every final report, include the required seven sections from `AGENTS.md`.
