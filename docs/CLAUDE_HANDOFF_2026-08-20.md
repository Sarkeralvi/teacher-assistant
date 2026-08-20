# Claude Handoff - 2026-08-20

## Purpose

This is the current operating handoff for ongoing development of Teacher Assistant / AEEM. It is deliberately concise and contains no credentials, private artifacts, uploaded PDFs, or model paths.

Read `AGENTS.md` and root `CLAUDE.md` before acting. They are the binding safety contract.

## Current baseline

- Repository root: `E:\teacher-assistant`
- Handoff baseline: `8cc6efc15bcda43f1236465f638421206f6d2c94`
- Working tree was clean when this handoff was written.
- Backend migration head: `0023_qwen38_visual_preparation`.
- Normal workflow: Custom Controlled only. Semi- and fully-automated modes are out of scope.
- Cohort model grading must remain disabled.

## Supported Windows runtime

The repository ships its own Windows pilot dependencies under ignored `.local-ai/runtime/`:

- PostgreSQL
- Memurai (Redis-compatible queue)
- Node.js
- Python virtual environment
- Local llama.cpp Qwen3.8 server

Do not assume system `node`, Docker, PostgreSQL, or Redis exists on PATH.

Use the supported launcher from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1 -StartLocalAi -LocalAiMode Qwen38
```

Check the stack with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll
```

The expected ready services are PostgreSQL, Redis/RQ, backend, RQ worker, frontend, and loopback-only Qwen3.8. The frontend is `http://localhost:3000`.

Do not manually run Uvicorn. A manually started API previously used a different storage root (`E:\data`) from the pilot runtime (`E:\teacher-assistant\data`), which produced database records for reference PDFs that the worker could not find.

## Recent changes and current reference-extraction issue

### What failed

A four-page reference bundle was uploaded successfully, then local Qwen3.8 reference extraction failed twice:

1. The first attempt was unable to find the stored PDFs because of the storage-root mismatch described above. The three original PDFs were restored to the pilot storage root; their SHA-256 hashes were verified equal to the originals.
2. The next attempt hit the old 8K context ceiling and produced truncated JSON. Raising context to 16K stopped JSON truncation but made generation slow enough for the fixed 600-second HTTP timeout to cancel the request.

The server log showed the request was still generating at about 3.5 tokens/second when it was cancelled at 600 seconds. This was a real configuration/performance issue, not normal successful completion.

### Fix now live

Commits:

- `c2bc1cc` - initial context increase for multi-page reference extraction.
- `8cc6efc` - bounded latency fix; this supersedes the first tuning.

The managed Qwen3.8 server must run with:

- `--reasoning off`
- context `12288`
- `--image-min-tokens 1024`
- `--image-max-tokens 1280`
- one parallel slot

The reference-bundle provider request explicitly sets `enable_thinking=false`, `preserve_thinking=false`, and caps its response at 1,800 tokens. It remains a one-call, no-retry action. These settings are implemented in:

- `scripts/local-ai/Start-LocalAi.ps1`
- `apps/api/packages/brain/llama_cpp_qwen38_vision_provider.py`

After changing either backend source or local configuration, use the pilot launcher so API and worker restart in the same configuration.

### Immediate next step

Only if the user explicitly authorizes one fresh bounded local provider call:

1. Confirm all six pilot services are healthy.
2. Confirm the target reference run uses files in `E:\teacher-assistant\data` through the managed API.
3. Ask the teacher/founder to confirm the three displayed reference PDFs and deliberately click **Start a new extraction**.
4. Watch the single worker job and Qwen log. Do not add a retry or run another provider request yourself.
5. If it succeeds, stop at teacher draft review. Do not confirm materials, map answers, grade, finalize, or export without the corresponding user authorization.
6. If it fails, capture the sanitized run state, response timing, server token counts, and error; do not broaden provider permissions or use a cloud fallback.

## Safety and workflow state

- Qwen3.8 visual preparation and single-answer grading are locally enabled for rehearsal.
- Provider use is still explicit and teacher-controlled.
- `COHORT_MODEL_GRADING_ENABLED=false` is required.
- AI cannot finalize grades. A grade stays a review-required suggestion.
- One Gate I4 visual-transcription smoke was teacher-reviewed and signed off. It is insufficient evidence for cohort/batch use.
- The founder-supervised rehearsal itself has not been completed.
- Use only synthetic/founder-authorized data for the rehearsal.

Canonical workflow documents:

- `docs/FOUNDER_PILOT_REHEARSAL.md`
- `docs/LOCAL_AI_RUNBOOK.md`
- `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`
- `docs/PROVIDER_USAGE_POLICY.md`
- `BACKLOG.md`

## Validation commands

Backend tests need a repository-local base temp directory on this machine because the default Windows pytest temp directory can deny access:

```powershell
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest -q --basetemp ..\..\tmp\pytest-claude
..\..\.venv\Scripts\python.exe -m ruff check .
Pop-Location
```

For frontend checks, use the bundled Node installation rather than assuming `npm` is on PATH:

```powershell
$env:Path = "$PWD\.local-ai\runtime\node-v22.14.0;$env:Path"
Push-Location apps\web
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run lint
& "$PWD\..\..\.local-ai\runtime\node-v22.14.0\npm.cmd" run build
Pop-Location
```

## OAuth problem in the prior Claude attempt

The message `Failed to authenticate: OAuth session expired and could not be refreshed` is a Claude client/account-session issue, not a Teacher Assistant repository defect.

The user must sign Claude back in through the Claude client/CLI that they use before Claude can access this workspace. Do not attempt to fix it by changing repository files, deleting credential directories, copying API keys, or committing any token. Once authenticated, Claude should open this repository; root `CLAUDE.md` will provide the entry instructions.

## Handoff discipline

- Preserve existing user changes if the working tree is dirty; do not reset or discard them.
- Prefer focused diagnostics and tests before code changes.
- Treat model calls, uploads, deletions, approvals, and exports as external state changes requiring user authorization.
- Keep all source changes small, test them, and commit them with an explanatory message.
- In every final report, include the required seven sections from `AGENTS.md`.
