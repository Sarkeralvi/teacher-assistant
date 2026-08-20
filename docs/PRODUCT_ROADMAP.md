# Product Roadmap

## Canonical current status — local-first milestone

Status date: 2026-08-20. This section is the canonical status for local OCR/Qwen and cohort safety; older task notes remain historical records.

- **Custom Controlled:** implemented as the only normal teacher workflow. Local draft evidence and local draft grading are integrated behind disabled-by-default flags and explicit teacher actions.
- **Local models:** Qwen3.8-27B (vision, port 8085) reads pages and grades; Qwen3.6-35B-A3B (text, port 8086) correlates reference text. Only one fits in VRAM, so selecting a phase unloads the other, mediated by a single-holder model lease so one job cannot switch the model out from under another. Normal app startup never loads a model.
- **Tier-1 OCR:** RapidOCR (PP-OCRv6 ONNX) runs in-process on the CPU. It needs no VRAM, so it costs no phase switch and never contends with a resident model. Disabled by default behind `LOCAL_OCR_ENABLED`. The retired PaddleOCR sidecar and its recognition stack were removed in `26d7ad0`.
- **Reference extraction:** the teacher uploads question, solution/model-answer, and rubric PDFs once. With tier-1 OCR enabled, every page is read on the CPU, pages the reader was not confident about are escalated to Qwen3.8 in one batched window, and Qwen3.6 then correlates the resulting text. Escalation is a pre-authorized budget that stops the run when exceeded, never a silent fallback. Per-page provenance is persisted in `reference_page_ocr_runs`. Existing teacher confirmation gates remain canonical.
- **Escalation policy:** two independent triggers. Recognition confidence, and structural signals that never consult confidence, because a line recognizer confidently emits short plausible strings for display equations. Thresholds are PROVISIONAL until the bake-off is run against teacher-verified fixtures.
- **Safe cohort execution:** implemented as question-wise, immutable-snapshot dispatches with exact provider/model authorization, a 25-call ceiling, sequential execution, stop-on-failure, stop/resume controls, zero automatic retries, no fallback, and draft suggestions only.
- **Teacher UI:** the old duplicate upload/extraction controls and seven-step scaffold are removed from the normal view. Reference preparation is a three-step progressive workflow; student/evidence controls stay hidden until canonical references are teacher-confirmed. The retired PaddleOCR review panels were removed once their endpoints no longer existed.
- **Verification completed:** 415 backend tests pass (3 skipped), Ruff passes, migration head is `0024`. Platform throughput measured on the reference host: Qwen3.6 ~67 tok/s, Qwen3.8 ~4.4 tok/s on a vision call. Tier-1 OCR reads a page in ~1 s on the CPU. Orchestration is covered by fake-provider tests asserting stage order, switch count and budget enforcement.
- **Verification remaining:** the escalation thresholds are unset pending teacher-verified fixtures; only 6 unique handwriting images exist, which cannot support a dev/holdout split. The 20-case curated evaluation gate is NOT RUNNABLE - its OCR stage is not wired to the replacement pipeline - so no result from it may be cited as pilot authorization. Script-checking (page-first detection and mapping) is not built. No founder-supervised rehearsal has been completed end to end. Real cohort grading remains locked.
- **Known limitation:** tier-1 OCR drops decimal points on some handwriting (`03` for `0.3`), a 10x error in a value a mark depends on. Handwriting therefore escalates often and teacher review remains mandatory.
- **Semi-Automated:** experimental and disabled; local integration does not activate it.
- **Fully Automated:** unreleased and disabled; automatic mapping/finalization remain out of scope.

Operational instructions are in `docs/LOCAL_AI_RUNBOOK.md`; provider rules are in `docs/PROVIDER_USAGE_POLICY.md`.

## Started prototype: Question paper import / question extraction

Teacher uploads an image/PDF of a question paper. The system extracts question numbers, question text, marks, and possible sub-questions into draft Questions. The teacher must review and edit the drafted Questions before saving.

Important: this is not simple OCR only. It needs document understanding, question segmentation, mark detection, and teacher confirmation.

Prototype status: local draft extraction is implemented in addition to deterministic/mock extraction. It is disabled by default, reads pages with CPU tier-1 OCR and escalates only what that reader could not handle, and still requires draft review/edit/select and teacher-confirmed canonical creation. Cloud/Codex fallback is not enabled.

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
