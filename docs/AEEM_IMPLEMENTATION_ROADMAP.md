## TA-GRADE-000 completion note

TA-GRADE-000 defines the confirmed-packet-only grading queue contract before TA-GRADE-001. This is a documentation/contract gate, not grading implementation. It makes the AEEM boundary explicit: batch evidence preparation produces readiness/quarantine evidence, while a future grading queue may only accept confirmed ready packets and must refuse all blocked/missing/partial/blank/unconfirmed evidence.

TA-GRADE-001 remains blocked until this contract is accepted. It is safe to plan only as a separate approved task, with tests proving queue creation has no grading/provider side effects and refuses every non-ready packet state.

## TA-BATCH-001A completion note

TA-BATCH-001A strengthens the AEEM batch-prep gate before grading queue work. Batch evidence preparation now treats expected packets as the Cartesian product of submissions and canonical grading units, then marks each slot ready or quarantined. This prevents silently ignoring missing answer regions.

The mixed-state backend test covers two submissions × three grading units and includes one ready packet, one missing answer region, one unconfirmed packet, one partial packet, one blank packet, one unresolved possible continuation, and missing active rubric blockers. Exact expected count is 6, with 1 ready, 5 blocked, 5 warning packets, 1 partial, and 1 blank.

TA-GRADE-001 should not start automatically. It is safer to plan after this gate remains green, but it still needs explicit approval and must consume only confirmed ready packets.

## TA-UI-001A completion note

TA-UI-001A hardens the evidence packet readiness layer before batch evidence preparation. Evidence packets now distinguish `unconfirmed`, `complete`, `partial`, and `blank`; continuation status is tracked separately; and readiness is derived from explicit packet status plus active rubric, canonical grading unit, crop/context, confirmed segment count, contiguous segment order, and continuation blockers. Segment corrections reopen confirmation, while continuation-not-needed clears only the continuation blocker.

This keeps TA-BATCH-001 as a planning candidate, not an automatically started task. Batch evidence preparation is safer to plan now because packet states are explicit, but it still requires a separate approved task. Real AI mapping/OCR remains blocked.

## TA-UI-001 completion note

TA-UI-001 is implemented as the first rough correction workflow between evaluation gates and grading. Backend correction endpoints now require auth and teacher ownership, reject cross-assessment/cross-teacher segment edits, keep page/question/submission boundaries safe, maintain contiguous segment order, and write lightweight audit records. The assessment detail review queue exposes numeric controls for editing bbox values, adding/splitting a segment, removing a segment, moving segments up/down, confirming full answer, marking continuation not needed, and marking partial/needs review.

This keeps real AI mapping and real OCR/vision blocked. The recommended next work should be a focused refinement task, not TA-MAP-004 by default, unless the founder explicitly wants planning only for a real provider. Good next candidates are: harden correction UX with better page/segment preview, add explicit blank/partial packet state, or improve deterministic fixture behavior where harness sanity needs it.

# AEEM Implementation Roadmap

Status: TA-CORE-002 bridge document. This maps the adopted Answer Evidence Extraction Machine architecture to the actual controlled implementation sequence in TAAgent.

Recorded at: 2026-06-04T12:13:40+06:00
Baseline: `52bd4ffb0950d841a22e0bb721585b2faebb5daa` (`Adopt answer evidence extraction architecture`)

## Plain answer to the founder concern

We are implementing the full AEEM direction, but not as one monolithic build and not by jumping straight to Claude/Gemini/Codex-style real AI mapping.

The implementation strategy is controlled slices:

1. preserve the existing safe teacher-reviewed product paths;
2. measure evidence extraction quality before adding real AI/OCR providers;
3. add real providers only behind benchmark/evaluation gates;
4. prepare batch evidence packets before any batch grading;
5. grade only from confirmed question-wise evidence packets.

So the project is **not abandoning AEEM** and is **not simply continuing the old TA-MAP plan**. TA-MAP now becomes one AEEM layer: answer boundary detection and multi-page grouping. The broader AEEM roadmap also includes reference understanding, script sequencing, teacher correction, batch evidence preparation, and question-wise grading queues.

## Implementation philosophy

- We are implementing the full AEEM architecture in controlled slices.
- We are not building the full machine monolithically.
- We will not build real AI mapping before evaluation harnesses exist.
- We will not run batch grading before evidence packet correctness is measurable.
- We will not claim grading quality unless question, solution/model-answer, rubric, canonical grading unit, page order, answer region, continuation, and readiness evidence are confirmed complete.
- For real scripts, high confidence means ready for teacher review, not auto-accepted.
- Teacher/founder confirmation remains required until benchmark evidence justifies a narrower automation boundary.

## AEEM layer-to-roadmap map

| AEEM layer | Current TAAgent status | Missing pieces | Next task | Why this order |
| --- | --- | --- | --- | --- |
| 1. Intake / ZIP upload / page rendering | Single PDF/image submission upload and page rendering exist. Local storage and page metadata exist. ZIP/batch intake is not the current production path. | ZIP manifesting, batch unpacking, integrity checks, duplicate detection, stronger private artifact policy enforcement in batch flows. | TA-BATCH-001 after evidence benchmarks; minor intake work may appear inside TA-SCRIPT-001 fixtures. | Intake is useful, but batch intake should not outrun page sequencing/evidence readiness. |
| 2. Question paper understanding | Question import prototype exists with deterministic/simple extraction and gated Codex question extraction history. Manual question creation remains available. | Evaluation harness for OCR/extraction correctness, field-level metrics, reliable subpart parsing, provider abstraction maturity, teacher-confirmed CGU registry. | TA-REF-001 | Reference errors invalidate every grading result, so extraction quality must be measured before relying on providers. |
| 3. Solution/model answer understanding | Model-answer text/reference can be stored with questions; evidence packet reports model-answer presence. | Dedicated solution parser/evaluator, source-page provenance, OCR confidence, confirmation workflow. | TA-REF-001 | Solution/model answer is part of the same reference arm as question/rubric extraction. |
| 4. Rubric understanding | Rubric schema validation and active rubric workflow exist; evidence packet checks active rubric presence. | Rubric OCR/parser evaluation, criterion extraction metrics, reference provenance, cross-check against CGU max marks after OCR. | TA-REF-001 | Rubric mistakes cause wrong grading even when answer mapping is correct. |
| 5. Canonical grading units | Flat `Question` rows support labels/max marks; canonical grading-unit confirmation exists through the controlled question/rubric workflow. | Rich CGU registry with label variants, parent/child structure, extraction provenance, versioning/sealing, confirmation state. | TA-REF-001 | CGU correctness anchors both mapping and grading; evaluate it before provider reliance. |
| 6. Student/script identification | Submission has a student identifier field/manual identity path. | OCR/barcode/name extraction, identity confidence, unresolved identity queue, benchmark cases. | TA-SCRIPT-001 or later identity-specific slice | Page/script benchmarks come before broader batch identity automation; current manual identity is enough for controlled tests. |
| 7. Page sequencing | Submission pages have page numbers from rendering order. | Logical page order detection, gap/duplicate/reversed-page handling, teacher confirmation, sequencing metrics. | TA-SCRIPT-001 | Continuation grouping cannot be trusted if page order is unmeasured. |
| 8. Answer boundary detection | Manual regions, deterministic/mock mapping suggestions, and draft segment contract exist. | Real layout/OCR/vision boundary detection, wrong-question trap detection, multi-question page benchmark, bbox quality metrics. | TA-MAP-003 first; TA-MAP-004 later | Build the mapping evaluation harness before a real provider so provider quality can be measured. |
| 9. Multi-page continuation grouping | Multi-segment `AnswerRegionSegment` support exists; possible continuation and continuation-included states exist; evidence packet sees segment count/pages. | Benchmark for missed/extra continuation, ambiguous chains, next-page wrong-question trap, teacher correction UX. | TA-MAP-003, then TA-UI-001 | This was the discovered failure, so measure it first and make correction practical before real mapping. |
| 10. Evidence packet readiness gate | Existing `grading-evidence-packet` endpoint and backend readiness gate block grading when evidence is missing/incomplete. | Broader AEEM gates for reference, identity, page sequencing, boundary mapping, continuations, batch sign-off, packet versioning. | TA-MAP-003/TA-REF-001/TA-SCRIPT-001 feed into gate expansion | The gate exists; now the missing inputs need measurable quality. |
| 11. Teacher correction workflow | Manual answer-region creation and acceptance endpoint exist; rough UI can accept deterministic suggestions. | Split/merge/reorder/edit bbox/add segment/reassign CGU/mark blank/partial/complete, audit log, visual overlays. | TA-UI-001 after initial benchmarks | Correction UI should be driven by measured failure modes, not guessed UI scope. |
| 12. Mapping evaluation harness | Implemented in TA-MAP-003 with synthetic JSON fixtures, provider-agnostic evaluator, and TA-MAP-003A quality gate policy. Current mock-provider outputs are measured honestly and remain ineligible for real-provider trial. | Richer bbox/IoU scoring, annotated real cases only after approval, report artifact persistence if needed. | TA-REF-001 or TA-SCRIPT-001 next; TA-MAP-004 only for planning unless explicitly approved. | The harness and gate are now the safety net before real mapping provider work. |
| 13. Reference OCR/extraction evaluation harness | Implemented in TA-REF-001 with synthetic question/solution/rubric fixtures, provider-agnostic evaluator, metrics, and quality gate policy. Real OCR/vision remains blocked. | Real OCR/vision provider implementation, richer provenance, annotated founder-approved real/anonymized reference datasets. | TA-SCRIPT-001 next; TA-MAP-004 only planning unless explicitly approved. | Reference evidence is now measurable before mapping/grading claims, but page order still needs a benchmark before batch evidence preparation. |
| 14. Script sequencing benchmark | Implemented in TA-SCRIPT-001 with synthetic page-order, blank/cover, boundary, and continuation fixtures plus a quality gate policy. Real OCR/vision sequencing remains blocked. | Real OCR/vision sequencing provider, richer layout/bbox scoring, annotated founder-approved real/anonymized script datasets. | TA-UI-001 or TA-MAP-004 planning only after explicit approval; do not start real provider automatically. | Page order and boundary assumptions are now measurable before real mapping or batch packet preparation. |
| 15. Real AI mapping provider | Not implemented for AEEM mapping. Existing Codex-related paths are gated dev/smoke paths, not production AEEM mapping. | Provider selection, strict schema validation, privacy rules, benchmark thresholds, no auto-accept, review-only UI. | TA-MAP-004 | Real provider comes after mapping/reference/script benchmarks so its output can be evaluated. |
| 16. Batch evidence packet preparation | Batch mock grading exists historically, but AEEM batch evidence preparation is not implemented. | Batch evidence jobs, quarantine queue, packet assembly per student×CGU, no grading side effects, final evidence sign-off. | TA-BATCH-001 | Batch evidence prep waits until page sequencing/mapping/reference correctness is measurable. |
| 17. Question-wise grading queue | Review/export/final-grade workflows exist for current regions/suggestions, but AEEM question-wise queue from confirmed packets is not implemented. | Queue from confirmed packets only, unconfirmed packet blocking, no cross-student answer leakage, teacher review/final authority. | TA-GRADE-001 | Grading queue is last because it must consume confirmed AEEM packets, not raw mapping guesses. |

## What already exists

Already built foundations:

- course/assessment/question/rubric workflows;
- submission upload and PDF/image page rendering;
- local artifact storage with ignored runtime artifacts;
- manual answer-region creation;
- mock grading and teacher review/finalization flows;
- rubric schema validation;
- question import prototype and controlled provider gating history;
- canonical grading-unit label/max-marks through current `Question`/rubric workflow;
- evidence packet readiness endpoint and grading gate;
- multi-segment answer-region evidence;
- deterministic/mock mapping provider and acceptance path;
- draft-only/no-auto-finalization safety invariants.

## What is missing

Missing AEEM-grade capabilities:

- rich CGU registry and versioning/sealing;
- script identity extraction/confidence;
- correction workflow for page/order/boundary issues;
- real answer boundary detection metrics;
- continuation grouping metrics;
- full teacher correction UI for split/merge/reorder/confirm;
- accepted/rejected suggestion audit trail for mapping corrections;
- batch evidence packet jobs and quarantine queue;
- real AI mapping provider behind evaluation gates;
- question-wise grading queue from confirmed packets;
- future sealed/immutable evidence store hardening.

## Why not implement the whole AEEM machine at once

Building AEEM monolithically would create several risks:

- too many moving parts would make failures impossible to classify;
- real provider outputs would look impressive without measurable correctness;
- teacher correction UI would be built before knowing the most common failure modes;
- batch processing could multiply silent evidence errors;
- grading quality claims could be based on incomplete/incorrect evidence.

The controlled-slice plan keeps every new layer measurable and reviewable.

## Why evaluation harnesses come before real AI/OCR providers

Real AI/OCR providers are not self-validating. Without benchmarks, the project cannot answer:

- Did the provider find the full answer or only part of it?
- Did it attach a segment to the right question?
- Did it miss a page continuation?
- Did it create false continuation warnings?
- Did it confuse nearby subparts on a multi-question page?
- Did it improve teacher workload or just move errors into the review queue?

Therefore TA-MAP-003, TA-REF-001, and TA-SCRIPT-001 exist to define measurement before provider implementation.

## Recommended next task

Recommended next implementation after TA-SCRIPT-001: **TA-UI-001 — Teacher correction workflow for split/merge/reorder/confirm**, or a TA-MAP-004 planning-only task if the founder wants provider planning before UI work. Do not start real AI mapping automatically.

Justification:

1. The immediate discovered failure was answer evidence boundary/continuation, not provider availability.
2. TA-MAP-002 already created the deterministic mapping contract and acceptance path, so the next safe step is to measure that contract against failure cases.
3. Real AI mapping is explicitly not allowed until mapping quality can be measured.
4. TA-MAP-003 can stay synthetic/non-private and manual controlled.
5. It produces the metrics needed to decide whether TA-MAP-004 real provider work is justified.

TA-MAP-003, TA-MAP-003A, TA-REF-001, and TA-SCRIPT-001 now close the first mapping, reference, and script-processing measurement/gate gaps. Real AI mapping is still not an automatic next step: the system now needs a teacher correction workflow to resolve the blockers/warnings that the harnesses surface, or a scoped planning-only TA-MAP-004 step if explicitly approved.

## Stop conditions preserved

This roadmap update does not start TA-MAP-004. It does not implement real AI mapping, real OCR/vision sequencing, run Codex, run batch grading, create `GradeSuggestion`, create `FinalGrade`, start teacher observation, or change grading logic.

## TA-BATCH-001 completion note

TA-BATCH-001 is implemented as an evidence-preparation scaffold, not grading. It adds batch prep run metadata, current assessment summary endpoints, per-student/per-question packet summaries, and quarantine counts for blocked evidence. The assessment UI shows an Evidence preparation summary with ready/blocked/warning/partial/blank counts and blocked packet reasons.

This satisfies the AEEM ordering principle: batch organization can exist before grading, but only as readiness/quarantine reporting. Real AI mapping, real OCR/vision providers, real Codex, `GradeSuggestion`, `FinalGrade`, and batch grading remain blocked. The next grading-related task must consume only ready/confirmed packets and must be separately approved.


## TA-GRADE-001 completion note

TA-GRADE-001 is complete as a scaffold, not as grading execution. It adds queue-run/item persistence and API/UI summaries for confirmed ready evidence packets only. Provider execution remains blocked for a future explicit task; no batch grading, model calls, `GradeSuggestion`, `FinalGrade`, or existing provider `GradingJob` creation is part of this milestone.


## TA-GRADE-001A completion note

TA-GRADE-001A is complete as a queue-boundary hardening slice. It adds stale/fresh status, a validation endpoint, rebuild audit preservation, and richer refused packet audit fields. Provider execution is still not implemented and remains blocked until a future task proves it re-checks readiness immediately before model invocation.
