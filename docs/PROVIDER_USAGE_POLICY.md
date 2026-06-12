# Provider Usage Policy

Provider/model usage is prohibited by default. This policy applies to Codex CLI, OpenAI, and any other AI/model provider used for grading, mapping, OCR, extraction, or feedback.

## Default rule

No provider/model call may run unless the active work order explicitly authorizes the exact bounded call scope.

For Custom Controlled V0:

- mock grading: not allowed in founder release-candidate flow
- batch grading: not allowed
- auto-finalize: not allowed
- auto-approve: not allowed
- real grading: single-packet only, explicitly triggered
- GradeSuggestion: draft only, `needs_review=true`
- FinalGrade: teacher approval only

## Required authorization packet before provider call

Before each real provider call, the operator must confirm:

1. assessment id
2. question/grading unit id or label
3. answer_region_id
4. model answer / solution present
5. active rubric present
6. crop/segment visible
7. `evidence_status = complete`
8. continuation resolved
9. `ready_for_grading = true`
10. blockers empty
11. queue item `stale_status = fresh`
12. no existing GradeSuggestion for the answer region unless the founder explicitly approves a rerun
13. approved provider/model name
14. remaining approved call count
15. teacher/founder approval for this call scope

If any item fails, do not call the provider.

## Provider refusal gates

Blocked/stale/unready packets must refuse provider access. Refuse if:

- missing model answer / solution
- missing active rubric
- incomplete/partial/blank evidence
- continuation unresolved
- queue stale or missing
- packet already has a GradeSuggestion and rerun was not approved
- provider auth unavailable
- worktree dirty before a controlled run
- call count would exceed approved limit

## Logging and audit requirements

Every provider-created GradingJob/GradeSuggestion must be traceable to:

- assessment id
- question id
- answer_region_id
- teacher/operator id when available
- provider name
- model name
- prompt version
- marking policy
- evidence readiness state at call time or queue item
- job status
- created timestamp

FinalGrade audit must separately log:

- teacher id
- FinalGrade id
- source GradeSuggestion id
- answer_region_id
- final score
- approval status

## Export policy

Exports must include approved FinalGrades only. They may include source GradeSuggestion id and safe AI summary fields, but must not export raw provider JSON, secrets, password hashes, or unapproved draft suggestions as final grades.

## Failure behavior

If a provider call fails:

- stop the run
- do not retry without founder approval
- do not fall back to mock
- do not create FinalGrade
- report the failed answer_region_id, provider/model, job status, and safety counts

## External pilot status

Provider use with real student data is blocked until:

- owner enforcement covers review/export/final-grade endpoints
- non-synthetic data policy is accepted
- privacy/retention policy is accepted
- teacher consent/authorization is captured
- provider prompt minimization and logging are verified
