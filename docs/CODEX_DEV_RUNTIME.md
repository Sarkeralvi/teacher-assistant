# Codex-enabled dev backend runtime

This runbook explains how to run the Teacher Assistant app so the browser can trigger the dev-only real Codex grading smoke path through the backend.

Baseline:

- `TA-W1-035C` added `POST /answer-regions/{answer_region_id}/grade-codex-dev`.
- The endpoint requires an authenticated teacher and `CODEX_BROWSER_GRADING_ENABLED=true`.
- The endpoint creates a `GradeSuggestion` only. It never creates a `FinalGrade`.
- Teacher review remains mandatory.
- The Docker backend image intentionally does **not** include Codex CLI.

## Safety rules

- Use synthetic/non-student data unless a separate privacy-reviewed task approves otherwise.
- Use **one answer region only** for real Codex smoke testing.
- Do **not** run real batch grading.
- Do **not** treat AI output as a final grade; approve/edit/reject through teacher review.
- Do **not** commit `.env`, local storage, uploads, exports, JWT tokens, Codex auth files, or API secrets.
- Do **not** expose JWT/Codex credentials in screenshots, logs, commits, or bug reports.
- Keep `CODEX_BROWSER_GRADING_ENABLED=false` by default. Enable it only in the host-backend dev shell that needs the smoke path.

## Runtime mode A: Docker-only normal demo

Use this for normal product demos.

Shape:

- PostgreSQL runs in Docker.
- Redis runs in Docker.
- Backend runs in Docker.
- Frontend runs in Docker.
- Mock grading works.
- The browser real Codex button may fail because the backend container cannot see the host `codex` command.

Commands:

```bash
cd /home/newton/teacher-assistant
cp .env.example .env  # only if .env does not already exist
make up
docker compose exec -T backend alembic upgrade head
make health
make frontend-health
```

Expected behavior:

- Use `Batch mock grade ungraded answers` for the normal demo.
- Do not enable real Codex grading for this mode.
- If `Real Codex grade this answer` is clicked, the request is blocked unless `CODEX_BROWSER_GRADING_ENABLED=true`; if enabled inside Docker, it can still fail with `codex` not found because Codex CLI is not installed in the backend container.

Shutdown:

```bash
make down
```

## Runtime mode B: Host-backend Codex dev mode

Use this only for a controlled one-answer Codex smoke. In this mode, Docker provides data services, but the backend runs on WSL/host where Codex CLI is installed and authenticated.

Shape:

- PostgreSQL runs in Docker.
- Redis runs in Docker.
- Backend runs on WSL/host.
- Frontend can run in Docker or on host.
- `CODEX_BROWSER_GRADING_ENABLED=true` is set only for the host backend process.
- Browser calls `http://localhost:8000`, and the host backend can call the host `codex` CLI.

### 1. Start only PostgreSQL and Redis

```bash
cd /home/newton/teacher-assistant
docker compose up -d postgres redis
docker compose ps
```

Wait until both services are healthy.

### 2. Run a safe no-repo Codex OK probe

Run this before starting a real Codex grading smoke. It proves the local CLI syntax/auth path works without sending project or student data.

```bash
codex exec --skip-git-repo-check --cd /tmp --sandbox read-only \
  --output-last-message /tmp/ta_codex_ok.txt 'Reply with OK only.'
cat /tmp/ta_codex_ok.txt
```

Expected output: `OK`.

If this fails, stop and fix Codex setup first. Do not change app code to work around Codex auth/setup failures.

### 3. Export host-backend environment

These values differ from Docker `.env` because the host backend reaches Docker-published ports through `localhost`, not Compose service names.

```bash
cd /home/newton/teacher-assistant
export APP_ENV=development
export DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant'
export REDIS_URL='redis://localhost:6379/0'
export LOCAL_STORAGE_ROOT="$PWD/data"
export UPLOADS_DIR="$PWD/data/uploads"
export ARTIFACTS_DIR="$PWD/data/artifacts"
export BRAIN_PROVIDER=mock
export CODEX_BROWSER_GRADING_ENABLED=true
export CODEX_CLI_COMMAND=codex
export CODEX_CLI_SANDBOX=read-only
export CODEX_CLI_APPROVAL_POLICY=never
export CODEX_CLI_USE_JSON=true
export CODEX_CLI_OUTPUT_LAST_MESSAGE=true
export CODEX_CLI_IMAGE_INPUT_ENABLED=false
export CODEX_CLI_WORKDIR="$PWD"
```

Notes:

- Keep `BRAIN_PROVIDER=mock`; the browser smoke endpoint constructs the Codex CLI provider explicitly.
- Keep `CODEX_CLI_IMAGE_INPUT_ENABLED=false` unless a separate image-input task approves it.
- Keep `CODEX_CLI_SANDBOX=read-only` and `CODEX_CLI_APPROVAL_POLICY=never`.

### 4. Apply migrations from the host backend environment

```bash
cd /home/newton/teacher-assistant/apps/api
alembic upgrade head
```

### 5. Start the host backend

```bash
cd /home/newton/teacher-assistant/apps/api
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check from another shell:

```bash
curl -fsS http://localhost:8000/health
```

### 6. Run/check frontend

Option A: Docker frontend only, with host backend already on `localhost:8000`:

```bash
cd /home/newton/teacher-assistant
docker compose up -d frontend
make frontend-health
```

Option B: Host frontend:

```bash
cd /home/newton/teacher-assistant/apps/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev -- --hostname 0.0.0.0 --port 3000
```

Then open:

```text
http://localhost:3000
```

### 7. One-answer browser smoke

1. Log in as a teacher.
2. Use synthetic/non-student data.
3. Create course → assessment → question → active rubric.
4. Upload one synthetic answer image/PDF.
5. Create one answer region for the question.
6. Open the assessment review page.
7. Click **Real Codex grade this answer** for exactly one answer region.
8. Confirm a `GradeSuggestion` appears and still requires teacher review.
9. Do not run real batch grading.
10. Approve/edit/reject only if you are intentionally testing final review behavior.

## Makefile helpers

Low-risk helpers exist for the host-backend workflow:

```bash
make codex-ok
make backend-host-dev
```

`make codex-ok` runs the safe `/tmp` Codex OK probe.

`make backend-host-dev` starts only the host backend. It assumes PostgreSQL/Redis are already running in Docker, migrations have been applied, and your shell environment is safe for host-backend mode. It sets host-safe defaults for database, Redis, storage, and Codex dev gating for that process.

## Troubleshooting

### `codex: command not found`

The backend runtime cannot find Codex CLI.

- In Docker-only mode, this is expected because the backend image does not install Codex.
- For host-backend mode, install/configure Codex CLI on WSL/host and confirm:

```bash
command -v codex
codex --version
make codex-ok
```

### Codex auth or quota failure

Symptoms include login-required messages, quota errors, provider errors, or non-`OK` output from the probe.

Fix:

- Re-authenticate Codex CLI in the host shell.
- Confirm quota/account access outside the app with `make codex-ok`.
- Stop if the probe fails. Do not alter app code to bypass a Codex account/setup problem.

### Trusted directory or git-repo check failure

Use the safe probe form for setup checks:

```bash
codex exec --skip-git-repo-check --cd /tmp --sandbox read-only \
  --output-last-message /tmp/ta_codex_ok.txt 'Reply with OK only.'
```

For app-triggered grading, set:

```bash
export CODEX_CLI_WORKDIR=/home/newton/teacher-assistant
```

If Codex rejects the repo/workdir, fix Codex trust/auth configuration in the host shell before retrying.

### Backend running in Docker cannot see host Codex

Symptom: browser request reaches backend but fails with `codex` not found or subprocess failure.

Cause: the backend process is inside the Docker container, and the container does not include the host `codex` binary/auth state.

Fix: use host-backend Codex dev mode. Do not add Codex to the production Docker image for this task.

### `CODEX_BROWSER_GRADING_ENABLED` not set

Symptom: `POST /answer-regions/{answer_region_id}/grade-codex-dev` returns `403` with a message that `CODEX_BROWSER_GRADING_ENABLED` must be true.

Fix: set it only in the host backend process:

```bash
export CODEX_BROWSER_GRADING_ENABLED=true
```

Restart the host backend after changing the environment.

### Frontend points at the wrong backend

Symptom: the browser UI loads but requests go to the wrong API or still hit a Docker backend without Codex.

Fix:

- Confirm the backend health at `http://localhost:8000/health`.
- For host frontend, start with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.
- For Docker frontend, make sure no stale Docker backend is also bound to port `8000`.

### Migrations or DB connection fail in host-backend mode

Use host URLs, not Compose service names:

```bash
export DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant'
export REDIS_URL='redis://localhost:6379/0'
cd apps/api
alembic upgrade head
```

If `localhost:5432` or `localhost:6379` is unavailable, check:

```bash
docker compose ps
docker compose up -d postgres redis
```
