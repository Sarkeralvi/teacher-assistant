# Full Workflow Baseline

## Passed workflow

Synthetic document workflow verified end-to-end:

1. Evidence extraction and readiness gating were already in place from TA-FULL-004.
2. Synthetic grading produced a draft GradeSuggestion.
3. Teacher review queue exposed the draft suggestion.
4. Explicit teacher approval created a FinalGrade.
5. Approved-only export produced an XLSX containing the FinalGrade row.
6. Duplicate approval was idempotent and updated the existing FinalGrade instead of duplicating it.

## Synthetic fixture used

- Teacher: synthetic authenticated teacher account created in test flow
- Course: `RVX102`
- Assessment: `Midterm`
- Question: `1(a)`
- Model answer: `4`
- Rubric: single correctness criterion worth `5.00`
- Submission identifier: `SYN-1`
- Answer region text: `Q1(a) 2+2=4`

## Provider / model

- Grading provider path used in this baseline: mock grading path for approval/export smoke
- Live provider smoke was already validated in TA-FULL-005 using `codex_cli` / `gpt-5.5`

## Results

- Draft GradeSuggestion created: `4828`
- FinalGrade created: `3159`
- FinalGrade approval status: `approved`
- Export row count: 2 worksheet rows total, 1 data row plus header
- Export excluded unapproved suggestions: yes
- Review queue exposed question context, rubric context, evidence text, score, feedback, provider/model metadata, and `needs_review=True`

## Limitations / remaining risks

- Review/approval/export baseline here used the mock grading path, not a live provider call.
- Frontend build emits a pre-existing ESLint config-format warning during Next build, but the build still completes.
- The workflow remains sensitive to stale `.next` artifacts; clearing only `apps/web/.next` restored runtime health during this recovery.

## Can teacher evaluation resume?

Yes. The full synthetic workflow from evidence through approval/export is now demonstrable end-to-end.