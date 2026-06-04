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
