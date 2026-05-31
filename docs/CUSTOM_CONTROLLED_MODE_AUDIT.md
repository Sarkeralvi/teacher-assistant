# Custom Controlled Mode Completion Audit

Task: `TA-W2-002 Custom Controlled Mode completion audit`  
Baseline commit audited: `904959d Define functional body execution plan`

## A. Audit summary

Current status: **partial**.

Custom Controlled Mode is not blocked at the data/API foundation level. The app already has enough separate pieces to perform a rough controlled grading path with individual scripts, manual answer-region creation, mock grading, teacher review, selected approval, and XLSX export.

It is not yet a cohesive first V0 workflow because the Custom Controlled run page is mostly a wrapper around existing tools. It tracks material uploads and a manually editable status, but it does not enforce or derive completion state from real records, does not guide the teacher through missing work precisely, and does not bind confirmed questions/rubrics/scripts/regions/grading/export back to the run.

### Main blockers

1. **No derived workflow status.** The run status is manually editable, not computed from materials/questions/rubrics/scripts/regions/suggestions/finals.
2. **No hard gate before grading.** Mock grading can run from the review page whenever answer regions exist; it is not tied to a confirmed Custom Controlled run state.
3. **Question/model-answer/rubric confirmation is indirect.** The existing assessment page supports manual question creation and question-paper import drafts, but Custom Controlled does not explicitly confirm separate question PDF, solution PDF, and rubric PDF into canonical records.
4. **Material uploads are stored but not parsed or connected to confirmation.** Question/solution/rubric PDFs persist safely, but they are evidence only; they do not generate or validate canonical questions/rubrics.
5. **Scripts are individual only.** ZIP ingestion is not implemented, by design for this task.
6. **Answer-region mapping remains manual and coordinate-based.** This is acceptable for V0, but the workflow needs clearer status and teacher guidance.
7. **Marking policy is absent.** Tough/General/Easy is not yet modeled or recorded.
8. **Custom Controlled page is a launcher, not a full body.** It links to assessment setup/review/export instead of presenting a single cohesive run dashboard with missing-step blockers.

### Main risks

- A teacher can mark a run as `review_ready` or `completed` manually without the underlying records actually being ready.
- The app can appear to have a Custom Controlled workflow while still relying on the teacher to know which existing pages/actions to use in the correct order.
- Material upload success can be mistaken for question/rubric confirmation.
- Existing mock grading remains safe, but it is not mode-aware and does not record run/mode/policy metadata.
- Real Codex remains correctly gated as a per-answer dev action, but it should not be treated as a batch Custom Controlled capability.

## B. Workflow checklist table

| Target workflow step | Status | Evidence | Missing work | Priority |
|---|---|---|---|---|
| 1. Teacher logs in | Pass | Auth API and login/register UI exist; grading-run routes require `get_current_user`; web API sends stored auth token for grading-run calls. | None for V0 audit. | P0 done |
| 2. Teacher creates/selects course and assessment | Pass | Course and assessment CRUD exist; assessment detail page links to Custom Controlled run. | Mode choice is not yet a unified selector. | P1 |
| 3. Teacher chooses Custom Controlled Mode | Partial | `/assessments/{assessmentId}/grading-run` and `CustomControlledGradingRunClient` exist; POST creates mode `custom_controlled`. | No unified mode selector; only Custom Controlled route exists. | P0 |
| 4. Teacher uploads question PDF, solution/model-answer PDF, rubric PDF | Pass for storage | `POST /grading-runs/{id}/materials` accepts three PDF fields and stores safe relative paths; focused test verifies non-absolute/no traversal paths. | No parsing/extraction/confirmation linkage from those PDFs. | P0 |
| 5. App persists uploaded materials | Pass | `GradingRun` has `question_pdf_path`, `solution_pdf_path`, `rubric_pdf_path`; upload sets status `materials_uploaded`; frontend reloads after upload. | No material preview/download route on the run page. | P1 |
| 6. Teacher confirms or creates questions/model answers/rubrics | Partial | Assessment detail page can manually create questions with `model_answer`; rubric API exists; question import draft accept flow exists. | No Custom Controlled-specific confirmation state; no solution/rubric PDF import workflow; no explicit “confirmed” flags. | P0 |
| 7. Teacher uploads scripts | Pass for individual files | `POST /assessments/{id}/submissions/upload` accepts PDF/image and extracts pages; frontend assessment page exposes upload. | No ZIP ingestion; not wired as a Custom Controlled run step. | P0 later (`TA-W2-004`) |
| 8. App stores script pages | Pass | Submission upload stores upload and creates `SubmissionPage` records/images; tests cover PDF/image upload. | Page quality/status not surfaced in run dashboard. | P1 |
| 9. Teacher creates/maps answer regions | Pass but rough | `POST /submission-pages/{page_id}/answer-regions` crops and stores region; assessment page exposes manual coordinate form. | Coordinate UX is rough; no mapping status per question/script; no confirmation flag. | P0/P1 |
| 10. Teacher runs grading | Partial | Single-answer mock grading and batch mock grading exist; batch mock works in Docker-compatible mode. Dev-only per-answer Codex endpoint exists. | Grading is not gated by Custom Controlled run readiness; suggestions do not record run/mode/policy. | P0 |
| 11. Suggestions appear in review queue | Pass | `GET /assessments/{id}/review-queue` exists; review UI shows suggested/ungraded/finalized states. | Review queue is assessment-level, not run-scoped. | P1 |
| 12. No FinalGrade is created automatically | Pass | Grading service creates `GradeSuggestion`; final-grade endpoints require approve/edit/reject. Prior Codex image-input work also verified no auto-finalization. | Keep invariant in all future modes. | P0 done |
| 13. Teacher can approve/edit/reject | Pass | Final-grade routes and review UI support approve/edit/reject. | None for basic V0. | P0 done |
| 14. Teacher can approve selected suggestions | Pass | `POST /assessments/{id}/final-grades/approve-selected` exists; focused test covers auth teacher and audit summary. | Selection is review-page level, not run-scoped. | P1 |
| 15. Teacher can export XLSX | Pass | `GET /assessments/{id}/export/final-grades.xlsx` exists; tests verify safe headers and no raw provider JSON/password hash. | Export is assessment-level; run-scoped export/status not present. | P1 |
| 16. App clearly shows statuses and blockers | Partial/fail | Custom page lists wizard steps and run status, but status can be manually set. | Need derived status checklist with blocking messages and next action links. | P0 |

## C. Backend audit

### Endpoints present

- `POST /assessments/{assessment_id}/grading-runs/custom`
- `GET /assessments/{assessment_id}/grading-runs`
- `GET /grading-runs/{grading_run_id}`
- `PATCH /grading-runs/{grading_run_id}`
- `POST /grading-runs/{grading_run_id}/materials`
- Existing supporting endpoints for questions, rubrics, submissions, answer regions, mock grading, review/finalization, selected approval, summary, and XLSX export.

### Endpoints missing or incomplete

- No `GET /grading-runs/{id}/status-checklist` or equivalent derived status endpoint.
- No run-scoped list of materials/questions/submissions/regions/suggestions/finals.
- No Custom Controlled confirmation endpoint for questions/model answers/rubrics.
- No run-scoped grading command that checks readiness before grading.
- No run-scoped export endpoint.
- No ZIP ingestion endpoint.
- No marking policy field/API yet.

### Auth status

- Custom Controlled grading-run create/list/detail/update/material upload require current authenticated user.
- Ownership is checked through assessment/course teacher or run creator.
- Existing supporting endpoints are mixed: newer review/Custom Controlled/Codex actions are auth-aware; some older CRUD/setup routes still support earlier demo patterns. This is acceptable for current audit but should be tightened as product hardens.

### Storage behavior

- Material upload accepts PDF content type and stores safe relative paths under local storage.
- Tests verify stored material paths are relative and do not contain traversal components.
- Submission upload stores PDFs/images and page images; answer-region creation stores crop images.
- Raw scripts/materials remain in storage and are not committed.

### Safety concerns

- Good: real Codex browser grading is disabled unless `CODEX_BROWSER_GRADING_ENABLED=true`; Docker mode remains mock-only for normal batch grading.
- Good: batch real Codex is not implemented.
- Good: grading creates suggestions, not final grades.
- Gap: run status can be manually advanced independent of real readiness.
- Gap: mode/policy/run metadata are not persisted on each suggestion yet.

## D. Frontend audit

### Page flow

- Assessment detail page links to Custom Controlled Grading Run and Teacher Review.
- Custom Controlled page can start a run, upload materials, edit run status/notes, and link to existing assessment/review/export tools.
- Review page supports batch mock grading, per-answer real Codex dev action, review filters, selected approval, and export.

### Token handling

- Custom Controlled frontend API calls pass `getStoredAuthToken()`.
- Upload/auth error message exists: `Please log in again before uploading materials.`
- Review page checks current user before real Codex and approve/edit actions.

### Upload behavior

- Material upload form supports question/solution/rubric PDF fields and calls the authenticated material upload endpoint.
- After material upload, the component resets files and reloads run data.
- Individual script upload exists on assessment detail page, not inside the Custom Controlled run dashboard.

### Status display

- Current page displays run status and material path fields.
- Wizard steps are static, not derived from actual readiness.
- Manual status selector is useful for internal experiments but unsafe as the source of truth for V0 readiness.

### Error handling

- Frontend catches errors for run load/start/upload/status update, assessment upload/import/create-region/grading, and review actions.
- Backend-unreachable handling exists in the API wrapper.
- Need clearer blocker messages such as “No active rubric for Q1”, “No scripts uploaded”, “No answer regions mapped”, and “No suggestions ready for review”.

### Teacher guidance

- Safety language is present: no auto-finalization, no real batch Codex by default, teacher confirmation required.
- Guidance is still spread across pages; a teacher must know how to move from Custom Controlled materials to assessment setup to review/export.

## E. Testing audit

### Current tests covering this body

- `tests/test_grading_runs_api.py`: custom run creation/list/detail, material upload storage, non-PDF rejection, ownership, status enum validation.
- `tests/test_grading_api.py`: single-answer mock grading, batch mock grading, provider failures, configured provider paths.
- `tests/test_final_grade_review_api.py`: approve/edit/reject, review queue, summary, selected approval, XLSX export safety.
- `tests/test_browser_codex_grading_api.py`: Codex dev endpoint auth, disabled-runtime guard, provider unavailable/error behavior.
- Frontend TypeScript/lint covers component/API typing.

### Missing tests

- No full Custom Controlled end-to-end test that creates a run, uploads all three materials, creates question/rubric/script/region, grades, reviews, and exports in one scenario.
- No derived status/checklist tests because the endpoint/model does not exist yet.
- No test that prevents grading before Custom Controlled confirmations are complete.
- No tests for run/mode/policy metadata on suggestions.
- No ZIP ingestion tests yet.

### Manual/API-equivalent audit validation run

Commands run during audit:

```bash
make up-infra
cd apps/api && python -m alembic upgrade head
python -m pytest -q \
  tests/test_grading_runs_api.py \
  tests/test_grading_api.py::test_batch_mock_grading_grades_ungraded_regions_only_and_skips_existing \
  tests/test_final_grade_review_api.py::test_batch_approve_selected_suggestions_uses_auth_teacher_and_writes_summary \
  tests/test_final_grade_review_api.py::test_export_xlsx_contains_headers_rows_and_safe_fields \
  tests/test_browser_codex_grading_api.py::test_browser_codex_endpoint_rejects_when_env_flag_disabled
```

Result: `9 passed`.

This validates the key existing pieces without running real Codex. It is API-equivalent coverage, not proof of a smooth single browser workflow.

## F. Recommended implementation plan for `TA-W2-003`

Priority order for the smallest safe V0 body fix:

1. **Add a derived Custom Controlled status/checklist.**
   - Compute material presence, question count, active rubric coverage, submission/page count, answer-region count, grade suggestion count, final-grade count, and export readiness.
   - Return pass/partial/fail plus next action for each step.

2. **Replace manual status-as-truth with status-as-note or derived display.**
   - Keep notes if useful.
   - Do not let a manual dropdown claim `completed` while required records are missing.

3. **Make the Custom Controlled page a real dashboard.**
   - Show checklist, blockers, counts, and next links/actions.
   - Keep rough UI; no redesign/polish.

4. **Add confirmation flags or minimal confirmation actions for questions/rubrics.**
   - For V0, “confirmed” may be a run-level checklist action after teacher reviews existing Question/Rubric records.
   - Do not implement AI parsing of solution/rubric PDFs in TA-W2-003.

5. **Gate Custom Controlled grading actions in the UI.**
   - Show mock grading only when questions/rubrics/scripts/regions are present.
   - Backend run-scoped gate can come with a focused endpoint if small; otherwise document as next subtask.

6. **Add one full end-to-end API test for Custom Controlled V0.**
   - Start run, upload materials, create question/rubric, upload one script, create answer region, mock grade, approve, export.
   - Assert no automatic final grade before teacher approval.

7. **Keep exclusions explicit.**
   - No ZIP upload in TA-W2-003.
   - No marking policy behavior in TA-W2-003.
   - No real batch Codex.
   - No answer-region auto-detection.
   - No UX redesign.

## G. Do-not-do list

- No full automation yet.
- No ZIP upload in this audit task.
- No real Codex grading in this audit task.
- No batch real Codex yet.
- No voice command work.
- No public launch claim.
- No UX polish before the functional body works.
- No raw private scripts/materials committed.

## Decision

`TA-W2-002` is complete as an audit/report task.

Next task remains:

```text
TA-W2-003 Custom Controlled Mode full usable workflow fix
```

The recommended TA-W2-003 target is not a redesign. It should add derived workflow status, clear blockers, minimal confirmation tracking, and one full V0 API test so Custom Controlled Mode becomes a coherent rough end-to-end workflow before ZIP, marking policy, semi-automation, or full automation.
