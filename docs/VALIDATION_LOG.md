# Validation Log

## TA-W1-019 — End-to-end teacher workflow validation

- Recorded at: 2026-05-27T05:23:20+06:00
- Baseline commit: `c7dc0b40214024c91e7556a41188682e3c994861`
- Workflow type: mixed API + health checks
- Real Codex calls: 0
- Provider used: mock
- Data policy: synthetic non-student data only
- Product code changes required: none
- Commit generated during TA-W1-019 validation itself: none

### Synthetic records created

| Record | ID |
| --- | ---: |
| Teacher | 901 |
| Course | 848 |
| Assessment | 831 |
| Question | 780 |
| Rubric | 538 |
| Submission | 593 |
| Submission page | 609 |
| Answer region | 576 |
| Grade suggestion | 410 |
| Final grade | 267 |

### Workflow result

- Grading call count during validation: 1
- Grading job status: succeeded
- Page image fetch: HTTP 200
- Answer-region image fetch: HTTP 200
- Grade suggestions for answer region: 1
- Review queue before teacher approval: `suggested`
- Review queue after teacher approval: `finalized`
- Final grade status: `approved`
- Final-grade readback ID matched created final grade ID: yes (`267`)

### Assessment summary counts

| Metric | Value |
| --- | ---: |
| Total submissions | 1 |
| Total answer regions | 1 |
| Total grade suggestions | 1 |
| Total final grades | 1 |
| Approved count | 1 |
| Edited count | 0 |
| Rejected count | 0 |
| Pending review count | 0 |
| Average final score | 0.00 |
| Max possible score | 10.00 |

### XLSX export result

- Endpoint: `/assessments/831/export/final-grades.xlsx`
- Workbook sheet: `Final Grades`
- Exported data rows: 1
- Reviewed row present: yes
- Forbidden headers present: none
- Confirmed absent: `raw_response_json`, `password_hash`
- Included final status/comment fields for the approved synthetic record.

### Verification results

- `make up`: passed
- `docker compose exec -T backend alembic upgrade head`: passed
- `make health`: passed
- Mixed API workflow smoke: passed
- `make test`: passed (`77 passed`)
- `make lint`: passed
- `docker compose exec -T frontend npm run build`: passed; emitted existing ESLint flat-config warning while exiting 0
- `make frontend-health`: passed after frontend restart
- `make down`: passed
- Final `git status --short` after TA-W1-019 validation: clean

### Known issue / observation

Running the frontend production build inside the same Docker dev container/volume temporarily poisoned the Next dev cache and made the immediate frontend health check return HTTP 500. Restarting the frontend container and waiting for readiness restored `make frontend-health`. No product code change was required for TA-W1-019.

## TA-W1-029B — Real Codex question extraction smoke

- Recorded at: 2026-05-29T15:22:25+06:00
- Code fix commit: `9d05806`
- Workflow type: controlled API smoke through `POST /assessments/{assessment_id}/question-imports`
- Real Codex calls: 1 question extraction call
- Provider used: `codex_cli_question_extractor`
- Data policy: synthetic non-student PNG question paper only
- Codex workdir: isolated `/tmp/ta-codex-question-import-smoke-workdir`
- Config enabled for smoke only: `CODEX_QUESTION_EXTRACTION_ENABLED=true`, `CODEX_CLI_IMAGE_INPUT_ENABLED=true`, `CODEX_CLI_SKIP_GIT_REPO_CHECK=true`

### Synthetic records created

| Record | ID |
| --- | ---: |
| Assessment | 2179 |
| Question import job | 63 |
| Accepted Question | 1924 |
| Accepted Question | 1925 |
| Accepted Question | 1926 |

### Extraction result

- Input type: `image/png`
- Draft count: 3
- Provider warnings: none
- All drafts had `needs_review=true`: yes
- Draft confidences: `0.95`, `0.95`, `0.95`
- Draft questions:
  1. `Differentiate y = x^2.` — 5 marks
  2. `Solve 2x + 3 = 7.` — 4 marks
  3. `State Newton's first law.` — 3 marks

### Teacher-review gate verification

- Real `Question` rows before accept: 0
- Accept selected drafts result: 3 created
- Real `Question` rows after accept: 3
- Accepted question IDs: 1924, 1925, 1926

### Verification results

- `git status --short` before work: clean at `23f8c48`
- Safe no-repo Codex auth check: passed, returned `OK`
- `make up`: passed
- `docker compose exec -T backend alembic upgrade head`: passed
- `make health`: initially hit transient connection reset while backend was still starting; retry passed
- Focused backend question import/provider tests: passed (`16 passed`)
- Frontend workflow static checks: passed
- `make test`: passed (`109 passed`)
- `make lint`: passed
- `docker compose exec -T frontend npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- `make down`: passed
- Final `git status --short` before docs commit: only `BACKLOG.md` and `docs/VALIDATION_LOG.md` modified

### Known issue / observation

The controlled smoke validated a simple synthetic image only. Extraction remains a teacher-reviewed draft feature, not automatic final question creation.
