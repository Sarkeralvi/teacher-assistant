# Teacher Assistant / AEEM - Claude Working Guide

This repository is handed to Claude for ongoing development and problem solving.

Before taking action, read these files in order:

1. `AGENTS.md` - binding product, safety, engineering, and reporting rules.
2. `docs/CLAUDE_HANDOFF_2026-08-31.md` - current state, recent fixes, known issues, and commands.
3. `docs/REPOSITORY_OVERVIEW.md` - repository structure, architecture, and full project status.
4. `docs/WINDOWS_TEACHER_PILOT_RUNTIME.md` - the supported local Windows runtime.
5. `docs/FOUNDER_PILOT_REHEARSAL.md` - mandatory sequence for any founder-supervised rehearsal.

## Non-negotiable operating constraints

- Work from the repository root and check `git status --short` before changing anything.
- This is a teacher-controlled, evidence-first system. Provider output is draft-only.
- Never create or imply a final grade without explicit teacher approval.
- Do not make a provider/model call, upload, deletion, batch run, or real grading call unless the user explicitly authorizes its exact bounded scope.
- Never commit `.env.local-ai`, `.local-ai/`, `data/`, uploaded PDFs/images, secrets, model files, exports, or private/student artifacts.
- Keep `COHORT_MODEL_GRADING_ENABLED=false` unless the user explicitly authorizes the separately documented evaluation gate.
- Use the supported pilot scripts; do not launch an ad-hoc Uvicorn process because it can use a different storage root and make uploaded references unavailable.
- Do not start, stop, or rebuild the stack unless the user has requested that operational action.

## Current objective

Make the local Custom Controlled workflow reliable for a founder-supervised, synthetic one-packet rehearsal:

`reference materials -> teacher-confirmed drafts -> synthetic script -> confirmed answer evidence -> one local Qwen draft grade -> teacher review -> optional approval/export`

The reference-extraction latency/failure path is resolved. The two remaining gates are a runnable, teacher-signed 20-case curated quality `PASS` and one completed end-to-end supervised rehearsal. Neither can be substituted by more engineering. Read the handoff before any provider call.

## Required final report

End implementation or investigation tasks with:

1. Summary
2. Files changed
3. Tests/checks run
4. Safety confirmations
5. Risks/follow-ups
6. Commit hash
7. Final git status
