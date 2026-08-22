# Local Curated Evaluation Runbook

This is the 20-case, synthetic, teacher-supervised quality gate. Qwen3.8-27B
performs visual transcription in a fresh non-thinking call. It never grades an
image. Qwen3.6 and Qwen3.8 are then compared as separate text-only graders on
the same hash-pinned teacher-confirmed evidence. Nothing in this run creates a
`FinalGrade` or changes normal pilot configuration.

All raw images, workbooks, transcripts, and results stay under ignored
`data/evaluation/<run_id>/`. A completed evaluation may honestly return
`NO_GO_QUALITY`; only a complete `PASS` plus the separate grader bake-off can
support a supervised Custom Controlled rehearsal.

## Safety rules

- Use synthetic material only. Never add real student material to this gate.
- Start models only through `scripts/local-ai`; ordinary app/page startup must not start one.
- Use a fresh, empty database named exactly `teacher_assistant_eval_<run_id>`.
- Lock teacher ground truth before any Qwen3.8 visual call.
- Do not correct a model transcript. A non-faithful transcript is a valid quality failure.
- Each source run makes exactly 20 Qwen3.8 visual calls. Each grading candidate makes exactly 18 text-only calls; two blanks are refused before dispatch.
- There are no retries, fallbacks, cloud calls, hidden calls, or automatic finalisation.
- Model leases are mandatory. A busy/missing lease fails before an inference request is sent.

## 1. Prepare and lock ground truth

From `apps/api`, use a lowercase run ID and record the reviewed integration
commit plus the current clean harness commit:

```powershell
$runId = 'lc_20260822_teacher01'
$integrationCommit = '<reviewed-integration-commit>'
$harnessCommit = git rev-parse HEAD
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation prepare --run-id $runId --integration-commit $integrationCommit --harness-commit $harnessCommit --grading-model qwen3.6-35b-a3b-q4km
```

This makes zero model calls. It creates deterministic images and
`ground_truth_review.xlsx`. A qualified teacher independently transcribes and
scores all 20 cases, approves every row, and confirms the three difficult
handwriting cases as legible. Then lock the workbook:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-ground-truth --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff
```

The lock refuses incomplete, altered, or unsigned ground truth.

## 2. Start host services and create the empty evaluation database

From the repository root, start the Windows host stack, then create the
create-only evaluation database. The helper refuses an existing database,
applies migrations to head, and sets `DATABASE_URL` only in the current
PowerShell session. It does not start a model.

```powershell
.\scripts\pilot\Start-TeacherPilot.ps1
.\scripts\evaluation\New-LocalCuratedEvaluationDatabase.ps1 -RunId $runId
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode Qwen38
.\scripts\local-ai\Start-LocalAi.ps1 -Mode Qwen38
```

## 3. Run Qwen3.8 visual transcription and teacher review

From `apps/api`:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation run-ocr --run-id $runId --allow-local-ocr --max-ocr-calls 20 --database-url $env:DATABASE_URL
```

The production visual-transcription job is called once per mapped answer
region under a Qwen3.8 lease. It produces `ocr_review.xlsx`. The teacher
compares each hash-pinned transcript against its image and does not type a
corrected answer.

If all readings are faithful, sign the confirmations:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-ocr-confirmations --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff --database-url $env:DATABASE_URL
```

That uses production confirmation and full-answer gates. Eighteen answers are
complete; the two genuinely blank answers remain blank and are never grading
ready.

If any reading is wrong, set `teacher_confirms_faithful=no`, select its fixed
quality-rejection reason, and set `teacher_approved=no`. Do not grade it. Lock
the valid quality failure instead:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation record-ocr-no-go --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff --database-url $env:DATABASE_URL
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation report --run-id $runId
```

This produces `NO_GO_QUALITY` with zero grading calls. It is not an integrity
failure and must not be tuned or rerun under the same run ID.

## 4. Run the isolated text-grader bake-off

Only after the source reaches `ocr_confirmed`, fork it. The fork locks the same
teacher-confirmed text and source-image hashes for both candidates. It makes no
provider call:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.grading_model_bakeoff fork --source-run-id $runId
```

Run one candidate at a time. `Enable-LocalCuratedEvaluation.ps1` is deliberately
session-scoped: it enables the bounded evaluation CLI only, not cohort grading
inside the already-running teacher-pilot API process.

```powershell
# Qwen3.6 text grader
$candidateRunId = "${runId}_qwen36"
..\..\scripts\evaluation\New-LocalCuratedEvaluationDatabase.ps1 -RunId $candidateRunId
..\..\scripts\evaluation\Enable-LocalCuratedEvaluation.ps1 -RunId $candidateRunId
..\..\.venv\Scripts\python.exe -m packages.evaluation.grading_model_bakeoff seed --source-run-id $runId --candidate qwen36 --database-url $env:DATABASE_URL
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation run-grading --run-id $candidateRunId --allow-local-qwen --max-qwen-calls 18 --expected-model qwen3.6-35b-a3b-q4km --database-url $env:DATABASE_URL
# Teacher completes and signs ${candidateRunId}/grading_review.xlsx
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-review --run-id $candidateRunId --reviewer-id '<teacher-id>' --confirm-teacher-signoff
..\..\scripts\evaluation\Disable-LocalCuratedEvaluation.ps1

# Qwen3.8 text grader
$candidateRunId = "${runId}_qwen38"
..\..\scripts\evaluation\New-LocalCuratedEvaluationDatabase.ps1 -RunId $candidateRunId
..\..\scripts\evaluation\Enable-LocalCuratedEvaluation.ps1 -RunId $candidateRunId
..\..\.venv\Scripts\python.exe -m packages.evaluation.grading_model_bakeoff seed --source-run-id $runId --candidate qwen38 --database-url $env:DATABASE_URL
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation run-grading --run-id $candidateRunId --allow-local-qwen --max-qwen-calls 18 --expected-model qwen3.8-27b-q4km --database-url $env:DATABASE_URL
# Teacher completes and signs ${candidateRunId}/grading_review.xlsx
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-review --run-id $candidateRunId --reviewer-id '<teacher-id>' --confirm-teacher-signoff
..\..\scripts\evaluation\Disable-LocalCuratedEvaluation.ps1
```

The production safe dispatch rechecks ownership, evidence, rubric, model alias,
and call caps immediately before each call. Grading receives only canonical
question/solution/rubric material and teacher-confirmed text; it receives no
student image. Every suggestion stays pending teacher review.

Compare only after both signed grading reviews:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.grading_model_bakeoff compare --source-run-id $runId
```

Qwen3.8 is promoted only if it passes every quality/safety gate, gains at least
two exact cases or improves MAE by at least 0.15, adds no severe error, and
meets the latency gates. Otherwise Qwen3.6 remains the default if it passes.
The comparison never changes normal configuration automatically.

## 5. Close out

At any non-invalid source stage, verify its lock chain:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation verify --run-id $runId
```

Stop the model explicitly after the operator review:

```powershell
.\scripts\local-ai\Stop-LocalAi.ps1
```

Keep disposable databases until reports have been audited. Never commit
generated run directories, raw material, API keys, machine paths, or student
text.
