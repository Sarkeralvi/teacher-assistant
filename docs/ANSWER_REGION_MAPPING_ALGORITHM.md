# Answer-Region Mapping Algorithm

Status: AEEM-aligned after TA-CORE-001. TA-MAP-002 deterministic/mock provider remains Done. Real AI mapping is deliberately deferred until evaluation harnesses and benchmark datasets exist.

## Role inside AEEM

Answer-region mapping is one subsystem inside the Answer Evidence Extraction Machine. It is not the whole pre-grading pipeline. Mapping must consume confirmed reference evidence and confirmed/ordered script pages, then produce draft answer evidence segments for teacher review.

```text
confirmed CGU registry + ordered script pages
  -> draft question boundary candidates
  -> draft answer evidence segments
  -> continuation grouping
  -> teacher correction / confirmation
  -> accepted AnswerRegion + ordered AnswerRegionSegment rows
  -> EvidencePacket readiness gate
```

No mapping result is a grading-quality claim until the evidence packet is complete and confirmed.

## Current implementation baseline

The current system has a useful safety foundation but not a business-grade mapping algorithm.

Current state:

- manual answer-region creation exists;
- multi-segment `AnswerRegionSegment` support exists;
- evidence packet readiness fields exist;
- TA-MAP-002 mock mapping suggestions are deterministic and synthetic-test-oriented;
- the submission-scoped mock provider can return single-segment, multi-segment continuation-included, and possible-continuation draft groups;
- accepted mapping suggestions create `AnswerRegion` + ordered `AnswerRegionSegment` rows only after explicit teacher/founder action;
- suggestion/acceptance paths create no `GradeSuggestion` and no `FinalGrade`;
- real AI/OCR mapping is not implemented;
- Codex-backed one-rectangle page suggestions remain a separate gated dev path and are not the AEEM mapping engine.

## Evidence-boundary lesson

The controlled `1(b)(i)` issue showed that a model score is not quality evidence if the selected answer region is incomplete. One logical answer can continue onto the next page before the next subpart. Therefore:

- page-local rectangles are insufficient as the final product model;
- continuation risk must be explicit;
- answer evidence may require multiple ordered segments;
- teacher/founder full-answer confirmation is required before grading;
- evaluation must measure missed continuations and wrong/partial mappings.

## AEEM mapping inputs

Mapping should eventually depend on:

- confirmed canonical grading units: label, variants, max marks, question text;
- confirmed solution/model-answer and active rubric availability;
- confirmed or reviewable script page sequence;
- rendered/preprocessed page images;
- OCR/layout/vision output where available;
- teacher corrections and prior accepted mapping history.

## Draft suggestion contract

Emit one `DraftAnswerRegionSuggestionGroup` per logical question answer. A group contains one or more ordered `DraftAnswerRegionSuggestionSegment` items across pages.

Required semantics:

- suggestions are draft-only;
- suggestions carry `needs_review=true` and `needs_teacher_confirmation=true`;
- high confidence means ready for teacher review, not accepted;
- suggestion generation never creates `AnswerRegion`, `GradeSuggestion`, or `FinalGrade` rows;
- each group has exactly one primary segment;
- segment `order_index` values are unique and contiguous on acceptance;
- cross-page answers are represented as multiple ordered segments;
- continuation risk is explicit.

Relevant schema contracts live in `apps/api/app/schemas.py`:

- `DraftAnswerRegionSuggestionSegment`
- `DraftAnswerRegionSuggestionGroup`
- `AnswerRegionSuggestionGroupResponse`
- `AnswerRegionSuggestionAcceptRequest`

## Continuation-risk states

Use these values in the draft mapping contract:

- `none`: no known continuation risk.
- `possible_continuation`: answer may continue beyond the current segment/page.
- `continuation_included`: continuation was found and included in ordered segments.
- `continuation_not_needed`: context indicates no continuation is needed.
- `ambiguous`: evidence is insufficient; teacher must decide.

Possible or ambiguous continuation must block grading readiness until resolved by teacher/founder confirmation or corrected segments.

## Evaluation-first next direction

TA-MAP-003 should not be real Codex/AI mapping. It should build a mapping evaluation harness and synthetic benchmark first.

Minimum benchmark cases:

1. single-page simple answer;
2. one answer spanning pages;
3. near-bottom answer with possible but absent continuation;
4. wrong/partial mapping;
5. multi-question page confusion;
6. skipped/blank answer;
7. inconsistent question labels;
8. page order anomaly affecting continuation.

Minimum metrics:

- question-label accuracy;
- segment recall/precision;
- bbox IoU where annotated;
- continuation detection recall/F1;
- false continuation rate;
- wrong-question assignment rate;
- packet readiness false-positive/false-negative rate;
- teacher correction burden.

## Safety rules

- Default provider remains mock/deterministic.
- Real provider paths stay explicitly gated.
- Suggestions are drafts only.
- Human acceptance is separate from suggestion generation.
- Grading is separate from mapping acceptance.
- Final grades require teacher action.
- No raw image bytes, secrets, private files, or provider internals should be returned in normal UI responses.
- No real-script auto-accept is allowed yet, even at high confidence.

## Revised build order

1. TA-MAP-003: Mapping evaluation harness and synthetic benchmark.
2. TA-REF-001: Question/solution/rubric extraction evaluation harness.
3. TA-SCRIPT-001: Script page sequencing and answer-boundary benchmark.
4. TA-MAP-004: Real AI mapping provider behind evaluation gate.
5. TA-UI-001: Teacher correction workflow for split/merge/reorder/confirm.
6. TA-BATCH-001: Batch evidence packet preparation.
7. TA-GRADE-001: Question-wise grading queue from confirmed packets.
