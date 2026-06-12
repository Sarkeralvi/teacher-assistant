# Custom Controlled V0 Failure Paths

Failure-path checklist and verification results for the founder-supervised Custom Controlled V0 release candidate.

No real provider/model calls are required for these checks unless a separate work order explicitly approves one. Use synthetic data only.

## Safety baseline

- Mock fallback is not allowed after provider failure.
- Batch grading is not allowed in the Custom Controlled founder flow.
- FinalGrade is created only after explicit teacher/founder approval.
- Export contains approved FinalGrade rows only.
- Blocked or stale packets must not reach provider calls.

## Failure paths to verify

### 1. Missing model answer blocks readiness and queue

Expected behavior:

- Evidence packet reports model answer missing.
- `ready_for_grading = false`.
- Evidence prep counts the packet as blocked.
- Queue scaffold refuses the packet.
- Provider call must not be made.

Pass signal:

- blocker mentions missing model answer / solution.
- no GradeSuggestion, FinalGrade, or GradingJob is created by this path.

### 2. Missing rubric blocks readiness and queue

Expected behavior:

- Evidence packet reports active rubric missing.
- `ready_for_grading = false`.
- Evidence prep counts the packet as blocked.
- Queue scaffold refuses the packet.
- Provider call must not be made.

Pass signal:

- blocker mentions missing active rubric.
- no GradeSuggestion, FinalGrade, or GradingJob is created by this path.

### 3. Partial packet blocks queue

Expected behavior:

- Answer region marked partial/blank/unconfirmed is not treated as complete evidence.
- Queue scaffold refuses it.
- Provider call must not be made.

Pass signal:

- `evidence_status != complete` or `ready_for_grading = false`.
- refused reason includes evidence status or missing complete confirmed segment.
- no GradeSuggestion, FinalGrade, or GradingJob is created by this path.

### 4. Stale queue item blocks provider call

Expected behavior:

- If answer evidence changes after queue creation, queued evidence becomes stale.
- Provider call preflight must stop before real grading.

Pass signal:

- queue item readback shows `stale_status = stale`, `blocked_now`, or `evidence_missing`.
- no provider/model call is made for the stale packet.

### 5. Unapproved GradeSuggestion is not exported

Expected behavior:

- Draft GradeSuggestion remains review-only.
- XLSX export excludes it until teacher approval creates FinalGrade.

Pass signal:

- export row count excludes the unapproved draft.
- no row has blank `final_grade_id` treated as final.

### 6. Export includes teacher-edited FinalGrade score, not raw AI suggestion

Expected behavior:

- Teacher-edited score/comment are preserved in FinalGrade.
- XLSX exports FinalGrade score, not raw AI score.

Pass signal:

- exported `final_score` equals the teacher-edited score.
- source GradeSuggestion id remains traceable separately.

### 7. Mock/batch grading buttons are not exposed in Custom Controlled founder flow

Expected behavior:

- Founder Custom Controlled path should not present mock or batch grading as the intended action.
- Real grading, if approved, is single-packet only and clearly teacher-review-gated.

Pass signal:

- UI/static workflow text emphasizes one real Codex call per packet and teacher review required.
- mock/batch grading is not used in rehearsal.

### 8. Provider unavailable/auth failure stops without fallback

Expected behavior:

- Provider failure creates no mock replacement.
- No retry occurs without founder approval.
- If a GradingJob exists, it is failed and no GradeSuggestion/FinalGrade is created.

Pass signal:

- error is reported honestly.
- mock count remains zero.
- GradeSuggestion/FinalGrade counts do not increase.

## Known verification status

Validated by focused backend tests and rehearsals:

- Missing model answer and missing rubric block readiness/queue in evidence-prep and queue tests.
- Partial/non-complete evidence blocks queue.
- Queue stale-status logic reports stale/blocked/missing evidence.
- Export excludes unapproved GradeSuggestion rows.
- Export includes approved FinalGrade rows only.
- Teacher-edited final score is exported instead of raw AI suggestion score.
- Real provider failure path previously produced no mock fallback and no FinalGrade.

## Commands used for failure-path checks

Run from repo root:

```bash
cd /home/newton/teacher-assistant
cd apps/api && DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant' ../../.venv/bin/python -m pytest -q \
  tests/test_evidence_prep_runs_api.py \
  tests/test_grading_queue_runs_api.py \
  tests/test_grading_api.py::test_unwritable_grading_context_blocks_before_provider_call \
  tests/test_final_grade_review_api.py::test_export_xlsx_contains_headers_rows_and_safe_fields \
  tests/test_final_grade_review_api.py::test_export_xlsx_excludes_pending_region_without_final_grade
```

Then from repo root:

```bash
make lint
git diff --check
make health
make frontend-health
git status --short
```

## Stop conditions for founder demos

Stop immediately and report if any of these appear:

- missing model answer
- missing active rubric
- partial/blank packet
- stale queue item
- provider unavailable or auth failure
- export attempted before approval
- GradeSuggestion count changes outside approved grading calls
- FinalGrade count changes before explicit teacher approval
- GradingJob count changes during docs/export-only work
- dirty git status before a controlled run
