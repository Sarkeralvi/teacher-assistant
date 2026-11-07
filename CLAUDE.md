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

## Current objective: v1 is frozen (from 2026-11-07)

The founder decided that **nothing in v1 is deleted**. v2 is a completely new, separate system in `E:\teacher-assistant-v2` (its own repository, database, ports and desktop icon). This repository stays as v1, runnable as it is:

- Branch `v2/claude` is **v1 with Claude added** (provider, grade checks, smoke-eval runner), not the new system. Until v2 can grade a real exam, real work runs here with Claude.
- Allowed here: fixes, and running `docs/CLAUDE_SMOKE_EVAL.md`. Not allowed: deleting the local-model code or restructuring v1 (the earlier "Phase 2 delete" plan is cancelled).
- Agent-initiated paid API calls need a cost estimate and the founder's OK. Trust in AI marks comes only from measured agreement with the teacher's own marks.

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
