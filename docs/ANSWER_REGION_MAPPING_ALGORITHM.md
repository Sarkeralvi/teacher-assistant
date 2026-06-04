## TA-UI-001 teacher correction policy

Mapping suggestions and accepted regions are not final evidence until teacher/founder correction and confirmation can resolve known evaluation-gate failures. TA-UI-001 adds correction operations for accepted `AnswerRegion` packets: edit segment bbox, add/split a segment from user-provided boxes, remove non-final segments, reorder segments into contiguous packet order, confirm full answer, mark continuation not needed, and mark partial/needs review.

Safety policy:

- correction APIs require authentication;
- only the owning teacher can correct the assessment/submission data;
- pages must remain inside the same submission/assessment;
- invalid boxes outside page bounds are rejected;
- segment order is normalized to unique contiguous order;
- corrections never create `GradeSuggestion` or `FinalGrade`;
- corrections never start batch grading, real AI mapping, real OCR, or Codex.

Current mock/deterministic mapping remains non-product-quality. Real AI mapping remains blocked until mapping gates are satisfied and teacher correction is available as the controlled fallback.

# Answer-Region Mapping Algorithm

Status: AEEM-aligned after TA-MAP-003. TA-MAP-002 deterministic/mock provider remains Done. TA-MAP-003 adds an executable synthetic mapping evaluation harness. Real AI mapping remains deliberately deferred.

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

## Evaluation-first harness now added

TA-MAP-003 implements the first executable synthetic mapping benchmark in `apps/api/packages/evaluation/answer_mapping_evaluator.py` with JSON fixtures under `apps/api/packages/evaluation/fixtures/answer_mapping/`.

Benchmark cases now present:

1. single-page complete answer;
2. multi-page continuation;
3. near-bottom complete answer with no continuation;
4. ambiguous / possible continuation;
5. multiple questions on one page;
6. wrong-question trap;
7. blank or low-content page.

Evaluator metrics now reported:

- suggestion group count accuracy;
- question-label accuracy;
- segment count accuracy;
- segment order accuracy;
- page coverage accuracy;
- continuation-risk accuracy;
- wrong-question detection accuracy;
- blank-page handling accuracy;
- complete-answer packet success;
- unsafe auto-accept count;
- `GradeSuggestion` created count;
- `FinalGrade` created count;
- continuation false-negative count;
- blank-page false mapping count;
- possible-continuation confirmation count.

The current deterministic/mock provider is measured honestly through saved synthetic provider outputs. It passes the simple single-page, multi-page continuation, and ambiguous-continuation cases, but it does not pass the full synthetic suite. That is expected: TA-MAP-003 is a measuring gate, not a claim that the mock provider is production-quality mapping.


## TA-MAP-003A mapping quality gate policy

TA-MAP-003A adds an executable gate policy on top of the synthetic evaluator. The policy returns:

- `eligible_for_real_provider_trial`: whether a provider cleared the synthetic blocker gate;
- `blocker_reasons`: hard failures that prevent a real-provider trial;
- `warning_reasons`: reviewable conditions that may proceed only with teacher/full-answer confirmation.

Critical blockers:

- wrong-question mapping or wrong-CGU/cross-assessment assignment;
- blank/low-content page mapped confidently;
- continuation false-negative;
- unsafe auto-accept or skipped teacher/full-answer confirmation;
- `GradeSuggestion` creation during mapping;
- `FinalGrade` creation during mapping.

Reviewable warnings:

- near-bottom complete answer marked possible continuation;
- low-confidence mapping;
- ambiguous continuation requiring teacher confirmation;
- multiple questions on one page flagged for review instead of confidently mapped to the wrong question.

Synthetic minimum gate for a future real provider:

- `critical_failure_count == 0`;
- `unsafe_auto_accept_count == 0`;
- `grade_suggestion_created_count == 0`;
- `final_grade_created_count == 0`;
- `continuation_false_negative_count == 0`;
- `wrong_question_critical_failure_count == 0`;
- `blank_page_false_mapping_count == 0`;
- all mandatory review cases preserve teacher/full-answer confirmation.

Current result: `current_mock_provider` is not eligible for real-provider trial as product-quality mapping. It remains useful only as deterministic contract plumbing.

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
