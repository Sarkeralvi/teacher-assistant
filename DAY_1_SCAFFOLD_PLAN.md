# Day 1 Scaffold Implementation Plan

> **For Hermes:** Hermes is the single builder/controller. Do not use a separate VS Code/Codex worker model. Do not start coding until this plan and `DEVELOPMENT_PROTOCOL.md` are updated and verified.

**Goal:** Create a clean repository scaffold for the locked Teacher Assistant stack without implementing product features.

**Architecture:** Monorepo with `apps/web` for Next.js frontend, `apps/api` for FastAPI backend, RQ worker entrypoint under `apps/api/app/worker`, backend domain package boundaries under `apps/api/app/modules`, and infrastructure at repo root. All storage and AI boundaries must exist as directories/contracts only; no real LLM integration.

**Tech Stack:** Next.js App Router, TypeScript, Tailwind CSS, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, PostgreSQL, Redis, RQ, local storage adapter, PyMuPDF, Pillow, OpenCV, openpyxl, Docker Compose, Makefile, pytest.

---

## Active Task

TASK-ID: `TA-W1-003`
Title: Create initial repository scaffold
Owner: Hermes

## Exact Repo Structure to Create

This is the exact repo structure to create for Day 1 scaffold:

```text
teacher-assistant/
├── PROJECT_CONSTITUTION.md
├── ARCHITECTURE.md
├── TECH_STACK_DECISION.md
├── BRAIN_ADAPTER_SPEC.md
├── GRADING_ENGINE_SPEC.md
├── DEVELOPMENT_PROTOCOL.md
├── WEEK_1_EXECUTION_MAP.md
├── DAY_1_SCAFFOLD_PLAN.md
├── BACKLOG.md
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── apps/
│   ├── web/
│   │   ├── package.json
│   │   ├── package-lock.json
│   │   ├── next.config.ts
│   │   ├── tsconfig.json
│   │   ├── postcss.config.mjs
│   │   ├── eslint.config.mjs
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx
│   │   │   └── globals.css
│   │   └── tests/
│   │       └── README.md
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── README
│   │   │   └── versions/.gitkeep
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── core/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── config.py
│   │   │   │   └── logging.py
│   │   │   ├── db/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   └── session.py
│   │   │   ├── api/
│   │   │   │   ├── __init__.py
│   │   │   │   └── routes/
│   │   │   │       ├── __init__.py
│   │   │   │       └── health.py
│   │   │   ├── modules/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── brain_adapter/__init__.py
│   │   │   │   ├── courses/__init__.py
│   │   │   │   ├── assessments/__init__.py
│   │   │   │   ├── rubrics/__init__.py
│   │   │   │   ├── submissions/__init__.py
│   │   │   │   ├── documents/__init__.py
│   │   │   │   ├── grading/__init__.py
│   │   │   │   ├── review/__init__.py
│   │   │   │   ├── export/__init__.py
│   │   │   │   ├── storage/__init__.py
│   │   │   │   └── audit/__init__.py
│   │   │   └── worker/
│   │   │       ├── __init__.py
│   │   │       └── rq_app.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── test_health.py
│   │       └── test_no_direct_llm_imports.py
│   └── web.Dockerfile or apps/web/Dockerfile
├── data/
│   ├── uploads/.gitkeep
│   ├── artifacts/.gitkeep
│   └── exports/.gitkeep
└── docs/
    └── decisions/.gitkeep
```

Note: If Next.js scaffold requires extra generated files, keep them only if they are standard for the locked stack and report them.

## Exact Services in `docker-compose.yml`

Required services:

1. `postgres`
   - image: `postgres:16-alpine`
   - env: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
   - port: `5432:5432`
   - volume: `postgres_data:/var/lib/postgresql/data`
   - healthcheck: `pg_isready`

2. `redis`
   - image: `redis:7-alpine`
   - port: `6379:6379`
   - healthcheck: `redis-cli ping`

3. `api`
   - build context: `./apps/api`
   - command: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
   - env file: `.env`
   - depends on healthy `postgres` and `redis`
   - port: `8000:8000`
   - volumes: `./apps/api:/app`, `./data:/data`

4. `worker`
   - build context: `./apps/api`
   - command: `rq worker --url redis://redis:6379/0 teacher-assistant-default`
   - env file: `.env`
   - depends on healthy `redis`, `postgres`
   - volumes: `./apps/api:/app`, `./data:/data`

5. `web`
   - build context: `./apps/web`
   - command: `npm run dev -- --hostname 0.0.0.0 --port 3000`
   - env file: `.env`
   - depends on `api`
   - port: `3000:3000`
   - volumes: `./apps/web:/app`

Required volumes:
- `postgres_data`

## Exact Backend Packages

Use Python 3.12 if available. Backend dependencies:

Runtime:
- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `pydantic-settings`
- `sqlalchemy>=2.0`
- `alembic`
- `psycopg[binary]`
- `redis`
- `rq`
- `PyMuPDF`
- `Pillow`
- `opencv-python-headless`
- `openpyxl`
- `python-multipart`
- `structlog`

Dev/test:
- `pytest`
- `pytest-cov`
- `httpx`
- `ruff`
- `mypy`

No provider LLM SDK packages are allowed in scaffold task.

## Exact Frontend Packages

Runtime/dev packages expected:
- `next`
- `react`
- `react-dom`
- `typescript`
- `tailwindcss`
- `@tailwindcss/postcss`
- `eslint`
- `eslint-config-next`
- `@types/node`
- `@types/react`
- `@types/react-dom`

No LLM SDK packages are allowed in frontend.

## Exact Environment Variables

Create `.env.example` with:

```env
# App
APP_ENV=development
APP_NAME=Teacher Assistant
API_HOST=0.0.0.0
API_PORT=8000
FRONTEND_URL=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Database
POSTGRES_DB=teacher_assistant
POSTGRES_USER=teacher_assistant
POSTGRES_PASSWORD=teacher_assistant_dev_password
DATABASE_URL=postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@postgres:5432/teacher_assistant

# Redis / RQ
REDIS_URL=redis://redis:6379/0
RQ_DEFAULT_QUEUE=teacher-assistant-default

# Storage adapter
STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=/data
UPLOADS_DIR=/data/uploads
ARTIFACTS_DIR=/data/artifacts
EXPORTS_DIR=/data/exports

# Brain Adapter
BRAIN_PROVIDER=fake
BRAIN_POLICY=week1_fake_only
BRAIN_ALLOW_REAL_PROVIDERS=false

# Logging
LOG_LEVEL=INFO
```

`.env` may be copied locally from `.env.example`; do not commit real secrets.

## Exact Commands Hermes Must Run

From repo root:

```bash
# verify docs exist before scaffold
ls PROJECT_CONSTITUTION.md ARCHITECTURE.md TECH_STACK_DECISION.md BRAIN_ADAPTER_SPEC.md GRADING_ENGINE_SPEC.md DEVELOPMENT_PROTOCOL.md WEEK_1_EXECUTION_MAP.md DAY_1_SCAFFOLD_PLAN.md BACKLOG.md

# inspect current status
git status --short || true

# create implementation branch if repo is git and branch does not exist
git checkout -b task/TA-W1-003-project-scaffold || true

# after files are created
cp .env.example .env
make test
make lint
make up
make health
make down

git status --short || true
```

Expected results:
- `make test` passes backend pytest smoke and boundary tests.
- `make lint` passes backend ruff check and frontend lint if dependencies install.
- `make up` starts postgres, redis, api, worker, and web.
- `make health` confirms FastAPI health endpoint responds.
- `make down` stops services cleanly.

If Docker is unavailable or blocked, Hermes must report exact error output and still run all non-Docker tests possible.

## Exact Acceptance Criteria

TA-W1-003 is accepted only if:
1. Repo structure matches this plan or deviations are documented.
2. Docker Compose defines `postgres`, `redis`, `api`, `worker`, and `web`.
3. Backend installs with listed packages.
4. Frontend installs with listed packages.
5. `.env.example` contains all listed variables.
6. FastAPI has health route only; no product feature routes yet.
7. Backend has module directories for architecture boundaries.
8. Storage adapter directory exists, but no S3/MinIO implementation yet.
9. Brain Adapter directory exists, but no real provider integration and no LLM SDK dependency.
10. Grading module directory exists, but no grading feature implementation yet.
11. `make test`, `make lint`, `make up`, `make health`, and `make down` pass, or failures are documented with exact error output and remaining issues.
12. `BACKLOG.md` is updated after task completion or failure.
13. Hermes reports files changed, commands run, test results, and remaining issues.

## Exact Tests Required

Backend Week 1 scaffold tests:

1. `apps/api/tests/test_health.py`
   - use FastAPI TestClient or httpx test client
   - assert `GET /health` returns HTTP 200
   - assert JSON includes `status: "ok"`

2. `apps/api/tests/test_no_direct_llm_imports.py`
   - fail if `openai`, `anthropic`, `google.generativeai`, or direct LLM provider imports appear outside `apps/api/app/modules/brain_adapter/`
   - for scaffold, no such imports should exist anywhere

Minimum command:

```bash
cd apps/api && pytest -q
```

Frontend Week 1 tests:
- Minimal only.
- `npm run lint` must pass if dependencies install.
- No frontend unit test required on Day 1 unless scaffold tool creates one.

## Hermes Implementation Tasks

### TA-W1-003A: Preflight
Owner: Hermes
Goal: Confirm docs and current repo status before scaffold.
Commands: `ls ...`, `git status --short || true`.
Done when: docs exist and current state is known.

### TA-W1-003B: Create backend scaffold
Owner: Hermes
Goal: Create FastAPI app, health route, config, DB placeholders, Alembic placeholders, worker entrypoint, module boundary directories, backend Dockerfile and pyproject.
Done when: backend files exist and `cd apps/api && pytest -q` can run after dependencies are available.

### TA-W1-003C: Create frontend scaffold
Owner: Hermes
Goal: Create minimal Next.js App Router + TypeScript + Tailwind app.
Done when: package files and basic app files exist.

### TA-W1-003D: Create infra scaffold
Owner: Hermes
Goal: Create Docker Compose, Makefile, `.env.example`, `.gitignore`, data directories, README.
Done when: root commands exist.

### TA-W1-003E: Verify and report
Owner: Hermes
Goal: Run required commands, fix in-scope failures, update backlog, and report.
Done when: command results are recorded and `BACKLOG.md` is updated.

## Files Hermes May Touch for TA-W1-003

Allowed for scaffold implementation:
- `README.md`
- `Makefile`
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `apps/**`
- `data/**`
- `docs/decisions/**`
- `BACKLOG.md` for task status update

Locked docs not to change during scaffold implementation unless Human requests:
- `PROJECT_CONSTITUTION.md`
- `ARCHITECTURE.md`
- `TECH_STACK_DECISION.md`
- `BRAIN_ADAPTER_SPEC.md`
- `GRADING_ENGINE_SPEC.md`
- `DEVELOPMENT_PROTOCOL.md`
- `WEEK_1_EXECUTION_MAP.md`
- `DAY_1_SCAFFOLD_PLAN.md`

## Stop Conditions for Hermes

Stop and ask Human if:
- any dependency outside locked stack seems needed
- a direct LLM package appears necessary
- Docker cannot run and scaffold verification cannot proceed meaningfully
- test setup requires changing architecture boundaries
- scaffold tool wants to create feature code beyond health check
- implementation would violate Constitution or Architecture

## Commit Requirement

After successful scaffold verification, if this is a git repo:

```bash
git add README.md Makefile docker-compose.yml .env.example .gitignore apps data docs/decisions BACKLOG.md
# include generated lockfiles if created
git commit -m "chore(scaffold): create initial project scaffold [TA-W1-003]"
```

## Required Final Report

Hermes must report:
- files changed
- commands run
- test results
- backlog status update
- remaining issues
