# Local Curated Evaluation Runbook

This runbook executes the 20-case synthetic, teacher-supervised PaddleOCR and Qwen gate. It never starts a model automatically and never creates a final grade. Raw images, workbooks, prompts, confirmations, and results stay under ignored `data/evaluation/<run_id>/`.

## Safety boundaries

- Use a clean harness commit and a dedicated PostgreSQL database named exactly `teacher_assistant_eval_<run_id>`.
- Use synthetic material only for this first run. Do not add student files to the run directory.
- Keep both services loopback-only and load secrets from the ignored `.env.local-ai` file.
- Do not run OCR before a teacher locks the ground-truth workbook.
- Do not run Qwen before a teacher confirms all OCR text.
- OCR is capped at exactly 20 calls. Qwen is capped at exactly 18 calls because both blanks are safety refusals.
- Every call has one attempt and no fallback. A provider failure makes that run invalid.
- `direct_host_eval` invokes the production dispatch worker synchronously because Redis is unavailable. It does not validate RQ crash recovery.

## 1. Prepare without model calls

From `apps/api`, choose a lowercase run ID containing only letters, digits, and underscores. Record the reviewed local-integration commit and current clean harness commit:

```powershell
$runId = 'lc_20260807_teacher01'
$integrationCommit = 'd77c324be425e002e0f5a1c655c38a0671cbf268'
$harnessCommit = git rev-parse HEAD
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation prepare --run-id $runId --integration-commit $integrationCommit --harness-commit $harnessCommit
```

This requires a clean worktree and the ignored `.env.local-ai` path settings. It hashes the local Qwen and Paddle model assets, verifies llama.cpp build `10249` and Paddle package versions, then records those values in the run manifest. It also generates 20 deterministic PNGs and `ground_truth_review.xlsx`. It starts no service and makes zero OCR or Qwen calls; hashing the 20.61 GiB GGUF may take several minutes.

The teacher independently transcribes and scores every case, approves all rows, and marks B4, C3, and E2 as genuinely difficult but legible handwriting. Then lock the workbook:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-ground-truth --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff
```

The lock refuses missing rows, changed scores, transcription disagreement, or unapproved handwriting. If no qualified teacher is available, stop here; the dataset is only an engineering rehearsal.

## 2. Create the disposable database and start services

Create the database using the local PostgreSQL operator account, then apply migrations. Substitute the local loopback port and account without writing credentials into Git:

```powershell
$databaseName = "teacher_assistant_eval_$runId"
$env:DATABASE_URL = "postgresql+psycopg://<local-user>@127.0.0.1:<port>/$databaseName"
..\..\.venv\Scripts\python.exe -m alembic upgrade head
```

Run the explicit preflight/start workflow from the repository root:

```powershell
.\scripts\local-ai\Test-LocalAiPreflight.ps1
.\scripts\local-ai\Start-LocalAi.ps1
```

Normal API or page startup must not replace these commands.

## 3. Run and confirm OCR

From `apps/api`:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation run-ocr --run-id $runId --allow-local-ocr --max-ocr-calls 20 --database-url $env:DATABASE_URL
```

The stage seeds four synthetic submissions across five questions, manually maps 20 answer regions, calls the production OCR endpoint once per region, verifies ownership isolation, and creates `ocr_review.xlsx`.

The teacher enters complete confirmed text for every row, leaves both blank answers empty, fixes every answer-changing OCR error, and explicitly approves all rows. Then run:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-ocr-confirmations --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff --database-url $env:DATABASE_URL
```

This uses the production confirmation API. It separately marks 18 packets complete and two packets blank.

## 4. Run Qwen and complete teacher review

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation run-grading --run-id $runId --allow-local-qwen --max-qwen-calls 18 --expected-model qwen3.6-35b-a3b-q4km --database-url $env:DATABASE_URL
```

The harness builds one immutable queue, verifies 18 ready and two blank-refused packets, then executes five sequential dispatches with limits A=3, B=4, C=3, D=4, and E=4. It stops on the first failure and verifies model alias, evidence hashes, review flags, zero cost, zero final grades, ownership, audit privacy, and an empty approved-only export.

The teacher completes `grading_review.xlsx`, classifies every disagreement, and signs it:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation lock-review --run-id $runId --reviewer-id '<teacher-id>' --confirm-teacher-signoff
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation report --run-id $runId
```

The report is `PASS`, `NO_GO_QUALITY`, or `INVALID_RUN`. Do not tune expected scores or rerun failed cases inside the same run. Only `PASS` permits a supervised Custom Controlled pilot.

## 5. Close out

Verify artifact integrity at any non-invalid stage:

```powershell
..\..\.venv\Scripts\python.exe -m packages.evaluation.local_curated_evaluation verify --run-id $runId
```

Stop Qwen and PaddleOCR after review:

```powershell
.\scripts\local-ai\Stop-LocalAi.ps1
```

Preserve the disposable database until the report has been audited, then remove it using the PostgreSQL operator workflow. Only a sanitized aggregate report may be considered for Git; never commit the generated run directory.
