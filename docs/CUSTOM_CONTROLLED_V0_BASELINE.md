# Custom Controlled V0 Baseline

Recorded for TA-PILOT-007.

Baseline commit: `e5bac289a2e7992011f78118d2c5951247cd4edd`

Custom Controlled V0 is an early founder-controlled pilot workflow for evidence-first, teacher-reviewed grading assistance. It can support a bounded manual grading-assistance flow when the evidence packet is complete and the founder explicitly permits each real single-packet provider call.

## Current passed workflow

Custom Controlled V0 can claim the following workflow only:

1. The teacher creates or provides the question.
2. A model answer is required before grading readiness.
3. An active rubric is required before grading readiness.
4. Teacher-confirmed manual answer evidence text is required for reliable V0 grading.
5. The system shows an evidence packet preview before grading.
6. Readiness blocking prevents incomplete packets from entering the grading path.
7. A queue scaffold can record which ready packets are queued and which packets are refused.
8. Real Codex draft grading is single-packet only and must be explicitly authorized.
9. Each real grading result is a draft `GradeSuggestion` with `needs_review=true`.
10. Teacher approval is required before any `FinalGrade` exists.
11. XLSX export is approved-only and must not export unapproved drafts as final grades.

## Passed milestone evidence

The following founder-controlled milestones have passed:

- One-packet real vertical slice passed.
- Two-packet workflow slice passed.
- Three-packet grading-quality sanity passed after dependent-rubric prompt hardening:
  - correct manual answer text: `10/10`
  - partial manual answer text: `6/10`
  - wrong manual answer text: `0/10`
  - real Codex calls: `3`
  - draft `GradeSuggestion` rows: `3`
  - `needs_review=true` for all draft suggestions
  - `FinalGrade=0`
  - mock grading: no
  - batch grading: no

## Explicit limitations

Custom Controlled V0 cannot claim these capabilities yet:

- No OCR yet.
- No image-input grading yet.
- No automatic answer mapping yet.
- No batch grading yet.
- No semi-automated or fully automated modes yet.
- No autonomous finalization.
- Manual answer text is required for reliable V0 grading.
- Provider output remains draft assistance, not final grading authority.

## Safety invariants

These invariants define the V0 pilot boundary:

- No `GradeSuggestion` without a ready evidence packet.
- No `FinalGrade` without explicit teacher approval.
- No export of unapproved drafts as final grades.
- Provider calls are explicit and single-packet only.
- Real Codex/provider calls must not be hidden inside evidence prep, queue creation, approval, export, or background automation.
- Draft suggestions must keep `needs_review=true`.
- Teacher final authority must remain visible in workflow copy and reporting.

## Founder pilot checklist

### Before any real grading

Verify:

- The repo baseline and worktree state are known.
- The task explicitly authorizes the exact number of real provider calls.
- The assessment is synthetic/demo or otherwise explicitly approved for the task.
- The question is visible.
- The model answer is visible.
- The active rubric is visible.
- Teacher-confirmed manual answer evidence text is present and visible.
- The crop/segment evidence is present and visible.
- The evidence packet reports `evidence_status=complete`.
- The evidence packet reports `ready_for_grading=true`.
- The blocker list is empty.
- The queue item is fresh.
- Scoped pre-call counts show no existing `GradeSuggestion` for the target packet unless the task explicitly says to inspect existing rows.

### After draft grading

Verify:

- Exactly the approved number of real provider calls occurred.
- Each call handled exactly one packet.
- No batch call occurred.
- No retry occurred unless separately approved.
- Each target packet has exactly one new draft `GradeSuggestion`.
- `needs_review=true` for every draft suggestion.
- Scores and rubric breakdowns are sane for the evidence and rubric.
- `FinalGrade` count remains zero before teacher approval.
- The provider/model and prompt version are recorded.
- Mock grading was not used when the task required real grading.

### Before approval/export

Verify:

- The teacher has reviewed each draft suggestion.
- Any edited final score/comment is teacher-approved.
- `FinalGrade` rows exist only for explicitly approved suggestions.
- Rejected or unapproved drafts are not exported as final grades.
- The XLSX export contains approved final grades only.
- No hidden auto-approval or autonomous finalization occurred.

## Known risks

- Codex availability or usage limits can block grading.
- Provider output remains draft only.
- The teacher remains the final authority.
- Real-model grading quality is prompt- and evidence-sensitive; passing synthetic sanity checks does not prove broad production accuracy.
- Missing manual answer text, missing model answer, missing active rubric, missing crop/segment evidence, or unresolved continuation/context risk should block grading rather than degrade silently.

## Next recommended tasks

- TA-PILOT-008: UI polish for Custom Controlled V0 pilot.
- TA-PILOT-009: Two-submission human-facing rehearsal.
- TA-PILOT-010: Batch-safe design only; no implementation until approved.
