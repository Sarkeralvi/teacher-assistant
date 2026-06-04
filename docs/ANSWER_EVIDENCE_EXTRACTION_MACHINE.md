## TA-UI-001A evidence packet state hardening

TA-UI-001A makes packet status explicit before batch evidence preparation. The current source of truth is `AnswerRegion.evidence_status` with values `unconfirmed`, `complete`, `partial`, and `blank`, plus `AnswerRegion.continuation_check_status` for continuation risk/resolution. `ready_for_grading` is derived, not manually set.

Readiness policy:

- `complete` + active rubric + valid canonical grading unit + valid crop/context + contiguous confirmed segments may be ready.
- `partial` is not ready for automatic grading and requires teacher review.
- `blank` is a confirmed blank evidence packet, but it is not treated as a normal answer-ready packet; grading remains blocked until a future zero-mark blank policy is explicitly added.
- unconfirmed packets, no segment, invalid segment order, missing active rubric, invalid crop/context, or unresolved continuation risk block readiness.
- continuation-not-needed clears only the continuation blocker; it does not make a partial/blank/unconfirmed packet ready.
- add/edit/remove/reorder segment operations reopen packet confirmation because the evidence changed.

TA-BATCH-001 remains blocked until packet states are clear enough to plan batch evidence preparation. Real AI mapping and real OCR/vision remain blocked. Corrections prepare evidence only and do not create `GradeSuggestion` or `FinalGrade`.

## TA-UI-001 correction workflow update

TA-UI-001 adds the controlled teacher/founder correction path required after evaluation gates expose blockers such as missed continuation, wrong mapping, ambiguous boundary, blank/cover-page confusion, duplicate/missing page, multiple questions on one page, and incomplete answer packets. Corrections are part of evidence preparation only: they edit, add/split, remove, reorder, and confirm `AnswerRegionSegment` evidence before grading readiness is recalculated. They do not create grades, do not invoke real AI mapping, and do not invoke real OCR/vision.

Correction effects on the evidence packet:

- `segment_count` reflects the corrected confirmed segment list.
- `pages_covered` reflects corrected ordered segments.
- segment order remains contiguous after reorder/remove.
- continuation blockers clear only after explicit full-answer or continuation-not-needed confirmation.
- `ready_for_grading` can change after correction, but grading still requires the existing readiness checks.
- correction audit metadata records correction type, before/after state, teacher id, and timestamp through `AuditLog`.

# TA-CORE-002 implementation-roadmap bridge

Recorded at: 2026-06-04T12:13:40+06:00

The detailed bridge from AEEM architecture to TAAgent implementation tasks is now maintained in `docs/AEEM_IMPLEMENTATION_ROADMAP.md`. That roadmap clarifies that AEEM is being implemented in controlled slices, not as a monolithic Claude/Gemini/Codex build. The next recommended implementation remains TA-MAP-003, the mapping evaluation harness and synthetic benchmark, because real AI mapping must wait until mapping quality is measurable.

# Answer Evidence Extraction Machine (AEEM)

Status: Adopted as the north-star architecture for the pre-grading pipeline in TA-CORE-001. This document is adapted for the current Teacher Assistant repo state and founder constraints; it is not a verbatim copy of the external architecture reference.

Recorded at: 2026-06-04T11:41:53+06:00
Baseline: `451b835776de6a1f535cd9929767676bbdaa3637` (`Add deterministic answer mapping provider`)

## Purpose

The Answer Evidence Extraction Machine turns exam reference material and student scripts into verified, question-wise `EvidencePacket[]` records per student/question before any grading quality claim is made.

Target flow:

```text
question / solution / rubric documents + ZIP/PDF student scripts
  -> confirmed canonical grading units
  -> ordered student script pages
  -> extracted answer evidence segments
  -> grouped multi-page answer packets
  -> readiness-gated EvidencePacket[]
  -> grading queue only after confirmed evidence completeness
```

AEEM does not assign marks, compare students, finalize grades, or tune grading prompts. Its output is confirmed evidence for downstream teacher-reviewed grading.

## Evidence-first, grading-last principle

No grading quality claim is valid unless the evidence is confirmed complete first. Before grading, the system must confirm:

1. question understanding / OCR;
2. solution or model-answer understanding / OCR;
3. rubric understanding / OCR;
4. canonical grading-unit label and max marks;
5. student script page ordering;
6. answer-region extraction;
7. multi-page continuation grouping;
8. evidence packet readiness.

AI/OCR may propose. Teacher/founder confirmation is required before grading until benchmark evidence proves a narrower safe automation boundary. Even high confidence means **ready for teacher review**, not auto-accepted, for real scripts in the current product.

## Current project state and why the pivot happened

Current repo state after TA-MAP-002:

- deterministic/mock multi-segment answer mapping provider exists;
- multi-segment `AnswerRegion` / `AnswerRegionSegment` evidence exists;
- evidence packet readiness gate exists;
- suggestion/acceptance paths are draft-first and teacher-controlled;
- real AI mapping has not started;
- batch real grading is not approved;
- teacher observation is not started by this architecture reset.

The pivot happened because the controlled `1(b)(i)` episode showed that a grading result can be invalid even when the model response appears plausible: the selected evidence can be incomplete. The product therefore needs an evidence-machine quality program before real AI mapping, batch grading, or prompt tuning.

## The 1(b)(i) evidence-boundary lesson

The key lesson is not private content-specific. It is architectural:

- one logical answer may span multiple pages;
- a page-local rectangle can miss continuation evidence;
- a wrong or partial answer region invalidates grading-quality interpretation;
- continuation risk must be explicit;
- full-answer confirmation is required before grading;
- no teacher-trust claim should be made from an unconfirmed crop or packet.

## Reference processing arm

The reference arm builds the canonical grading-unit registry for an assessment.

### Question parser

- Render and parse the question paper.
- Extract candidate question labels, subpart structure, question text, and max marks.
- Preserve raw parse/OCR provenance.
- Keep provider abstraction: deterministic/mock, OCR, document AI, or vision model can be added behind explicit gates.

### Solution parser

- Parse model-answer / solution documents.
- Link solution evidence to canonical grading-unit candidates.
- Preserve model-answer text/reference and source page provenance.

### Rubric parser

- Parse rubric criteria and marks.
- Validate that rubric criteria totals match the canonical grading unit max marks.
- Block readiness when active rubric evidence is absent or inconsistent.

### Canonical grading unit builder

Build one scoreable unit per grading target, such as `1(b)(i)`, with:

- label and label variants;
- parent/child relation where needed;
- max marks;
- question text;
- solution/model-answer reference;
- active rubric criteria;
- confirmation status.

The current repo stores these as `Question` rows plus rubric/model-answer fields. AEEM can evolve this into a richer CGU registry without weakening the existing evidence packet gate.

### TA-REF-001 evaluation harness

TA-REF-001 adds the first executable benchmark for this reference arm. It is evaluation-first only: it does not implement real OCR/vision extraction, does not call Codex, does not create product `Question`/rubric records, and does not grade.

Fixture format lives under `apps/api/packages/evaluation/fixtures/reference_extraction/`. Each synthetic case records:

- `case_id` and `description`;
- involved document types: `question`, `solution`, and/or `rubric`;
- expected canonical grading units with labels, max marks, question text, parent labels, solution requirement, and visual-confirmation requirement;
- expected solution/model-answer sections;
- expected rubric criteria per grading unit;
- expected total-mark validation result;
- expected blockers/warnings and teacher-confirmation requirement;
- saved deterministic provider output for `synthetic_reference_extractor`.

The evaluator reports label exact-match accuracy, max-mark exact-match accuracy, parent/child structure accuracy, question-text completeness, solution-section mapping accuracy, rubric-criteria extraction accuracy, rubric-total match accuracy, duplicate-label detection, missing-solution detection, missing-rubric detection, visual-confirmation detection, unsafe auto-confirm count, `GradeSuggestion` count, and `FinalGrade` count.

Critical reference blockers are max-mark mismatch, missing rubric, missing required solution/model answer, unresolved duplicate labels, extracted label mismatch, unsafe auto-confirm, and any `GradeSuggestion` or `FinalGrade` creation during reference extraction. Reviewable warnings include low OCR confidence, image-only math requiring visual confirmation, ambiguous teacher-reviewable text, and optional solution notes missing.

Wrong reference extraction poisons mapping and grading: if labels, max marks, solution/model answers, or rubric criteria are wrong, later answer-region mapping can be attached to the wrong CGU and any grading-quality claim becomes invalid.

### Teacher confirmation

Gate R1 blocks script-side grading readiness until the teacher/founder confirms:

- all intended grading units exist;
- labels and max marks are correct;
- solution/model-answer evidence is attached;
- rubric totals match the grading unit;
- no hidden or duplicate grading units exist.

## Script processing arm

The script arm processes each student script independently.

### ZIP/PDF intake

- Accept founder/teacher-approved ZIP/PDF/image inputs.
- Validate file type and integrity.
- Create a manifest of source files and generated pages.
- Do not commit raw PDFs, rendered pages, crops, screenshots, exports, or private artifacts.

### Page rendering

- Render PDFs/images to page images through storage adapters.
- Preserve original file references and relative generated paths.
- Keep rendered pages private/ignored unless explicit publication is approved.

### Cleanup / deskew / rotation

Future implementation should normalize page orientation, skew, contrast, and noise. This is a prerequisite for reliable OCR/layout evaluation but is not implemented by TA-CORE-001.

### Student/script identification

- Detect or confirm student/script identity.
- Low-confidence or conflicting identity enters teacher review.
- Scripts must remain isolated; one student's evidence must not leak into another student's grading context.

### Page sequencing

- Resolve logical page order from printed numbers, physical PDF order, and anomaly checks.
- Detect gaps, duplicates, reversed uploads, and inserted pages.
- Teacher confirmation is required when sequence confidence is not benchmark-proven.


### TA-SCRIPT-001 evaluation harness

TA-SCRIPT-001 adds the first executable benchmark for the script-processing arm. It is evaluation-first only: it does not implement real OCR/vision page sequencing, does not call Codex, does not run real AI mapping, does not use private scripts, and does not grade.

Fixture format lives under `apps/api/packages/evaluation/fixtures/script_processing/`. Each synthetic case records:

- `case_id` and `description`;
- pages with source index, expected logical page number, and page kind;
- source order and expected logical order;
- expected blank/cover classifications;
- expected detected labels;
- expected answer boundaries and ordered page segments;
- expected continuation signals;
- expected missing/duplicate page blockers or warnings;
- expected teacher-confirmation requirement;
- saved deterministic provider output for `synthetic_script_processor`.

The evaluator reports page-order accuracy, missing-page detection, duplicate-page detection, blank/cover classification accuracy, detected-label count accuracy, answer-boundary count accuracy, boundary page coverage accuracy, boundary order accuracy, continuation-signal accuracy, false continuation count, missed continuation count, unsafe auto-confirm count, `GradeSuggestion` count, and `FinalGrade` count.

Critical script blockers are missed continuation, wrong page order accepted as ready, missing page, duplicate page, blank/cover page mapped as a confident answer, unsafe auto-confirm, and any `GradeSuggestion` or `FinalGrade` creation during script processing. Reviewable warnings include ambiguous boundaries requiring teacher confirmation, low-confidence labels, near-bottom complete answers flagged for review but not falsely confirmed, and non-sequential student answering patterns.

The previous `1(b)(i)` evidence failure proves why missed continuation is critical: if page sequencing or boundary grouping loses continuation context, grading quality cannot be interpreted even when reference extraction is correct.

### Question boundary detection

- Detect question labels and content blocks.
- Map labels to confirmed canonical grading units.
- Flag unresolved labels, wrong-question traps, overlapping regions, and multi-question page confusion.

### Answer-region extraction

- Propose page-local evidence segments for each grading unit.
- Use OCR/layout/vision/provider abstractions later; deterministic fixtures remain acceptable for benchmark construction.
- Suggestions remain draft-only until teacher action.

### Multi-page grouping

- Group one logical answer into ordered segments across pages.
- Track continuation risk: none, possible, included, not needed, or ambiguous.
- Require explicit resolution of possible/ambiguous continuation before grading.

## Evidence packet assembler

The assembler creates the question-wise packet from confirmed reference evidence and confirmed script evidence:

- assessment/submission context;
- canonical grading unit label and max marks;
- question evidence;
- solution/model-answer evidence;
- rubric evidence;
- ordered student answer segments and crops/context;
- continuation status;
- readiness blockers/warnings;
- teacher/founder full-answer confirmation.

The current `grading-evidence-packet` endpoint is the existing repo foundation for this assembler.

## Readiness gates

Minimum AEEM gates:

| Gate | Meaning | Blocks when |
| --- | --- | --- |
| R1 | CGU/reference confirmed | question, max marks, solution, or rubric is missing/unconfirmed |
| S1 | student/script identity confirmed | identity is missing, conflicting, or low-confidence |
| S2 | page sequence confirmed | page order has gaps, duplicates, or unresolved ambiguity |
| S3 | question boundaries mapped | labels/regions are unresolved or likely assigned to the wrong grading unit |
| S4 | continuations resolved | continuation risk is possible/ambiguous and unconfirmed |
| S5 | packets assembled | any student×CGU packet is missing or unknown |
| S6 | completeness confirmed | packet is not marked complete/blank/partial by teacher/founder |
| FINAL | grading release | any prior gate is unresolved or teacher sign-off is absent |

For the current repo, the immediate enforceable gate is the evidence packet readiness check before grading provider/job creation. Broader gates are follow-up implementation tasks, not implemented here.

## Teacher correction workflow

Teacher correction must support:

- accept suggestion;
- reject suggestion;
- edit bounding box;
- split a segment;
- merge segments;
- reorder segments;
- add missed segment;
- reassign grading unit;
- mark blank;
- mark partial;
- mark complete/full answer confirmed.

Corrections should produce an audit trail with before/after state, actor, timestamp, and comment where practical. In the current repo this is a product gap; TA-UI-001 is the planned task.

## Batch behavior

Batch behavior is evidence preparation first, grading last:

- process each script independently;
- failures enter a quarantine/review queue instead of blocking the whole batch;
- no real-provider batch grading before confirmed packets;
- no `GradeSuggestion` or `FinalGrade` creation during evidence extraction;
- downstream grading queue should be question-wise from confirmed packets, not a hidden whole-script auto-grading loop.

## Evaluation strategy

Before real AI mapping, build evaluation harnesses and benchmark datasets.

Required benchmark coverage:

- one-page answer;
- answer continues to next page;
- possible continuation that turns out closed;
- wrong/partial mapping;
- multi-question page confusion;
- missing page / reversed pages;
- blank skipped answer;
- diagram/equation-heavy answer;
- low-contrast or skewed page;
- inconsistent labels.

Suggested metrics:

- question-label accuracy;
- page-sequence accuracy;
- segment recall and precision;
- bounding-box IoU against annotation;
- continuation recall/F1;
- false continuation rate;
- wrong-question assignment rate;
- packet readiness false-positive/false-negative rate;
- teacher correction burden.

Do not claim "100% AI OCR." The target is **100% confirmed evidence before grading**.

## Risk register

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Incomplete answer evidence | Critical | continuation gates, multi-segment packets, teacher confirmation |
| Wrong CGU label/max marks | Critical | reference arm confirmation and total-mark checks |
| Page-order error | High | sequencing benchmark and teacher review gate |
| Fake deterministic success misread as AI quality | High | evaluation harness before real provider |
| High-confidence auto-accept on real scripts | High | forbidden for now; high confidence means ready for review |
| Private artifact exposure | High | ignored storage, no artifact commits, provider abstraction/privacy review |
| Vendor lock-in | Medium | OCR/vision/provider abstraction, no hardcoded single vendor |
| Overbuilding sealed store too early | Medium | record sealing/hash store as future; current focus is confirmed packet readiness |
| Teacher rubber-stamping | Medium | correction UX, explicit stop conditions, audit log, review burden metrics |
| Batch grading drift | High | batch evidence prep first; question-wise grading queue only from confirmed packets |

## Implementation phases

1. **TA-CORE-001 — Adopt AEEM architecture and reset implementation sequence.** Docs/backlog reset only.
2. **TA-MAP-003 — Mapping evaluation harness and synthetic benchmark.** Measure mapping contract quality before real provider work.
3. **TA-REF-001 — Question/solution/rubric extraction evaluation harness.** Measure reference-arm extraction and CGU correctness.
4. **TA-SCRIPT-001 — Script page sequencing and answer-boundary benchmark.** Build page-order and boundary benchmark coverage.
5. **TA-MAP-004 — Real AI mapping provider behind evaluation gate.** Add provider only after benchmark definitions exist.
6. **TA-UI-001 — Teacher correction workflow for split/merge/reorder/confirm.** Make human correction practical and auditable.
7. **TA-BATCH-001 — Batch evidence packet preparation.** Prepare packets, quarantine failures, no grading side effects.
8. **TA-GRADE-001 — Question-wise grading queue from confirmed packets.** Start grading integration only from confirmed evidence packets.

## Explicit modifications to the external AEEM reference

Adopted:

- evidence-first, grading-last principle;
- two-arm reference/script architecture;
- evidence packet assembler;
- readiness gates;
- teacher correction workflow;
- batch quarantine / independent script processing;
- benchmark-first strategy.

Modified or rejected for this repo now:

- rejected real-script auto-accept, even at high confidence;
- changed high confidence to "ready for teacher review," not accepted;
- marked cryptographic sealed store as future, not current implementation;
- kept OCR/vision provider abstraction instead of hardcoding one vendor;
- replaced "100% AI OCR" style claims with "100% confirmed evidence before grading";
- did not start real AI mapping, batch grading, prompt tuning, teacher observation, or product-code implementation in TA-CORE-001.
## TA-MAP-003 executable mapping benchmark

TA-MAP-003 adds the first executable AEEM safety net for answer-boundary evidence. The benchmark is synthetic JSON only and lives under `apps/api/packages/evaluation/fixtures/answer_mapping/`. The evaluator is provider-agnostic and compares draft mapping provider output to expected `EvidencePacket`-oriented answer groups before real AI mapping is allowed.

The benchmark covers single-page complete answers, multi-page continuations, near-bottom no-continuation cases, ambiguous possible continuation, multiple questions on one page, wrong-question traps, and blank/low-content pages. Metrics include question-label, group, segment, order, page coverage, continuation-risk, wrong-question, blank-page, full-answer-confirmation, unsafe auto-accept, `GradeSuggestion`, and `FinalGrade` counts.

Current result: the deterministic/mock provider is useful contract plumbing but is not a production mapper. It passes only the cases matching its deliberately simple behavior and fails realistic traps such as multi-question page confusion, wrong-question detection, and blank/low-content pages. Real AI mapping remains blocked until benchmark expectations and follow-up gates are accepted.

## TA-BATCH-001 batch evidence preparation scaffold

TA-BATCH-001 adds batch evidence packet preparation only. It organizes the current assessment into student × canonical-grading-unit packet summaries and reports readiness/quarantine state before any grading queue exists. The scaffold records `BatchEvidencePrepRun` metadata for assessment, teacher, status, total submissions, expected packet count, ready count, blocked count, warning count, blank count, and partial count.

Per-packet summaries include submission id, student identifier, grading-unit label, max marks, packet status, continuation status, readiness, blockers, warnings, segment count, and pages covered. Quarantine blockers include unknown page order, missing answer region/segment, unconfirmed packet, partial packet, blank packet under current policy, possible continuation not confirmed, missing active rubric, invalid segment order, and missing crop/context.

This is not batch grading. It creates no `GradeSuggestion`, no `FinalGrade`, no grading job, no real Codex job, and no real AI/OCR work. Real providers remain blocked behind the evaluation gates.
