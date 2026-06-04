# Answer-Region Mapping Algorithm

Status: TA-MAP-002 deterministic/mock provider prototype implemented. Real AI/OCR mapping is still not implemented; batch grading, export, and finalization remain outside this subsystem.

## Current limitation

The current system has a useful safety foundation but not a business-grade mapping algorithm. The evidence-boundary lesson from the controlled `1(b)(i)` grading issue is that grading quality cannot be interpreted safely when the selected answer evidence may be incomplete. This document references that lesson only at the workflow level; it does not expose private student content, crops, PDFs, or provider payloads.

Current limits:

- manual answer-region creation remains rectangular and page-local;
- TA-MAP-002 mock mapping suggestions are deterministic and synthetic-test-oriented, not real layout/OCR/AI understanding;
- the submission-scoped mock provider can return single-segment, multi-segment continuation-included, and possible-continuation draft groups;
- Codex-backed one-rectangle page suggestions remain gated separately and are not the TA-MAP-002 real mapping provider;
- accepted mapping suggestions create `AnswerRegion` + ordered `AnswerRegionSegment` rows only after explicit teacher/founder action;
- the page-bottom continuation check is a safety blocker, not true answer-span detection;
- the frontend review workflow is rough-functional, not yet a polished teacher-grade visual mapping experience.

## Design principle

Answer-region mapping should be a review-first subsystem:

```text
submission pages
  -> deterministic layout candidates
  -> question-order-aware cross-page grouping
  -> draft multi-segment suggestion groups
  -> teacher/founder review and correction
  -> accepted AnswerRegion + ordered AnswerRegionSegment rows
  -> evidence packet readiness gate
  -> draft-only grading suggestion
  -> teacher final grade action
```

The algorithm should prefer high recall with visible warnings over silent precision failures. Missing part of an answer is worse than asking the teacher to reject an extra segment.

## Proposed staged algorithm

### Stage 1: Page preprocessing

For every `SubmissionPage` in order:

1. Load image dimensions and normalize orientation metadata if needed.
2. Compute simple ink-density / whitespace bands.
3. Detect candidate text/answer blocks using deterministic CV/layout heuristics.
4. Record page-level warnings: blank page, low contrast, dense writing, skew, or unreadable image.

No grading or real AI runs in this stage.

### Stage 2: Canonical question sequence

Use confirmed `Question` rows for the assessment as the authoritative order:

- `question_id`
- `question_no`
- `question_text`
- expected ordering from the database/question import confirmation

The mapping layer must not invent new canonical questions.

### Stage 3: Candidate answer spans

For each confirmed question, build a draft answer span:

- start anchor: detected label, teacher-selected point, or best layout estimate;
- end anchor: next detected question label, next canonical question start, page end, or teacher stop marker;
- possible continuation: if the span reaches a page break or the next question is not confidently found;
- blank-bottom exception: if page-bottom area is visually blank and the next question starts clearly later, mark `continuation_not_needed` instead of blocking by geometry alone.

### Stage 4: Draft suggestion groups

Emit one `DraftAnswerRegionSuggestionGroup` per logical question answer. A group contains one or more ordered `DraftAnswerRegionSuggestionSegment` items across pages.

Required semantics:

- suggestions are draft-only;
- suggestions carry `needs_review=true` and `needs_teacher_confirmation=true`;
- suggestion groups never create `AnswerRegion`, `GradeSuggestion`, or `FinalGrade` rows by themselves;
- each group has exactly one primary segment;
- segment `order_index` values are unique within a group;
- cross-page answers are represented as multiple ordered segments;
- continuation risk is explicit.

Initial schema contract lives in `apps/api/app/schemas.py`:

- `DraftAnswerRegionSuggestionSegment`
- `DraftAnswerRegionSuggestionGroup`
- `AnswerRegionSuggestionGroupResponse`
- `AnswerRegionSuggestionAcceptRequest`

### Stage 5: Teacher acceptance

Acceptance should eventually create exactly one logical `AnswerRegion` for the selected question and one or more ordered `AnswerRegionSegment` rows.

Acceptance must require:

- confirmed question ID;
- ordered segment list;
- teacher/founder full-answer confirmation if continuation risk is possible or ambiguous;
- same-submission validation for all segment pages;
- crop-bounds validation for every segment;
- no automatic grading after acceptance.

### Stage 6: Evidence packet gate

The existing evidence packet remains the final readiness gate before grading. It should block provider/job creation when:

- no accepted region exists;
- no confirmed segment exists;
- continuation risk is unresolved;
- active rubric/model answer evidence is missing;
- crop/context artifacts cannot be resolved.

## Continuation-risk states

Use these values in the draft mapping contract:

- `none`: no known continuation risk.
- `possible_continuation`: answer likely may continue beyond the current segment/page.
- `continuation_included`: continuation was found and included in ordered segments.
- `continuation_not_needed`: page-bottom/next-page context indicates no continuation is needed.
- `ambiguous`: evidence is insufficient; teacher must decide.

## Non-goals for this milestone

TA-MAP-001 does not build:

- real OCR;
- real Codex/OpenAI mapping;
- frontend crop review UI;
- acceptance endpoint implementation;
- migrations for persisted suggestion jobs;
- batch grading;
- export;
- finalization;
- fully automated grading.

## Safety rules

- Default provider remains mock/deterministic.
- Real provider paths stay explicitly gated.
- Suggestions are drafts only.
- Human acceptance is separate from suggestion generation.
- Grading is separate from mapping acceptance.
- Final grades require teacher action.
- No raw image bytes, secrets, or provider internals should be returned in normal UI responses.

## Immediate build order after this contract

1. Add a persisted or request-scoped draft suggestion-group endpoint for one submission.
2. Add deterministic layout fixture tests for single-page and cross-page answers.
3. Add an acceptance endpoint that creates one `AnswerRegion` plus ordered `AnswerRegionSegment` rows.
4. Add UI for teacher review/add/remove/reorder/confirm.
5. Reuse the evidence packet gate to block grading when mapping is incomplete.
