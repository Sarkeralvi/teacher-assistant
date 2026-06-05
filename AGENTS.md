# TAAgent / Answer Evidence Extraction Machine — Agent Operating Rules

This repository is the TAAgent project implementing the Answer Evidence Extraction Machine (AEEM): a teacher-controlled evidence preparation and grading-assistance workflow.

## Core product principles

- Evidence first, grading last: confirm question, solution/model answer, rubric, canonical grading unit, page order, answer-region extraction, continuation state, and packet readiness before any grading-quality claim.
- Teacher final authority: AI/provider output, when explicitly approved, is draft assistance only.
- No auto-finalization: never create or imply final grades without explicit teacher review/approval.
- No provider/model calls unless the active task explicitly approves them.
- No real Codex grading or mapping unless the active task explicitly approves the exact bounded call scope.
- No private files, PDFs, images, crops, screenshots, exports, secrets, or student artifacts may be committed.
- No VSCode/Codex workflow. Use repo-local Hermes/tool execution only unless the founder explicitly changes the operating mode.
- No autonomous loop. Every task is manual controlled mode unless the founder explicitly approves otherwise.

## Engineering rules

- Detect and work from the repo root before changing files.
- Check `git status --short` and the expected baseline HEAD before implementation.
- Refuse to proceed on unrelated dirty worktree state unless the founder approves how to handle it.
- Keep changes scoped and minimal to the task prompt.
- Do not change application behavior during docs/config-rules tasks.
- Prefer tests/checks over assumptions.
- Run the validation commands named in the task prompt.
- Do not stop, restart, rebuild, or modify a running app stack unless the task explicitly allows it.
- Do not run package installs, network-heavy actions, provider calls, or extra agents unless explicitly approved.

## Required task shape

Future implementation prompts should be bounded engineering tasks, not vague chat requests. Each task should provide:

- Goal
- Context
- Constraints
- Execution steps
- Done when
- Validation commands
- Final report format
- PM safety prohibitions

Use `docs/HERMES_TASK_PROMPT_TEMPLATE.md` for reusable prompt structure and `docs/HERMES_CODEX_OPERATING_CONTRACT.md` for the full operating contract.

## Required final report format

Every implementation/reporting task should end with:

1. Summary
2. Files changed
3. Tests/checks run
4. Safety confirmations
5. Risks/follow-ups
6. Commit hash
7. Final git status
