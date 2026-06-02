# Project Supervision Context

## Purpose
This document is the durable supervision handoff for the Teacher Assistant project. It is meant for a future supervising LLM or maintainer who needs the current product direction, non-negotiables, validation history, and next-step sequencing without re-deriving the entire project.

## Product vision
Build a teacher-controlled grading workflow that moves from uploaded scripts to AI-assisted answer-region suggestions, teacher correction/confirmation, region grading, teacher review/finalization, and export.

The intended end state is:

1. Upload scripts / answer pages.
2. AI suggests answer regions.
3. Teacher confirms or corrects the suggestions.
4. Accepted regions are graded.
5. Teacher reviews and finalizes.
6. Export happens only after teacher authority is preserved.

Manual mapping remains a fallback/debug/scaffold path, not the final teacher experience.

## Founder non-negotiables
- Teacher remains final authority.
- No auto-finalization.
- No autonomous Hermes loop.
- No batch real Codex without explicit approval.
- No private data, exports, PDFs, crops, screenshots, or artifacts committed to git.
- No hidden or misleading “ready” modes.
- Real AI actions must stay explicit, gated, logged, and review-required.
- Manual controlled mode only unless the founder explicitly approves a broader run.
- Do not silently expand scope beyond the active task.

## Current working capabilities
- Teacher auth/login exists.
- Course / assessment / question / rubric workflow exists.
- Submission upload and page extraction exist.
- Manual answer-region creation exists.
- Mock grading exists.
- Codex-backed answer-region suggestions exist behind an explicit gate.
- Browser-backend Codex dev grading smoke exists behind explicit gate.
- Teacher review / finalization / export flows exist.
- Batch mock grading exists.
- Selected batch approval exists.
- Evaluation harnesses exist for question import and grading-related flows.

## Real Codex validations completed
### TA-W2-016A
- One controlled real Codex grading call was validated against a single selected answer region.
- `make codex-ok` required `CODEX_CLI_MODEL=gpt-5.5` under the current ChatGPT-backed login; the default `gpt-5.3-codex` was rejected.
- Host backend ran with Codex dev flags.
- Exactly one real grading call was run.
- A `GradeSuggestion` was created with `model_provider=codex_cli`.
- `needs_review=true` was preserved.
- `image_input_used` was recorded.
- No `FinalGrade` was created.
- No auto-finalization occurred.

### TA-W2-018A
- Real Codex answer-region suggestion smoke succeeded only when `CODEX_CLI_MODEL=gpt-5.5` was explicitly set.
- Call count: 2 real Codex suggestion attempts total.
- Attempt 1: direct provider call on a blank synthetic page; success, but no suggestions were returned because the page was blank.
- Attempt 2: API smoke on a synthetic page with one bordered answer area; success.
- Provider: `codex_cli_answer_region_suggester`.
- Suggestion count: 1.
- `needs_review=true`.
- Confidence: `0.96`.
- The suggestion remained draft-only.
- No `AnswerRegion` was auto-created.
- No `GradeSuggestion` was created by the suggestion endpoint.
- No `FinalGrade` was created by the suggestion endpoint.
- Root cause of the earlier failure was runtime model selection, not provider code.
- The default `gpt-5.3-codex` is rejected under the current ChatGPT-backed Codex login.

## What is not ready
- Manual answer-region mapping is not the final teacher workflow.
- Marking policy calibration is still weak and needs a proper fix.
- E2E smoke coverage is too thin.
- Mode gating / ghost-mode clarity still needs hardening.
- Privacy baseline documentation and deletion support are incomplete.
- Codex CLI is useful for internal validation, but it is not the scalable production runtime.
- Broad real-document validation is not yet approved.
- Batch real Codex remains out of scope.

## Expert-review synthesis
The expert reviews were mostly right on the big points:
- Stabilize Custom Controlled mode first.
- Fix marking policy calibration.
- Increase validation depth and add E2E smoke coverage.
- Treat Codex CLI as a validation tool, not a production-scale runtime.
- Improve privacy controls; current privacy handling is policy-heavy and still technically weak.
- Manual answer-region mapping cannot remain the final teacher experience.

Important correction from later validation:
- TA-W2-018A proved that real Codex answer-region suggestions can work in this environment when the runtime model is explicitly set to a supported value (`gpt-5.5`).
- That does **not** mean the product is ready for broad real-mode use.
- It only means the runtime blocker was understood and isolated.

## One-week recovery plan
### Day 1
- Record TA-W2-018A and the expert-review-adjusted project context.
- Keep automation disabled.
- Keep scope documentation current.

### Day 2
- TA-W2-019: marking policy calibration fix.
- Acceptance: same synthetic answer plus same rubric should produce `tough < general < easy` with meaningful deltas.

### Day 3
- TA-W2-020: Playwright E2E smoke suite.
- Minimum tests: auth, Custom Controlled mock flow, and no-FinalGrade-before-approval.

### Day 4
- Codex runtime/model hardening and/or TA-W2-021 mode gating.
- Ensure unsupported Codex models fail clearly.
- Ensure non-ready modes are not misleading.

### Day 5
- Core AI loop synthetic validation.
- Validate the sequence: Codex suggests region → teacher accepts → Codex grades accepted region → no auto-finalization → export.

### Day 6
- TA-W2-022A privacy baseline.
- Add privacy README guidance, deletion endpoint, ignore artifacts, and storage warnings.

### Day 7
- Founder real-document controlled evaluation.
- Limit to 3–5 selected pages/regions only.
- No batch.
- Compare against known marks.

## Next task sequence
1. TA-W2-019: Marking policy calibration fix
2. TA-W2-020: Playwright E2E smoke suite
3. TA-W2-021: Mode gating / ghost-mode clarity
4. TA-W2-022A: Privacy baseline documentation and deletion endpoint
5. Controlled founder real-document AI loop validation

## Gates before teacher pilot
- Marking policy calibration shows the expected ordering and usable deltas.
- E2E smoke coverage passes for auth and core custom-controlled flow.
- Mode naming and gating are not misleading.
- Privacy baseline is documented and deletion behavior exists.
- No auto-finalization is possible.
- Teacher approval remains required for finalization.
- Draft suggestions and grading suggestions remain review-required.
- No batch real Codex path is enabled without approval.
- The team can explain exactly which modes are experimental, disabled, or ready.

## Safety invariants
- No autonomous Hermes loop.
- No auto-finalization.
- Teacher final authority.
- No batch real Codex without approval.
- No private data without anonymization or explicit approval.
- No hidden product behavior changes.
- Suggestions remain draft-only until teacher action.
- Unsupported runtime settings must fail clearly rather than silently degrading.

## Supervision operating notes
- Start by checking `BACKLOG.md`, `docs/VALIDATION_LOG.md`, and `docs/CODEX_DEV_RUNTIME.md`.
- Treat this document as the project memory for the next supervisor.
- If a future task needs implementation, ensure it is a single, bounded task with explicit acceptance criteria.
- If a task is docs-only, do not expand it into product work.
- If a task requires real Codex, use the smallest safe validation possible and keep the call count bounded.
