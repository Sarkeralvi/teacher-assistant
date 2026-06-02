# Product Roadmap

## Started prototype: Question paper import / question extraction

Teacher uploads an image/PDF of a question paper. The system extracts question numbers, question text, marks, and possible sub-questions into draft Questions. The teacher must review and edit the drafted Questions before saving.

Important: this is not simple OCR only. It needs document understanding, question segmentation, mark detection, and teacher confirmation.

Prototype status: Started in TA-W1-028B. Current foundation supports safe question-paper upload, deterministic/mock draft extraction, draft question review/edit/select, and teacher-confirmed creation of real Questions. Real Codex/OCR extraction is not enabled by default.

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

Planned build order:

1. `TA-W1-035B` — Custom controlled grading run wizard.
2. `TA-W1-036` — Semi-automated question/rubric confirmation workflow.
3. `TA-W1-037` — Fully automated ZIP grading prototype.
4. `TA-W1-038` — Marking policy calibration.

## Future extension: Voice command assistant

Teacher can use voice commands for common UI actions, such as upload, next item, approve selected, go to review, and export result.

Status: Future extension, not implemented now.
