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

## TA-W1-036B — Custom controlled grading run end-to-end validation

- Recorded at: 2026-05-31T12:56:02+06:00
- Baseline commit: `fb903828b3c16c44ce5925c1f6097bc847954412`
- Workflow type: API-equivalent validation with host backend and frontend running
- Real Codex calls: 1 grading call through `POST /answer-regions/{answer_region_id}/grade-codex-dev`
- Provider used for real-grade step: `codex_cli`
- Mock grading calls during real-grade step: 0
- Data policy: synthetic non-student PDFs/image only; no sample PDFs were present in the repository
- Product code changes required: none

### Synthetic records created

| Record | ID |
| --- | ---: |
| Teacher | 4011 |
| Course | 3598 |
| Assessment | 3494 |
| Custom grading run | 118 |
| Question | 3024 |
| Rubric | 2034 |
| Submission | 2682 |
| Submission page | 2762 |
| Answer region | 2597 |
| Grade suggestion | 1752 |
| Final grade | 1236 |

### Controlled workflow result

- Material upload endpoint: `POST /grading-runs/118/materials`
- Material status after refresh: `materials_uploaded`
- Uploaded material paths persisted after refresh: yes
- Uploaded material types: synthetic question PDF, solution/model-answer PDF, rubric PDF
- Uploaded script: synthetic PNG image
- Manual answer region creation: passed
- Codex suggestion provider: `codex_cli`
- Codex suggestion `needs_review`: true
- Codex suggestion score/confidence: `0.00` / `0.0000`
- Review queue before teacher action: `suggested`
- Final grade before teacher action: HTTP 404, confirming no auto-finalization
- Teacher action: manual edit/finalization
- Final grade status after teacher action: `edited`

### Assessment summary counts

| Metric | Value |
| --- | ---: |
| Total submissions | 1 |
| Total answer regions | 1 |
| Total grade suggestions | 1 |
| Total final grades | 1 |
| Approved count | 0 |
| Edited count | 1 |
| Rejected count | 0 |
| Pending review count | 0 |
| Average final score | 5.00 |
| Max possible score | 5.00 |

### XLSX export result

- Endpoint: `/assessments/3494/export/final-grades.xlsx`
- Local exported file: `/tmp/ta-w1-036b/assessment-3494-final-grades.xlsx`
- Export HTTP status: 200
- Export size: 5273 bytes
- Workbook rows including header: 2
- Created record IDs were present in export cells: yes
- Confirmed absent from exported workbook text: `raw_response_json`, `password_hash`

### Verification results

- Initial `git status --short`: clean
- `make up-infra`: passed
- `make codex-ok`: passed, returned `OK`
- Local Alembic migration against localhost Postgres: passed
- Host backend health: passed
- Frontend readiness at `localhost:3000`: passed
- Custom controlled workflow validation: passed
- `make test`: passed (`135 passed`)
- `make lint`: passed
- `npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- Services shutdown: passed (`docker compose down` completed; no compose services left running)
- Final `git status --short` before docs commit: clean except `BACKLOG.md` and `docs/VALIDATION_LOG.md` after recording this validation

### Known issue / observation

The real Codex grading call was operationally verified, but Codex image input remains disabled in the current runtime. The provider therefore produced a conservative zero-score suggestion from available metadata/rubric context. This validation proves the controlled workflow and teacher-review/export gate, not grading quality or full automation.

## TA-W1-037A — Codex image-input browser/backend smoke

Date: 2026-05-31

### Scope

Enable and validate image input for exactly one browser/backend Codex grading smoke using synthetic/non-student data. No batch real grading, no auto-finalization, no final-grade rule change, no fully automated grading, no voice command, and no TA-W1-038 work.

### Codex CLI support

- Installed CLI: `codex-cli 0.128.0`
- `codex exec --help` advertises image input: `-i, --image <FILE>...`
- Safe auth/syntax probe: `make codex-ok` passed and returned `OK`.

### Config/runtime changes

- Docker/demo default remains image-input off through `.env.example` and app settings.
- `make backend-host-dev` now preserves the safe default while allowing explicit override:
  - default: `CODEX_CLI_IMAGE_INPUT_ENABLED=false`
  - image smoke: `CODEX_CLI_IMAGE_INPUT_ENABLED=true make backend-host-dev`
- Host-backend image-input instructions were added to `docs/CODEX_DEV_RUNTIME.md`.
- Provider behavior:
  - includes `--image <answer crop path>` only when image input is enabled and an answer image path is present;
  - omits `--image` when image input is disabled or no image path exists;
  - never stores or sends base64 image data through raw persisted output.

### Smoke setup

- Infra: `make up-infra`
- Migrations: local Alembic upgrade against localhost Postgres
- Backend: host `make backend-host-dev` with `CODEX_CLI_IMAGE_INPUT_ENABLED=true`
- Frontend: host Next dev server on `localhost:3000`, readiness returned HTTP 307
- Synthetic fixture: `/tmp/ta-w1-037a/synthetic-answer.png`

### Created IDs

| Item | ID |
| --- | ---: |
| Teacher | 4092 |
| Course | 3669 |
| Assessment | 3563 |
| Question | 3078 |
| Rubric | 2072 |
| Submission | 2734 |
| Submission page | 2815 |
| Answer region | 2647 |
| Grade suggestion | 1782 |

### Smoke result

- Real Codex calls through app endpoint: exactly one `POST /answer-regions/2647/grade-codex-dev`
- `model_provider`: `codex_cli`
- `score`: `5.00`
- `confidence`: `0.9900`
- `needs_review`: true
- `review_flags`: `teacher_review_required`, `codex_cli_provider`, `image_input_used`
- Final grade before teacher action: HTTP 404, confirming no auto-finalization
- Review queue count: 1
- Summary after smoke: `total_grade_suggestions=1`, `total_final_grades=0`, `pending_review_count=1`

### Verification results

- Focused provider tests: passed (`16 passed` including provider and image-unsupported API check)
- `make test`: passed (`137 passed`)
- `make lint`: passed
- `npm run build`: passed; emitted existing non-fatal ESLint flat-config warning while exiting 0
- Service shutdown: passed (`make down` completed; no compose services left running)

### Known issue / observation

This validates one synthetic image-input path and mandatory teacher review. It does not validate grading quality on real handwriting, batch grading, fully automated grading, voice command, or TA-W1-038.
