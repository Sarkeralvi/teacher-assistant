# Hermes/Codex Operating Contract

This contract governs how Hermes should run engineering work in the TAAgent / Answer Evidence Extraction Machine repository.

It is intentionally conservative. The project is evidence-first and teacher-controlled. Hermes should execute bounded tasks with explicit validation, not open-ended autonomous work.

## 1. Hermes preflight

Before changing files, Hermes must:

1. Detect the repository root.
2. Run `git status --short`.
3. Run `git rev-parse HEAD` and compare it with the task's expected baseline.
4. Refuse unrelated dirty worktree state unless the founder approves exactly how to proceed.
5. Identify the task scope and allowed files.
6. Confirm whether the running app stack may be touched. If the task does not explicitly allow it, do not stop, restart, rebuild, or modify running containers/processes.
7. Confirm whether provider/model calls are explicitly approved. If not, provider/model calls are forbidden.

If preflight does not match the task prompt, stop and report. Do not repair by guessing.

## 2. Required Hermes task prompt structure

Every future implementation task should include these sections:

- **Goal** — the specific outcome.
- **Context** — current baseline, relevant prior decisions, runtime state, and why this task exists.
- **Constraints** — prohibitions and boundaries.
- **Execution** — ordered steps and allowed files.
- **Done when** — concrete acceptance criteria.
- **Checks** — exact validation commands.
- **Final report** — required reporting fields.

Use `docs/HERMES_TASK_PROMPT_TEMPLATE.md` as the default reusable template.

## 3. Safe Codex CLI pattern, if Hermes is explicitly allowed to use Codex CLI internally

Codex CLI is not the normal workflow for this repository. If a future founder-approved task explicitly allows Hermes to use Codex CLI internally, Hermes must follow these rules:

1. Run from the repository root.
2. Keep the workspace scoped to the task files.
3. Do not use `--yolo`, unsafe auto-approval, or broad filesystem access.
4. Do not use unbounded network/package installs.
5. Record the model selection explicitly if a model is needed.
6. Record the approval policy and sandbox policy in the task report.
7. Never use Codex CLI for product grading/mapping unless the task explicitly approves a bounded real Codex grading/mapping call.
8. Never use private files or student artifacts in Codex prompts unless the founder explicitly approves the exact private-file scope.

A non-active example config may live at `.codex/config.example.toml`. Do not create active `.codex/config.toml` unless explicitly instructed.

## 4. Validation loop

For implementation tasks, Hermes should use this loop:

1. Inspect only the relevant files and docs.
2. Plan briefly.
3. Implement the smallest safe change.
4. Run the task's required checks.
5. If checks fail, perform at most one focused repair cycle unless the founder authorizes more.
6. Summarize the diff and validation evidence.

For docs/config-rules tasks, do not expand into product behavior changes.

## 5. Postflight

Before reporting or committing, Hermes must run the task's requested postflight checks. Default postflight for docs/config-rules tasks is:

```bash
git status --short
git diff --check
make lint  # only when explicitly requested and safe for the running app
# final
git status --short
```

For product-code tasks, add focused tests, relevant backend/frontend checks, lint/typecheck, and any task-specific validation.

Do not stop, restart, rebuild, or otherwise modify the runtime unless the task explicitly permits it.

## 6. Forbidden unless explicitly approved

The following are forbidden by default:

- Provider/model calls.
- Real Codex grading.
- Real Codex mapping.
- Batch grading.
- Teacher observation.
- Private student data or private files.
- Additional coding agents.
- VSCode/Codex workflow.
- Autonomous loop.
- Auto-finalization.
- Creating `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` rows outside a task that explicitly approves those exact side effects.
- Hidden changes to product behavior during docs/config-rules tasks.

## 7. Reporting standard

The final report must include:

- Summary.
- Files changed.
- Tests/checks run.
- Safety confirmations.
- Risks/follow-ups.
- Commit hash, if committed.
- Final git status.

If the task modifies docs/config-rules only, the report must explicitly say no product code changed and whether the app stack was untouched.
