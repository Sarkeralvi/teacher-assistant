# Operational Failure Runbook

Operational failure handling for Custom Controlled V0 and future external teacher pilot hardening.

## General rule

Stop first, preserve evidence, and report exact counts. Do not improvise provider retries, mock fallback, batch grading, auto-finalization, or DB resets.

## Required first snapshot

From repo root:

```bash
cd /home/newton/teacher-assistant
git status --short
make health
make frontend-health
```

For a grading incident, also capture counts:

```bash
docker compose exec -T backend python - <<'PY'
from app.db.session import SessionLocal
from app.models import GradeSuggestion, FinalGrade, GradingJob
s = SessionLocal()
print('GradeSuggestion', s.query(GradeSuggestion).count())
print('FinalGrade', s.query(FinalGrade).count())
print('GradingJob', s.query(GradingJob).count())
s.close()
PY
```

Do not run destructive/resetting tests as incident commands.

## Provider failure

Symptoms:

- Codex/provider auth failure
- provider timeout
- malformed provider output
- GradingJob failed

Action:

1. Stop the run at the failed packet.
2. Record assessment id, answer_region_id, provider, model, and job status.
3. Confirm whether any GradeSuggestion was created for that packet.
4. Confirm no FinalGrade was created.
5. Do not retry without founder approval.
6. Do not use mock fallback.
7. Do not continue to later packets unless founder explicitly approves a new bounded scope.

Report:

- failed packet id
- real provider call count before failure
- GradeSuggestion/FinalGrade/GradingJob counts before/after
- whether mock/batch was used

## Stale or blocked queue item

Symptoms:

- `stale_status != fresh`
- `ready_for_grading != true`
- blockers not empty
- evidence changed after queue creation

Action:

1. Do not call provider.
2. Re-open evidence preview.
3. Fix evidence manually only if founder/teacher approves.
4. Re-run evidence prep/queue after the fix.
5. Confirm fresh queue before any provider call.

Report:

- blocker list
- stale status
- whether any provider call was avoided

## Missing model answer or rubric

Action:

1. Stop grading.
2. Add/activate only teacher-approved model answer/rubric.
3. Re-run evidence prep.
4. Confirm ready count and blocked count.
5. Do not grade until queue is fresh.

## Incorrect upload or private data uploaded outside scope

Action:

1. Stop all grading/provider calls.
2. Identify assessment/submission/page ids.
3. Do not open/share files beyond what is needed for deletion verification.
4. Delete according to `STUDENT_SCRIPT_PRIVACY_AND_RETENTION.md`.
5. Capture deletion report.
6. Notify founder.

## Export issue

Symptoms:

- export includes draft/unapproved GradeSuggestion
- exported final score does not match teacher-edited FinalGrade
- unsafe fields appear, such as raw provider JSON or password hashes
- cross-teacher export access suspected

Action:

1. Stop sharing the export.
2. Preserve the bad export only in local incident evidence if needed; do not commit it.
3. Verify FinalGrade and GradeSuggestion ids in DB.
4. Run focused export tests.
5. Patch only after root cause is identified.

Required export checks:

- row count equals approved FinalGrade count
- `approval_status = approved`
- source GradeSuggestion id included
- answer_region_id included
- edited final score preserved
- unsafe internals excluded

## DB reset or data loss risk

Symptoms:

- focused tests cleared demo records
- assessment no longer exists after tests
- GradeSuggestion/FinalGrade/GradingJob counts unexpectedly zero

Action:

1. Stop demo operation.
2. Confirm whether reset came from test fixtures.
3. Do not run provider/model calls to recreate inspectability.
4. If synthetic demo records must be restored, restore deterministic synthetic fixtures only and report that restoration clearly.
5. Never use DB-resetting tests as demo commands.

## Dirty git status before controlled run

Action:

1. Stop before side effects.
2. Inspect `git status --short` and `git diff --stat`.
3. Classify changes as intended, generated, or unsafe.
4. Continue only after founder approves or working tree is clean.

## Final incident report fields

- incident type
- assessment id
- answer_region_id(s)
- GradeSuggestion/FinalGrade/GradingJob counts before/after
- provider call count
- mock used yes/no
- batch used yes/no
- FinalGrade created yes/no
- export shared yes/no
- files deleted/restored yes/no
- tests/checks run
- final git status
- whether founder demo can continue
- whether external pilot remains blocked
