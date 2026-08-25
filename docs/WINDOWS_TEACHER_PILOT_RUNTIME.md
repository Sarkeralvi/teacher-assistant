# Windows Teacher Pilot Runtime

The teacher-pilot stack runs directly on Windows. Docker and WSL are not required for this milestone. The local models remain explicit operator-started services, while PostgreSQL, the Redis-compatible queue, the API, the Windows-compatible sequential RQ worker, and the frontend are managed together.

## Local runtime layout

Machine binaries and mutable service data live under ignored `.local-ai/runtime/`:

- Node.js 22.14.0
- PostgreSQL 17.10 and the host database cluster
- Memurai Developer 4.1.2, providing the Redis 7-compatible RQ transport
- Redis persistence data

Memurai Developer is suitable only for this non-production pilot/evaluation environment and automatically stops after ten continuous days. The status/start workflow detects and restarts it. Replace it with a properly licensed production Redis-compatible service before any production deployment.

Model files, API keys, and machine paths remain in the ignored `.env.local-ai` configuration and their existing external locations. No model or private evaluation artifact belongs in Git. Local models are deliberately off after ordinary pilot startup: this prevents Qwen from occupying GPU memory while no approved AI action is running.

## Start

From the repository root, use an execution-policy override scoped to this one process:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1
```

The script starts PostgreSQL and Redis, applies Alembic migrations, starts the API and Windows RQ worker, and serves the production frontend. It does not start a local model. An explicit teacher extraction action starts only the required local phase; it does not make a grading call. RQ uses `SimpleWorker` on Windows because RQ 2.10's process monitor depends on the POSIX-only `os.wait4`; dispatches remain sequential, and persisted application heartbeats provide stale/crash reconciliation.

The launcher automatically restarts the API and worker when backend source or the
local configuration is newer than either process. It also rebuilds the production
frontend when app, component, library, E2E, configuration, or package files are
newer than the current Next.js build. A running Next server is stopped before the
build is replaced and restarted afterward, preventing stale browser chunk maps.

For an operator health-check session, explicitly request one local phase (normally never both on this GPU):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1 -StartLocalAi -LocalAiMode Qwen
```

Use `-LocalAiMode PaddleOcr` for an OCR health-check session or `-LocalAiMode Qwen` for Qwen3.6. Only one of `PaddleOcr`, `Qwen`, or `Qwen38` may be loaded. The services can also be started/stopped through `scripts\local-ai\Start-LocalAi.ps1` and `Stop-LocalAi.ps1` using the same process-local execution-policy override.

To rebuild the frontend before startup:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1 -RebuildFrontend
```

## Status

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll
```

The status output contains availability only. It does not print API keys, model paths, or student text.

## Stop

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Stop-TeacherPilot.ps1
```

Shutdown verifies executable paths before stopping managed processes. If a local-AI
PID record is missing, recovery is limited to the exact configured executable on
its dedicated port; an unknown process is refused. PostgreSQL and Redis data are
preserved.

## Safety gate

The runtime intentionally honors `COHORT_MODEL_GRADING_ENABLED=false`. Starting healthy services does not authorize a provider call. PaddleOCR and Qwen3.6 are disabled in the active workflow. Qwen3.8 mapping, verbatim transcription, and text-only grading each require a separate teacher action and valid model lease; every AI grade remains a pending suggestion until teacher review.
