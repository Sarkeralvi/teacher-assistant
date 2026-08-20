# Provider Usage Policy

Provider/model usage is prohibited by default. This policy applies to local Qwen3.6/Qwen3.8, Codex CLI, OpenAI, and any other AI/model provider used for grading, mapping, OCR, extraction, or feedback.

## Default rule

No provider/model call may run unless the active work order explicitly authorizes the exact bounded call scope.

For Custom Controlled V0:

- mock grading: not allowed in founder release-candidate flow
- local cohort grading: allowed only through the safe dispatch contract below
- external/Codex batch grading: not allowed
- auto-finalize: not allowed
- auto-approve: not allowed
- single-packet real grading: explicitly triggered
- GradeSuggestion: draft only, `needs_review=true`
- FinalGrade: teacher approval only

## Local safe-dispatch exception

Local Qwen cohort execution is allowed only when all of these controls are active:

- `BRAIN_ALLOW_REAL_PROVIDERS=true`
- `LOCAL_QWEN_ENABLED=true`
- `COHORT_MODEL_GRADING_ENABLED=true`
- loopback API-key-authenticated llama.cpp with the exact configured model alias
- an explicit request naming queue run, grading run, question, provider, expected model, call limit, and draft-only confirmation
- a fresh immutable queue snapshot and exactly one active rubric
- teacher-confirmed manual/OCR answer text; Qwen image input disabled
- sequential execution with a server ceiling of 25 calls
- stop before the next call, stop on first provider failure, and zero automatic retries
- no provider fallback and no automatic `FinalGrade`

Tier-1 OCR runs in-process on the CPU and contacts no service, so it is not a provider call. Its output is still a draft until teacher confirmation, and escalating a page it could not read to the local vision model IS a provider call: it is bounded by a pre-authorized escalation budget and stops the run rather than exceeding it.

## Required authorization packet before provider call

Before each real provider call, the operator must confirm:

1. assessment id
2. question/grading unit id or label
3. answer_region_id, or the explicit selected queue items in a capped local dispatch
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
15. teacher/founder approval for this call scope and draft-only confirmation

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
- do not automatically retry; an uncertain in-flight item must never be retried automatically
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
