# Product Roadmap

## Canonical current status — local-first milestone

Status date: 2026-08-08. This section is the canonical status for local OCR/Qwen and cohort safety; older task notes remain historical records.

- **Custom Controlled:** implemented as the only normal teacher workflow. Local PaddleOCR draft evidence and local Qwen draft grading are integrated behind disabled-by-default flags and explicit teacher actions.
- **Local services:** Windows-host llama.cpp Qwen and PaddleOCR startup/preflight/stop workflows are implemented. Reference extraction uses a sequential GPU phase: PaddleOCR runs on `gpu:0`, releases VRAM, and only then Qwen starts. CPU OCR remains available for bounded concurrent diagnostics. Normal app startup never loads a model.
- **OCR evidence:** implemented as persisted draft runs with editable teacher confirmation. Confirmation copies text only and does not mark evidence complete or accept mappings.
- **Reference extraction:** the teacher uploads question, solution/model-answer, and rubric PDFs once. `local_paddle_qwen` performs page-ordered GPU OCR followed by one bounded Qwen draft-linking call; migration `0020` persists its status and draft linkage. Existing teacher confirmation gates remain canonical.
- **Safe cohort execution:** implemented as question-wise, immutable-snapshot dispatches with exact provider/model authorization, a 25-call ceiling, sequential execution, stop-on-failure, stop/resume controls, zero automatic retries, no fallback, and draft suggestions only.
- **Teacher UI:** the old duplicate upload/extraction controls and seven-step scaffold are removed from the normal view. Reference preparation is a three-step progressive workflow; student/evidence controls stay hidden until canonical references are teacher-confirmed.
- **Verification completed:** 373 backend tests, Ruff, migration head `0020`, all PowerShell parsing, frontend type/static/production-build checks, and four browser E2E flows pass. The launcher now restarts stale API/worker processes and never replaces a Next build beneath a running server. On the supplied three-PDF reference bundle, production extraction completed five GPU OCR calls followed by one bounded Qwen call, produced exactly the seven expected leaves with linked solution pages and exact marks, and left every draft for teacher review. The engineering-only curated rehearsal achieved the OCR thresholds and 18/18 exact Qwen scores under `real-grading-v2`; a separate real adapter smoke graded a supplied-bundle question from its question, solution, rubric, and confirmed answer at the expected 6/6.
- **Verification remaining:** prepare a fresh curated run under `real-grading-v2` and complete all three mandatory teacher sign-offs. The old prepared `lc_20260807_teacher01` manifest predates the tightened prompt contract and is superseded for pilot authorization. Real cohort grading remains locked until a fresh signed run passes with no severe stop condition.
- **Semi-Automated:** experimental and disabled; local integration does not activate it.
- **Fully Automated:** unreleased and disabled; automatic mapping/finalization remain out of scope.

Operational instructions are in `docs/LOCAL_AI_RUNBOOK.md`; provider rules are in `docs/PROVIDER_USAGE_POLICY.md`.

## Started prototype: Question paper import / question extraction

Teacher uploads an image/PDF of a question paper. The system extracts question numbers, question text, marks, and possible sub-questions into draft Questions. The teacher must review and edit the drafted Questions before saving.

Important: this is not simple OCR only. It needs document understanding, question segmentation, mark detection, and teacher confirmation.

Prototype status: local `local_paddle_qwen` draft extraction is implemented in addition to deterministic/mock extraction. It is disabled by default, runs PaddleOCR locally before Qwen, and still requires draft review/edit/select and teacher-confirmed canonical creation. Cloud/Codex fallback is not enabled.

## Planned grading workflow modes

The product roadmap now separates grading into three workflow modes, documented in `docs/GRADING_WORKFLOW_MODES.md`:

1. **Custom / Controlled Grading** — teacher provides question, solution, and rubric sources; teacher finalizes canonical grading materials; system grades selected/available scripts; teacher reviews all suggestions and exports final results. This should be built first because it has the lowest ambiguity and uses teacher-provided solution/rubric materials.
2. **Semi-Automated Grading** — teacher provides question PDF and scripts; system drafts questions/model answers/rubrics; teacher confirms or edits them before batch grading; teacher reviews all suggestions. This should be built second.
3. **Fully Automated Grading** — teacher provides question PDF and script ZIP; system attempts question extraction, model-answer/rubric drafting, script processing, region mapping, and grading. This is highest risk and should be built last, after extraction and grading quality are proven.

All modes must keep teacher review mandatory. The system must not auto-finalize grades without teacher approval. Fully automated grading must not be claimed reliable yet.

Current product gating: Custom Controlled is the normal teacher workflow. Semi-Automated is experimental-only and blocked by default from normal entry points. Fully Automated is not available as a teacher workflow and should be treated as unreleased until the reactivation criteria in `docs/GRADING_WORKFLOW_MODES.md` are satisfied.

### Marking policy roadmap

Each grading run should eventually record a rubric interpretation policy:

- **Tough** — stricter on missing reasoning and ambiguous unsupported answers.
- **General** — normal rubric interpretation with equivalent methods allowed.
- **Easy** — benefit of doubt for minor notation/presentation issues while still flagging unclear work.

Build order and current state:

1. `TA-W1-035B` — Custom controlled grading run wizard: implemented.
2. Local-first OCR/Qwen and safe cohort dispatch: implemented and host-smoke verified; curated quality evaluation remains.
3. `TA-W1-038` — Marking policy recording: implemented; local 20-case calibration still required.
4. `TA-W1-036` — Semi-automated question/rubric workflow: experimental and disabled.
5. `TA-W1-037` — Fully automated ZIP grading: unreleased and disabled.

## Future extension: Voice command assistant

Teacher can use voice commands for common UI actions, such as upload, next item, approve selected, go to review, and export result.

Status: Future extension, not implemented now.
