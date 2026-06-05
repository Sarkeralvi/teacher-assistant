# TA-UX-001 — Founder Evidence Workflow V0

- Recorded at: 2026-06-05
- Baseline commit: `a9c11b62e72309372c9061e2e6afceb7d31c22c5`
- Workflow type: manual controlled V0/V0.5 UX clarity task
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Provider/model calls: 0
- Real Codex grading/mapping: not run
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created: 0
- FinalGrade created: 0
- GradingJob created: 0
- Private files/artifacts used: no

## Change made

TA-UX-001 clarifies the assessment page as the current Founder Evidence Workflow. The page now shows the evidence-only safety banner, ordered Step 0–7 guide, grouped student script upload/list sections, Step 4 answer evidence mapping, Step 5/6 evidence readiness/prep warnings, Step 7 queue scaffold warnings, and a hard STOP after queue scaffold. It labels Custom Controlled as legacy/internal material-upload navigation for Step 1 and labels review/export/semi-automated/grading surfaces as FUTURE/out-of-scope for the founder evidence-to-queue test.

## Safety result

This is UX clarity only. It does not change grading logic, run grading, call providers, enable real AI mapping/OCR, start teacher observation, or create grading/finalization rows. Queue records remain not grades.

## Checks run

To be completed by the TA-UX-001 commit gate: `git status --short`, frontend static workflow test, `make lint`, `cd apps/web && npm run build`, `make test` if backend touched, `make e2e` if stack is available, `git diff --check`, final `git status --short`.

# TA-OPS-001 — Hermes/Codex operating contract

- Recorded at: 2026-06-05
- Baseline commit: `e3b7d9bcacfff5ec437d4dd291a372ee9a77d503`
- Workflow type: manual controlled docs/config-rules task
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Provider/model calls: 0
- Real Codex grading/mapping: not run
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created: 0
- FinalGrade created: 0
- GradingJob created: 0
- Private files/artifacts used: no
- Running app stack stopped/restarted/rebuilt/modified: no

## Change made

TA-OPS-001 adds stable repo-level agent instructions and a reusable task prompt contract: root `AGENTS.md`, `docs/HERMES_CODEX_OPERATING_CONTRACT.md`, `docs/HERMES_TASK_PROMPT_TEMPLATE.md`, and non-active `.codex/config.example.toml`. It also records the task in backlog and supervision docs.

## Safety result

This task is docs/config-rules only. It does not implement product features, change application behavior, run providers, start manual testing, create grading/finalization rows, or touch Docker containers. The `.codex/config.example.toml` file is example-only; no active `.codex/config.toml` was created.

## Checks run

- `git status --short` — showed only scoped TA-OPS-001 docs/config-rules files.
- `git diff --check` — passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- `ss -ltnp '( sport = :3000 or sport = :8000 )'` — ports 3000 and 8000 remained listening; no stack stop/restart/rebuild command was run.
- Final `git status --short` — to be checked after commit.

# TA-MANUAL-001A — Founder manual evidence-to-queue checklist

- Recorded at: 2026-06-04
- Baseline commit: `258de5556c588c5776ab0df64a5c158adb68c7a4`
- Workflow type: docs/backlog-only founder manual smoke checklist
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Provider/model calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created: 0
- FinalGrade created: 0
- GradingJob created: 0
- Private files/artifacts used: no

## Change made

TA-MANUAL-001A adds `docs/FOUNDER_MANUAL_EVIDENCE_QUEUE_CHECKLIST.md` and records the founder-only/manual evidence-to-queue testing scope. The checklist documents what the founder can safely test, what remains prohibited, expected zero safety counts, stop conditions, known rough UI states, and the Dockerized browser registration/login `localhost` API caveat observed during TA-MANUAL-001.

## Safety result

This is documentation/backlog only. It does not implement product features, grading, provider execution, real Codex, real AI mapping, real OCR/vision, batch grading, teacher observation, `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` creation. Founder direct manual testing remains safe for evidence-to-queue only.

## Checks run

- `git status --short` — clean at baseline.
- `git rev-parse HEAD` — `258de5556c588c5776ab0df64a5c158adb68c7a4`.
- `git diff --check` — passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- Full `make test` not run because TA-MANUAL-001A is docs/backlog only and product behavior was not changed.
- `git diff --check` — passed again before commit.

# TA-GRADE-000 — Confirmed-packet-only grading queue contract

- Recorded at: 2026-06-04
- Baseline commit: `f64d2b4636eacf8b5402cc297569b6c1692ac00d`
- Workflow type: manual controlled documentation/contract gate
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created: 0
- FinalGrade created: 0
- GradingJob created: 0
- Private files/artifacts used: no

## Change made

TA-GRADE-000 defines the confirmed-packet-only grading queue contract in `docs/GRADING_QUEUE_CONTRACT.md` and records the boundary across backlog/AEEM/grading-quality supervision docs. A future queue may accept only confirmed ready evidence packets and must refuse missing, unconfirmed, partial, blank, possible-continuation, not-checked-risk, missing-rubric, no-region/no-segment, invalid-order, missing-context, blocker-bearing, cross-assessment, and cross-teacher packets.

## Safety result

TA-GRADE-000 is documentation/contract only. It does not implement TA-GRADE-001, does not create queue runtime behavior, does not run grading, does not call providers, and does not create `GradeSuggestion`, `FinalGrade`, or `GradingJob`. TA-GRADE-001 remains blocked until this contract is accepted.

## Checks run

- `git status --short` — clean at baseline.
- `git diff --check` — passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- Full `make test` not run because TA-GRADE-000 is docs/contract only and product behavior was not changed.

# TA-BATCH-001A — Harden batch evidence prep correctness and quarantine workflow

- Recorded at: 2026-06-04
- Baseline commit: `0bb79cf8e61c1875d0620c938610420690dcb0d6`
- Workflow type: manual controlled evidence-prep hardening
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created by prep run: 0
- FinalGrade created by prep run: 0
- GradingJob created by prep run: 0
- Private files/artifacts used: no

## Change made

TA-BATCH-001A hardens expected-packet accounting: batch prep now treats expected evidence slots as submissions × active/canonical grading units and represents missing answer regions as blocked packets instead of omitting them. Quarantine items include submission id, student identifier, grading unit label, blocker/warning reasons, `evidence_status`, `continuation_check_status`, segment count, pages covered, answer-region/question ids, and correction target metadata.

The mixed-state backend test covers two submissions × three grading units: one ready complete packet; one missing answer region; one unconfirmed packet; one partial packet; one blank packet; one unresolved possible continuation; and missing active rubric blockers. Exact expected counts are 6 total packets, 1 ready, 5 blocked, 5 warning packets, 1 partial, and 1 blank.

## Safety result

TA-BATCH-001A is evidence preparation only. It is not batch grading. It creates no `GradeSuggestion`, no `FinalGrade`, no `GradingJob`, no real Codex job, and no real AI/OCR provider output. Partial packets are blocked from normal grading. Blank packets are blocked from normal AI grading for now; future zero-mark blank handling remains separate and was not implemented. TA-GRADE-001 remains blocked until batch prep proves no missing evidence is silently ignored and the next task is explicitly approved.

## Checks run

- `git status --short` — clean at baseline.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_evidence_prep_runs_api.py::test_mixed_state_prep_accounts_for_every_expected_packet_slot -q` — first failed on missing `correction_target`, then passed after implementation.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_evidence_prep_runs_api.py -q` — 6 passed.
- `node tests/workflow-ui.test.mjs` — frontend workflow static checks passed.
- `node tests/workflow-ui.test.mjs && npm run build` — static check passed; Next production build completed successfully. Existing ESLint flat-config warning printed, command exited 0.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... make test` — 246 passed.
- `PATH=/tmp/ta-bin:$PATH make up`; `docker compose exec -T backend alembic upgrade head`; health retry via `curl` — services healthy after backend startup.
- Playwright E2E via Windows Docker CLI with WSL path volume — 2 passed.
- `git diff --check` — passed.
- `PATH=/tmp/ta-bin:$PATH make down` — services stopped and removed.

# TA-BATCH-001 — Batch evidence packet preparation scaffold

- Recorded at: 2026-06-04
- Baseline commit: `423f4a3ed5691aa91aae20618756eae0746d0c35`
- Workflow type: manual controlled evidence-preparation scaffold
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion created by prep run: 0
- FinalGrade created by prep run: 0
- Private files/artifacts used: no

## Change made

Added `BatchEvidencePrepRun` metadata, evidence prep summary/run endpoints, and a service that summarizes student×grading-unit evidence readiness. Packets are quarantined for page-order uncertainty, missing regions/segments, unconfirmed/partial/blank status, possible continuation not confirmed, missing rubric, invalid segment order, and missing crop/context. The assessment UI now shows an Evidence preparation summary with ready/blocked/warning/partial/blank counts and blocked item reasons.

## Safety result

TA-BATCH-001 is evidence preparation only. It is not batch grading. It creates no `GradeSuggestion`, no `FinalGrade`, no grading job, no real Codex job, and no real AI/OCR provider output. Real AI/OCR providers remain blocked.

## Checks run

- `git status --short` — checked at start; clean at baseline.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant' python -m pytest tests/test_evidence_prep_runs_api.py -q` — 5 passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant' python -m pytest tests/test_evidence_prep_runs_api.py tests/test_models_metadata.py tests/test_migrations.py -q` — 9 passed.
- `node tests/workflow-ui.test.mjs` — frontend workflow static checks passed.
- `npm run build` in `apps/web` — compiled and built successfully; existing Next/ESLint flat-config warning printed but command exited 0.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... make test` — 245 passed.
- `PATH=/tmp/ta-bin:$PATH make up`; `docker compose exec -T backend alembic upgrade head`; `make health` — services started, migration applied, health passed after startup completed.
- `make e2e` via the Windows Docker CLI failed to mount the WSL repo path (`/work/apps/web/package.json` missing). Re-run with the equivalent `\\wsl.localhost\\Ubuntu\\home\\newton\\teacher-assistant` volume path passed: 2 passed.
- `git diff --check` — passed before final verification.

# TA-UI-001A — Harden evidence packet status and correction semantics

- Recorded at: 2026-06-04
- Baseline commit: `2a2aa87a5b87288aca89f3d6772c552331b40c80`
- Workflow type: manual controlled evidence-state hardening
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation by correction path: 0
- FinalGrade creation by correction path: 0
- Private files/artifacts used: no

## Change made

Added explicit `AnswerRegion.evidence_status` and `AnswerRegion.continuation_check_status` fields and used them in evidence packet readiness. Segment edit/add/remove/reorder operations reopen confirmation. Full-answer confirmation marks packets complete. Partial and blank packets block grading readiness. Continuation-not-needed clears only continuation risk. The review UI now shows Unconfirmed, Complete, Partial / needs review, Blank, Ready for grading, and Blocked labels plus warning text that partial/blank/blocked/continuation states affect readiness.

## Safety result

TA-UI-001A clarifies packet status before batch evidence preparation. Real AI mapping/OCR remains blocked. TA-BATCH-001 was not started. Corrections prepare evidence only and do not create `GradeSuggestion` or `FinalGrade`.

## Checks run

- `git status --short` — checked at start; clean at baseline.
- `cd apps/api && python -m pytest tests/test_answer_regions_api.py -q` — 27 passed.
- `node tests/workflow-ui.test.mjs` — frontend workflow static checks passed.
- `make test` — 240 passed.
- `make lint` — backend ruff and web TypeScript checks passed.
- `cd apps/web && npm run build` — compiled and built successfully; existing Next/ESLint flat-config warning printed but command exited 0.
- `git diff --check` — passed.
- `make up`; `docker compose exec -T backend alembic upgrade head`; `make health` — services started and health passed after startup completed.
- `make e2e` — 2 passed after services were running. The first e2e attempt failed with `ERR_CONNECTION_REFUSED` because the frontend service was not running; no product assertion failed in that attempt.

# TA-UI-001 — Teacher correction workflow for split/merge/reorder/confirm

- Recorded at: 2026-06-04
- Baseline commit: `a379d2b8cce1e153f871fffc38ac478e35912543`
- Workflow type: manual controlled evidence-correction workflow
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Real OCR/vision implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- Private files/artifacts used: no

## Change made

Added auth-required AnswerRegion/AnswerRegionSegment correction APIs and a rough review-queue UI for numeric bbox edit, add/split segment, remove segment, reorder segment, confirm full answer, mark continuation not needed, and mark partial/needs review. Correction audit metadata is written to `AuditLog` with correction type, before/after state, teacher id, and timestamp.

## Safety result

TA-UI-001 adds the correction path needed to resolve evaluation-gate blockers before grading. Corrections prepare evidence only. They do not create `GradeSuggestion`, do not create `FinalGrade`, do not run batch grading, do not start real AI mapping/OCR, and do not invoke Codex. Real AI mapping remains blocked.

## Checks run

- `cd apps/api && python -m pytest tests/test_answer_regions_api.py -q` — 23 passed.
- `node tests/workflow-ui.test.mjs` — frontend workflow static checks passed.
- `npm run build` in `apps/web` — compiled and built successfully; existing Next/ESLint flat-config warning printed but command exited 0.
- `make lint` — backend ruff and web TypeScript checks passed.
- `make test` — 236 passed.
- `make e2e` — 2 passed.

# TA-SCRIPT-001 — Script page sequencing and answer-boundary benchmark

- Recorded at: 2026-06-04
- Baseline commit: `0eb6b2ab61f7b6c6c48fbf516d69e7aa3eb0bd3a`
- Workflow type: manual controlled evaluation harness and synthetic fixtures
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real OCR/vision script provider implementation: not started
- Real AI mapping implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Private files/artifacts used: no

## Change made

Added `apps/api/packages/evaluation/script_processing_evaluator.py`, ten tiny synthetic JSON fixtures, and focused evaluator tests. The harness loads provider-agnostic script-processing fixtures, replays saved deterministic processor output, compares source/logical page order, missing/duplicate page detection, blank/cover classification, detected label counts, answer-boundary counts, boundary page coverage/order, and continuation signals, then reports metrics and a quality gate policy for future real-provider trial eligibility.

## Synthetic script cases

1. ordered pages;
2. reversed pages;
3. missing page gap;
4. duplicate page;
5. blank/cover page;
6. single-page answer boundary;
7. multi-question same page;
8. near-bottom continuation;
9. near-bottom complete answer;
10. low-confidence / ambiguous boundary.

## Deterministic synthetic result

`synthetic_script_processor` result: overall pass false, eligible false, 10 cases, 5 passed, 5 critical failures, page-order accuracy 0.9, missing-page detection count 1, duplicate-page detection count 1, blank/cover classification accuracy 1, missed continuation count 1, false continuation count 0, unsafe auto-confirm count 0, `GradeSuggestion` count 0, and `FinalGrade` count 0. This intentionally keeps unsafe fixture failures visible instead of presenting the saved deterministic output as product-quality sequencing.

## Checks run

- `cd apps/api && python -m pytest tests/test_script_processing_evaluation.py tests/test_answer_mapping_evaluation.py tests/test_reference_extraction_evaluation.py -q` — 28 passed.
- `make test` — 229 passed after starting services with `make up`.
- `make lint` — backend ruff and web TypeScript checks passed.
- `git diff --check` — passed.
- `make down` — services stopped.

## Safety result

TA-SCRIPT-001 is evaluation-only. Real OCR/vision script sequencing remains blocked. Real AI mapping remains blocked. No grading logic changed. No `GradeSuggestion` or `FinalGrade` records are created by the evaluator.

# TA-REF-001 — Reference extraction evaluation harness

- Recorded at: 2026-06-04
- Baseline commit: `bd0c24853fdeaea8331058699e26128a9f909c58`
- Workflow type: manual controlled evaluation harness and synthetic fixtures
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real OCR/vision reference extraction implementation: not started
- Real AI mapping implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Private files/artifacts used: no

## Change made

Added `apps/api/packages/evaluation/reference_extraction_evaluator.py`, eight tiny synthetic JSON fixtures, and focused evaluator tests. The harness loads provider-agnostic reference fixtures, replays saved deterministic extractor output, compares CGU labels/max marks/question text/parent-child structure/solution sections/rubric criteria/rubric totals, reports per-case pass/fail plus metric summaries, and applies a quality gate policy for future real-provider trial eligibility.

## Synthetic reference cases

1. clean question paper with labels/max marks;
2. nested subparts such as `1(a)(i)`;
3. rubric criteria whose totals match max marks;
4. rubric total mismatch;
5. solution/model answer sections matching grading units;
6. missing solution section for one grading unit;
7. duplicate/ambiguous labels;
8. image-only/math placeholder requiring visual confirmation.

## Safety result

TA-REF-001 is evaluation-only. Real OCR/vision reference extraction remains blocked. No grading logic changed. No `GradeSuggestion` or `FinalGrade` records are created by the evaluator.

# TA-MAP-003A — Define mapping quality gates and failure policy

- Recorded at: 2026-06-04
- Baseline commit: `2587be9135a81208ef80e846893731b6cd59f5cb`
- Workflow type: manual controlled quality-gate policy over synthetic evaluator
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI/OCR mapping implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Private files/artifacts used: no

## Change made

Added `evaluate_mapping_quality_gate(...)` to the mapping evaluator. The policy returns `eligible_for_real_provider_trial`, `blocker_reasons`, `warning_reasons`, and the evaluated metrics. It blocks provider advancement on critical failures, unsafe auto-accept, grading/finalization side effects, missed continuations, wrong-question critical failures, blank false mappings, and mandatory-review confirmation gaps.

## Policy result

`current_mock_provider` remains ineligible for a real-provider trial as product-quality mapping. Its TA-MAP-003 result is useful as a measurement baseline only: 3/7 cases passed, 2 critical failures, 0 unsafe auto-accepts, 0 `GradeSuggestion` creations, and 0 `FinalGrade` creations.

## Safety result

Real AI mapping remains blocked. TA-MAP-004 was not started. Critical failures are treated as blockers, not nice-to-fix issues.

# TA-MAP-003 — Mapping evaluation harness and synthetic benchmark

- Recorded at: 2026-06-04
- Baseline commit: `1c69a1ae2c0e514caf11cf5decb7bc653086bf8d`
- Workflow type: manual controlled evaluation harness and synthetic fixtures
- VSCode/Codex used: no
- Additional coding agent used: no
- Real Codex calls: 0
- Real AI/OCR mapping implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Private files/artifacts used: no

## Change made

Added `apps/api/packages/evaluation/answer_mapping_evaluator.py`, seven tiny synthetic JSON fixtures, and focused evaluator tests. The harness loads provider-agnostic fixture definitions, compares provider output to expected mapping groups/segments/continuation states, reports per-case pass/fail plus metric summaries, and classifies critical failures such as missed continuation, wrong-question traps, blank-page false mappings, unsafe auto-accept, or grading/finalization side effects.

## Synthetic benchmark cases

1. single-page complete answer;
2. multi-page continuation;
3. near-bottom complete answer with no continuation;
4. ambiguous / possible continuation;
5. multiple questions on one page;
6. wrong-question trap;
7. blank or low-content page.

## Current mock-provider result

Using saved `current_mock_provider` synthetic outputs: overall pass is false, 3/7 cases pass, critical failures are reported for wrong-question trap and blank/low-content false mapping, unsafe auto-accept count is 0, `GradeSuggestion` count is 0, and `FinalGrade` count is 0. This is an honest benchmark result, not a production mapping-quality claim.

## Safety result

TA-MAP-003 is evaluation-only. Real AI mapping remains blocked. TA-MAP-004 was not started. No grading or finalization records are created by the evaluator.

# TA-CORE-002 — Map AEEM architecture to implementation roadmap

- Recorded at: 2026-06-04T12:13:40+06:00
- Baseline commit: `52bd4ffb0950d841a22e0bb721585b2faebb5daa`
- Workflow type: documentation/backlog-only roadmap bridge
- Real Codex calls: 0
- Real AI mapping implementation: not started
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Product code changed: no
- Private files/artifacts committed: no

## Change made

Created `docs/AEEM_IMPLEMENTATION_ROADMAP.md` and updated AEEM/supervision/backlog/validation docs to map each AEEM layer to current TAAgent status, missing pieces, next task, and ordering rationale.

## Roadmap decision

Recommended next implementation is TA-MAP-003: Mapping evaluation harness and synthetic benchmark. The rationale is that mapping/continuation was the discovered evidence failure, TA-MAP-002 already provides the draft contract, and real AI mapping must wait until quality can be measured.

## Safety result

TA-CORE-002 is docs/backlog only. It does not start TA-MAP-003, real AI mapping, batch grading, Codex calls, teacher observation, or grading/finalization records.

## Verification results

To be completed by the TA-CORE-002 commit gate: `git status --short`, `git diff --check`, `make lint`, final `git status --short`.

# TA-CORE-001 — Adopt AEEM architecture and reset implementation sequence

- Recorded at: 2026-06-04T11:41:53+06:00
- Baseline commit: `451b835776de6a1f535cd9929767676bbdaa3637`
- Workflow type: documentation/backlog-only architecture reset
- Real Codex calls: 0
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation: 0
- FinalGrade creation: 0
- Product code changed: no
- Private files/artifacts committed: no

## Change made

Created `docs/ANSWER_EVIDENCE_EXTRACTION_MACHINE.md` and updated the mapping, supervision, grading-quality, validation, and backlog documents to adopt AEEM as the north-star pre-grading architecture.

## Architecture decision

The next direction is evidence-machine quality measurement, not real AI mapping, batch grading, or grading prompt tuning. The required next implementation sequence starts with mapping and reference/script extraction evaluation harnesses before any real mapping provider.

## Safety result

TA-CORE-001 is docs/backlog only. It does not implement follow-up tasks, does not start TA-MAP-003 implementation, does not run real providers, and does not create grading/final-grade records.

## Verification results

To be completed by the TA-CORE-001 commit gate: `git status --short`, `git diff --check`, `make lint`, final `git status --short`.

# Validation Log

## TA-MAP-002 — Deterministic multi-segment answer-region mapping provider prototype

- Recorded at: 2026-06-04
- Baseline commit: `746a59bcb5c650f92b5ed481611f32057d260911`
- Workflow type: manual controlled deterministic/mock mapping provider prototype
- Real Codex calls: 0
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- GradeSuggestion creation by mapping suggestion/acceptance path: 0, covered by focused API tests
- FinalGrade creation by mapping suggestion/acceptance path: 0, covered by focused API tests

### Change made

Implemented the first deterministic/mock provider path for TA-MAP-001 draft multi-segment mapping suggestions. The backend now exposes a submission-scoped suggestion endpoint that returns draft suggestion groups with ordered page-local segments, confidence, warnings, continuation risk, review flags, and teacher/founder confirmation requirements. The acceptance endpoint creates real `AnswerRegion` plus ordered `AnswerRegionSegment` rows only after explicit acceptance.

### Safety result

Suggestions are draft-only and are not persisted unless accepted. Acceptance creates answer-region evidence only; it does not create `GradingJob`, `GradeSuggestion`, or `FinalGrade`, does not invoke Codex/LLMs, does not run batch grading, and does not auto-finalize. Possible continuation remains a warning/block through the existing evidence packet gate until full-answer confirmation is recorded.

### Verification results

Verification for the final commit is recorded in the commit task report. Focused TA-MAP-002 tests cover single-segment suggestions, multi-segment continuation, possible continuation warnings, acceptance, invalid/cross-assessment rejection, no grading/finalization side effects, and evidence-packet visibility.

## TA-W2-027 — Prepare controlled teacher workflow observation

- Recorded at: 2026-06-03
- Baseline commit: `5c0d5c6c26c1bf134f68bc50b31c097a084d3e82`
- Workflow type: docs-only controlled observation preparation
- Real Codex calls: 0
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not started
- FinalGrade creation: 0
- Product code changed: no

### Scope
Prepared documentation for a safe in-person teacher workflow observation using the already-validated `1(b)(i)` multi-segment case as a controlled demo. The observation is framed as workflow/trust feedback for an early AI draft marking assistant, not a public pilot and not a production accuracy claim.

### Safety framing recorded
The plan requires manual controlled mode, teacher review, evidence packet review, full-answer confirmation, no automatic finalization, no unapproved exports, no private artifact commits, no batch grading, and no new real Codex calls unless explicitly approved during the observation plan.

### Demonstration baseline
The demo may show the existing `1(b)(i)` draft suggestion only: page 3 + page 4 continuation evidence, full-answer confirmation, `multi_segment_composite` context, draft score `6/6`, confidence `0.88`, `needs_review=true`, and no `FinalGrade` before teacher action.

### Follow-up sequencing
Next possible tasks are TA-W2-028 (conduct teacher observation and record feedback) and TA-W2-029 (post-observation improvement plan). Neither should be treated as approval for autonomous grading, batch grading, or production claims.


## TA-W2-026 — Multi-segment answer evidence and continuation gate

Recorded at: 2026-06-03

### Root cause/classification
The latest one-call real grading attempt for `1(b)(i)` must be treated as invalid for quality benchmarking: `answer_region_id=5552` covered only one rectangle on page 3 while the student answer continued onto page 4 before `1(b)(ii)`. The failure class is answer-region capture / multi-page answer evidence, not primarily prompt quality.

### Product correction
A canonical grading unit may require multiple ordered answer segments. Real grading readiness must therefore validate segment completeness and continuation risk before provider execution.

### Implementation summary
- Added persistent `AnswerRegionSegment` support linked to existing `AnswerRegion` rows.
- Existing single-page regions remain backward-compatible through a primary segment.
- Evidence packets now report `segment_count`, `pages_covered`, ordered segment metadata, `continuation_check_status`, `next_page_context_available`, and full-answer confirmation state.
- A deterministic page-bottom heuristic marks possible continuation and blocks grading until teacher/founder full-answer confirmation is recorded.
- Multi-segment grading uses a local composite grading-context image with ordered segment labels, stored only in ignored local artifacts.

### Safety result
No real Codex was run in TA-W2-026. No teacher observation was started. The blocked path creates no `GradingJob`, `GradeSuggestion`, or `FinalGrade`. Teacher observation remains blocked until multi-segment evidence is validated with the full page 3 + page 4 `1(b)(i)` answer.

### Verification results
- Focused multi-segment/evidence tests: `4 passed`.
- Focused metadata/migration/answer-region/grading API tests: `30 passed`.
- `make test`: `187 passed`.
- `node apps/web/tests/workflow-ui.test.mjs`: passed.
- `make lint`: passed (`ruff check`, `tsc --noEmit`).
- `cd apps/web && npm run build`: passed; retained existing non-fatal ESLint flat-config warning.
- `make e2e`: passed (`2 passed`) after restarting the dev server cleanly because running `next build` while dev server was active corrupted `.next` for the first attempt.
- `git diff --check`: passed.
- `make down`: run after verification.


## TA-W2-025 — Pre-grading evidence packet gate

- Recorded at: 2026-06-03T10:05:27+06:00
- Baseline commit: `73f9898152a9641ae7519b49a5b5f77ce6b57a00`
- Workflow type: manual controlled evidence-packet implementation + verification
- Real Codex calls: 0
- Batch grading: not run
- Autonomous loop: not enabled
- Teacher observation: not run; remains blocked until evidence-packet flow is validated with real documents
- FinalGrade creation by evidence packet endpoint or blocked grading path: 0, covered by focused API tests

### Change made

Added `GET /answer-regions/{answer_region_id}/grading-evidence-packet` plus typed response schemas and a reusable backend readiness gate before grading provider/job execution. The packet records assessment/submission/page/answer-region context, canonical grading unit, question evidence, solution/model-answer evidence, rubric evidence, student answer crop/context evidence, and readiness blockers/warnings.

### Readiness gate behavior

`POST /answer-regions/{answer_region_id}/grade` now checks the evidence packet first and returns HTTP 400 before creating a `GradingJob`, invoking a provider, or creating downstream grading records when the packet is not ready. Missing active rubric and missing answer-region image/context are tested blockers. The endpoint itself is read-only.

### Founder principle recorded

Teacher/founder confirmation of the exact question, solution/model answer, rubric, and student-answer mapping is a prerequisite for real grading. This task addresses the founder principle that grading quality depends first on confirmed evidence and bounded context, not question-specific prompt hacks.

### Frontend behavior

The review card fetches and displays the evidence-packet readiness checklist, including ready/not-ready state, blockers, and warnings. Mock Grade remains usable when the packet is ready and is disabled while the packet is missing/not ready.

### Verification results

- Initial repo state: `git status --short` showed only scoped in-progress files; baseline `git rev-parse HEAD` was `73f9898152a9641ae7519b49a5b5f77ce6b57a00`.
- `python -m pytest tests/test_grading_api.py -q`: passed (`14 passed`).
- `make test`: passed (`182 passed`).
- `node apps/web/tests/workflow-ui.test.mjs`: passed (`frontend workflow static checks passed`).
- `make e2e`: passed (`2 passed`): auth smoke and Custom Controlled mock grading loop, including no-FinalGrade-before-approval.
- `make lint`: passed (`ruff check` and `tsc --noEmit`).
- `cd apps/web && npm run build`: passed; emitted the existing non-fatal ESLint flat-config warning while exiting 0.
- `git diff --check`: passed.
- `make down`: run after verification to stop compose services.

## TA-W2-024 — Answer-region crop/context audit for real grading quality

- Recorded at: 2026-06-03T00:53:02+06:00
- Baseline commit: `9ccadf028411ce966813dee58d2a725516a5c869`
- Workflow type: answer-region crop/context audit + minimal AI-grading context fix
- Real Codex grading calls: 1
- Region suggestion calls: 0
- Batch grading: not run
- FinalGrade creation: 0
- Teacher approval/edit/export/observation: not run

### Crop/context finding

The original `1(b)(i)` crop used the preserved coordinates `x=118`, `y=1176`, `width=1018`, `height=430` on page 3. Visual audit of the private local crop and full rendered page classified the crop as **mixed but inadequate**: it included the Bayes setup/denominator work, but it was tight at the bottom/right and cut off visible denominator arithmetic/result context. A 10% padded context crop recovered more of the denominator/result evidence without adding excessive unrelated content. The full visible page still did not show a fully completed posterior division/value, so the remaining grading-quality issue is not purely a crop problem.

### Change made

Added configurable AI-grading-only answer-region crop padding via `ANSWER_REGION_GRADING_CROP_PADDING_RATIO` (default `0.10`). The original teacher/founder answer-region coordinates and stored crop remain unchanged; grading now sends a separate clamped relative `artifacts/grading_context/...` crop and records `grading_crop_padded` plus relative-path metadata in the suggestion raw response.

### Real retest result

The prior TA-W2-023C score was `4/6`; founder fair remained `6/6`. After the padded context fix, one real Codex retest for recreated `1(b)(i)` again returned `4/6` with `model_provider=codex_cli`, `model_name=gpt-5.5`, `needs_review=true`, and no `FinalGrade`. The grading context expanded from `1018x430` to `1174x516`.

### Classification

Mixed: crop/context was inadequate and is now improved for future grading calls, but the post-fix real Codex score remained `4/6`. Treat the remaining under-credit as a real-model scoring limitation for now, not another prompt-only/crop-only fix target.

### Limitation

During focused backend tests, the live local Postgres test data from the previous TA-W2-023C run was cleared by the existing cleanup fixture; the retest state was recreated from preserved local artifacts and scripts. No private PDFs, crops, pages, exports, screenshots, or generated artifacts were committed.

## TA-W2-023B — Bayes-specific score-band grading guidance

- Recorded at: 2026-06-03T00:16:25+06:00
- Baseline commit: `aadfb13972adb297ee47920261dae4dbb8344395`
- Workflow type: prompt/rubric grounding + deterministic synthetic calibration
- Real Codex calls during code/harness phase: 0
- Product scope: grading prompt/evaluation harness only; no workflow, answer-region, canonical-unit, auth, frontend, approval, export, or deletion changes

### Trigger

TA-W2-023A's capped real retest improved `1(b)(i)` from `3/6` to `4/6`, but founder fair mark remained `6/6`. The remaining blocker is Bayes/probability work being under-credited when formula, denominator expansion, and posterior expression are conceptually present but compact or imperfectly written.

### Coverage added

- Shared Bayes/probability 6-mark score-band guidance in the handwritten math/stat grading prompt.
- Provider prompt tests verify the score-band text reaches both the Codex CLI and OpenAI-compatible grading prompt paths.
- Deterministic math/stat calibration now includes a Bayes score-band near-full-credit case with fake score `5.5/6`, `needs_review=true`, and `final_grade_count=0`.

### Caveat

A single capped real Codex retest for existing `1(b)(i)` region `5120` was allowed after checks, but it was not run because the region was no longer present after the required test-suite database cleanup. Teacher observation remains blocked until a future capped retest is acceptable or the workflow is framed as conservative human-in-loop draft review only.


## TA-W2-023 — Handwritten math/stat grading prompt grounding

- Recorded at: 2026-06-02T23:00:47+06:00
- Baseline commit: `b881f11237e85304a900b3905e1b1b8929937f01`
- Workflow type: prompt/rubric grounding + deterministic synthetic calibration
- Real Codex calls: 0
- Provider used: fake/synthetic only
- Data policy: no private files or generated private artifacts committed
- Product code changes required: yes

### Coverage added

- Shared handwritten math/stat guidance in grading prompt registry.
- Codex CLI prompt includes the same guidance via shared prompt helpers.
- OpenAI-compatible prompt path receives the guidance through `build_grading_prompt()`.
- Synthetic math/stat calibration cases added:
  - Bayes correct setup + compact/imperfect working: fake score `5.5/6`, not severe under-score.
  - Correct formula with arithmetic slip: fake score `4/6`, meaningful partial credit.
  - Wrong conceptual setup: fake score `1.5/6`, low score.
- Safety preserved: `needs_review=true`; harness creates no `FinalGrade`; real provider disabled by default.

### Runtime and test results

- Focused prompt/provider/calibration tests: `33 passed`.
- Deterministic calibration harness: passed in fake mode with `call_count=0`, `real_provider_used=false`, `final_grade_count=0`.
- Full checks recorded in the final task report.

### Remaining caveat

TA-W2-023 does not prove real founder-document quality. A capped corrected retest is still needed after this prompt fix.


## TA-W2-022C — Canonical grading-unit confirmation

- Recorded at: 2026-06-02T21:06:01+06:00
- Baseline commit: `58a52c85a27d5199eab29555dbd1bfa89dd486e6`
- Workflow type: canonical grading-unit setup hardening + synthetic tests
- Real Codex calls: 0
- Provider used: mock/synthetic only
- Data policy: no private files committed; founder material structure recorded as text only
- Product code changes required: yes

### Root-cause finding

TA-W2-022B is invalid for grading-quality evaluation because the canonical grading units were ambiguous/wrong. The rehearsal used/report labels like `2(a)(i)`, `2(b)(i)`, and `2(c)(i)` even though the founder-confirmed material answers Question 1. This was primarily a manual setup error by Hermes, enabled by UI ambiguity and the absence of a required canonical grading-unit confirmation table. The existing schema could store labels such as `1(a)(i)`, so the core issue was not a schema inability.

### Correct founder material structure to confirm before any future real grading

- Whole sub-question totals: `1(a)=10`, `1(b)=12`, `1(c)=13`.
- Subpart rubric totals: `1(a)(i)=6`, `1(a)(ii)=4`, `1(b)(i)=6`, `1(b)(ii)=6`, `1(c)(i)=5`, `1(c)(ii)=4`, `1(c)(iii)=4`.
- Future real grading must first confirm whether the unit is a whole sub-question (`1(a)`) or a subpart (`1(a)(i)`) and must show the matching max marks.

### Coverage added

- Backend validates duplicate canonical grading-unit labels per assessment on direct question creation/update and accepted import drafts.
- Custom Controlled run page now displays a canonical grading-unit confirmation table with label, max marks, model answer/rubric status, active-rubric status, and whole-sub-question/subpart classification.
- Answer-region selector/cards and review queue show grading-unit label plus max marks.
- Final-grade XLSX export includes `grading_unit_label` and `grading_unit_max_marks`.
- E2E synthetic fixture now uses `1(a)(i)` out of 6 to protect subpart label handling.

### Runtime and test results

- Focused backend tests: `24 passed`.
- Full backend tests via `make test`: `173 passed`.
- Frontend static workflow test: passed.
- `make e2e`: passed, 2/2 Playwright smoke tests.
- `make lint`: passed.
- `cd apps/web && npm run build`: passed; Next still reports the existing ESLint flat-config warning during build.
- `git diff --check`: passed.

### Notes

- No new real grading was run in TA-W2-022C.
- No FinalGrade auto-finalization behavior was added.

## TA-W2-022A — Privacy baseline and deletion workflow

- Recorded at: 2026-06-02T18:51:31+06:00
- Baseline commit: `27a8332833c4e9c4f49962acf66d89e1569d6eb1`
- Workflow type: privacy baseline docs + authenticated deletion endpoint + synthetic backend tests
- Real Codex calls: 0
- Provider used: mock/synthetic only
- Data policy: synthetic non-student records/files only
- Product code changes required: yes

### Coverage added

- Added `docs/PRIVACY_BASELINE.md` for founder/internal testing rules, sensitive artifact handling, teacher authority, AI-suggestion limits, deletion workflow, and explicit non-production gaps.
- Expanded `.gitignore` for local uploads, rendered pages, crops, exports, Playwright outputs, evaluation outputs, local/private PDFs, Office files, and image artifacts.
- Added authenticated `DELETE /assessments/{assessment_id}/test-data` for owner-only assessment test-data cleanup.
- Added best-effort local file cleanup helpers for stored relative files, grading-run directories, and question-import directories.
- Added synthetic backend deletion tests for owner deletion, cross-teacher rejection, auth requirement, dependent-row cleanup, no FinalGrade creation, best-effort file cleanup, and avoiding absolute-path exposure in normal deletion responses.

### Runtime and test results

- Focused privacy deletion tests: passed (`3 passed`).
- Focused academic/submission/privacy tests: passed (`19 passed`).
- `node apps/web/tests/workflow-ui.test.mjs`: passed.
- `make lint`: passed.
- `make test`: passed (`170 passed`).
- `git diff --check`: passed.

### Notes

- The deletion endpoint preserves the assessment shell but removes submissions, submission pages, answer regions, grading jobs, grade suggestions, final grades, grading runs, question-import jobs, questions, and rubrics for that assessment's test workflow.
- Physical file deletion is best-effort under configured local storage paths; API responses return counts and `file_delete_error_count` only, not private absolute paths.
- This is not full compliance: encryption at rest, formal retention, audit-grade compliance, robust production multi-tenancy, and external teacher production deployment remain unresolved.
- Founder approval is still required before any real teacher/private-document grading rehearsal.

## TA-W2-021 — Mode gating / ghost-mode clarity

- Recorded at: 2026-06-02T18:20:04+06:00
- Baseline commit: `f27230aaea4360cc145989cae3189277237388a0`
- Workflow type: backend gating + frontend clarity + docs reconciliation
- Real Codex calls: 0
- Provider used: mock/synthetic only
- Data policy: no private teacher/student data
- Product code changes required: yes

### Coverage added

- Added backend mode gating so Semi-Automated is blocked by default with a clear 400 message and Fully Automated is rejected with the same teacher-workflow message.
- Kept Custom Controlled as the only normal teacher workflow entry point.
- Removed the normal assessment-page Semi-Automated button and replaced it with a non-clickable readiness note.
- Added an explicit blocked-mode page for direct `?mode=semi_automated` / `?mode=fully_automated` navigation.

### Runtime and test results

- Targeted grading-run tests: passed (`5 passed, 11 deselected`).
- `node apps/web/tests/workflow-ui.test.mjs`: passed.
- `make e2e`: passed (`2 passed`).
- `make lint`: passed.
- `make test`: passed (`167 passed`).
- `npm run build` in `apps/web`: passed; Next still reports the existing ESLint flat-config warning while completing successfully.
- `git diff --check`: passed.

### Notes

- Semi-Automated is now an explicit experimental gate instead of a normal teacher entry point.
- Fully Automated is not presented as usable and is rejected instead of being silently implied by schema presence.
- During verification, the E2E auth helper exposed a Playwright timing issue around `waitForURL(..., waitUntil: "commit")`; replacing that with click plus `expect(page).toHaveURL(...)` kept browser-only auth coverage while removing the flake.

## TA-W2-020 — Playwright E2E smoke suite

- Recorded at: 2026-06-02T10:00:00+06:00
- Baseline commit: `dbb5961f126751f77b1022f3ca4546a449a9da74`
- Workflow type: browser-first Playwright smoke plus synthetic backend seeding
- Real Codex calls: 0
- Provider used: mock/synthetic only
- Data policy: synthetic non-student PDFs/images only
- Product code changes required: yes
- Commit generated during TA-W2-020 validation itself: pending

### Coverage added

- Added Playwright config and npm scripts for web E2E smoke runs.
- Added auth smoke coverage that registers a synthetic teacher in-browser, logs out, and logs back in without token injection fallback.
- Added Custom Controlled mock flow coverage that seeds a synthetic course/assessment/question/rubric/submission/answer-region stack, runs mock grading, and verifies teacher-gated approval.
- Added an explicit no-FinalGrade-before-approval assertion via the review queue before teacher approval.

### Runtime and test results

- `make e2e`: passed after fixing the synthetic PNG fixture, the demo-teacher selection, and the approval assertions.
- `node apps/web/tests/workflow-ui.test.mjs`: passed.
- `make lint`: passed.
- `make test`: passed (`164 passed`).
- `npm run build` in `apps/web`: passed.
- `git diff --check`: passed.

### Notes

- The first E2E failure came from a malformed synthetic PNG. Replacing it with a valid 1×1 PNG and tightening the crop fixture fixed the upload path.
- The review/approval page uses a demo-teacher selector, so the smoke now selects the synthetic teacher before approving the suggestion.
- The export-link assertion is intentionally lightweight and only checks the generated link target.

## TA-W2-019 — Marking policy calibration fix

- Recorded at: 2026-06-02T08:00:00+06:00
- Baseline commit: `5066b860ecc76c3351e3b2e53a0642b18ecefd8b`
- Workflow type: prompt calibration + deterministic synthetic harness
- Real Codex calls: 0
- Provider used: fake/mock deterministic harness
- Data policy: synthetic non-student examples only
- Product code changes required: yes
- Commit generated during TA-W2-019 validation itself: pending

### Prompt and harness changes

- Added a shared `build_marking_policy_instruction()` source so Tough/General/Easy guidance is consistent across grading prompts.
- Tough now explicitly biases toward the lower end of the rubric range, especially when working is weak or missing.
- General now explicitly targets the middle of the plausible rubric range.
- Easy now explicitly biases toward the higher end of the rubric range when the rubric allows it.
- Added a deterministic marking-policy calibration harness with synthetic non-student examples and a fake default run mode.

### Synthetic calibration cases

|| Case | Scenario | Fake Tough | Fake General | Fake Easy | Adjacent gap |
|| --- | --- | ---: | ---: | ---: | ---: |
|| A | Correct final answer, weak/no working | 3.0 | 5.0 | 7.0 | 2.0 / 2.0 |
|| B | Partially correct method with one wrong step | 2.0 | 4.0 | 6.0 | 2.0 / 2.0 |
|| C | Mostly complete answer with minor notation issue | 7.0 | 8.0 | 9.0 | 1.0 / 1.0 |

### Calibration result

- `case_count`: 3
- `call_count`: 0 real provider calls
- `monotonic_ordering`: true (`tough <= general <= easy` held for every synthetic case)
- `meaningful_separation`: true (adjacent gaps were at least 10% of max marks)
- `final_grade_count`: 0
- `real_provider_used`: false

### Interpretation

The prompt is now more operational and the harness can prove the desired ordering on controlled synthetic cases without using real AI. This does **not** prove production calibration on real student work. If a future real Codex calibration still collapses to identical scores, the next action is stronger few-shot or score-band prompting, not hidden fallback logic.

## TA-W1-019 — End-to-end teacher workflow validation

- Recorded at: 2026-05-27T05:23:20+06:00
- Baseline commit: `c7dc0b40214024c91e7556a41188682e3c994861`
- Workflow type: mixed API + health checks
- Real Codex calls: 0
- Provider used: mock
- Data policy: synthetic non-student data only
- Product code changes required: none
- Commit generated during TA-W1-019 validation itself: none

### Synthetic records created

| Record | ID |
| --- | ---: |
| Teacher | 901 |
| Course | 848 |
| Assessment | 831 |
| Question | 780 |
| Rubric | 538 |
| Submission | 593 |
| Submission page | 609 |
| Answer region | 576 |
| Grade suggestion | 410 |
| Final grade | 267 |

### Workflow result

- Grading call count during validation: 1
- Grading job status: succeeded
- Page image fetch: HTTP 200
- Answer-region image fetch: HTTP 200
- Grade suggestions for answer region: 1
- Review queue before teacher approval: `suggested`
- Review queue after teacher approval: `finalized`
- Final grade status: `approved`
- Final-grade readback ID matched created final grade ID: yes (`267`)

### Assessment summary counts

| Metric | Value |
| --- | ---: |
| Total submissions | 1 |
| Total answer regions | 1 |
| Total grade suggestions | 1 |
| Total final grades | 1 |
| Approved count | 1 |
| Edited count | 0 |
| Rejected count | 0 |
| Pending review count | 0 |
| Average final score | 0.00 |
| Max possible score | 10.00 |

### XLSX export result

- Endpoint: `/assessments/831/export/final-grades.xlsx`
- Workbook sheet: `Final Grades`
- Exported data rows: 1
- Reviewed row present: yes
- Forbidden headers present: none
- Confirmed absent: `raw_response_json`, `password_hash`
- Included final status/comment fields for the approved synthetic record.

### Verification results

- `make up`: passed
- `docker compose exec -T backend alembic upgrade head`: passed
- `make health`: passed
- Mixed API workflow smoke: passed
- `make test`: passed (`77 passed`)
- `make lint`: passed
- `docker compose exec -T frontend npm run build`: passed; emitted existing ESLint flat-config warning while exiting 0
- `make frontend-health`: passed after frontend restart
- `make down`: passed
- Final `git status --short` after TA-W1-019 validation: clean

### Known issue / observation

Running the frontend production build inside the same Docker dev container/volume temporarily poisoned the Next dev cache and made the immediate frontend health check return HTTP 500. Restarting the frontend container and waiting for readiness restored `make frontend-health`. No product code change was required for TA-W1-019.

## TA-W1-029B — Real Codex question extraction smoke

- Recorded at: 2026-05-29T15:22:25+06:00
- Code fix commit: `9d05806`
- Workflow type: controlled API smoke through `POST /assessments/{assessment_id}/question-imports`
- Real Codex calls: 1 question extraction call
- Provider used: `codex_cli_question_extractor`
- Data policy: synthetic non-student PNG question paper only
- Codex workdir: isolated `/tmp/ta-codex-question-import-smoke-workdir`
- Config enabled for smoke only: `CODEX_QUESTION_EXTRACTION_ENABLED=true`, `CODEX_CLI_IMAGE_INPUT_ENABLED=true`, `CODEX_CLI_SKIP_GIT_REPO_CHECK=true`

### Synthetic records created

| Record | ID |
| --- | ---: |
| Assessment | 2179 |
| Question import job | 63 |
| Accepted Question | 1924 |
| Accepted Question | 1925 |
| Accepted Question | 1926 |

### Extraction result

- Input type: `image/png`
- Draft count: 3
- Provider warnings: none
- All drafts had `needs_review=true`: yes
- Draft confidences: `0.95`, `0.95`, `0.95`
- Draft questions:
  1. `Differentiate y = x^2.` — 5 marks
  2. `Solve 2x + 3 = 7.` — 4 marks
  3. `State Newton's first law.` — 3 marks

### Teacher-review gate verification

- Real `Question` rows before accept: 0
- Accept selected drafts result: 3 created
- Real `Question` rows after accept: 3
- Accepted question IDs: 1924, 1925, 1926

### Verification results

- `git status --short` before work: clean at `23f8c48`
- Safe no-repo Codex auth check: passed, returned `OK`
- `make up`: passed
- `docker compose exec -T backend alembic upgrade head`: passed
- `make health`: initially hit transient connection reset while backend was still starting; retry passed
- Focused backend question import/provider tests: passed (`16 passed`)
- Frontend workflow static checks: passed
- `make test`: passed (`109 passed`)
- `make lint`: passed
- `docker compose exec -T frontend npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- `make down`: passed
- Final `git status --short` before docs commit: only `BACKLOG.md` and `docs/VALIDATION_LOG.md` modified

### Known issue / observation

The controlled smoke validated a simple synthetic image only. Extraction remains a teacher-reviewed draft feature, not automatic final question creation.

## TA-W1-036B — Custom controlled grading run end-to-end validation

- Recorded at: 2026-05-31T12:56:02+06:00
- Baseline commit: `fb903828b3c16c44ce5925c1f6097bc847954412`
- Workflow type: API-equivalent validation with host backend and frontend running
- Real Codex calls: 1 grading call through `POST /answer-regions/{answer_region_id}/grade-codex-dev`
- Provider used for real-grade step: `codex_cli`
- Mock grading calls during real-grade step: 0
- Data policy: synthetic non-student PDFs/image only; no sample PDFs were present in the repository
- Product code changes required: none

### Synthetic records created

| Record | ID |
| --- | ---: |
| Teacher | 4011 |
| Course | 3598 |
| Assessment | 3494 |
| Custom grading run | 118 |
| Question | 3024 |
| Rubric | 2034 |
| Submission | 2682 |
| Submission page | 2762 |
| Answer region | 2597 |
| Grade suggestion | 1752 |
| Final grade | 1236 |

### Controlled workflow result

- Material upload endpoint: `POST /grading-runs/118/materials`
- Material status after refresh: `materials_uploaded`
- Uploaded material paths persisted after refresh: yes
- Uploaded material types: synthetic question PDF, solution/model-answer PDF, rubric PDF
- Uploaded script: synthetic PNG image
- Manual answer region creation: passed
- Codex suggestion provider: `codex_cli`
- Codex suggestion `needs_review`: true
- Codex suggestion score/confidence: `0.00` / `0.0000`
- Review queue before teacher action: `suggested`
- Final grade before teacher action: HTTP 404, confirming no auto-finalization
- Teacher action: manual edit/finalization
- Final grade status after teacher action: `edited`

### Assessment summary counts

| Metric | Value |
| --- | ---: |
| Total submissions | 1 |
| Total answer regions | 1 |
| Total grade suggestions | 1 |
| Total final grades | 1 |
| Approved count | 0 |
| Edited count | 1 |
| Rejected count | 0 |
| Pending review count | 0 |
| Average final score | 5.00 |
| Max possible score | 5.00 |

### XLSX export result

- Endpoint: `/assessments/3494/export/final-grades.xlsx`
- Local exported file: `/tmp/ta-w1-036b/assessment-3494-final-grades.xlsx`
- Export HTTP status: 200
- Export size: 5273 bytes
- Workbook rows including header: 2
- Created record IDs were present in export cells: yes
- Confirmed absent from exported workbook text: `raw_response_json`, `password_hash`

### Verification results

- Initial `git status --short`: clean
- `make up-infra`: passed
- `make codex-ok`: passed, returned `OK`
- Local Alembic migration against localhost Postgres: passed
- Host backend health: passed
- Frontend readiness at `localhost:3000`: passed
- Custom controlled workflow validation: passed
- `make test`: passed (`135 passed`)
- `make lint`: passed
- `npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- Services shutdown: passed (`docker compose down` completed; no compose services left running)
- Final `git status --short` before docs commit: clean except `BACKLOG.md` and `docs/VALIDATION_LOG.md` after recording this validation

### Known issue / observation

The real Codex grading call was operationally verified, but Codex image input remains disabled in the current runtime. The provider therefore produced a conservative zero-score suggestion from available metadata/rubric context. This validation proves the controlled workflow and teacher-review/export gate, not grading quality or full automation.

## TA-W1-037A — Codex image-input browser/backend smoke

Date: 2026-05-31

### Scope

Enable and validate image input for exactly one browser/backend Codex grading smoke using synthetic/non-student data. No batch real grading, no auto-finalization, no final-grade rule change, no fully automated grading, no voice command, and no TA-W1-038 work.

### Codex CLI support

- Installed CLI: `codex-cli 0.128.0`
- `codex exec --help` advertises image input: `-i, --image <FILE>...`
- Safe auth/syntax probe: `make codex-ok` passed and returned `OK`.

### Config/runtime changes

- Docker/demo default remains image-input off through `.env.example` and app settings.
- `make backend-host-dev` now preserves the safe default while allowing explicit override:
  - default: `CODEX_CLI_IMAGE_INPUT_ENABLED=false`
  - image smoke: `CODEX_CLI_IMAGE_INPUT_ENABLED=true make backend-host-dev`
- Host-backend image-input instructions were added to `docs/CODEX_DEV_RUNTIME.md`.
- Provider behavior:
  - includes `--image <answer crop path>` only when image input is enabled and an answer image path is present;
  - omits `--image` when image input is disabled or no image path exists;
  - never stores or sends base64 image data through raw persisted output.

### Smoke setup

- Infra: `make up-infra`
- Migrations: local Alembic upgrade against localhost Postgres
- Backend: host `make backend-host-dev` with `CODEX_CLI_IMAGE_INPUT_ENABLED=true`
- Frontend: host Next dev server on `localhost:3000`, readiness returned HTTP 307
- Synthetic fixture: `/tmp/ta-w1-037a/synthetic-answer.png`

### Created IDs

| Item | ID |
| --- | ---: |
| Teacher | 4092 |
| Course | 3669 |
| Assessment | 3563 |
| Question | 3078 |
| Rubric | 2072 |
| Submission | 2734 |
| Submission page | 2815 |
| Answer region | 2647 |
| Grade suggestion | 1782 |

### Smoke result

- Real Codex calls through app endpoint: exactly one `POST /answer-regions/2647/grade-codex-dev`
- `model_provider`: `codex_cli`
- `score`: `5.00`
- `confidence`: `0.9900`
- `needs_review`: true
- `review_flags`: `teacher_review_required`, `codex_cli_provider`, `image_input_used`
- Final grade before teacher action: HTTP 404, confirming no auto-finalization
- Review queue count: 1
- Summary after smoke: `total_grade_suggestions=1`, `total_final_grades=0`, `pending_review_count=1`

### Verification results

- Focused provider tests: passed (`16 passed` including provider and image-unsupported API check)
- `make test`: passed (`137 passed`)
- `make lint`: passed
- `npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- Service shutdown: passed (`make down` completed; no compose services left running)

### Known issue / observation

This validates one synthetic image-input path and mandatory teacher review. It does not validate grading quality on real handwriting, batch grading, fully automated grading, voice command, or TA-W1-038.

## TA-W2-008A browser validation closeout

- Assessment / branch: `#5242 / Demo Midterm Review`
- Browser validation confirmed: mock-grade flow reached a suggestion, `needs_review=true` was verified, teacher approval was completed manually, and XLSX export succeeded.
- Repository state at closeout: clean at commit `6d8e5f1`.
- No product code changed.
- No new task was started; this closeout records the completion of TA-W2-008A only.

## TA-W2-011 functional-body validation checkpoint

- Validation scope: full functional-body smoke after the recent core workflow additions.
- Live checks:
  - `make up`
  - `docker compose exec -T backend alembic upgrade head`
  - `make health`
  - `make frontend-health`
  - end-to-end API smoke against the live app
- Smoke flow evidence:
  - registered a teacher account
  - created course and assessment
  - created question and active rubric
  - started custom controlled grading run with `marking_policy=tough`
  - uploaded question/solution/rubric PDFs and confirmed materials
  - uploaded ZIP with 3 synthetic script submissions
  - received 1 draft answer-region suggestion from the browser/API suggestion path
  - verified the suggestion did not persist automatically
  - created 1 real AnswerRegion from the draft coordinates
  - verified `grading_ready=true`
  - ran gated mock grading
  - verified `GradeSuggestion` creation and `final_grade is None` before teacher action
  - approved the suggestion manually
  - exported final grades to XLSX and verified the export row included `marking_policy=tough` and the created `final_grade_id`
- Final outcome: validation passed; no product code changes were required for this checkpoint.
- Repository state at closeout: clean after docs updates and commit.

2026-06-01 — TA-W2-013 semi_automated grading-run mode verification
- Added semi_automated grading-run support in API/models/migration and made workflow state mode-aware.
- Updated frontend entry point, mode labels, and assessment link behavior for semi_automated runs.
- Added focused coverage for semi_automated API flow and preserved the custom controlled workflow checks.
- Verification passed: Alembic migration check, focused grading-run tests, frontend workflow static test, `make test`, `make lint`, `npm run build`, and `git diff --check`.

## TA-W2-014A backlog and validation reconciliation

|- Reconciled the backlog against committed history after the automation-loop confusion.
|- Confirmed task mapping: TA-W2-009 done (mapping improvement, commit `34ab04b`), TA-W2-010 done (answer-region suggestion prototype, commit `0678709`), TA-W2-011 done (functional-body validation checkpoint, commit `4a9fc9e`), TA-W2-012 reserved/skipped, TA-W2-013 done (semi_automated grading-run mode, commit `2f44f81`).
|- Removed stale/ambiguous backlog wording and restored clean documentation-only status tracking.
|- No product code changed in this reconciliation.

## TA-W2-014C-final — Custom controlled browser validation record

- Recorded at: 2026-06-01
- Validation type: browser smoke + live API verification after Docker runtime restoration
- Real Codex calls: 0
- Product code changes required: none
- Repository state before recording: clean

### Outcome summary

|- Docker available and stack started: yes
|- Browser smoke completed: yes
|- Course ID: `5994`
|- Assessment ID: `5844`
|- Grading run ID: `701`
|- Answer region ID: `4181`
|- Final grade ID: `1864`
|- Rubric visible/persisted: yes
|- Answer region visible/persisted: yes
|- Mock suggestion visible: yes
|- No FinalGrade before teacher action: yes
|- Approval/edit worked: yes
|- XLSX export worked: yes
|- Export bytes: `5249`
|- Final git status: clean

### Caveat

|- Browser register/login was flaky, so API registration plus token injection fallback was used after recording the browser-auth failure.

### Verification results

|- `make up`: passed
|- `docker compose exec -T backend alembic upgrade head`: passed
|- `make health`: passed
|- `make frontend-health`: passed
|- `make down`: passed
|- Final `git status --short`: clean

## TA-W2-014D — Record custom controlled browser validation and auth blocker

|- Validation-only follow-up task created after TA-W2-014C-final succeeded.
|- Scope: documentation + targeted auth investigation only.
|- Auth blocker to investigate: browser register/login flakiness that required API registration/token injection fallback.
|- No product code changed.

## TA-W2-015 — Browser auth flow reliability fix

- Recorded at: 2026-06-01
- Scope: targeted auth reliability investigation and minimal browser-automation hardening
- Real Codex calls: 0
- Product code changes required: yes, minimal

### Root cause

- The browser smoke could hit the auth forms before they were fully hydrated / ready, so the submit action occasionally failed to fire and no `/auth/login` request reached the backend.
- The issue was on the browser-automation side, not in backend credential handling: `/auth/register`, `/auth/logout`, and `/auth/me` behaved correctly once the form was driven with proper waits.

### Fix applied

- Added stable `data-testid` hooks for the register/login forms, inputs, submit buttons, current-teacher marker, and logout button.
- Added a small hydration gate so the submit buttons stay disabled until the client has mounted.
- Updated static workflow coverage to assert the new auth hooks.

### Verification results

|- `make test`: passed (`156 passed`)
|- `make lint`: passed
|- `git diff --check`: passed
|- `npm run build`: passed after restarting the stack cleanly
|- 3-cycle browser auth smoke: passed end to end
|- Backend auth logs showed register/logout/me calls; no `/auth/login` request was missing after the wait-based smoke was corrected
|- Final `git status --short`: clean before commit

### Caveat

|- The auth flow is now reliable for browser validation as long as the smoke waits for the new stable hooks / hydrated submit buttons.

## TA-W2-016A — Single real Codex grading validation

- Recorded at: 2026-06-02T07:58:22+06:00
- Baseline commit: `938804bf9550cfd6f94259754fb5e0d7c3ccafb5`
- Workflow type: manual controlled host-backend smoke with one selected answer region only
- Real Codex calls: 1 grading call through `POST /answer-regions/4281/grade-codex-dev`
- Provider used for real-grade step: `codex_cli`
- Data policy: synthetic/non-student teacher demo data only
- Product code changes required: none
- Codex CLI model compatibility: `gpt-5.5` worked; the default `gpt-5.3-codex` was rejected under the current ChatGPT-backed login

### Validation result

- HTTP result: `201 Created`
- GradeSuggestion created: yes
- `model_provider`: `codex_cli`
- `needs_review`: `true`
- `review_flags` included: `image_input_used`
- FinalGrade existed afterward: no
- Auto-finalization occurred: no
- Host backend stopped afterward: yes
- Postgres and Redis left running: yes

### Caveats

- This proves a single selected answer region only, not batch grading.
- This is not fully automated grading; teacher review remains mandatory.
- This is not a grading-quality proof.
- The run validates the real Codex path and persistence contract only.

## TA-W2-018A — Real Codex answer-region suggestion smoke

- Recorded at: 2026-06-02
- Real Codex calls: 2 suggestion attempts total
- Provider used: `codex_cli_answer_region_suggester`
- Runtime note: the answer-region suggestion smoke succeeded only when `CODEX_CLI_MODEL=gpt-5.5` was explicitly set
- Attempt 1: direct provider call against a blank synthetic page; no suggestions were returned because the page was blank
- Attempt 2: API smoke against a synthetic page with one bordered answer area; returned 1 draft suggestion
- `needs_review`: `true`
- Confidence: `0.96`
- The suggestion stayed draft-only
- No `AnswerRegion` was auto-created
- No `GradeSuggestion` was created by the suggestion endpoint
- No `FinalGrade` was created by the suggestion endpoint
- Root cause of the earlier failure: runtime model selection, not provider code
- The default `gpt-5.3-codex` is rejected under the current ChatGPT-backed login

### Validation result

- HTTP result: `200 OK`
- Draft suggestions returned: 1
- Provider warnings: none
- Summary: real Codex answer-region suggestions work when the runtime model is explicitly set to a supported value

### Caveats

- This is a suggestion smoke, not a grading-quality proof.
- This does not authorize batch real Codex.
- This does not remove the need for teacher review and acceptance.


# TA-GRADE-001 — Confirmed-packet-only grading queue scaffold

- Recorded at: 2026-06-04
- Baseline commit: `2bfa4e80c8de5d6872dd331c50d0187178dd4a25`
- Workflow type: manual controlled mode

## Scope result

TA-GRADE-001 adds scaffold-only grading queue records and endpoints. Queue creation only persists `GradingQueueRun` and eligible `GradingQueueItem` records from confirmed ready evidence packets. Refused packet states and reasons are reported. Provider execution remains blocked for future explicit work.

## Safety record

No grading was run. No Codex/OpenAI/Claude/Gemini/provider call was made. No `GradeSuggestion`, `FinalGrade`, or existing provider `GradingJob` was created by queue creation. No batch grading execution, real AI mapping, real OCR/vision provider, auto-finalization, teacher observation, private-file access, VSCode/Codex, or additional coding agent was used.

## Checks run

- `git status --short` — clean at baseline.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... alembic upgrade head` — applied `0012_grading_queue_scaffold` locally.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_grading_queue_runs_api.py -q` — 4 passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_evidence_prep_runs_api.py -q` — 6 passed.
- `node tests/workflow-ui.test.mjs && npm run build` — frontend static markers passed and Next build completed; existing ESLint flat-config warning printed during build, exit 0.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... make test` — 250 passed.
- `PATH=/tmp/ta-bin:$PATH make up` — services built/started for E2E.
- `PATH=/tmp/ta-bin:$PATH docker compose exec -T backend alembic upgrade head` — migration check passed in service container.
- health checks for backend/frontend — passed.
- Playwright Docker E2E command — first attempt failed with WSL `UtilAcceptVsock: accept4 failed 110`; retry passed with 2 tests passed.
- `git diff --check` — passed.
- `PATH=/tmp/ta-bin:$PATH make down` — services stopped and removed.


# TA-GRADE-001A — Harden grading queue staleness, rebuild, and refusal auditing

- Recorded at: 2026-06-04
- Baseline commit: `67b2e694c16ed3a8cab5fc3ed931fd5fc36cf01f`
- Workflow type: manual controlled mode

## Verifier warning reconciliation

Initial checks showed a clean worktree at the expected HEAD. `apps/api/tests/test_models_metadata.py` existed in HEAD and had no diff versus committed state, so the prior verifier warning was stale rather than a real repo issue.

## Scope result

TA-GRADE-001A adds staleness validation and richer queue/refusal audit behavior. Queue item responses now report stale/fresh status and current refusal reasons. Segment-aware snapshot hashes detect evidence edits. Rebuilding creates a new run without mutating older runs.

## Safety record

No grading was run. No Codex/OpenAI/Claude/Gemini/provider call was made. No `GradeSuggestion`, `FinalGrade`, or provider `GradingJob` was created by queue validation/rebuild. No batch grading execution, real AI mapping, real OCR/vision provider, auto-finalization, teacher observation, private-file access, VSCode/Codex, or additional coding agent was used.

## Checks run

- `git status --short` — clean at baseline.
- `git rev-parse HEAD` — `67b2e694c16ed3a8cab5fc3ed931fd5fc36cf01f`.
- `git ls-tree HEAD apps/api/tests/test_models_metadata.py` and `git diff --exit-code -- apps/api/tests/test_models_metadata.py` — file present and unchanged; previous verifier warning was stale.
- Initial focused staleness test after starting infra failed RED with `KeyError: 'stale_status'`, confirming missing behavior before implementation.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... alembic upgrade head` — database migrated before focused tests.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_grading_queue_runs_api.py -q` — 6 passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... python -m pytest tests/test_evidence_prep_runs_api.py -q` — 6 passed.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH DATABASE_URL=... make test` — 252 passed.
- `node tests/workflow-ui.test.mjs && npm run lint` — frontend static markers and TypeScript passed.
- `node tests/workflow-ui.test.mjs && npm run build` — frontend static markers passed and Next build completed; existing ESLint flat-config warning printed during build, exit 0.
- `PATH=/home/newton/teacher-assistant/.venv/bin:$PATH make lint` — backend ruff and web TypeScript checks passed.
- `PATH=/tmp/ta-bin:$PATH make up` — services built/started for E2E.
- `PATH=/tmp/ta-bin:$PATH docker compose exec -T backend alembic upgrade head` — migration check passed in service container.
- health checks for backend/frontend — passed.
- Playwright Docker E2E command — 2 passed.
- `git diff --check` — passed.
- `PATH=/tmp/ta-bin:$PATH make down` — services stopped and removed.
