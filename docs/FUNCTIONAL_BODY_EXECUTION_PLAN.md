# Functional Body Execution Plan

## A. Program director principle

The immediate objective is not launch polish. The immediate objective is a complete functional body: a teacher can move from login to export through one coherent grading workflow, even if the UI is rough.

Program rules:

- Build the full body first.
- UX polish second.
- Professional polish third.
- Do not build random isolated features.
- Every task must move the app closer to a usable teacher grading product.
- The founder/owner sets product direction; Hermes implements disciplined milestones.
- No public launch until functional gates and grading-quality gates pass.
- Teacher remains final authority.
- AI never auto-finalizes grades.
- Real AI actions stay explicit, gated, logged, and review-required.

## Current implementation audit

### Proven capabilities

| Capability | Current support |
|---|---|
| Teacher auth/login | Backend auth routes and web login/register pages exist. |
| Course/assessment/question/rubric workflow | CRUD foundations exist for courses, assessments, questions, and rubrics. |
| Question paper extraction | `question_imports` routes and extractor/evaluation harness exist; real extraction remains gated. |
| PDF/image script upload | Submission upload and page extraction exist. |
| Manual answer-region creation | `answer_regions` route and crop storage exist. |
| Mock grading | Grading service and mock provider path exist. |
| Browser/backend Codex CLI grading | Dev-only single-answer Codex route exists behind explicit flag/runtime. |
| Codex image input | Codex CLI image flag path is proven in capped smoke/eval. |
| Teacher review/finalization | Final-grade and review-queue flows exist. |
| Batch mock grading | Batch mock grading path exists. |
| Selected batch approval | Selected approval flow exists. |
| XLSX export | Export from finalized grades exists. |
| Custom controlled grading run | `grading_runs` model/routes and rough wizard exist. |
| Evaluation harnesses | Question-import and grading evaluation packages exist. |
| Original-document grading tests | Original-script smoke/eval artifacts recorded in quality notes. |
| Host-backend Codex dev runtime | `backend-host-dev` and Codex dev runtime docs exist. |

### Current limitations

- Custom Controlled mode is not yet smooth enough as one complete teacher workflow.
- Fully Automated grading is not implemented.
- Semi-Automated confirmation flow is incomplete.
- ZIP script upload and batch submission ingestion are missing.
- Answer-region detection/mapping remains manual.
- Tough/General/Easy marking policy is not implemented or persisted.
- Real grading quality needs broader evaluation on mixed original teacher-marked cases.
- Docker backend does not contain Codex CLI; real Codex browser grading requires host-backend mode.
- UI is rough, but UX polish is intentionally deferred until the body works.

## B. Three grading modes

## Mode 1 — Fully Automated

### Required inputs

- Question PDF.
- ZIP file containing all student scripts.
- Marking policy: Tough, General, or Easy.

### Teacher confirmation points

- Teacher must approve/edit every final grade.
- V0 should still expose extracted questions/model answers/rubrics for teacher inspection before grading when feasible.
- Teacher must select or confirm marking policy before grading starts.

### Backend workflow

1. Create a grading run with mode `fully_automated`.
2. Upload question PDF.
3. Upload ZIP of scripts.
4. Extract/discretize questions and sub-questions.
5. Draft model answers and rubrics.
6. Process ZIP into submissions/pages.
7. Attempt answer-region detection/mapping.
8. Create grading jobs for mapped regions only after required run state is ready.
9. Generate AI suggestions with mode and marking policy recorded.
10. Send all suggestions to review queue.
11. Export only teacher-approved final grades.

### Frontend workflow

1. Teacher selects Fully Automated mode.
2. Teacher uploads question PDF and ZIP.
3. Teacher sees extraction/mapping/grading statuses.
4. Teacher confirms marking policy.
5. Teacher reviews AI output and all uncertain/error cases.
6. Teacher approves/edits/rejects suggestions.
7. Teacher exports XLSX.

### AI usage

- Highest AI usage: question extraction, model-answer drafting, rubric drafting, possible answer-region detection/mapping support, and grading.
- Real AI must be explicitly enabled and bounded until quality is proven.

### Safety gates

- No automatic final grades.
- Batch real AI disabled until validation gates pass.
- Every suggestion records mode, policy, provider, prompt version, image-input state, confidence, and review flags.
- Failed extraction/mapping/grading creates visible statuses and does not silently disappear.

### Current app support

- Question import foundation.
- Submission processing foundation.
- Manual answer regions.
- Mock/Codex grading path.
- Review/finalization/export.
- Evaluation harnesses.

### Missing pieces

- ZIP ingestion.
- `fully_automated` grading-run mode.
- Automated or assisted answer-region mapping.
- Question-to-region mapping.
- Draft model-answer/rubric generation quality gates.
- Batch real grading controls.
- Mode-specific status orchestration.

### MVP usable definition

A teacher can upload a question PDF and script ZIP, get draft extracted questions and script submissions, manually correct/confirm any uncertain mapping, run mock or tightly controlled grading suggestions, review every suggestion, and export teacher-approved grades. It is not reliable or launch-ready until quality gates pass.

## Mode 2 — Semi-Automated

### Required inputs

- Question PDF.
- Scripts as individual PDFs/images initially; ZIP after ZIP ingestion exists.
- Marking policy: Tough, General, or Easy.

### Teacher confirmation points

- Question discretization.
- Model answers.
- Rubrics and mark allocation.
- Marking policy.
- Every final grade.

### Backend workflow

1. Create a grading run with mode `semi_automated`.
2. Upload/import question PDF.
3. Generate draft questions, model answers, and rubrics.
4. Store drafts separately from confirmed records.
5. Teacher confirms/edits drafts into canonical Question/Rubric records.
6. Upload scripts or ZIP.
7. Create/manual-map answer regions or use assisted mapping when available.
8. Run grading only after required confirmations are complete.
9. Send suggestions to review queue.
10. Export only finalized grades.

### Frontend workflow

1. Teacher selects Semi-Automated mode.
2. Teacher uploads question PDF.
3. Teacher reviews editable draft questions/model answers/rubrics.
4. Teacher confirms marking policy.
5. Teacher uploads scripts.
6. Teacher maps/validates answer regions.
7. Teacher runs grading suggestions.
8. Teacher reviews/finalizes and exports.

### AI usage

- AI drafts questions, model answers, and rubrics.
- AI grades confirmed materials after teacher approval.
- Real AI extraction/grading must remain explicit and logged.

### Safety gates

- Grading cannot start until questions/model answers/rubrics/policy are confirmed.
- AI-created drafts remain drafts until teacher accepts them.
- Every grade suggestion requires teacher review.

### Current app support

- Question import draft/accept foundation.
- Question/rubric CRUD.
- Submission upload.
- Manual answer regions.
- Grading/review/export.

### Missing pieces

- Model-answer draft workflow.
- Rubric draft confirmation workflow tied to question import.
- Marking policy selection/persistence.
- Grading-run mode `semi_automated`.
- Confirmation state gates.
- ZIP ingestion.

### MVP usable definition

A teacher can upload a question PDF, review/edit/confirm AI-drafted questions/model answers/rubrics, select marking policy, upload scripts, create answer regions, run suggestions, review/finalize, and export. Batch real AI remains disabled unless explicitly validated.

## Mode 3 — Custom Controlled

### Required inputs

- Question PDF.
- Solution/model answer PDF.
- Rubric PDF.
- Scripts as individual PDFs/images initially; ZIP after ZIP ingestion exists.
- Marking policy: Tough, General, or Easy.

### Teacher confirmation points

- Questions/sub-questions.
- Model answers.
- Rubrics/mark allocation.
- Marking policy.
- Answer-region mapping where manual/assisted mapping is used.
- Every final grade.

### Backend workflow

1. Create a grading run with mode `custom_controlled`.
2. Upload question, solution, and rubric PDFs as separate materials.
3. Track material status and safe relative paths.
4. Teacher creates/imports/edits canonical questions/model answers/rubrics.
5. Teacher uploads scripts.
6. Teacher manually maps answer regions for V0.
7. System runs mock grading or controlled single-answer Codex grading; controlled batch real grading only after later gates.
8. Suggestions enter teacher review.
9. Teacher edits/approves/rejects.
10. Export final XLSX.

### Frontend workflow

1. Teacher selects Custom Controlled mode or starts a custom controlled grading run.
2. Teacher uploads question/solution/rubric materials.
3. Teacher follows links/actions to create/import questions and rubrics.
4. Teacher uploads scripts.
5. Teacher creates answer regions manually.
6. Teacher runs grading suggestions.
7. Teacher reviews/finalizes.
8. Teacher exports.

### AI usage

- Minimal AI requirement for V0: mock grading and explicitly gated single-answer Codex dev grading.
- Later: controlled batch Codex grading with strict limits and review gates.

### Safety gates

- Required material and confirmation statuses must be visible.
- Grading must not start without confirmed questions/rubrics and mapped answer regions.
- Real Codex remains explicit and review-required.
- No raw docs/artifacts in git.

### Current app support

- Custom grading-run model/routes and rough page.
- Material upload for question/solution/rubric PDFs.
- Existing question/rubric/submission/answer-region/review/export flows.
- Mock grading and single-answer Codex dev path.

### Missing pieces

- One coherent mode selector / run entry point.
- Completion audit of every step in the Custom Controlled run.
- Status gating that tells teacher what is missing before grading/export.
- Integrated material/question/script/region/review/export workflow state.
- ZIP script ingestion.
- Marking policy selection and persistence.

### MVP usable definition

A teacher can use Custom Controlled mode from start to export with rough UI: login, create course/assessment, start run, upload question/solution/rubric, confirm questions/model answers/rubrics, upload scripts, manually map answer regions, run mock or explicitly controlled grading suggestions, review/approve, and export XLSX.

## C. Functional V0 definition

A usable V0 must allow a teacher to:

1. Login.
2. Create a course and assessment.
3. Choose a grading mode.
4. Upload required materials.
5. Confirm questions, model answers, and rubrics.
6. Upload scripts.
7. Create or map answer regions.
8. Run grading suggestions.
9. Review, edit, and approve suggestions.
10. Export XLSX.

V0 success means this path works end-to-end for at least Custom Controlled mode. It does not mean the app is professionally polished or ready for launch.

## D. Required core modules

| Module | Purpose | Current state | Next action |
|---|---|---|---|
| Grading run mode selector | Teacher chooses Custom Controlled, Semi-Automated, or Fully Automated. | Custom Controlled route exists; unified selector missing. | Add after Custom Controlled audit. |
| Material upload manager | Upload question/solution/rubric/script/ZIP materials with safe storage and statuses. | Custom materials and script uploads exist separately. | Unify status and missing-step reporting. |
| Question/model-answer/rubric confirmation | Teacher confirms canonical grading materials. | Question import and rubric CRUD exist; model/rubric confirmation incomplete. | Build confirmation gates. |
| Script upload manager | Process PDFs/images and later ZIP into submissions/pages. | Individual PDF/image upload exists. | Add ZIP ingestion later. |
| Answer-region mapping workflow | Create/manual/assisted answer regions and track mapping status. | Manual answer-region creation exists. | Improve workflow status before automation. |
| Grading execution workflow | Run mock/controlled AI suggestions with mode/policy metadata. | Mock and gated single-answer Codex exist. | Add policy and controlled batch gates later. |
| Review/finalization workflow | Teacher reviews/edits/approves/rejects; AI never finalizes. | Exists. | Ensure every mode routes here. |
| Export workflow | Export teacher-approved final grades. | XLSX export exists. | Wire clearly from each mode. |
| Evaluation/quality logging | Measure grading quality and provider behavior. | Evaluation harness exists. | Expand datasets and policy/mode metrics. |

## E. Build order

1. Stabilize Custom Controlled Mode as the first complete mode.
2. Add ZIP script upload and batch submission ingestion.
3. Add marking policy selection and persistence.
4. Add semi-automated question/model/rubric confirmation.
5. Add controlled batch real grading with strict limits.
6. Add answer-region mapping improvements.
7. Add fully automated prototype last.
8. UX polish after functional body is complete.

Rationale:

- Custom Controlled is safest because teacher-provided question/solution/rubric materials reduce ambiguity.
- ZIP ingestion is a body-level requirement for real classroom batches.
- Marking policy must be persisted before prompt behavior changes matter.
- Semi-Automated adds AI drafting only after the controlled path is coherent.
- Batch real grading must wait for mode/policy/status gates.
- Answer-region mapping automation should improve a working manual flow, not replace it prematurely.
- Fully Automated is last because extraction, drafting, ZIP processing, mapping, and grading errors compound.
- UX polish is valuable only after the workflow body exists.

## F. Immediate next implementation tasks

- `TA-W2-001` — Functional body reset and unified grading workflow foundation.
- `TA-W2-002` — Custom Controlled Mode completion audit.
- `TA-W2-003` — Custom Controlled Mode full usable workflow fix.
- `TA-W2-004` — ZIP script upload and batch submission ingestion.
- `TA-W2-005` — Marking policy model: Tough/General/Easy.
- `TA-W2-006` — Marking policy-aware Codex grading prompt.
- `TA-W2-007` — Semi-automated question/model/rubric confirmation flow.
- `TA-W2-008` — Controlled batch Codex grading with review gates.
- `TA-W2-009` — Answer-region mapping improvement.
- `TA-W2-010` — Fully automated mode prototype planning.
- `TA-W2-011` — UX redesign after full functional body works.

## G. Quality rules

- No auto-final grade.
- Every AI suggestion needs teacher review.
- Real AI calls must be explicit.
- Batch real AI must be disabled until validated.
- Raw private data must not be committed.
- All scripts/materials stay out of git.
- Failed grading must not block review/export for already available suggestions/finals.
- Every workflow must have clear status.
- Every real provider path must sanitize errors and avoid leaking secrets or raw base64.
- Mode, policy, provider, prompt version, confidence, and review flags must be auditable.
- The app must not be marked launch-ready until end-to-end body and quality gates pass.

## H. Decision

The next implementation after this task should be:

```text
TA-W2-002 Custom Controlled Mode completion audit
```

Reason: Custom Controlled Mode is the safest first full-body workflow. It already has the most supporting code, relies on teacher-provided solution/rubric materials, and can become the first complete V0 path before adding ZIP ingestion, marking policy, semi-automation, controlled batch real grading, or fully automated prototypes.

## Stop line for TA-W2-001

TA-W2-001 intentionally stops at execution structure and backlog reset. It does not implement Fully Automated mode, ZIP upload, grading behavior changes, UI polish, marking policy behavior, or real Codex grading.
