# Hermes Task Prompt Template

Use this reusable template for future TAAgent / AEEM implementation tasks. Replace every `{{placeholder}}` before sending the task.

```markdown
Proceed to {{task_id}}: {{goal}}

Manual controlled mode only.
Do not enable autonomous loop.
Do not use VSCode/Codex unless explicitly approved below.
Do not run provider/model calls unless explicitly approved below.
Do not use private files unless explicitly approved below.

Repo:
`{{repo_path}}`

Expected HEAD:
`{{baseline_head}}`

Relevant files:
{{relevant_files}}

## Goal

{{goal}}

## Context

{{context}}

## Constraints

{{constraints}}

Minimum project safety constraints unless explicitly overridden:

- Evidence first, grading last.
- Teacher remains final authority.
- No auto-finalization.
- No real Codex grading/mapping unless this task explicitly approves the exact bounded call scope.
- No provider/model calls unless this task explicitly approves them.
- No `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` creation unless explicitly approved.
- No batch grading unless explicitly approved.
- No teacher observation unless explicitly approved.
- No private files committed.
- No autonomous loop.
- No unrelated dirty worktree changes.
- Do not stop/restart/rebuild/modify a running app stack unless explicitly allowed.

## Execution

1. `cd {{repo_path}}`
2. Run preflight:
   ```bash
   git status --short
   git rev-parse HEAD
   ```
3. Confirm HEAD matches `{{baseline_head}}` and worktree state is acceptable.
4. Inspect only relevant files.
5. Make the smallest scoped change needed for `{{task_id}}`.
6. Do not expand into product features or unrelated cleanup.
7. Run validation commands exactly.
8. If checks fail, perform at most one focused repair cycle unless instructed otherwise.
9. Stage only the approved files.
10. Commit only if checks pass and the task asks for a commit.

## Done when

{{done_when}}

## Validation commands

```bash
{{validation_commands}}
```

## Final report format

Report:

- Summary.
- Files changed.
- Tests/checks run.
- Safety confirmations.
- Risks/follow-ups.
- Commit hash.
- Final git status.

Also explicitly confirm:

- Whether product code changed.
- Whether provider/model calls happened.
- Whether any `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` was created.
- Whether the running app stack was stopped/restarted/rebuilt/modified.
```
