## TA-OPS-001 supervision record

TA-OPS-001 was executed in manual controlled mode as a docs/config-rules task while the founder was manually checking the already-running app. The running stack was not stopped, restarted, rebuilt, or modified.

It adds root `AGENTS.md`, `docs/HERMES_CODEX_OPERATING_CONTRACT.md`, `docs/HERMES_TASK_PROMPT_TEMPLATE.md`, and a non-active `.codex/config.example.toml` so future Hermes work is bounded by explicit goals, context, constraints, execution steps, done-when criteria, validation commands, final report format, and PM safety prohibitions.

No product behavior was changed. No autonomous loop was enabled. No VSCode/Codex workflow was used. No real Codex grading/mapping, provider/model call, batch grading, teacher observation, private-file use, `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` creation occurred. Future implementation prompts should use the new operating contract and template.

## TA-MANUAL-001A supervision record

TA-MANUAL-001A was executed in manual controlled mode as a docs/backlog-only task after the TA-MANUAL-001 synthetic founder smoke passed. It creates the founder manual evidence-to-queue checklist and records the safe testing boundary: demo/synthetic evidence-to-queue only, not real grading, not provider execution, not teacher observation, and not production/pilot use.

The documented runtime caveat is that browser registration/login in a Dockerized browser may hit the frontend `localhost` API URL issue. The TA-MANUAL-001 smoke used API-assisted setup and then verified the final workflow state in the browser. Founder manual testing should use the normal browser where possible; if setup blocks, the founder should report the blocker rather than bypassing silently.

No product code was changed. No autonomous loop was enabled. Real Codex, OpenAI, Claude, Gemini, provider execution, real AI mapping, real OCR/vision, batch grading, teacher observation, `GradeSuggestion`, `FinalGrade`, and provider `GradingJob` creation remain blocked.

## TA-GRADE-000 supervision record

TA-GRADE-000 was executed in manual controlled mode as a documentation/contract task. It defines the boundary for a future confirmed-packet-only grading queue and records that batch evidence preparation is still not grading.

No autonomous loop was enabled. TA-GRADE-001 implementation was not started. No grading was run. Real Codex was not run. No `GradeSuggestion`, `FinalGrade`, or `GradingJob` was created. No real AI mapping or real OCR/vision provider was implemented. Teacher observation was not started, and no private files were used.

## TA-BATCH-001A supervision record

TA-BATCH-001A was executed in manual controlled mode to harden batch evidence prep accounting and quarantine workflow. The important project-management result is that batch prep must account for every expected submission × canonical grading-unit packet, including missing evidence, before any grading queue is allowed.

The mixed-state fixture proves six expected slots from two submissions × three grading units and covers ready, missing answer region, unconfirmed, partial, blank, unresolved continuation, and missing-rubric blockers. Quarantine summaries expose correction targets so the teacher/founder can resolve evidence gaps without grading.

No autonomous loop was enabled. Real Codex was not run. Real AI mapping and real OCR/vision were not implemented. TA-GRADE-001 was not started. Batch grading and teacher observation were not started. Batch prep creates no `GradeSuggestion`, `FinalGrade`, `GradingJob`, or real Codex job.

## TA-UI-001A supervision record

TA-UI-001A was executed in manual controlled mode to harden evidence packet state before batch evidence preparation. Backend state now distinguishes unconfirmed, complete, partial, blank, continuation-not-needed, continuation-included/confirmed, blocked, and ready-for-grading through explicit packet fields and derived readiness gates. Correction operations update readiness consistently and preserve lightweight `AuditLog` records with correction type, before/after payload, teacher id, and timestamp.

No autonomous loop was enabled. Real Codex was not run. Real AI mapping and real OCR/vision remain blocked. TA-BATCH-001 and TA-MAP-004 were not started. No batch grading or teacher observation was started. Correction paths do not create `GradeSuggestion` or `FinalGrade`.

## TA-UI-001 supervision record

TA-UI-001 added a manual-controlled teacher correction workflow for accepted answer-region evidence. The workflow is explicitly evidence preparation, not grading. It supports segment bbox edit, add/split, removal with invariant checks, reorder, full-answer confirmation, continuation-not-needed confirmation, and partial/needs-review marking. Backend correction APIs require auth and teacher ownership; cross-assessment/cross-teacher corrections are rejected. Audit metadata is recorded through `AuditLog` with correction type, before/after payload, teacher id, and timestamp.

No autonomous loop was enabled. Real Codex was not run. Real AI mapping and real OCR/vision remain blocked. No batch grading or teacher observation was started. Correction paths do not create `GradeSuggestion` or `FinalGrade`.

# TA-CORE-002 current state — AEEM mapped to implementation roadmap

Recorded at: 2026-06-04T12:13:40+06:00
Baseline: `52bd4ffb0950d841a22e0bb721585b2faebb5daa` (`Adopt answer evidence extraction architecture`)

TA-CORE-002 creates the project-manager bridge document `docs/AEEM_IMPLEMENTATION_ROADMAP.md`. Use it to answer founder confusion about whether the project is implementing AEEM or continuing old TA-MAP work. The answer is: AEEM is the full north-star, and TA-MAP is now one controlled slice inside it.

Implementation philosophy recorded:

- implement AEEM in controlled slices, not one monolithic machine;
- evaluation harnesses before real AI/OCR providers;
- no real AI mapping before TA-MAP-003;
- no batch grading before evidence packet correctness is measurable;
- no grading quality claims unless question/solution/rubric/answer evidence is confirmed complete.

Recommended next task after TA-CORE-002: TA-MAP-003 — Mapping evaluation harness and synthetic benchmark. Do not start it automatically.

# TA-CORE-001 current state — AEEM adopted as pre-grading architecture

Recorded at: 2026-06-04T11:41:53+06:00
Baseline: `451b835776de6a1f535cd9929767676bbdaa3637` (`Add deterministic answer mapping provider`)

Founder/PM decision: adopt the Answer Evidence Extraction Machine as the north-star architecture for the pre-grading pipeline.

Core rule: no grading quality claim is valid unless the evidence is confirmed complete first. The system must confirm question, solution/model-answer, rubric, canonical grading unit, student page order, answer-region extraction, multi-page continuation grouping, and evidence packet readiness before grading is quality-evaluable.

Current direction:

- Do not build real AI mapping next.
- Do not build batch grading next.
- Do not tune grading prompts next.
- Build evidence-machine quality measurement first.
- AI/OCR may propose, but teacher/founder confirmation is required before grading until benchmark evidence proves a narrower safe automation boundary.
- High confidence means ready for teacher review, not auto-accepted, for real scripts.

Revised next task sequence:

1. TA-CORE-001: Adopt AEEM architecture and reset implementation sequence — Done when this docs/backlog commit lands.
2. TA-MAP-003: Mapping evaluation harness and synthetic benchmark.
3. TA-REF-001: Question/solution/rubric extraction evaluation harness.
4. TA-SCRIPT-001: Script page sequencing and answer-boundary benchmark.
5. TA-MAP-004: Real AI mapping provider behind evaluation gate.
6. TA-UI-001: Teacher correction workflow for split/merge/reorder/confirm.
7. TA-BATCH-001: Batch evidence packet preparation.
8. TA-GRADE-001: Question-wise grading queue from confirmed packets.

Manual controlled constraints remain active: no autonomous loop, no real Codex, no batch grading, no `GradeSuggestion`, no `FinalGrade`, no teacher observation, no private artifact commits, and no product code changes in TA-CORE-001.

# Project Supervision Context

## TA-MAP-002 current state — deterministic mapping prototype implemented

TA-MAP-002 moves the mapping subsystem from contract-only to a deterministic/mock provider prototype. The system can now propose draft multi-segment answer-region mapping groups and create real answer-region evidence only after explicit teacher/founder acceptance.

Current baseline after TA-MAP-002:

- HEAD after TA-MAP-002: commit message `Add deterministic answer mapping provider` (see git log for exact hash).
- TA-MAP-001R contract/design is complete at `746a59bcb5c650f92b5ed481611f32057d260911`.
- Deterministic/mock mapping suggestions are implemented for one submission/page set at a time.
- Suggestion groups include ordered segments, page-local boxes, confidence, warnings, continuation risk, needs-review flags, and teacher/founder confirmation requirements.
- Acceptance creates real `AnswerRegion` plus ordered `AnswerRegionSegment` rows only after explicit action.
- Evidence packets see accepted multi-segment regions through `segment_count`, `pages_covered`, `continuation_check_status`, and `teacher_founder_confirmed_full_answer`.
- Real AI mapping is not implemented yet.
- No real Codex, batch grading, autonomous loop, teacher observation, `GradeSuggestion`, or `FinalGrade` is created by the mapping suggestion/acceptance path.

Allowed next step after review: TA-MAP-003 real-provider planning only, if explicitly approved. Do not start real AI mapping, autonomous grading, batch grading, or teacher observation automatically.


## TA-W2-027 current state — controlled teacher workflow observation may be prepared

TA-W2-026 plus the controlled `1(b)(i)` multi-segment retest changed the project state: a safe in-person teacher workflow observation can be prepared, but only as a manual controlled observation.

Current baseline:

- HEAD: `5c0d5c6c26c1bf134f68bc50b31c097a084d3e82` (`Add multi-segment answer evidence gate`).
- Multi-segment evidence gate is implemented and validated.
- `1(b)(i)` was retested with page 3 + page 4 continuation segments, full-answer confirmation, and `multi_segment_composite` context.
- Real Codex draft score: `6/6`; founder fair score: `6/6`; confidence: `0.88`; `needs_review=true`; `FinalGrade` count: `0`.
- The earlier `4/6` result is classified as evidence-boundary failure, not confirmed model-quality failure.

Allowed next step: prepare a controlled teacher workflow observation plan. This is not a teacher pilot, not full batch grading, not fully automated grading, and not a public/product accuracy claim.

Required framing:

- early controlled prototype;
- AI draft marking assistant;
- teacher review required;
- evidence packet and full-answer confirmation are central;
- AI suggestions remain draft-only until teacher approval/edit;
- no autonomous loop;
- no new real Codex calls unless explicitly approved during the observation plan;
- no batch grading;
- no auto-finalization.


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
- Pre-grading evidence packet/readiness endpoint exists and is reused as a grading gate before provider/job execution.
- Multi-segment answer evidence exists: one logical `AnswerRegion` can have ordered `AnswerRegionSegment` crops, and grading can use a composite context image when multiple confirmed segments are present.
- Canonical grading-unit labels such as `1(a)(i)` are supported through flat Question rows and must be confirmed with max marks before real grading.
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
- Handwritten math grading remains quality-gated. The latest `1(b)(i)` `4/6` result is invalid as a quality benchmark because the answer evidence was incomplete: the app graded only page 3 while the answer continued on page 4 before `1(b)(ii)`.
- E2E smoke coverage is too thin.
- Mode gating / ghost-mode clarity still needs hardening.
- Privacy baseline documentation and an owner-only assessment test-data deletion endpoint now exist for internal/founder testing.
- Codex CLI is useful for internal validation, but it is not the scalable production runtime.
- Broad real-document validation is not yet approved.
- TA-W2-022B founder real-document grading rehearsal is invalidated for quality evaluation because canonical question labels/max marks were wrong or ambiguous.
- TA-W2-022D corrected canonical-unit rehearsal worked technically but showed Codex under-crediting near-correct handwritten Bayes/statistics work (`1(b)(i)` scored 3/6 vs founder fair 6/6).
- TA-W2-024/025 improved crop context and evidence readiness, but the later page-4 continuation finding reclassifies the latest `1(b)(i)` result as an evidence-completeness failure rather than proof of model under-crediting.
- TA-W2-025 adds an evidence-first grading gate: exact question, solution/model answer, rubric, and answer mapping must be confirmed before real grading is quality-evaluable.
- TA-W2-026 adds multi-segment evidence and a page-bottom continuation gate. Teacher observation remains blocked until the full page 3 + page 4 `1(b)(i)` evidence path is validated.
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
- TA-W2-020: Playwright E2E smoke suite — completed and validated.
- Minimum tests: auth, Custom Controlled mock flow, and no-FinalGrade-before-approval.
- Coverage now includes a browser-only auth smoke, a Custom Controlled mock grading smoke, and an explicit approval-gating assertion.

### Day 4
- TA-W2-021: mode gating / ghost-mode clarity — completed and validated.
- Semi-Automated is blocked by default and hidden from the normal teacher flow.
- Fully Automated is explicitly rejected as not ready.

### Day 5
- TA-W2-022A privacy baseline — completed and validated.
- Added `docs/PRIVACY_BASELINE.md`, expanded artifact ignore rules, and added authenticated `DELETE /assessments/{assessment_id}/test-data` for owner-only test-data cleanup.
- This is an internal/local safety baseline only, not production compliance.

### Day 6
- Founder real-document controlled evaluation.
- Requires explicit founder approval for the exact private documents/pages/regions.

### Day 7
- TA-W2-022C: canonical grading-unit confirmation before any real grading retest.
- Optional follow-up hardening based on founder rehearsal findings.
- Limit to 3–5 selected pages/regions only.
- No batch.
- Compare against known marks.

## Next task sequence
1. TA-W2-019: Marking policy calibration fix
2. TA-W2-020: Playwright E2E smoke suite
3. TA-W2-021: Mode gating / ghost-mode clarity
4. TA-W2-022A: Privacy baseline documentation and deletion endpoint — completed
5. TA-W2-022C: canonical grading-unit confirmation — completed
6. TA-W2-022D: corrected founder real-document retest — technically successful, grading-quality blocked
7. TA-W2-023: handwritten math/stat prompt grounding — completed
8. TA-W2-024: crop/context audit and padded grading context — completed, grading-quality blocked
9. TA-W2-025: pre-grading evidence packet gate — completed
10. TA-W2-026: multi-segment answer evidence and continuation gate — completed; rerun `1(b)(i)` only after page 3 + page 4 continuation segments are confirmed

## Gates before teacher pilot
- Marking policy calibration shows expected ordering/deltas and handwritten math/stat prompt grounding is verified synthetically.
- E2E smoke coverage passes for auth and core custom-controlled flow.
- Mode naming and gating are not misleading.
- Privacy baseline is documented and deletion behavior exists for internal/local assessment test data.
- Canonical grading units are confirmed with label, max marks, active rubric, and unit type before real grading.
- Evidence packet readiness is green for the exact bounded grading unit before real grading: confirmed question, solution/model answer, rubric, and complete student-answer mapping, including all required page segments.
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
## TA-MAP-003 status — mapping evaluation harness

TA-MAP-003 is Done as an evaluation-first implementation. It adds `apps/api/packages/evaluation/answer_mapping_evaluator.py`, seven synthetic JSON benchmark fixtures, and focused tests. It does not use VSCode/Codex, real Codex, real OCR, real AI mapping, private files, batch grading, teacher observation, `GradeSuggestion`, or `FinalGrade`.

The benchmark result is intentionally conservative: current mock-provider saved outputs pass 3/7 cases and fail realistic gaps such as multi-question page confusion, wrong-question trap detection, and blank/low-content page handling. This is not a product-quality claim; it is the first executable gate before TA-MAP-004 can be planned.
## TA-MAP-003A status — mapping quality gates

TA-MAP-003A is Done as a policy layer over the synthetic mapping evaluator. It defines critical blockers, reviewable warnings, minimum synthetic gates, and aspirational later real-anonymized evaluation targets. The current mock provider remains ineligible for real-provider trial as product-quality mapping.

Critical blockers are not nice-to-fix issues: wrong-question/CGU assignment, blank-page confident mapping, missed continuation, unsafe auto-accept, and any `GradeSuggestion`/`FinalGrade` creation during mapping block provider advancement. Real AI mapping remains blocked until a candidate provider satisfies the gate and the founder explicitly approves the next scope.

## TA-REF-001 status — reference extraction evaluation harness

TA-REF-001 is Done as an evaluation-first synthetic harness for the AEEM reference arm. It measures canonical grading-unit labels, max marks, parent/child structure, question text, solution/model-answer mapping, rubric criteria, rubric total validation, duplicate labels, missing solutions, visual-confirmation requirements, unsafe auto-confirm, and grading/finalization side effects.

Real OCR/vision reference extraction remains blocked. Wrong reference extraction poisons both mapping and grading, so no mapping or grading quality claim should be made unless the reference side is measurable and teacher-confirmed. TA-MAP-004 remains not started.


## TA-SCRIPT-001 status — script page sequencing and answer-boundary benchmark

TA-SCRIPT-001 is Done as an evaluation-first harness over synthetic/non-private script-processing fixtures. It measures ordered/reversed pages, missing pages, duplicate pages, blank/cover pages, single-page boundaries, multi-question same-page boundaries, near-bottom continuations, near-bottom complete answers, and ambiguous low-confidence boundaries.

Real OCR/vision sequencing, real AI mapping, TA-MAP-004 implementation, Codex, private files, grading, batch grading, teacher observation, `GradeSuggestion`, and `FinalGrade` remain blocked/out of scope. Script sequencing and answer-boundary detection must be measurable before real mapping providers or batch evidence packet preparation.

## TA-BATCH-001 supervision note

TA-BATCH-001 is evidence preparation only. It may create `BatchEvidencePrepRun` metadata and compute evidence-readiness summaries. It must not create `GradeSuggestion`, must not create `FinalGrade`, must not start batch grading, must not run real Codex, and must not invoke real AI/OCR providers.

Current quarantine policy blocks packets for unknown page order, no mapped region/segment, unconfirmed/partial/blank packet status, unconfirmed possible continuation, missing active rubric, invalid segment order, and missing crop/context. The UI warning must continue saying evidence preparation does not grade.


## TA-GRADE-001 supervision record

TA-GRADE-001 was executed in manual controlled mode. The accepted TA-GRADE-000 contract is now represented by scaffold queue records and endpoints. The implementation deliberately stops at queue creation: no grading execution, no real Codex/provider calls, no `GradeSuggestion`, no `FinalGrade`, no existing provider `GradingJob`, no auto-finalization, no teacher observation, and no private files. Batch evidence prep remains separate from grading.


## TA-GRADE-001A supervision record

TA-GRADE-001A was executed in manual controlled mode. It hardens the queue scaffold only: no grading, no provider/model call, no real Codex, no `GradeSuggestion`, no `FinalGrade`, no provider `GradingJob`, no batch grading execution, no real AI mapping, no real OCR/vision provider, no teacher observation, no private files, and no additional coding agent.
