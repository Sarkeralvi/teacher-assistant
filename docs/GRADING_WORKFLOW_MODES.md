# Grading Workflow Modes

## Purpose

Define the product architecture and roadmap for three grading workflow modes:

1. Fully Automated Grading
2. Semi-Automated Grading
3. Custom / Controlled Grading

This is a planning document only. It does not enable automatic final grading, ZIP upload, answer-region auto-detection, voice commands, or any new product behavior.

## Non-negotiable safety rules

- Teacher review remains mandatory for every AI-generated grade suggestion.
- The system must never auto-finalize grades without teacher approval.
- Fully automated grading must not be treated as reliable until extraction, region mapping, and grading quality are proven on mixed teacher-marked original documents.
- Real provider grading must remain explicitly opted in and bounded during evaluation.
- Every grade suggestion must record its source mode, marking policy, model/provider metadata, prompt version, confidence, review flags, and whether image input was used.
- Raw student scripts, page images, crops, and provider artifacts must stay in controlled storage and must not be committed to the repository.

## Mode comparison

| Mode | Primary inputs | Automation level | Teacher confirmation points | Risk level | Intended first use |
|---|---|---|---|---|---|
| Fully Automated | Question PDF + ZIP of all student scripts | Highest: extract questions, draft model answers/rubrics, process scripts, map regions, grade all | Review all AI results before finalization; optional review of generated question/rubric drafts before grading should still be supported | Highest | Last, after quality evidence is strong |
| Semi-Automated | Question PDF + ZIP of all student scripts | Medium: draft questions/model answers/rubrics, then batch grade after teacher confirmation | Teacher confirms question discretization, model answer, rubric, and marking strictness before grading; then reviews all grade suggestions | Medium | Second |
| Custom / Controlled | Question PDF + answer/script PDFs or ZIP + solution PDF + rubric PDF | Lowest: import each source separately, teacher finalizes canonical grading materials, then system grades | Teacher finalizes questions, model answers, rubrics, and marking policy before grading; then reviews all suggestions | Lowest | First |

## Current product gating

- **Custom / Controlled** is the active teacher-ready workflow and remains available in the normal product surface.
- **Semi-Automated** is experimental groundwork only. It is blocked by default and hidden from the normal teacher entry point so it does not look production-ready.
- **Fully Automated** is not available for teacher workflow yet and is rejected/hidden so its presence in planning docs is not mistaken for a usable mode.

Reactivation criteria for future work:

1. Answer-region detection validated on multiple pages and layouts.
2. Solution/rubric generation validated on real teacher-marked examples.
3. E2E coverage added for the re-enabled mode path.
4. Teacher review gates preserved end to end.

## Mode 1 — Fully Automated Grading

### Inputs required

- Question PDF.
- ZIP file containing all student scripts.

### Expected outputs

- Draft extracted/discretized questions and sub-questions.
- Draft model answers for each question.
- Draft rubric for each question.
- Processed student submissions and page images.
- Detected or mapped answer regions where possible.
- AI grade suggestions for all mapped answer regions.
- Teacher-review queue with confidence, review flags, and marking policy per suggestion.
- Teacher-approved final grades and export after manual approval only.

### Workflow

1. Teacher uploads a question PDF and a ZIP of scripts.
2. System extracts and discretizes multiple questions/sub-questions.
3. System drafts model answers and rubrics for each question.
4. System processes all scripts into submissions/pages.
5. System attempts answer-region detection and question-to-region mapping.
6. System grades mapped regions using the selected marking policy.
7. System sends all AI results to teacher review.
8. Teacher approves/edits/rejects suggestions.
9. System exports final results only after teacher approval.

### Teacher confirmation points

- At minimum: every final grade.
- Strongly recommended before broad use: teacher reviews draft question/rubric extraction before grading.
- Teacher selects or confirms marking policy: Tough, General, or Easy.

### Risk level

Highest. This mode compounds errors from question extraction, model-answer generation, rubric generation, ZIP/script processing, answer-region detection, question-region mapping, and AI grading.

## Mode 2 — Semi-Automated Grading

### Inputs required

- Question PDF.
- ZIP file containing all student scripts.

### Expected outputs

- Draft extracted questions/sub-questions.
- Draft model answers.
- Draft rubrics.
- Teacher-confirmed canonical questions/model answers/rubrics.
- Batch AI grade suggestions after confirmation.
- Teacher-reviewed final grades and export.

### Workflow

1. Teacher uploads a question PDF and ZIP of scripts.
2. System extracts draft questions.
3. System prepares draft model answers and rubrics.
4. Teacher confirms/edits:
   - question discretization,
   - model answer,
   - rubric,
   - marking strictness.
5. System processes scripts and creates or assists answer-region mapping.
6. System grades scripts in batch using confirmed materials.
7. System sends all results to teacher review.
8. Teacher finalizes and exports.

### Teacher confirmation points

- Question discretization before grading.
- Model answer before grading.
- Rubric before grading.
- Marking policy before grading.
- Every final grade after grading.

### Risk level

Medium. The teacher blocks the highest-risk AI-generated grading materials before grading begins, but script processing and region mapping still carry risk.

## Mode 3 — Custom / Controlled Grading

### Inputs required

- Question PDF.
- Answer/script PDFs or ZIP.
- Solution PDF.
- Rubric PDF.

### Expected outputs

- Separately imported question, solution, and rubric drafts.
- Teacher-finalized canonical questions/model answers/rubrics.
- Uploaded submissions and mapped answer regions.
- AI grade suggestions for available scripts.
- Teacher-reviewed final grades.
- XLSX export after teacher finalization.

### Workflow

1. Teacher uploads/imports question PDF.
2. Teacher uploads/imports solution PDF.
3. Teacher uploads/imports rubric PDF.
4. System parses or stages each source separately.
5. Teacher finalizes:
   - question list and sub-question boundaries,
   - model answers,
   - rubrics and mark allocation,
   - marking policy.
6. Teacher uploads answer/script PDFs or a ZIP when ZIP support exists.
7. System processes available scripts.
8. Teacher or system maps answer regions; early builds should prefer manual/controlled mapping.
9. System grades all selected/available mapped regions.
10. Teacher reviews all suggestions.
11. Teacher exports final result.

### Teacher confirmation points

- All canonical grading materials before grading.
- Marking policy before grading.
- All final grades after grading.

### Risk level

Lowest. It uses teacher-provided solution/rubric and explicit confirmation, reducing ambiguity before grading.

## Marking policy design

Marking policy is a rubric interpretation setting, not a replacement for the rubric. All modes must record the selected policy for every grading run and suggestion.

| Policy | Interpretation |
|---|---|
| Tough | Penalize missing reasoning; penalize ambiguous or unsupported final answers; lower confidence when work is unclear; avoid benefit-of-doubt scoring when evidence is weak. |
| General | Follow rubric normally; allow standard equivalent methods; grade according to visible reasoning and final answer. |
| Easy | Give benefit of doubt for minor notation/arithmetic presentation issues; accept equivalent reasoning when the final answer is close; still flag unclear or unsupported work for teacher review. |

Implementation implication: prompts and persisted grading metadata should include `marking_policy` with allowed values such as `tough`, `general`, and `easy`.

## Existing app capabilities that already support these modes

- Question paper import/extraction foundation.
- Teacher review/edit/select flow for drafted questions.
- Answer/script upload and PDF-to-page-image processing.
- Answer-region creation and crop storage.
- Codex grading through the Brain Adapter / provider path.
- Grading evaluation harness with capped real-provider runs.
- Teacher review/final-grade workflow.
- Batch mock grading.
- Selected batch approval.
- XLSX export.

## Missing capabilities

- ZIP upload and multi-script unpacking workflow.
- Robust answer-region auto-detection.
- Reliable question-to-answer-region mapping across varied scripts.
- Separate solution PDF import/parsing pipeline.
- Separate rubric PDF import/parsing pipeline.
- Mode selection persisted on assessments/grading runs.
- Marking policy persisted and passed into grading prompts.
- Batch real-provider grading controls for production use.
- Teacher-facing wizard that guides source import, confirmation, grading, review, and export.
- Evaluation datasets covering partial, wrong, blank, irrelevant, messy, and ambiguous original-document cases.
- Quality dashboards by mode, policy, question, script, and review flag.

## Recommended build order

1. Custom / Controlled mode first.
2. Semi-Automated mode second.
3. Fully Automated mode last.

### Why this order

Custom / Controlled mode has the lowest ambiguity because the teacher can provide the question paper, solution PDF, and rubric PDF separately, then finalize canonical grading materials before any AI grading. It most directly builds on the original-document smoke test and current answer-region/evaluation path.

Semi-Automated mode should come second because it adds AI draft creation for questions/model answers/rubrics but keeps teacher confirmation before grading. This adds useful automation without trusting unconfirmed AI-generated grading materials.

Fully Automated mode should come last because it has the highest risk. It depends on reliable question extraction, model-answer generation, rubric generation, ZIP processing, answer-region detection, answer mapping, and grading. It should wait until extraction and grading quality are proven on mixed teacher-marked original documents.

## Data model implications

Future implementation should consider adding or extending records for:

- `grading_workflow_mode`: `custom_controlled`, `semi_automated`, `fully_automated`.
- `marking_policy`: `tough`, `general`, `easy`.
- `source_document_type`: question, solution, rubric, script, zip batch.
- Import job records for each source document.
- Draft-vs-confirmed state for questions, model answers, and rubrics.
- Grading run records that capture mode, policy, provider, prompt version, case count, and safety flags.
- Region mapping status: manual, detected, confirmed, pending, failed.
- Per-suggestion review status and finalization status.

## API implications

Likely future API additions:

- Create/update assessment workflow mode.
- Upload/import source documents by type.
- Confirm question/model-answer/rubric drafts.
- Select marking policy before grading.
- Start controlled grading run for confirmed materials only.
- Upload ZIP and create submissions after ZIP support is intentionally implemented.
- List import/grading run status and review queues.
- Export final results only from teacher-approved final grades.

API guardrails:

- Reject grading runs when required teacher confirmations are missing.
- Reject final-grade creation without explicit teacher approval.
- Preserve current real-provider opt-in and case caps for evaluation paths.

## UI implications

A future wizard should show mode-specific steps:

- Mode picker with clear risk labels.
- Required input checklist per mode.
- Source document import status.
- Question/model-answer/rubric confirmation screen.
- Marking policy selector with Tough/General/Easy explanations.
- Script processing and answer-region mapping screen.
- Batch grading launch screen with safety summary.
- Teacher review queue with confidence, policy, flags, and source images.
- Export screen after finalization.

Initial UI work should focus on Custom / Controlled mode and avoid promising reliable full automation.

## Evaluation implications

Each mode and marking policy needs separate evaluation evidence:

- Exact match rate.
- Within-1-mark rate.
- Mean absolute error.
- False-confident error count.
- Severe error count.
- Over-score and under-score counts.
- Needs-review rate.
- Breakdown by question, script, answer type, workflow mode, and marking policy.

Evaluation should include mixed real/original teacher-marked cases, not only full-score correct cases. The false-confident over-score found in TA-W1-034A should be treated as evidence that review flags and teacher approval are mandatory.

## Next implementation proposal

Next: `TA-W1-035B — Custom controlled grading run wizard`.

Future sequence:

- `TA-W1-036 — Semi-automated question/rubric confirmation workflow`.
- `TA-W1-037 — Fully automated ZIP grading prototype`.
- `TA-W1-038 — Marking policy calibration`.
