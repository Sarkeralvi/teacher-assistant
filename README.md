# Teacher Assistant

AI-powered, teacher-controlled assessment platform. AI proposes; the teacher
governs. Every grade suggestion requires explicit teacher approval before a
FinalGrade exists or is exported.

## Stack

- Frontend: Next.js App Router, TypeScript, Tailwind CSS
- Backend: FastAPI, Pydantic, SQLAlchemy 2.x, Alembic
- Database: PostgreSQL
- Cache/Queue: Redis + RQ (`worker` service in docker-compose runs
  `python -m app.worker.run`) for explicit asynchronous single-region work
  and safe sequential cohort dispatch orchestration.
- Storage: local filesystem behind future storage adapter
- AI boundary: the Brain Adapter (`apps/api/packages/brain`) is the only
  module allowed to call grading/extraction language-model providers.
  Providers include `mock` (default), `gemini`, `openai`, `codex_cli`, and
  loopback-only `llama_cpp_qwen` (Qwen3.6 text) and `llama_cpp_qwen38`
  (Qwen3.8 vision). Qwen3.8 performs non-thinking visual transcription of
  answer evidence; Qwen3.6/Qwen3.8 grading receives teacher-confirmed text
  only. The retired PaddleOCR sidecar is not part of the active workflow. All
  real/local providers are off unless explicitly configured.

## First Run

```bash
cp .env.example .env
make test
make lint
make up
make health
make down
```

For a reliable local demo path and troubleshooting notes, see `docs/DEMO_RUNBOOK.md`.
For Windows-host local-Qwen operation, see `docs/LOCAL_AI_RUNBOOK.md`.
For the complete Windows teacher-pilot service stack, see
`docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`.

## Local service URLs

- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/health

## Rules

Do not add product features before architecture tasks approve them.
Do not bypass the Brain Adapter boundary — `tests/test_no_direct_llm_imports.py`
enforces this.
Real provider calls stay disabled by default and follow
`docs/PROVIDER_USAGE_POLICY.md`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs backend ruff + Alembic
migration + pytest against Postgres, and frontend type-check + static
workflow checks + build, on every push and pull request.
