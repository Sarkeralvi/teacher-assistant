# Demo Runbook

Reliable local demo path for the Teacher Assistant workflow.

## Prerequisites

- Run commands from the project root: `/home/newton/teacher-assistant`.
- Docker Compose must be available and the Docker daemon must be running.
- Copy local env defaults if needed: `cp .env.example .env`.
- Use the default mock Brain Adapter provider for demos unless a real-provider smoke is explicitly approved.
- Use synthetic/non-student data only.

## Startup

```bash
cd /home/newton/teacher-assistant
cp .env.example .env  # only if .env does not already exist
make up
docker compose exec -T backend alembic upgrade head
make health
make frontend-health
```

Expected health signals:

- Backend health returns a successful response from `http://localhost:8000/health`.
- Frontend health reaches `http://localhost:3000` successfully.

## Full teacher workflow demo

Use the browser at `http://localhost:3000` and synthetic data only:

1. Create or select a dev teacher/user.
2. Create a course.
3. Create an assessment under the course.
4. Create at least one question with a total mark.
5. Create an active rubric for the question.
6. Upload a synthetic answer image or PDF submission.
7. Open the uploaded page image and create an answer region crop for the question.
8. Run mock grading only; confirm the suggestion is clearly marked as mock and still requires teacher review.
9. Open the assessment review page.
10. Approve, edit, or reject the mock suggestion into a final grade.
11. Confirm the review queue/summary reflects the final grade state.
12. Download the final-grade XLSX export and verify it opens with the expected reviewed row.

## Provider warnings

- Default demo mode is mock-provider-only.
- Do not run real Codex/OpenAI grading during the normal demo path.
- Real Codex grading requires separate explicit approval, a configured local Codex CLI session, and a narrow smoke/evaluation scope.
- The Docker backend image does not include Codex CLI. For the browser-triggered one-answer Codex smoke path, use the host-backend workflow in [`docs/CODEX_DEV_RUNTIME.md`](CODEX_DEV_RUNTIME.md).
- Never treat AI suggestions as final grades without teacher review.

## Verification workflow

With services already running and migrations applied:

```bash
make verify
```

`make verify` is intentionally non-destructive. It does not start or stop Docker, reset the database, clean volumes, or call real Codex. It runs backend health, frontend health, backend tests, and lint checks.

## XLSX export verification

During the demo, after at least one answer region has a reviewed final grade:

1. Use the assessment review page export link, or request the assessment export endpoint directly.
2. Open the downloaded `.xlsx` workbook.
3. Confirm the workbook includes reviewed final-grade fields and excludes unsafe internals such as raw provider JSON and password hashes.

## Shutdown

```bash
make down
```

## Troubleshooting

### Docker unavailable

- Symptom: `make up` cannot connect to Docker or reports the daemon is unavailable.
- Fix: start Docker Desktop/daemon, then rerun `make up` from the project root.

### Docker permission or socket error

- Symptom: permission denied on `/var/run/docker.sock` or Docker socket access.
- Fix: run from a shell with Docker access. On WSL, ensure Docker Desktop WSL integration is enabled and the current distro is integrated.

### PostgreSQL down

- Symptom: backend errors mention database connection refusal or unavailable PostgreSQL.
- Fix: run `docker compose ps`, then `make up` if services are missing. Recheck with `make health` after PostgreSQL is healthy.

### Migrations not applied

- Symptom: API/database errors mention missing tables or columns.
- Fix:

```bash
docker compose exec -T backend alembic upgrade head
make health
```

### Frontend cache issue after `next build`

- Symptom: after running `docker compose exec -T frontend npm run build`, immediate frontend health may return HTTP 500 because the dev container cache was affected by the production build.
- Fix:

```bash
docker compose restart frontend
make frontend-health
```

Wait briefly and rerun `make frontend-health` if the frontend is still starting.

### Codex auth issue

- Symptom: real Codex provider smoke fails because Codex CLI is not authenticated.
- Fix: do not use real Codex for the normal demo. Only troubleshoot Codex auth during a separately approved real-provider task.

### Context overload / stale agent session

- Symptom: Hermes session becomes overloaded, confused, or carries too much prior context.
- Fix: start a fresh Hermes session and provide a narrow `/goal` with the exact task scope and constraints.
