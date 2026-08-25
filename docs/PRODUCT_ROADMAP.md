# Product Roadmap

## Canonical current status — local-first milestone

Status date: 2026-08-25. This section is the canonical status for local OCR/Qwen and cohort safety; older validation notes remain historical records.

- **Custom Controlled:** implemented as the only normal teacher workflow. Local draft evidence and local draft grading are integrated behind disabled-by-default flags and explicit teacher actions.
- **Active local model:** Qwen3.8-27B vision on port 8085 is the only model selectable by the supervised teacher workflow. PaddleOCR and Qwen3.6 are disabled rollback assets. Every Qwen3.8 call requires the matching fail-closed single-holder database lease; normal app startup never loads a model.
- **Reference extraction:** the teacher uploads question, solution/model-answer, and rubric PDFs once. One thinking-disabled Qwen3.8 visual task creates review-only draft references. Existing teacher confirmation gates remain canonical; there is no OCR/text-model fallback or retry.
- **Script workflow:** Qwen3.8 maps complete answer regions and ordered continuations from full pages. After separate geometry confirmation, a fresh thinking-disabled Qwen3.8 task first classifies visible cancellation/correction marks and then transcribes only the student's surviving final work. Ambiguous overwrites stay `[unclear correction]`; mathematical context cannot repair them. Mapping, transcript fidelity, and complete-answer coverage are independent gates.
- **Safe cohort execution:** implemented as question-wise, immutable-snapshot dispatches with exact provider/model authorization, a 25-call ceiling, sequential execution, stop-on-failure, stop/resume controls, zero automatic retries, no fallback, and draft suggestions only.
- **Teacher UI:** the active path is linear: Qwen3.8 reference drafts, complete script, Qwen3.8 mapping, Qwen3.8 final-intent transcription, full-answer confirmation, Qwen3.8 text-only draft grade, review, and approved-only export. Legacy Paddle/Qwen3.6 controls are removed.
- **Verification completed:** fake-provider and ownership tests cover lease enforcement, exact identity, hash-only evidence confirmation, audit privacy, and draft-only grading safeguards. Live teacher data still requires teacher confirmation and does not become a grade automatically.
- **Verification remaining:** no teacher-signed real 20-case `PASS` exists, and no signed end-to-end teacher rehearsal has completed. Engineering readiness must not be described as a quality/pilot pass.
- **Known limitation:** local OCR can misread critical handwriting symbols. The teacher must compare every transcript with the image; rejection and explicit vision rescue are safety behavior, not exceptional failure.
- **Semi-Automated:** experimental and disabled; local integration does not activate it.
- **Fully Automated:** unreleased and disabled; automatic mapping/finalization remain out of scope.

Operational instructions are in `docs/LOCAL_AI_RUNBOOK.md`; provider rules are in `docs/PROVIDER_USAGE_POLICY.md`.

## Started prototype: Question paper import / question extraction

Teacher uploads an image/PDF of a question paper. The system extracts question numbers, question text, marks, and possible sub-questions into draft Questions. The teacher must review and edit the drafted Questions before saving.

Important: this is not simple OCR only. It needs document understanding, question segmentation, mark detection, and teacher confirmation.

Prototype status: local draft extraction is implemented in addition to deterministic/mock extraction. It is disabled by default, uses one thinking-disabled Qwen3.8 visual task, and requires draft review/edit/select and teacher-confirmed canonical creation. No cloud/Codex/provider fallback is enabled.

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
