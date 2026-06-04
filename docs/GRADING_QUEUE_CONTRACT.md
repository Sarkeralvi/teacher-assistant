# TA-GRADE-000 — Confirmed-Packet-Only Grading Queue Contract

Recorded at: 2026-06-04

## Purpose

TA-GRADE-000 defines the boundary between batch evidence preparation and any future grading queue. Batch evidence prep is still not grading. A future grading queue may only consume confirmed ready evidence packets and must refuse blocked, partial, blank, unconfirmed, missing, or cross-teacher/cross-assessment packets.

This contract must be accepted before TA-GRADE-001 implementation starts.

## Non-goals for TA-GRADE-000

TA-GRADE-000 does not implement a grading queue, does not run grading, does not call Codex/OpenAI/any model, does not create `GradeSuggestion`, does not create `FinalGrade`, does not create `GradingJob`, does not implement real AI mapping, and does not implement real OCR/vision.

## Queue-entry contract

A future `GradingQueueItem` may be created only when all of the following are true:

1. The teacher owns the assessment and the submission.
2. An evidence prep run exists or the readiness summary is current enough for the future implementation's freshness rule.
3. The expected submission × grading-unit slot exists.
4. `answer_region_id` exists.
5. `evidence_status = complete`.
6. `ready_for_grading = true`.
7. Active rubric exists.
8. Valid canonical grading unit exists.
9. `max_marks > 0`.
10. Valid crop/context exists.
11. `segment_count >= 1`.
12. Segment order is valid and contiguous.
13. `continuation_check_status` is one of:
    - `checked_no_continuation`
    - `continuation_confirmed_included`
    - `continuation_confirmed_not_needed`
14. The evidence packet has no blockers.
15. The packet belongs to the same assessment/submission/teacher boundary as the future queue request.

If any condition is false, the packet must be refused and remain in evidence correction/quarantine workflow.

## Refused packet states and blockers

The future queue must exclude/refuse:

- `evidence_status = missing`
- `evidence_status = unconfirmed`
- `evidence_status = partial`
- `evidence_status = blank`
- `continuation_check_status = possible_continuation`
- `continuation_check_status = not_checked` when continuation risk exists
- missing active rubric
- no answer region
- no confirmed segment
- invalid/non-contiguous segment order
- missing crop/context
- any blocker in the evidence packet
- cross-assessment item
- cross-teacher item

Blank/partial policy remains conservative: `partial` is blocked from normal grading; `blank` is blocked from normal AI grading for now. Future zero-mark blank handling is separate and must not be implied by this queue contract.

## Future queue item fields

A future `GradingQueueItem` should record at least:

- `assessment_id`
- `evidence_prep_run_id`
- `submission_id`
- `student_identifier`
- `question_id` / `grading_unit_id`
- `grading_unit_label`
- `max_marks`
- `answer_region_id`
- `segment_count`
- `pages_covered`
- `evidence_status`
- `continuation_check_status`
- `packet_hash` or evidence snapshot hash if available later
- `queue_status`
- `provider_allowed`

Allowed future `queue_status` values:

- `pending_review`
- `ready_for_provider`
- `provider_running`
- `provider_succeeded`
- `provider_failed`
- `teacher_review_required`
- `finalized`

`provider_allowed` must default to `false` unless a separate explicit future teacher-controlled action triggers provider execution.

## Safety invariants

Creating a future queue item must not:

- create `GradeSuggestion`
- create `FinalGrade`
- create `GradingJob`
- call Codex/OpenAI/Claude/Gemini/any model provider
- start batch grading
- auto-finalize anything
- bypass teacher review

Queue execution must be a separate explicit future action. Teacher review remains mandatory before any `FinalGrade` exists.

## Implementation gate for TA-GRADE-001

TA-GRADE-001 remains blocked until this contract is accepted. When TA-GRADE-001 is approved, its implementation must include tests proving:

- only confirmed ready packets can enter the queue;
- missing/unconfirmed/partial/blank/possible-continuation packets are refused;
- active rubric, canonical grading unit, crop/context, segment count, segment order, ownership, and blocker checks are enforced;
- queue-item creation has zero grading/provider side effects.
