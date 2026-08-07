# Windows Teacher Pilot Runtime

The teacher-pilot stack runs directly on Windows. Docker and WSL are not required for this milestone. Qwen and PaddleOCR remain explicit operator-started services, while PostgreSQL, the Redis-compatible queue, the API, the Windows-compatible sequential RQ worker, and the frontend are managed together.

## Local runtime layout

Machine binaries and mutable service data live under ignored `.local-ai/runtime/`:

- Node.js 22.14.0
- PostgreSQL 17.10 and the host database cluster
- Memurai Developer 4.1.2, providing the Redis 7-compatible RQ transport
- Redis persistence data

Memurai Developer is suitable only for this non-production pilot/evaluation environment and automatically stops after ten continuous days. The status/start workflow detects and restarts it. Replace it with a properly licensed production Redis-compatible service before any production deployment.

Qwen, PaddleOCR models, API keys, and machine paths remain in the ignored `.env.local-ai` configuration and their existing external locations. No model or private evaluation artifact belongs in Git.

## Start

From the repository root, use an execution-policy override scoped to this one process:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1
```

The script starts PostgreSQL and Redis, applies Alembic migrations, explicitly starts both local models, starts the API and Windows RQ worker, and serves the production frontend. It does not make OCR or grading calls. RQ uses `SimpleWorker` on Windows because RQ 2.10's process monitor depends on the POSIX-only `os.wait4`; dispatches remain sequential, and persisted application heartbeats provide stale/crash reconciliation.

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

Shutdown only manages PID-recorded processes whose executable paths match the expected local runtime. PostgreSQL and Redis data are preserved.

## Safety gate

The runtime intentionally honors `COHORT_MODEL_GRADING_ENABLED=false`. Starting healthy services does not authorize a provider call. Real cohort grading may be enabled only after the locked 20-case curated evaluation produces `PASS`, and every dispatch still requires explicit teacher authorization. OCR remains draft-only until teacher confirmation, Qwen consumes confirmed text only, and every AI grade remains a pending suggestion until teacher review.
