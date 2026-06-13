# Batch-Safe Design and Real-Teacher Pilot Gate

Recorded for `TA-PILOT-010` after the successful `TA-PILOT-009` two-submission Custom Controlled V0 rehearsal.

This document is a safety gate, not an implementation plan for batch grading. It defines what must remain true before any future batch expansion or real-teacher pilot expansion is approved.

## Current allowed Custom Controlled V0 mode

The only currently allowed real-provider workflow is the manual Custom Controlled V0 path:

1. Teacher manually creates or verifies the assessment.
2. Teacher manually creates the question.
3. Teacher manually enters the model answer or solution text.
4. Teacher manually creates and activates the rubric.
5. Teacher uploads or creates only synthetic/demo submissions unless explicit data approval exists.
6. Teacher manually creates answer evidence regions/crops.
7. Teacher enters teacher-confirmed manual answer evidence text for each answer region.
8. Evidence readiness gate must show a complete packet before grading:
   - manual answer text visible;
   - model answer visible;
   - active rubric visible;
   - crop/segment visible;
   - `evidence_status = complete`;
   - `ready_for_grading = true`;
   - `blockers = none`.
9. Queue scaffold may identify fresh ready packets, but it does not grade by itself.
10. Real grading is allowed only as explicit single-packet calls approved by the task/founder.
11. Every provider result remains a draft `GradeSuggestion` with `needs_review = true`.
12. Teacher must inspect score, feedback, rubric breakdown, and linked evidence before approval.
13. `FinalGrade` may be created only by explicit teacher review/approval.
14. Export may include only approved `FinalGrade` rows; unapproved drafts must be excluded.

## Explicitly forbidden until later approval

The following remain out of scope until separately designed, reviewed, and approved:

- Batch real grading.
- Automatic OCR.
- Automatic answer mapping.
- Autonomous grading.
- Autonomous `FinalGrade` creation.
- Export of unapproved draft `GradeSuggestion` rows as final grades.
- Semi-automated grading mode.
- Fully automated grading mode.
- Hidden provider/model calls from UI load, queue creation, preview, export, or background jobs.
- Provider/model retries unless explicitly approved for a bounded task.

## Batch-safe design requirements

Any future batch design must satisfy all requirements below before implementation.

### Packet eligibility

- Batch can consume only confirmed ready packets.
- Every packet must have teacher-confirmed manual answer text, visible model answer, active rubric, and confirmed crop/segment evidence.
- Packets with blockers, incomplete evidence, missing rubric, missing model answer, missing manual answer text, missing crop/segment, or uncertain continuation state must be refused before any provider call.

### Provider-call transparency

- No hidden provider calls are allowed.
- Batch start must show the exact provider/model, maximum call count, eligible packet count, and refused packet count.
- Teacher must explicitly start the batch after reviewing the queue state.
- UI copy must distinguish queue preparation from provider grading.

### Per-packet preflight

Each packet requires a fresh preflight immediately before its provider call:

- readiness status still complete;
- manual answer text still present;
- model answer still present;
- active rubric still present;
- crop/segment still present;
- no existing unreviewed duplicate `GradeSuggestion` for the same packet/run policy unless explicitly resuming;
- no existing `FinalGrade` that would make new draft grading unsafe or confusing.

### Per-packet stale check

- Queue entries must include a staleness fingerprint of question, model answer, active rubric, answer region, manual answer text, crop/segment metadata, and readiness status.
- The stale check must be performed immediately before each provider call.
- Stale packets must be refused or paused, not graded.

### Failure isolation

- One packet failure must not silently invalidate other packet results.
- Failed packets must record a failed status with sanitized error details.
- Batch must stop or continue according to an explicitly selected teacher-visible policy.
- No retry may occur unless retry count and retry conditions are explicitly approved before the run.

### Maximum call limit

- Batch must have a hard maximum provider-call limit.
- The call limit must be visible before start.
- The system must stop when the limit is reached, even if eligible packets remain.
- The final report must state attempted, succeeded, failed, skipped/refused, and remaining counts.

### Resumability without duplicates

- Resuming a batch must not create duplicate `GradeSuggestion` rows for already succeeded packets.
- Resumption must reuse run/queue status and skip completed packets unless the teacher explicitly requests a new draft with a new run reason.
- The UI must show whether each packet is ungraded, suggested, failed, refused, stale, skipped, finalized, or cancelled.

### Teacher-visible queue status

The teacher must be able to see, before and during a run:

- total packets;
- ready packets;
- refused packets and refusal reasons;
- stale packets;
- completed draft suggestions;
- failed packets;
- skipped packets;
- remaining call budget;
- current provider/model;
- whether the run is active, paused, stopped, completed, or cancelled.

### Teacher cancel/stop control

- Teacher must have a visible stop/cancel control.
- Stop/cancel must prevent any new provider call from starting after the current in-flight packet completes or fails.
- The system must clearly state whether an in-flight provider call may still complete.

### Draft-only output

- Batch must never create `FinalGrade` directly.
- Batch outputs must remain draft `GradeSuggestion` rows.
- Every draft must require teacher review.
- Teacher approval/edit/reject remains a separate explicit action.
- Export remains approved-final-grade-only.

## Real-teacher pilot gate

A real-teacher pilot may begin only after the founder explicitly approves the scope and the conditions below are satisfied.

### Data scope

- Use only synthetic data or explicitly approved data.
- No private, high-stakes, identifiable, or sensitive student data without written approval.
- If non-synthetic data is approved, the data owner, retention window, deletion path, and export rules must be documented before upload.

### Account and ownership scope

- Use one teacher account only at first.
- Verify teacher ownership isolation before pilot start.
- Cross-teacher access to submissions, pages, answer regions, grade suggestions, final grades, exports, and artifacts must be blocked or hidden.

### Teacher enablement

- A teacher-facing quick-start guide is required before a real-teacher pilot.
- The guide must explain allowed V0 mode, evidence readiness, manual answer text, single-packet grading, draft suggestions, review/approval, and approved-only export.
- The guide must explicitly say the tool is decision support, not autonomous marking.

### Observation and control

- Founder or approved observer must be present for the first teacher pilot.
- The observer must confirm every provider call is intentional.
- The observer must confirm no batch, OCR, answer mapping, or autonomous finalization is used.

### Hard stop conditions

Stop the pilot immediately if any condition occurs:

- unexpected provider/model call;
- Codex/provider auth or model failure;
- usage limit or rate-limit uncertainty;
- private/unapproved data appears;
- teacher cannot understand draft-vs-final state;
- evidence packet is incomplete but grading appears possible;
- queue stale state is unclear;
- duplicate `GradeSuggestion` or unexpected `FinalGrade` appears;
- export includes unapproved draft rows;
- cross-teacher data exposure is suspected;
- artifact deletion/privacy behavior is unclear.

### Final report template

Every supervised teacher pilot report must include:

- date/time and observer;
- teacher account id;
- data type: synthetic or approved real data;
- assessment id;
- question ids;
- submission ids;
- answer region ids;
- evidence ready/blocked counts;
- queue queued/refused/stale counts;
- provider/model call count;
- provider/model used;
- `GradeSuggestion` ids, scores, and `needs_review` values;
- `FinalGrade` ids and approval source ids;
- export row count;
- whether drafts were excluded;
- DB safety counts before/after;
- mock used yes/no;
- batch used yes/no;
- provider/model calls outside grading yes/no;
- private data used yes/no;
- code changed yes/no;
- final git status;
- usability verdict;
- stop conditions encountered;
- next recommended action.

## Operational readiness checklist

Before any future batch or real-teacher pilot expansion:

- [ ] Docker/WSL stack is healthy.
- [ ] `make health` passes.
- [ ] `make frontend-health` passes.
- [ ] Codex authentication is healthy, if real grading is approved for the task.
- [ ] Approved Codex/model name is visible and verified before calls.
- [ ] Usage limit/rate-limit expectations are known before calls.
- [ ] `git status --short` is clean before the run.
- [ ] DB safety counts are captured before and after:
  - `GradeSuggestion` count for target regions;
  - `FinalGrade` count for target regions;
  - `GradingJob` count for target regions;
  - queue run/item counts.
- [ ] Evidence packet counts are captured before grading.
- [ ] Queue refused/stale reasons are captured.
- [ ] Export is inspected for row count and approved-only inclusion.
- [ ] Audit logs exist for approval/final-grade actions and destructive/privacy-sensitive actions.
- [ ] Final report is written before declaring readiness for the next phase.

## Risk register

| Risk | Why it matters | Required mitigation |
| --- | --- | --- |
| Codex availability or usage limits | Provider failure can interrupt a teacher session or create failed jobs. | Preflight auth/model/usage expectations; stop on failure unless retry is explicitly approved. |
| Wrong or weak evidence text | Manual answer text drives grading reliability while image input/OCR is unavailable. | Teacher confirms text before readiness; preview must show text clearly. |
| Rubric ambiguity | Ambiguous criteria can produce unstable or unfair suggestions. | Teacher reviews active rubric before grading; use conservative feedback and draft-only output. |
| Teacher confusion | Teachers may mistake draft suggestions for final grades. | UI and guide must label suggestions as draft and require explicit approval. |
| Accidental provider call | Hidden calls can create cost, privacy, and audit problems. | Provider calls only behind explicit start action and bounded call count. |
| Stale queue | Changed evidence/rubric/model answer can make queued packets unsafe. | Per-packet stale fingerprint and immediate pre-call stale check. |
| Cross-teacher privacy | One teacher must not access another teacher's data or artifacts. | Owner isolation tests and route/service checks before real-teacher use. |
| Artifact deletion/privacy | Uploaded pages/crops/exports may remain after deletion or policy expiry. | Verify deletion paths, retention policy, ignored runtime storage, and audit logs. |

## Next recommended tasks

### TA-PILOT-011 — Teacher-facing quick-start guide

Create a concise teacher-facing guide for the currently allowed Custom Controlled V0 flow. It must explain setup, manual evidence entry, readiness gate, single-packet draft grading, review/approval, approved-only export, and stop conditions.

### TA-PILOT-012 — First supervised teacher test with tiny synthetic data

Run the first supervised teacher test using tiny synthetic data only. Keep one teacher account, one small assessment, bounded single-packet provider calls only if explicitly approved, observer present, and full final report required.
