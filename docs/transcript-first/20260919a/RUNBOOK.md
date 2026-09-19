# Reproducing run `20260919a`

Sanitized. No private paths, script identifiers or credentials.

This run made **zero** product-provider requests and touched **no** real script. Everything below
is offline and runs against a disposable database.

## 1. Isolated worktree

The original checkout is left untouched, including any staged work in it.

```bash
git worktree add <worktree-path> -b codex/transcript-first-<run-id> f08552962f9276dacdbb3ad2c47c38356a2aad9b
```

The worktree shares `.git` but not `.venv` or `node_modules`. Use the repository's existing
interpreter by absolute path, and link the existing web install rather than reinstalling:

```powershell
cmd /c mklink /J "<worktree-path>\apps\web\node_modules" "<repo>\apps\web\node_modules"
```

## 2. Disposable database

The pilot stack must stay stopped, and its `postgres-data` directory is never opened. Create a
separate cluster from the repository's own portable PostgreSQL 17.10 binaries, on its own port and
its own data directory outside the repository:

```powershell
$pgbin = "<repo>\.local-ai\runtime\postgresql-17.10\bin"
& "$pgbin\initdb.exe" -D <disposable-data-dir> -U postgres --auth=trust -E UTF8
& "$pgbin\pg_ctl.exe" -D <disposable-data-dir> -l <log-path> -o "-p 55432 -c listen_addresses=127.0.0.1" start
& "$pgbin\psql.exe" -h 127.0.0.1 -p 55432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
    -c "create role teacher_assistant login password '<dev-password>' superuser" `
    -c "create database teacher_assistant_test owner teacher_assistant"
```

Stop it again with `pg_ctl -D <disposable-data-dir> stop`. Delete the data directory to discard it.

`apps/api/tests/conftest.py` refuses to run outside a `*_test` database, so the target is checked
before anything destructive happens. Set it explicitly; never accept the default:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://teacher_assistant:<dev-password>@127.0.0.1:55432/teacher_assistant_test"
```

## 3. Checks

From `apps/api`:

```powershell
<repo>\.venv\Scripts\python.exe -m ruff check .
<repo>\.venv\Scripts\python.exe -m alembic upgrade head
<repo>\.venv\Scripts\python.exe -m pytest -q
```

From `apps/web`, with the portable Node on `PATH`:

```powershell
npm run lint
node tests/workflow-ui.test.mjs
npm run build
```

`npm run e2e` needs the isolated stack from §4 below. With it running:

```powershell
$env:E2E_BASE_URL = "http://127.0.0.1:53000"
$env:E2E_API_BASE_URL = "http://127.0.0.1:58000"
npm run e2e
```

## 4. The isolated rehearsal stack

Do **not** run `scripts/pilot/Start-TeacherPilot.ps1`. It targets the existing application:
`.local-ai\runtime\postgres-data`, the repository's `data/` directory, and ports 5432, 6379, 8000
and 3000. Read it and `scripts/pilot/Common.ps1` for the environment contract, then override every
value:

| Component | Existing application | Isolated rehearsal |
| --- | --- | --- |
| PostgreSQL | 5432, repository data dir | 55432, disposable cluster, database `teacher_assistant_rehearsal` |
| Redis-compatible | 6379 | 56379, own data dir |
| Queue namespace | `teacher-assistant-default` | `transcript-first-rehearsal` |
| Worker name | `teacher-assistant-windows-pilot` | `transcript-first-rehearsal-worker` |
| API | 8000 | 58000 |
| Web | 3000 | 53000 |
| Storage | repository `data/` | a disposable directory |

Set `BRAIN_PROVIDER=mock`, `BRAIN_ALLOW_REAL_PROVIDERS=false`,
`COHORT_MODEL_GRADING_ENABLED=false`, and point `LOCAL_STORAGE_ROOT`, `UPLOADS_DIR` and
`ARTIFACTS_DIR` at the disposable directory. Print the resolved `DATABASE_URL`, Redis URL, queue
name and storage root and check them **before** migrating:

```powershell
<repo>\.venv\Scripts\python.exe -c "from app.core.config import get_settings; s=get_settings(); print(s.database_url, s.redis_url, s.rq_default_queue, s.local_storage_root)"
```

Start the Redis-compatible server with its own config file on 56379, then from `apps/api`:
`alembic upgrade head`, `python -m uvicorn app.main:app --host 127.0.0.1 --port 58000`, and
`python -m app.worker.run`. Prove the worker is not merely started by enqueueing a job on the
isolated queue and waiting for it to finish.

The web app inlines `NEXT_PUBLIC_*` at **build** time, so it must be rebuilt with
`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:58000` before `next start --port 53000`; a build made
without it silently targets port 8000.

Populating a transcript needs a vision provider, which is not authorized, so the rehearsal seeds
invented evidence directly through the application's own models: a course, an assessment, three
questions with rubrics and confirmed question nodes, a submission with three rendered pages, and a
transcript whose page 1 succeeded, page 2 carries an unresolved line, and page 3 is
`unknown_outcome`. Stop everything afterwards: `Stop-Process` by port for the API, worker and web,
and `pg_ctl -D <dir> stop` for the cluster. Never kill a process tree that contains PostgreSQL —
doing so takes the server down with `0xC0000142`.

## 5. Migration rollback

All six migrations (`0031`–`0036`) are additive and reversible. From `apps/api`:

```powershell
<repo>\.venv\Scripts\python.exe -m alembic downgrade 0030_grading_run_brain_profile
```

That drops `script_transcripts`, `script_page_transcripts`, `script_transcript_blocks`,
`script_transcript_block_revisions`, `answer_evidence_assignments` and `answer_evidence_spans`,
and removes the columns added to `grade_suggestions`. Every pre-existing table is left as it was,
including `answer_region_mappings` and its unchanged status CHECK. The `0034` downgrade maps the
two new page states onto `failed` and keeps the reason in the error text, because an unknown
outcome must never silently become retriable. The full `head → 0030 → head` round trip was
exercised on the disposable cluster.

The behavioural rollback is separate and simpler: the page-read path stays gated behind
`LOCAL_QWEN38_PAGE_READ_ENABLED` / `ANTIGRAVITY_GEMINI_PAGE_READ_ENABLED`, both defaulting to
false. With them off, preparation runs the unchanged mapping-then-transcription path.

## 6. What is not reproducible here

Real-script rehearsal and any grading-quality measurement. Both authorization fields in the work
order arrived unfilled and the repository contains no approved rehearsal manifest, so this run is
`REAL_REHEARSAL_BLOCKED`. Synthetic fixtures prove mechanics; they are not handwriting, and they
are not evidence of grading quality.
