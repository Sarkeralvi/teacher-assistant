# Founder Pilot Rehearsal Checklist and Demo Reset Plan

This checklist is for founder-supervised rehearsals of the Teacher Assistant / AEEM Custom Controlled V0 vertical slice. It is a safety runbook, not a grading shortcut. The teacher remains the final authority, AI/provider output is draft assistance only, and no final grade is created without explicit teacher approval.

## Scope and safety boundary

Use this document only for local/dev or founder-controlled rehearsal data. Do not use private student scripts, production data, or external-teacher pilot data unless the founder explicitly authorizes that dataset and rehearsal.

The rehearsal may verify readiness, queue state, one bounded real provider draft, teacher review, approval, and approved-only export. It must not run grading automatically, in batches, or with mock output hidden as real output.

## Exact preflight checks

Run these before any rehearsal action:

```bash
cd /home/newton/teacher-assistant
git status --short
git rev-parse HEAD
make health
make frontend-health
```

Expected preflight state:

- `git status --short` is empty, unless the founder has approved the exact dirty files.
- Backend health returns `{"status":"ok", ...}`.
- Frontend health returns HTTP success.
- Current task explicitly allows any real provider call before a provider call is made.
- The rehearsal assessment, question, rubric, submission, page, answer region, and crop are all synthetic/demo unless explicitly approved otherwise.
- The target packet has a model answer / solution before it can be ready or queued.

Recommended safety-count snapshot before any grading step:

```sql
select count(*) from grade_suggestions;
select count(*) from final_grades;
select count(*) from grading_jobs;
```

Do not proceed if unexpected draft/final/job rows are present for the target assessment unless the founder explicitly identifies them as the intended rehearsal records.

## Clean demo data requirements

A clean founder rehearsal should use one named synthetic assessment with one controlled packet unless the founder explicitly expands the scope.

Required objects:

1. One teacher-controlled account/session.
2. One synthetic/demo course if needed.
3. One synthetic/demo assessment.
4. One question / canonical grading unit containing:
   - question label;
   - max marks;
   - question text;
   - model answer / solution text.
5. One active rubric for the question.
6. One uploaded synthetic script.
7. One manually created answer region/crop.
8. Continuation state resolved.
9. Full-answer confirmation only when the crop contains the complete answer.
10. No private PDFs, images, screenshots, exports, or real student artifacts.

## Custom Controlled V0 flow

The founder-safe flow is deliberately sequential:

1. Create or select the synthetic assessment.
2. Create the question / grading unit with model answer.
3. Attach one active rubric.
4. Upload the synthetic script.
5. Manually create the answer region/crop.
6. Inspect the evidence packet preview.
7. Run evidence prep / queue scaffold only when readiness is complete.
8. If and only if explicitly approved, run one real provider draft for one packet.
9. Review the draft as teacher.
10. Edit if needed.
11. Approve only after teacher review.
12. Export approved final grades only.
13. Capture the final report and stop.

Do not skip from upload directly to grading. Evidence must be ready first.

## Evidence packet readiness checklist

The target packet is ready only when the evidence preview shows all of the following:

- question label visible;
- max marks visible;
- model answer / solution visible;
- active rubric criteria visible;
- student crop/segment info visible;
- `evidence_status = complete`;
- continuation resolved;
- `ready_for_grading = true`;
- blockers are empty / none.

Evidence prep expected state for a one-packet rehearsal:

- `ready = 1` for the target packet;
- `blocked = 0` for the target packet.

Queue scaffold expected state:

- `queued = 1` for the target packet;
- `refused = 0` for the target packet;
- provider gate shown explicitly;
- stale status is `fresh`.

Stop if the model answer, active rubric, crop, continuation state, or full-answer confirmation is missing.

## One-real-grade safety checklist

A real provider draft is allowed only after the founder explicitly approves a bounded one-packet call.

Before the call:

- Confirm the exact target assessment id.
- Confirm the exact question id.
- Confirm the exact answer region id.
- Confirm the packet is ready and fresh.
- Confirm no batch path is being used.
- Confirm no mock provider output will be used.
- Confirm the provider/model path is the approved one.
- Confirm expected safety counts before the call.

During the call:

- Call only the one approved packet.
- Do not retry automatically after provider/auth failure unless the founder explicitly approves a retry.
- Do not fall back to mock grading.
- Do not create or approve a final grade.

After the call:

- Confirm one draft `GradeSuggestion` exists for the target answer region.
- Confirm it is labeled as provider/model draft assistance.
- Confirm `needs_review` / teacher-review-required semantics remain true.
- Confirm no `FinalGrade` exists until teacher approval.
- Confirm any `GradingJob` row corresponds only to the approved one-packet call.

## Teacher review / approval checklist

Teacher review is mandatory. The teacher must inspect:

- the crop image / answer segment;
- question text and max marks;
- model answer / solution;
- active rubric criteria;
- provider draft score and comments;
- rubric breakdown;
- any uncertainty or missing-evidence notes.

Teacher approval requirements:

- The teacher may edit score/comment before approval.
- The approved score must remain within the question max marks.
- `FinalGrade` is created only by an explicit teacher approval action.
- Rejection or no action must leave the provider output as draft only.
- Export must not treat an unapproved `GradeSuggestion` as a final grade.

## Export checklist

Export only after teacher approval.

Before export:

- Confirm the target answer region has an approved `FinalGrade`.
- Confirm unapproved draft suggestions are excluded.
- Confirm the assessment id is correct.
- Confirm the export type is the approved-only grade export.

After export:

- Open or inspect the generated XLSX/CSV.
- Confirm it contains the approved final grade row.
- Confirm it does not contain draft-only suggestions as final grades.
- Confirm teacher-edited score/comment, if any, appears in the export.
- Record export path, row count, assessment id, answer region id, and final grade id in the final report.

## Stop conditions

Stop immediately and report the blocker if any of these occur:

- git working tree has unapproved dirty files;
- backend or frontend health check fails;
- target data is private or not explicitly approved;
- model answer / solution is missing;
- active rubric is missing;
- crop is missing or partial but marked complete;
- continuation is unresolved;
- evidence packet is blocked or stale;
- queue refuses the packet;
- provider gate is closed when a real provider call is requested;
- provider/auth failure occurs;
- mock grading appears in a real-grading rehearsal;
- any batch path is triggered;
- a `FinalGrade` appears before teacher approval;
- export includes unapproved draft suggestions;
- a teacher can view/delete another teacher's submissions or artifacts.

## What must never happen automatically

The system must never automatically:

- detect answers or OCR private scripts without explicit approval;
- run provider/model grading;
- run batch grading;
- retry a failed provider call;
- fall back to mock grading when real grading fails;
- create a `GradeSuggestion` outside the approved call path;
- create a `FinalGrade`;
- approve, edit, reject, or export grades;
- delete or reset production/private data;
- expose dev reset tooling in normal teacher UI.

## How to confirm no mock grading was used

Use both UI/API labels and database inspection:

- Confirm the provider/model label on the draft is the approved real provider, not `mock`.
- Confirm no mock-grading endpoint/button/path was used during the rehearsal.
- Inspect the target `GradeSuggestion` provider/model fields.
- Inspect the associated `GradingJob` provider/status metadata if present.
- Confirm the final report states provider/model, target answer region id, and the exact call count.

If any provider field says `mock`, the run is not a real grading rehearsal.

## How to confirm FinalGrade is only created after teacher approval

Use a before/after approval count:

1. Before teacher approval, confirm the target answer region has no `FinalGrade`.
2. Confirm the draft exists only as a `GradeSuggestion`.
3. Perform the explicit teacher approve/edit action.
4. Confirm exactly one `FinalGrade` exists for the target answer region.
5. Confirm its score/comment match the teacher-approved values.
6. Confirm audit/review metadata if present.

A `FinalGrade` that exists before explicit approval is a hard stop.

## How to capture the final report

The final report should include:

- assessment id;
- question id;
- submission id;
- page id;
- answer region id;
- whether model answer was visible;
- whether rubric was visible;
- whether crop/segment was visible;
- `ready_for_grading` value;
- evidence prep ready/blocked counts;
- queue queued/refused counts;
- provider/model used, or confirmation no provider call was made;
- `GradeSuggestion` id/count;
- `FinalGrade` id/count;
- `GradingJob` id/count;
- teacher approval action and any teacher edits;
- export path and row count;
- safety confirmations;
- final git status;
- whether the next rehearsal can start.

## Known safe vertical slice

The known safe founder-supervised vertical slice is:

1. Ready packet: one complete evidence packet with question, max marks, model answer, active rubric, full crop/segment, continuation resolved, and `ready_for_grading = true`.
2. Real Codex draft `GradeSuggestion`: one explicitly approved real Codex call creates draft assistance only for the one target packet.
3. Teacher edited/approved `FinalGrade`: teacher reviews the draft, edits if needed, and explicitly approves the final grade.
4. Approved-only XLSX export: export includes approved `FinalGrade` rows only and excludes unapproved draft `GradeSuggestion` rows.

This vertical slice is founder-supervised demo readiness. It is not permission for unattended external teacher pilot use.

## Optional demo reset plan

No reset script is added in this task. A script that deletes data is risky unless it is tightly scoped to known synthetic demo identifiers and guarded by explicit local/dev confirmation. For now, use manual reset steps only.

Manual local/dev reset guidance:

1. Confirm this is local/dev, not production.
2. Confirm the target assessment/course/student identifiers are synthetic demo records.
3. Export or note ids needed for audit before deletion.
4. Prefer app/API deletion paths over direct SQL when those paths exercise artifact cleanup.
5. Delete only the named synthetic submission/assessment records.
6. Confirm related local artifacts were removed or quarantined by the app path.
7. Confirm no unrelated teacher/course/submission records were deleted.
8. Confirm `git status --short` remains clean after reset.

Do not run a direct database wipe. Do not broad-delete storage roots. Do not add a normal UI reset button.

## Next planned rehearsal

TA-PILOT-005 should be a small supervised two-packet rehearsal:

- two synthetic ready packets;
- explicit founder approval before any real provider call;
- no batch grading unless explicitly scoped;
- teacher review for each draft;
- approved-only export inspection;
- same safety counts and stop conditions as this checklist.
