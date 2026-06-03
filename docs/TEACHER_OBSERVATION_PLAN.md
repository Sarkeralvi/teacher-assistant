# Teacher Observation Plan

## TA-W2-027 — Controlled teacher workflow observation preparation

Recorded: 2026-06-03

## Purpose

Prepare a safe, in-person, founder-controlled teacher workflow observation for the Teacher Assistant prototype. This is not a public pilot, not a production rollout, and not an accuracy claim.

The goal is to learn whether the workflow is understandable and trustworthy when the teacher remains final authority:

- Are canonical grading units clear?
- Is the question/rubric/answer evidence packet understandable?
- Is multi-page answer confirmation usable?
- Is the AI draft suggestion useful as a review aid?
- Is the teacher review/edit/export flow understandable and privacy-safe?

## Observation framing

Present the system as:

- an early controlled prototype;
- an AI draft marking assistant;
- a teacher-reviewed workflow, not automated grading;
- evidence-first: question, rubric, solution/model answer, and complete student answer evidence must be confirmed before a draft suggestion is quality-evaluable;
- draft-only: no AI grade is final until a teacher approves or edits it;
- a workflow/trust feedback session, not proof of production grading accuracy.

Use the validated `1(b)(i)` multi-segment case only as a controlled demonstration that evidence completeness matters and that the review workflow can surface a draft suggestion.

## What to show

Show only the controlled workflow and already-validated draft state:

1. Teacher login.
2. Controlled assessment context.
3. Canonical grading units, including `1(b)(i)` out of 6 marks.
4. Evidence packet/readiness checklist.
5. Multi-segment full-answer confirmation for `1(b)(i)`:
   - page 3 segment;
   - page 4 continuation segment;
   - full answer confirmed;
   - `multi_segment_composite` context used.
6. Existing AI draft suggestion for `1(b)(i)`:
   - score: `6/6`;
   - confidence: `0.88`;
   - `needs_review=true`;
   - rubric breakdown and feedback.
7. That no `FinalGrade` exists before teacher action.
8. Optional, only with explicit founder approval during the session: teacher edits/approves the suggestion.
9. Optional, only with explicit founder approval and no private concerns: export flow.
10. Teacher feedback questions.

## What not to claim

Do not claim:

- that the product is production-ready;
- that this is a teacher pilot;
- that the AI is accurate on general classroom data;
- that the validated `1(b)(i)` result proves broad grading quality;
- that future answers will be auto-marked correctly;
- that the system replaces teacher judgment;
- that batch grading is ready;
- that private data handling is production-compliant;
- that exported results are approved unless a teacher explicitly approves/edits them.

The correct claim is narrower: the system can prepare an evidence-bounded draft suggestion that remains teacher-review-required.

## Exact demo flow

1. Login.
2. Open the existing controlled assessment if available; otherwise create a clean demo assessment using only approved/anonymized demo material.
3. Show the canonical grading-unit table and identify `1(b)(i)` as a 6-mark unit.
4. Show the answer evidence packet and explain that grading is blocked or not quality-evaluable without complete evidence.
5. Show the two-segment full-answer confirmation for `1(b)(i)`:
   - page 3 lower answer segment;
   - page 4 top continuation before `1(b)(ii)`;
   - full-answer confirmation enabled.
6. Show the existing AI draft suggestion:
   - `6/6`;
   - confidence `0.88`;
   - `needs_review=true`;
   - rubric breakdown: identify givens `1/1`, total probability `2/2`, Bayes setup `2/2`, final value `1/1`;
   - feedback explaining that the final value around `0.417`/`0.418` is acceptable.
7. Show that no `FinalGrade` exists before teacher action.
8. If the founder explicitly approves during the session, let the teacher edit/approve the draft; otherwise stop before finalization.
9. If the founder explicitly approves and the teacher has no privacy concern, show export; otherwise skip export.
10. Ask feedback questions and record observations.

## Founder script / wording

Use this wording at the start:

> “This is an early controlled prototype. I am not asking you to trust the AI score yet. I want your feedback on the workflow: whether the question/rubric/answer evidence is clear, whether the AI draft is useful, and whether the review/edit/export process could save time.”

Additional safe wording:

- “The AI score is a draft only.”
- “The teacher remains final authority.”
- “If evidence is incomplete, the AI result should not be trusted as grading-quality evidence.”
- “We are observing workflow clarity and trust barriers, not making a production accuracy claim.”
- “We can stop immediately if the workflow feels misleading, unstable, or privacy-sensitive.”

## Privacy warnings

Before showing data, confirm:

- The displayed script/material is approved for this observation.
- Any private student identifiers are absent, hidden, or explicitly approved by the founder.
- No private PDFs, scripts, crops, pages, exports, screenshots, or generated artifacts will be committed to git.
- Do not export unless the founder approves and the teacher has no privacy concern.
- Do not delete test data unless the founder explicitly asks.
- Do not approve/edit/export private real data without explicit founder approval.

## Teacher questions

Ask:

1. Are grading unit labels clear?
2. Is the evidence packet understandable?
3. Is multi-page answer confirmation usable?
4. Would AI draft suggestions save time if the teacher remains final authority?
5. Is the feedback useful?
6. What would make you trust it?
7. What would make you distrust it?
8. Which UI steps feel confusing?
9. What privacy concerns do you have?
10. Would you prefer a different review/edit/export sequence?

## Safe observation criteria

The observation is acceptable only if:

- the founder is present or has explicitly approved the exact session;
- the workflow is manual controlled mode only;
- no autonomous loop is enabled;
- no batch grading is run;
- no new real Codex call is run unless explicitly approved during the observation plan;
- the teacher sees that AI suggestions are draft-only and review-required;
- the evidence packet and full-answer confirmation are shown before discussing the AI score;
- no `FinalGrade` is created unless the founder explicitly approves teacher action;
- no export is performed unless the founder explicitly approves and privacy concerns are cleared.

## Stop conditions

Stop immediately if any of these occur:

- Teacher expects fully automatic grading.
- Teacher wants to use real student data without anonymization approval.
- Wrong grading unit or incomplete answer evidence appears.
- AI score is clearly wrong and cannot be explained as draft-only.
- App instability or confusing state prevents safe explanation.
- Any privacy concern arises.
- The workflow implies that AI output is final without teacher action.
- Batch grading, autonomous mode, or unapproved new real Codex calls become necessary to proceed.

## Observation notes to record

Record only non-private workflow feedback:

- whether canonical units were understood;
- whether evidence completeness felt clear;
- whether the draft suggestion/rubric breakdown helped;
- whether review/edit/finalize/export steps were understandable;
- confusion points;
- trust/distrust reasons;
- privacy concerns;
- teacher-requested changes.

Do not record private student identifiers or commit private artifacts.

## Post-observation next steps

If the observation is conducted later, create a follow-up note/task for:

- TA-W2-028: Conduct teacher observation and record feedback.
- TA-W2-029: Post-observation improvement plan.

Do not convert the observation into a public pilot or production accuracy claim without separate founder approval and broader validation.
