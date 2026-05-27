# Week 1 Checkpoint

## Current completed capabilities

- Project scaffold exists for a Next.js frontend, FastAPI backend, PostgreSQL, Redis-ready cache/queue layer, local storage, and Brain Adapter AI boundary.
- Core academic workflow exists for dev teacher/user placeholder, courses, assessments, questions, and rubric creation/validation.
- Submission workflow supports image/PDF upload, generated page metadata, page image serving, and manual answer-region crop creation.
- Grading workflow supports structured GradeSuggestion creation through the Brain Adapter with mock default, OpenAI-compatible provider support, and Codex CLI provider support behind the adapter.
- Teacher review workflow supports review queue states, approve/edit/reject actions, current FinalGrade records, and audit logging for review actions.
- Assessment summary and safe XLSX final-grade export exist.
- Demo/developer workflow now has `docs/DEMO_RUNBOOK.md` and a non-destructive `make verify` target.

## Current limitations

- Authentication is not implemented; teacher identity remains a dev/manual placeholder.
- No student portal, payment/subscription flow, or production authorization model exists.
- No batch grading workflow exists.
- No automatic OCR or answer-region detection exists.
- Answer-region mapping is manual and coordinate-based.
- Real-provider grading quality is not established; existing real-provider work is limited to controlled smoke/evaluation checks.
- UI is functional but still minimal and not polished for a smooth product demo.

## Verified vertical slice status

The Week-1 vertical slice has been verified with synthetic non-student data and the mock provider:

1. Dev teacher/user setup.
2. Course creation.
3. Assessment creation.
4. Question and rubric setup.
5. Submission upload.
6. Page image serving.
7. Manual answer-region crop creation.
8. Mock GradeSuggestion creation.
9. Teacher approval into FinalGrade.
10. Assessment summary readback.
11. XLSX final-grade export verification.

The recorded TA-W1-019 validation used zero real Codex calls and exactly one mock grading call.

## Known technical issues

- Running `next build` inside the frontend dev Docker container can poison the dev cache and make immediate frontend health return HTTP 500.
- The documented recovery is to restart the frontend container and rerun `make frontend-health` after a short wait.
- Next build still emits an existing ESLint flat-config warning, but exits successfully.
- Backend health can briefly fail during container startup before the service is ready.
- `make verify` assumes services are already running and migrations have already been applied.

## Test / verification status

Latest documented verification from TA-W1-020:

- `make up`: passed.
- `docker compose exec -T backend alembic upgrade head`: passed.
- `make health`: passed after transient startup retry.
- `make frontend-health`: passed.
- `make verify`: passed.
- Backend tests: `77 passed`.
- Ruff: passed.
- Frontend typecheck/lint: passed.
- Frontend build: passed with existing ESLint warning.
- Post-build frontend health required frontend restart, then passed.
- `make down`: passed.
- Final git status was clean after commit.

## Next 3 track options

### A. Demo/UI polish

Improve the existing browser demo path without changing the core architecture. Focus on clearer navigation, better assessment/review screens, visible mock-provider safety labels, smoother answer-region/review/export flow, and fewer demo rough edges.

### B. Auth and teacher identity

Replace dev teacher placeholders with real teacher identity/session behavior. This would require ownership checks, endpoint protection, frontend session handling, and removal of manual teacher inputs.

### C. Batch grading/review improvements

Add multi-answer-region grading and review controls. This would require batch status tracking, progress/error handling, stricter provider guardrails, and careful separation between mock batch flow and any real-provider use.

## Decision

Choose **Demo/UI polish** first.

## Reason for decision

The Week-1 vertical slice already works end to end, but the product is still rough to demonstrate. Demo/UI polish gives the fastest practical improvement with the lowest architectural risk. Auth is important but cross-cutting, and batch grading is higher-risk before the single-teacher demo flow is smooth and clear. Keeping the next task mock-provider-only also preserves safety and avoids accidental real Codex grading.

## Proposed next task

TASK-ID: TA-W1-022
Title: Demo UI polish for Week-1 vertical slice
Owner: Hermes
Priority: P0
Dependencies: TA-W1-021
Goal: Improve the existing mock-provider teacher demo flow without adding auth, real Codex grading, student portal, payment, or batch grading.
Likely files affected: frontend assessment/course/review components, frontend workflow tests, BACKLOG.md, and possibly demo runbook notes.
Acceptance criteria: Browser demo is clearer, mock/provider safety is visible, review/export path is easier to follow, and existing tests/lint/build pass.
Status: Pending
