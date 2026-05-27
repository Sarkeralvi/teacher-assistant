# Teacher Assistant

Independent AI-powered Teacher Assistant product scaffold.

## Stack

- Frontend: Next.js App Router, TypeScript, Tailwind CSS
- Backend: FastAPI, Pydantic, SQLAlchemy 2.x, Alembic
- Database: PostgreSQL
- Cache/Queue: Redis / RQ-ready scaffold
- Storage: local filesystem behind future storage adapter
- AI boundary: custom Brain Adapter only; no direct LLM calls elsewhere

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

## Local service URLs

- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/health

## Rules

Do not add product features before architecture tasks approve them.
Do not add real LLM providers yet.
Do not bypass the Brain Adapter boundary.
