# Teacher Assistant / AEEM - Claude Working Guide

This repository is handed to Claude for ongoing development and problem solving.

Before taking action, read these files in order:

1. `AGENTS.md` - binding product, safety, engineering, and reporting rules.
2. `docs/decisions/2026-11-07-claude-api.md` - the v2 direction: Claude (Anthropic API) as the production model, and what it changes.
3. `docs/CLAUDE_HANDOFF_2026-08-31.md` - v1 state, recent fixes, known issues, and commands (historical where the decision record differs).
4. `docs/REPOSITORY_OVERVIEW.md` - repository structure, architecture, and full project status.
5. `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md` - the supported local Windows runtime.
6. `docs/FOUNDER_PILOT_REHEARSAL.md` - mandatory sequence for any founder-supervised rehearsal.

## Non-negotiable operating constraints

- Work from the repository root and check `git status --short` before changing anything.
- This is a teacher-controlled, evidence-first system. Provider output is draft-only.
- Never create or imply a final grade without explicit teacher approval.
- Do not make a provider/model call, upload, deletion, batch run, or real grading call unless the user explicitly authorizes its exact bounded scope.
- Never commit `.env.local-ai`, `.local-ai/`, `data/`, uploaded PDFs/images, secrets, model files, exports, or private/student artifacts.
- Keep `COHORT_MODEL_GRADING_ENABLED=false` unless the user explicitly authorizes the separately documented evaluation gate.
- Use the supported pilot scripts; do not launch an ad-hoc Uvicorn process because it can use a different storage root and make uploaded references unavailable.
- Do not start, stop, or rebuild the stack unless the user has requested that operational action.

## Current objective (v2, from 2026-11-07)

Turn the system into a one-click local app that uses Claude (Anthropic API) as the production model, in the phases of the approved v2 plan, on branch `v2/claude`:

1. Claude provider plus a smoke eval against the founder's two marked scripts.
2. Delete the local-model machinery (Qwen, GPU lease and phases, OCR stacks, unused orchestrators and settings).
3. One pipeline for any number of scripts, one combined teacher review, and parallel durable jobs.
4. A new review-centric teacher UI with calibration (blind marking) mode.
5. Local production hardening: launcher, backups, crash recovery, cost caps.
6. The first real exam run in calibration mode, which sets the trust policy.

Agent-initiated paid API calls need a cost estimate and the founder's OK. Trust in AI marks comes only from measured agreement with the teacher's own marks.

v1 objective (historical): a founder-supervised synthetic rehearsal with one local Qwen draft grade, gated by a teacher-signed 20-case curated `PASS`.

## Required final report

End implementation or investigation tasks with:

1. Summary
2. Files changed
3. Tests/checks run
4. Safety confirmations
5. Risks/follow-ups
6. Commit hash
7. Final git status
