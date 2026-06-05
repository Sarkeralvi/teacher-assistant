# Founder Manual Evidence-to-Queue Checklist

Recorded: 2026-06-04  
Task: TA-MANUAL-001A  
Mode: manual controlled founder/internal smoke only

## Purpose

This checklist is for founder/internal evidence-to-queue testing only.

It is **not**:

- real grading;
- teacher observation;
- a production pilot;
- a quality claim about AI grading;
- permission to run Codex, OpenAI, Claude, Gemini, OCR/vision, or any provider.

The safe scope is the current evidence workflow:

assessment → grading units/rubrics → synthetic submissions/pages → answer regions/segments → evidence readiness → correction → batch evidence prep → grading queue scaffold → staleness/rebuild check.

## Required safety boundary

During this manual test:

- do not run real Codex grading;
- do not run provider execution;
- do not run batch grading;
- do not run real AI mapping;
- do not run real OCR/vision extraction;
- do not start teacher observation;
- do not use private student data unless separately approved for a specific smoke;
- do not finalize/export anything as a teacher-facing result.

Expected safety counts must remain:

- `GradeSuggestion = 0`
- `FinalGrade = 0`
- `GradingJob = 0`
- provider/model calls = `0`

The UI must continue to show no provider run button and no batch grade button in the grading queue scaffold.

## What the founder can test

The assessment page now labels the current manual path as **Founder Evidence Workflow**. Follow the page order:

1. Step 0: select/log in as a demo teacher and confirm the synthetic/demo assessment.
2. Step 1: reference materials — question paper, solution/model answer, and rubric. If upload still lives in the legacy/internal material step, use that Step 1 link and return to the assessment page.
3. Step 2: canonical grading units & rubrics. Confirmation is blocked until a grading/evidence run exists, reference materials are uploaded/confirmed, at least one canonical question exists, and every canonical question has an active rubric.
4. Step 3: upload synthetic/demo student scripts/submissions only. This uploads pages only; it does not grade or OCR.
5. Step 4: create/correct answer evidence mapping. Multi-page answers must use ordered segments and be confirmed.
6. Step 5/6: check evidence readiness and create evidence preparation summary.
7. Step 7: create grading queue scaffold.
8. STOP: no grading/provider execution. Queue records are not grades.

Legacy/future grading, review, export, and semi-automated surfaces should be treated as **FUTURE / not part of current founder test**.

Detailed checks:

1. Select or log in as a demo teacher.
2. Create or open a synthetic/demo assessment.
3. Create grading units/questions.
4. Create active rubrics.
5. Upload synthetic/demo submissions only.
6. Create answer regions manually.
7. Add, reorder, and confirm answer-region segments.
8. Check evidence packet readiness:
   - ready packet should show `ready_for_grading=true`;
   - blocked/unconfirmed/missing packet should show blockers.
9. Create a batch evidence prep run.
10. Verify expected packet counts:
    - expected packets = submissions × grading units;
    - missing packets must not be silently skipped;
    - blocked/quarantined packets must show reasons.
11. Create a grading queue scaffold run.
12. Verify queue behavior:
    - confirmed ready packets are queued;
    - blocked, missing, unconfirmed, blank, partial, and unsafe packets are refused;
    - queued items have `provider_allowed=false`.
13. Change evidence after queue creation.
14. Re-open or validate the queue run and verify the queued item becomes `stale`, `blocked_now`, or `evidence_missing` as appropriate.
15. Create a new queue run and verify it recomputes current counts without mutating the old auditable run.

## What the founder must not test yet

Do **not** test:

- real Codex grading;
- provider execution;
- batch grading;
- real AI mapping;
- real OCR/vision extraction;
- teacher observation;
- private student data unless separately approved;
- finalization/export as a teacher-facing result.

If any page exposes a route or button that appears to execute real grading/provider work, stop and report it instead of clicking it.

## Runtime caveats

TA-MANUAL-001 passed with synthetic/demo data. The final assessment page and grading queue scaffold were browser-visible.

Known runtime caveat:

- browser registration/login inside the Dockerized browser may hit the frontend `localhost` API URL issue;
- the TA-MANUAL-001 smoke therefore used API-assisted setup, then checked the final workflow state in the browser;
- for founder manual testing, use the normal browser where possible;
- if setup is blocked by the runtime caveat, report the blocker instead of bypassing it silently.

## Known UX caveats

- The assessment page is crowded and founder/internal only.
- Evidence prep and grading queue sections are rough functional UI, not polished teacher UI.
- Founder should verify teacher selection/login before testing.
- Empty states may show many sections with no data; that is expected.
- Queue records are not grades. Stale queue items must be rebuilt before any future provider execution.

## Stop conditions

Stop immediately and report if any of these occur:

- any `GradeSuggestion`, `FinalGrade`, or `GradingJob` appears unexpectedly;
- any provider/model call happens;
- queue includes a blocked, unconfirmed, blank, partial, or missing packet as queued;
- missing packets are silently skipped from evidence prep or queue refusal reporting;
- a stale queue item still appears fresh after evidence changes;
- app instability prevents a coherent smoke;
- any private data concern arises.

## TA-MANUAL-001 reference result

The prior founder/manual smoke used synthetic data only and verified:

- evidence packet readiness worked;
- correction workflow worked;
- batch evidence prep counted all expected packets;
- grading queue scaffold queued only the ready packet and refused blocked/missing/unconfirmed packets;
- staleness detection worked after evidence changed;
- safety counts stayed at zero:
  - `GradeSuggestion: 0`
  - `FinalGrade: 0`
  - `GradingJob: 0`
  - provider/model calls: `0`

Founder direct manual testing is safe for evidence-to-queue only. Provider execution and grading remain blocked.
