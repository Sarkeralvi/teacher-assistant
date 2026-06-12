# External Teacher Pilot Checklist

This checklist is the gate for any external teacher pilot. Passing TA-DEMO-007 means the founder-supervised synthetic demo path works; it does not authorize external teacher pilot use.

## Current verdict

- Founder-supervised demo ready: yes.
- External teacher pilot ready: no.

## Pre-pilot critical gates

All critical gates must pass before external teacher access.

### Auth/session and access control

- [ ] All pilot routes require authenticated sessions.
- [ ] Teacher identity comes from the session/token, not from request payload `teacher_id`.
- [ ] Teachers can access only courses they own.
- [ ] Teachers can access only assessments under their courses.
- [ ] Teachers can access only submissions/answer regions under their assessments.
- [ ] Review queue, summary, final-grade lookup, approval/edit/reject, and export all enforce owner access.
- [ ] Cross-teacher access tests pass.

### Privacy and retention

- [ ] Founder approves exact teacher/cohort/data scope.
- [ ] Teacher approves use of real scripts.
- [ ] Retention window is documented.
- [ ] Deletion workflow is tested and has a report format.
- [ ] Real files/crops/exports are excluded from git and logs.
- [ ] Provider prompt minimization is documented if real provider use is approved.

### Provider authorization

- [ ] Provider/model calls disabled by default.
- [ ] Each real call requires explicit packet-level approval.
- [ ] No mock fallback after provider failure.
- [ ] No batch grading.
- [ ] Ready evidence preflight runs immediately before provider call.
- [ ] Provider log includes model, packet, teacher/operator, and evidence trace.

### Evidence and queue gates

- [ ] Missing model answer blocks readiness/queue.
- [ ] Missing active rubric blocks readiness/queue.
- [ ] Partial/blank/unconfirmed packet blocks queue.
- [ ] Stale queue item blocks provider call.
- [ ] Existing GradeSuggestion blocks accidental duplicate call unless founder approves rerun.

### Teacher review/final grade gates

- [ ] GradeSuggestion remains draft with `needs_review=true`.
- [ ] FinalGrade is created only by explicit teacher approval/edit/reject.
- [ ] Payload-supplied teacher identity cannot impersonate another teacher.
- [ ] Audit log records teacher id, source GradeSuggestion id, answer_region_id, final score, and approval status.

### Export gates

- [ ] Export requires authenticated owner access.
- [ ] Export includes approved FinalGrades only.
- [ ] Export excludes draft/unapproved GradeSuggestions.
- [ ] Export excludes raw provider JSON, password hashes, secrets, and unsafe internals.
- [ ] Export preserves teacher-edited final score.
- [ ] Export includes source GradeSuggestion id and answer_region_id for traceability.

### Operational safety

- [ ] Demo/operator runbook does not include DB-resetting tests.
- [ ] Destructive tests are clearly labeled as test-only.
- [ ] Backup/restore or inspectability plan exists before pilot day.
- [ ] Failure recovery runbook covers provider failure, stale queue, deletion failure, and accidental wrong upload.
- [ ] Incident stop conditions are known by founder/operator.

## Current audit findings

Critical:

- Review/final-grade/export routes currently include unauthenticated or payload-teacher paths that are acceptable for local demos but not external pilot.
- External pilot cannot start until owner enforcement covers all review/export/final-grade paths.

High:

- Privacy/retention policy is now documented but not operationally accepted/tested with real deletion reports.
- DB-resetting tests can wipe demo inspectability; they must not be part of pilot/demo operator commands.

Medium:

- Runbooks now separate founder demo from external pilot, but a teacher-facing pilot script and consent language still need founder approval.

## Pilot authorization statement

Do not start external teacher pilot until every critical item above is checked and verified with tests or an approved operational control.
