# Pilot Monitoring

How to observe the running Windows teacher-pilot stack: service health, GPU
headroom, the application's audit trail, and where each background job's
status lives. This is monitoring for the current local-host pilot described
in `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`, not a cloud/production
observability stack — none exists for this project, and none should be
implied to exist.

## Service health

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll
```

Reports PostgreSQL, Redis/RQ, backend, RQ worker, frontend, and whichever
local-AI phase (if any) is loaded. Output is availability only — no API
keys, model paths, or student text.

The backend also exposes a plain liveness check with no auth:

```powershell
curl http://localhost:8000/health
```

## GPU / VRAM headroom

This host has one GPU shared by every local model. Check before starting or
switching a local-AI phase:

```powershell
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv
```

Qwen3.8 needs roughly 10.4 GiB; keep total usage under the documented
11,000 MiB safety ceiling on this machine. If something else (e.g. a
separate, non-project Qwen bridge) already holds the GPU, `Start-LocalAi.ps1`
will not stop it for you — check `nvidia-smi` first, since loading two
heavy models at once is what has previously destabilized this host.

## Log files

`Start-TeacherPilot.ps1` and `Start-LocalAi.ps1` redirect each managed
process's stdout/stderr to `.local-ai\logs\<service>.stdout.log` /
`.stderr.log` (git-ignored). Useful ones:

- `api.stdout.log` / `api.stderr.log` — backend, including uvicorn's access
  log (method, path, status code) for every request. This is the fastest
  way to find the real cause of a frontend error: grep for the failing path
  and status code here first.
- `worker.stdout.log` / `worker.stderr.log` — the RQ worker running grading,
  transcription, and bulk-evaluation jobs.
- `qwen38.stdout.log` / `qwen38.stderr.log` — the Qwen3.8 llama.cpp server.
- `frontend.stdout.log` / `frontend.stderr.log` — the Next.js server.
- `postgres.log` — the PostgreSQL server log.

There is no separate structured application log file; `app/core/logging.py`
logs to stdout at `settings.log_level`, which is why the log files above are
the only durable record of what the backend did.

## Application audit trail

Every safety-relevant action (grading, approval, correction, transcription,
bulk-evaluation dispatch, submission deletion, and more) writes a row to the
`audit_logs` table (`app/models.py::AuditLog`): `actor_type`, `actor_id`,
`event_type`, `entity_type`, `entity_id`, `payload_json`, `created_at`. This
is the source of truth for "what happened and who did it" — inspect it
directly with `psql` against the managed database rather than trusting a UI
summary:

```powershell
$env:Path = "$PWD\.local-ai\runtime\node-v22.14.0;$env:Path"  # not required for psql; shown for consistency
& ".\.local-ai\runtime\<postgres-version>\bin\psql.exe" -U postgres -d teacher_assistant `
  -c "select created_at, actor_type, event_type, entity_type, entity_id from audit_logs order by id desc limit 50;"
```

(Exact PostgreSQL binary path depends on the installed runtime version under
`.local-ai\runtime\`; check `Get-PilotPaths` in `scripts\pilot\Common.ps1`
for the resolved path on this machine.)

## Background job / run status

Long-running or async work does not live only in logs — each has a durable
status column that a stuck or failed run will show without needing logs at
all:

| Model | Table | What it tracks |
|---|---|---|
| `GradingJob` | `grading_jobs` | one grading call (mock, local Qwen, or Codex dev path) |
| `AnswerRegionOcrRun` | (see `app/models.py`) | one Qwen3.8 visual-transcription or thinking-repair call |
| `GradingDispatchRun` / `GradingDispatchItem` | | a cohort grading dispatch batch and its per-item state |
| `BulkEvaluationRun` / `BulkEvaluationItem` | | a Bulk Supervised ZIP-cohort run and its per-student state |
| `BatchEvidencePrepRun` | | a batch evidence-preparation pass |

A run stuck in a "queued"/"running"-like status past a reasonable time
(the RQ worker log shows nothing new for it) usually means the RQ enqueue
or the worker itself failed — see `docs/BULK_SUPERVISED_RUNBOOK.md` and the
enqueue-failure recovery paths added in TA-SEC-001 (`docs/VALIDATION_LOG.md`)
before assuming the job is silently still in flight.

## Evaluation-harness ledger

Each curated-evaluation run under `data/evaluation/<run_id>/` (git-ignored)
keeps its own `ledger.jsonl`: an append-only, hash-chained record of every
stage transition (`prepared`, `ground_truth_locked`, `ocr_completed`, ...),
each entry covering the SHA-256 of every artifact locked at that point. Use
`python -m packages.evaluation.local_curated_evaluation verify --run-id
<id>` (from `apps/api`) to check the chain rather than reading the JSONL by
hand.

## What this is not

There is no metrics/alerting system, no dashboard, and no production
deployment for this project — it is a single-teacher, single-host pilot by
design (`AGENTS.md`, `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`). Building one
is out of scope unless the founder explicitly changes that operating mode.
