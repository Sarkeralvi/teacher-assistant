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

`npm run e2e` needs a live API and web stack and was not run in this run.

## 4. Migration rollback

Both migrations are additive and reversible. From `apps/api`:

```powershell
<repo>\.venv\Scripts\python.exe -m alembic downgrade 0030_grading_run_brain_profile
```

That drops `answer_evidence_spans`, `answer_evidence_assignments`, `script_transcript_blocks`,
`script_page_transcripts` and `script_transcripts` and leaves every pre-existing table, including
`answer_region_mappings` and its unchanged status CHECK, exactly as it was. Both directions were
exercised on the disposable cluster.

The behavioural rollback is separate and simpler: the page-read path stays gated behind
`LOCAL_QWEN38_PAGE_READ_ENABLED` / `ANTIGRAVITY_GEMINI_PAGE_READ_ENABLED`, both defaulting to
false. With them off, preparation runs the unchanged mapping-then-transcription path.

## 5. What is not reproducible here

Real-script rehearsal and any grading-quality measurement. Both authorization fields in the work
order arrived unfilled and the repository contains no approved rehearsal manifest, so this run is
`REAL_REHEARSAL_BLOCKED`. Synthetic fixtures prove mechanics; they are not handwriting, and they
are not evidence of grading quality.
