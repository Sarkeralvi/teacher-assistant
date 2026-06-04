# INITIAL TASK BACKLOG

TASK-ID: TA-W1-001
Title: Create project operating system documents
Owner: Hermes
Priority: P0
Dependencies: None
Files affected: PROJECT_CONSTITUTION.md, ARCHITECTURE.md, BRAIN_ADAPTER_SPEC.md, GRADING_ENGINE_SPEC.md, DEVELOPMENT_PROTOCOL.md, WEEK_1_EXECUTION_MAP.md, BACKLOG.md
Goal: Establish the rules, boundaries, and first-week execution plan before coding.
Implementation notes: Docs only. No production code.
Acceptance criteria: Required documents exist and include requested sections.
Tests required: Manual document completeness review.
Risks: Overdesign or vague rules.
Status: Done

TASK-ID: TA-W1-002
Title: Lock initial tech stack
Owner: Human
Priority: P0
Dependencies: TA-W1-001
Files affected: TECH_STACK_DECISION.md, ARCHITECTURE.md, BRAIN_ADAPTER_SPEC.md, GRADING_ENGINE_SPEC.md, DEVELOPMENT_PROTOCOL.md
Goal: Lock frontend, backend, database, worker, storage, AI, document processing, export, dev, and testing stack.
Implementation notes: Human provided exact stack. Hermes documented it and aligned architecture/spec/protocol docs.
Acceptance criteria: `TECH_STACK_DECISION.md` exists and architecture/spec/protocol docs reflect the locked stack.
Tests required: Manual document consistency review.
Risks: Introducing unapproved dependency later.
Status: Done

TASK-ID: TA-W1-002A
Title: Convert development protocol to Hermes-only builder model
Owner: Hermes
Priority: P0
Dependencies: TA-W1-002
Files affected: DEVELOPMENT_PROTOCOL.md, DAY_1_SCAFFOLD_PLAN.md, BACKLOG.md
Goal: Remove separate VS Code/Codex worker model and define Hermes as planner + coder + tester + reviewer.
Implementation notes: Docs only. No production code.
Acceptance criteria: Protocol and scaffold plan assign implementation/control to Hermes only; backlog owners updated.
Tests required: Search docs for obsolete VS Code/Codex worker ownership references.
Risks: Hidden stale ownership references may confuse execution.
Status: Done

TASK-ID: TA-W1-003
Title: Create initial repository scaffold
Owner: Hermes
Priority: P0
Dependencies: TA-W1-002, TA-W1-002A, DAY_1_SCAFFOLD_PLAN.md
Files affected: README.md, Makefile, docker-compose.yml, .env.example, .gitignore, apps/**, packages/**, data/**, docs/**, BACKLOG.md
Goal: Create a clean monorepo scaffold for Next.js frontend, FastAPI backend, PostgreSQL, Redis, local storage directories, and baseline health/boundary tests.
Implementation notes: Follow `DAY_1_SCAFFOLD_PLAN.md` plus latest Human scope exactly. No product feature logic. No real LLM provider integration. Hermes must run commands/tests before marking done.
Acceptance criteria: Repo structure matches plan/latest scope; docker-compose has frontend/backend/postgres/redis; backend and frontend dependencies match locked stack; health endpoint exists; Brain Adapter/storage/grading directories exist as boundaries only; no LLM SDK outside Brain Adapter; required commands run and pass or failures are documented exactly.
Tests required: `cd apps/api && pytest -q`; `make test`; `make lint`; `make up`; `make health`; `make down`.
Risks: Scaffold tool may add unwanted dependencies or feature code; Docker may be unavailable.
Status: Done

TASK-ID: TA-W1-004
Title: Backend core data model and database migrations
Owner: Hermes
Priority: P0
Dependencies: TA-W1-003
Files affected: apps/api/app/models.py, apps/api/app/db/**, apps/api/alembic/**, apps/api/tests/**, BACKLOG.md
Goal: Implement the backend database foundation for Teacher Assistant using SQLAlchemy 2.x and Alembic.
Implementation notes: Includes typed SQLAlchemy models, PostgreSQL-friendly JSONB/Numeric fields, relationships, indexes, and initial Alembic migration. No API CRUD endpoints, auth logic, grading logic, upload pipeline, or LLM/Brain Adapter calls.
Acceptance criteria: Initial schema migration applies reproducibly against Docker PostgreSQL; required tables, relationships, indexes, JSONB/Numeric fields, and import/migration tests exist; Docker health, tests, and lint pass.
Tests required: `make up`; `docker compose exec -T backend alembic upgrade head`; table verification via PostgreSQL; `make test`; `make lint`; `make down`.
Risks: Early schema may need evolution after product workflows are refined.
Status: Done

TASK-ID: TA-W1-005
Title: Backend CRUD APIs for core academic workflow
Owner: Hermes
Priority: P0
Dependencies: TA-W1-003, TA-W1-004
Files affected: apps/api/app/main.py, apps/api/app/api/routes/**, apps/api/app/schemas.py, apps/api/tests/test_academic_crud_api.py, BACKLOG.md
Goal: Implement minimal backend CRUD APIs for Teacher/User placeholder → Course → Assessment → Question → Rubric.
Implementation notes: Adds FastAPI route modules, database session dependency usage, Pydantic create/update/read schemas, relationship validation, Decimal-compatible mark fields, password_hash-safe user responses, and app-level one-active-rubric enforcement. No auth, login, uploads, grading, LLM calls, or frontend UI.
Acceptance criteria: Required CRUD endpoints exist; invalid parent relationships return 404; rubric_json must be a JSON object; user responses do not expose password_hash; tests and lint pass against the Docker PostgreSQL stack.
Tests required: `make up`; `docker compose exec -T backend alembic upgrade head`; `make test`; `make lint`; optional curl smoke if service is running; `make down`.
Risks: Delete behavior remains conservative; deeper cascade/soft-delete policy can be refined later.
Status: Done

TASK-ID: TA-W1-006
Title: Frontend core workflow UI
Owner: Hermes
Priority: P0
Dependencies: TA-W1-003, TA-W1-004, TA-W1-005
Files affected: apps/web/app/**, apps/web/components/**, apps/web/lib/api.ts, apps/web/tests/**, BACKLOG.md
Goal: Implement the first usable browser workflow for Teacher/User placeholder → Course → Assessment → Question → Rubric.
Implementation notes: Adds a centralized frontend API client, dashboard/navigation shell, users/dev teacher setup, course list/create/detail, assessment list/create/detail, question list/create/detail, and rubric JSON create/list UI. No auth, uploads, grading, student portal, Brain Adapter, or LLM calls.
Acceptance criteria: Frontend pages load, API base URL is centralized/env-backed, create/list workflow works from browser-facing routes, records persist after refresh, backend tests and frontend typecheck/lint pass.
Tests required: `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; `make test`; `make lint`; frontend static workflow check; curl/manual workflow smoke; `make down`.
Risks: UI is intentionally minimal; richer validation and styling remain future work.
Status: Done

TASK-ID: TA-W1-006C
Title: Frontend Docker artifact permission hygiene
Owner: Hermes
Priority: P0
Dependencies: TA-W1-006
Files affected: docker-compose.yml, apps/web/.dockerignore, BACKLOG.md
Goal: Fix frontend Docker/dev setup so Docker does not leave root-owned generated frontend artifacts that break local builds.
Implementation notes: Frontend container now runs as the host developer UID/GID defaults and keeps node_modules in a Docker volume. Docker build context ignores generated frontend artifacts. Existing root-owned .next/next-cache artifacts were cleaned.
Acceptance criteria: `make up`, `make health`, `curl -fsS http://localhost:3000`, Docker frontend build, local frontend build/typecheck, `make lint`, `make down`, and final git status checks pass without root-owned frontend artifacts.
Tests required: Inspect ownership; inspect docker-compose frontend service; run Docker and local frontend build/typecheck/lint checks.
Risks: ESLint flat-config warning remains from existing scaffold, but Next build exits successfully.
Status: Done

TASK-ID: TA-W1-007
Title: Submission upload and PDF/image storage foundation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-006, TA-W1-006C
Files affected: apps/api/app/core/config.py, apps/api/app/main.py, apps/api/app/schemas.py, apps/api/app/api/routes/submissions.py, apps/api/app/services/storage.py, apps/api/app/services/submission_processing.py, apps/api/tests/test_submission_upload_api.py, apps/web/components/AssessmentDetailClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Implement the foundation for uploading scanned answer files for an assessment and storing generated submission page metadata.
Implementation notes: Adds a local filesystem storage adapter, upload/artifact directory configuration, PDF/PNG/JPG/JPEG validation, original upload storage, PyMuPDF PDF-to-page-image extraction, image normalization to one page, submission listing/detail APIs, safe page-image serving, and assessment-detail upload/list UI. No grading, OCR, answer-region detection, auth, student portal, LLM, or Brain Adapter calls.
Acceptance criteria: Image upload to a valid assessment creates a Submission and exactly one SubmissionPage; PDF upload creates a Submission and one or more SubmissionPage records; invalid assessment IDs return 404; unsupported file types return 415; stored DB paths are relative and safely resolved; uploaded/generated runtime files stay ignored by git; frontend can upload, list submissions, and link page images from the assessment detail page.
Tests required: `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; backend upload tests for image/PDF/invalid assessment/unsupported types/page serving; `make test`; `make lint`; manual API upload smoke for image and PDF; `curl -fsS http://localhost:8000/health`; `curl -fsS http://localhost:3000`; Docker frontend build; `make down`; final git status review.
Risks: Local storage is intentionally minimal and adapter-backed for later S3/MinIO; quality scoring remains nullable placeholder; richer previews and upload size limits can be refined later.
Status: Done

TASK-ID: TA-W1-007A
Title: Rubric schema validation and rubric editor hardening
Owner: Hermes
Priority: P0
Dependencies: TA-W1-005, TA-W1-006, TA-W1-007
Files affected: apps/api/app/schemas.py, apps/api/app/api/routes/rubrics.py, apps/api/tests/**, apps/web/components/QuestionDetailClient.tsx, apps/web/tests/**, BACKLOG.md
Goal: Enforce strict rubric schema v1 before grading work starts and provide a simple criteria editor instead of raw JSON-only entry.
Implementation notes: Added Pydantic RubricCriterionSchema/RubricJsonSchema validation, question total-mark matching, active-rubric conflict preservation, and frontend criteria editor with raw preview.
Acceptance criteria: Valid rubrics save; malformed rubrics fail with displayable backend errors; inactive rubrics remain allowed while a question already has an active rubric.
Tests required: Focused backend schema validation tests, full backend suite, lint/typecheck, frontend build, manual rubric workflow smoke.
Risks: ESLint flat-config warning remains from existing scaffold during Next build, but build exits successfully.
Status: Done

TASK-ID: TA-W1-008
Title: Manual answer-region mapping and crop storage
Owner: Hermes
Priority: P0
Dependencies: TA-W1-006, TA-W1-007A
Files affected: apps/api/app/api/routes/answer_regions.py, apps/api/app/services/answer_region_processing.py, apps/api/app/services/storage.py, apps/api/app/schemas.py, apps/api/app/main.py, apps/api/tests/**, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/**, BACKLOG.md
Goal: Allow teachers to manually map a question to a rectangular crop on an uploaded submission page and store/serve the cropped answer image.
Implementation notes: Added answer-region create/list/detail/image/delete APIs, safe root-guarded crop storage, crop bounds validation, assessment/question consistency validation, frontend coordinate-entry workflow, and deterministic API/static tests. No grading, OCR, answer detection, LLM, or Brain Adapter calls.
Acceptance criteria: Valid answer regions persist with relative crop image paths; invalid pages/questions/coordinates fail; crop image is served as PNG; frontend exposes upload-to-region workflow.
Tests required: Focused backend answer-region API tests, full backend suite, lint/typecheck, frontend build, health curls, manual API crop smoke.
Risks: Coordinate entry is manual/numeric only until a later visual crop UI is assigned.
Status: Done

TASK-ID: TA-W1-009
Title: Brain Adapter v1 and mock grading contract
Owner: Hermes
Priority: P0
Dependencies: TA-W1-007A, TA-W1-008
Files affected: apps/api/packages/brain/**, apps/api/app/services/grading_service.py, apps/api/app/api/routes/grading.py, apps/api/app/schemas.py, apps/api/app/main.py, apps/api/tests/**, apps/api/pyproject.toml, BACKLOG.md
Goal: Prove the structured AI-grading contract through a Brain Adapter mock provider without real external LLM calls.
Implementation notes: Added provider base, mock provider, model policy, prompt registry, cost placeholder, structured output validation, grading service, and read/create grading endpoints. Mock output is explicitly provider/model labeled as mock, confidence 0, needs_review true, score 0, and teacher-review flagged.
Acceptance criteria: POST grading from an AnswerRegion creates a succeeded GradingJob and schema-valid GradeSuggestion; missing region returns 404; missing active rubric returns 400; suggestions/jobs are readable; no direct external LLM imports exist outside packages/brain.
Tests required: Focused Brain Adapter contract tests, focused grading API tests, full backend suite, lint/typecheck, Docker health curls.
Risks: Frontend mock-grading UI intentionally deferred; current task validates backend contract only.
Status: Done

TASK-ID: TA-W1-010
Title: Teacher review and final grade workflow
Owner: Hermes
Priority: P0
Dependencies: TA-W1-008, TA-W1-009
Files affected: apps/api/app/api/routes/final_grades.py, apps/api/app/services/final_grade_service.py, apps/api/app/schemas.py, apps/api/app/models.py, apps/api/alembic/versions/**, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/api/tests/**, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Implement AnswerRegion → Mock GradeSuggestion → Teacher review → FinalGrade workflow without real LLM/OCR/auth.
Implementation notes: Added FinalGrade finalize/read endpoints, assessment review queue, explicit teacher_id validation, final_score bounds validation, current-final-grade upsert behavior per AnswerRegion, centralized frontend API calls, and functional assessment-detail review UI with MOCK label, rubric breakdown, final score/comment, and approve/edit/reject actions.
Acceptance criteria: GradeSuggestion can be finalized into FinalGrade; invalid score/teacher/suggestion cases fail clearly; review queue reports ungraded/suggested/finalized states; browser workflow supports mock grading review and persists final grade after refresh.
Tests required: Focused final-grade/review API tests, frontend workflow static checks, full backend suite, lint/typecheck, frontend build, health curls, and manual API smoke for upload → answer region → mock grade → final grade.
Risks: No real auth yet; teacher_id is explicit dev input. No audit-event persistence yet.
Status: Done

TASK-ID: TA-W1-011
Title: Real LLM provider integration behind Brain Adapter
Owner: Hermes
Priority: P0
Dependencies: TA-W1-009, TA-W1-010
Files affected: apps/api/packages/brain/**, apps/api/app/core/config.py, apps/api/app/services/grading_service.py, apps/api/tests/test_openai_provider.py, apps/api/tests/test_grading_api.py, .env.example, docs/BRAIN_ADAPTER.md, BACKLOG.md
Goal: Add one OpenAI-compatible provider behind the Brain Adapter while preserving mock default, structured output validation, teacher review, safe errors, and no direct LLM calls outside packages/brain.
Implementation notes: Mock remains default and works without keys. BRAIN_PROVIDER=openai requires OPENAI_API_KEY. OPENAI_MODEL and OPENAI_BASE_URL are optional. OpenAI-compatible v1 is text-only; image transmission is deferred and the prompt forbids claiming handwriting/image understanding. Provider errors are sanitized before API response/GradingJob storage.
Acceptance criteria: OpenAI-compatible provider exists only under packages/brain; real provider output validates into GradeSuggestionOutput; invalid/provider-error paths fail safely and mark jobs failed; no API keys are committed or logged; teacher review remains required.
Tests required: Focused OpenAI provider/config tests, grading provider-failure API test, no-direct-LLM-import test, full backend suite, lint/typecheck, Docker health checks.
Risks: Text-only real provider cannot honestly grade handwritten/image-only answers until image input is implemented.
Status: Done

TASK-ID: TA-W1-012
Title: OpenAI vision input support for cropped answer images
Owner: Hermes
Priority: P0
Dependencies: TA-W1-011, TA-W1-011A
Files affected: apps/api/packages/brain/**, apps/api/app/core/config.py, apps/api/tests/test_openai_provider.py, apps/api/tests/test_grading_api.py, .env.example, docs/BRAIN_ADAPTER.md, BACKLOG.md
Goal: Add optional cropped answer-region image input for the OpenAI-compatible Brain Adapter provider while preserving mock default, structured output validation, and teacher review.
Implementation notes: OPENAI_IMAGE_INPUT_ENABLED defaults false. When true with BRAIN_PROVIDER=openai, Brain Adapter safely resolves the existing cropped PNG/JPEG under local storage, encodes it as a base64 data URL, and includes it in the OpenAI-compatible chat-completions user message. Mock provider ignores image input. Text-only mode remains available and honest. Image base64 is not persisted in GradeSuggestion raw_response_json.
Acceptance criteria: Image payload is included only when OpenAI image input is enabled; disabled mode sends no image data; missing/invalid image fails safely; provider output remains a GradeSuggestion with needs_review=true and teacher_review_required; no direct LLM imports outside packages/brain; no real API calls in tests.
Tests required: Focused OpenAI image-provider tests, focused grading API image tests, no-direct-LLM-import test, full backend suite, lint/typecheck, Docker health checks, frontend build.
Risks: Real handwritten grading quality remains unvalidated until a separately approved manual smoke with a real API key.
Status: Done

TASK-ID: TA-W1-013
Title: Codex CLI provider behind Brain Adapter
Owner: Hermes
Priority: P0
Dependencies: TA-W1-009, TA-W1-010, TA-W1-012
Files affected: apps/api/packages/brain/codex_cli_provider.py, apps/api/packages/brain/adapter.py, apps/api/app/core/config.py, apps/api/tests/test_codex_cli_provider.py, apps/api/tests/test_grading_api.py, .env.example, docs/BRAIN_ADAPTER.md, BACKLOG.md
Goal: Add a local Codex CLI provider behind the Brain Adapter using `codex exec` subprocess execution and no direct OpenAI API key requirement.
Implementation notes: Added `BRAIN_PROVIDER=codex_cli`, Codex CLI preflight, `codex exec --cd ... --sandbox read-only --output-last-message ...` command construction, JSON parsing/validation against existing `GradeSuggestionOutput`, sanitized failure handling, forced teacher review flags, and default-disabled image input. Mock remains default. OpenAI provider remains unchanged. No OCR, automatic answer detection, autonomous final grading, or app-server runtime added.
Acceptance criteria: Codex CLI provider requires local `codex` command but not `OPENAI_API_KEY`; uses `--output-last-message` as authoritative output; fails clearly for missing flags, unsupported image input, non-JSON, timeouts, and non-zero exits; persists `GradeSuggestion` through existing grading flow; teacher review remains mandatory.
Tests required: Focused Codex CLI provider tests with mocked subprocess, focused grading API tests with mocked Codex provider, existing mock/OpenAI tests, no-direct-external-LLM-import scan, full backend suite, lint/typecheck, Docker health checks, frontend build.
Risks: Codex CLI image grading is default-off and only allowed when actual CLI image flag support is detected; real Codex grading smoke intentionally deferred to a separate task.
Status: Done


TASK-ID: TA-W1-014
Title: Real Codex grading smoke test
Owner: Hermes
Priority: P0
Dependencies: TA-W1-013, TA-W1-013A
Files affected: No code files; used existing Brain Adapter/Codex CLI provider path and runtime data under ignored storage.
Goal: Run exactly one controlled real Codex grading call through the existing Brain Adapter path and persist a GradeSuggestion.
Implementation notes: Verified Codex auth, Docker services, migrations, health, one answer region fixture, active rubric, cropped image, image input, structured output validation, GradeSuggestion persistence, and GradingJob success. No code changes were required.
Acceptance criteria: One real Codex grading call succeeds through GradingService -> BrainAdapter -> CodexCliProvider; saved output includes provider/model/prompt version, raw JSON, score/max/confidence/needs_review, rubric breakdown, and succeeded job status.
Tests required: `make test`; `make lint`; backend/frontend health curls; `make down`; final clean git status.
Risks: Single smoke proves path viability only, not grading quality.
Status: Done

TASK-ID: TA-W1-015
Title: Real grading evaluation harness
Owner: Hermes
Priority: P0
Dependencies: TA-W1-014
Files affected: apps/api/packages/evaluation/**, apps/api/tests/test_grading_evaluation.py, docs/GRADING_EVALUATION.md, BACKLOG.md
Goal: Measure grading behavior against teacher/reference scores before trusting AI grading output.
Implementation notes: Adds a documented JSON/JSONL evaluation case format, backend evaluation runner, explicit real-provider guard, hard max real-case guard, metric calculation, and ignored JSON/Markdown artifacts under data/exports/grading_evals. No teacher review UI, final grade updates, Excel export, or production batch grading.
Acceptance criteria: Harness can load selected answer-region cases, call the existing grading service/provider path, persist GradeSuggestion records, compare AI score to expected score, calculate metrics, flag false-confident errors, and write ignored evaluation artifacts.
Tests required: Focused evaluation tests; `make test`; `make lint`; Docker migration/health checks; frontend build; `make down`; final clean git status.
Risks: Metrics quality depends on human-curated reference cases; real provider mode must remain small and explicitly approved.
Status: Done

TASK-ID: TA-W1-016
Title: First controlled real grading evaluation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-015
Files affected: Temporary ignored dataset/artifacts only; no committed code changes.
Goal: Run the first tiny controlled real-provider grading evaluation through the harness.
Implementation notes: Used one synthetic non-student fixture case, explicit Codex provider enablement, and max real cases guard. Produced ignored JSON/Markdown evaluation artifacts under /tmp. No production batch grading and no final-grade updates.
Acceptance criteria: Real-provider harness run completes on 1 controlled case, reports metrics and per-case result, then test/lint/Docker checks pass.
Tests required: `make test`; `make lint`; Docker health; `make down`; clean git status.
Risks: One synthetic case validates pipeline only and does not establish grading accuracy.
Status: Done

TASK-ID: TA-W1-017
Title: Teacher review and final grade approval workflow
Owner: Hermes
Priority: P0
Dependencies: TA-W1-013, TA-W1-014, TA-W1-015, TA-W1-016
Files affected: apps/api/app/api/routes/final_grades.py, apps/api/app/schemas.py, apps/api/app/services/final_grade_service.py, apps/api/tests/test_final_grade_review_api.py, apps/web/lib/api.ts, apps/web/components/AssessmentReviewClient.tsx, apps/web/app/assessments/[assessmentId]/review/page.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Convert AI GradeSuggestions into teacher-controlled FinalGrade records through approve, edit, or reject review actions.
Implementation notes: Adds explicit approve/edit/reject endpoints, keeps legacy finalize endpoint, upserts one current FinalGrade per answer region, writes audit logs for teacher review actions, validates score bounds, and adds a simple assessment review route/UI using the central API client. No Excel export, student portal, batch grading, or real grading call added.
Acceptance criteria: Review queue exposes answer regions with submission/question/image/latest suggestion/final grade/status; teacher can approve, edit, or reject suggestions into FinalGrade records; duplicate current FinalGrade rows are avoided; frontend review page supports the workflow; tests/lint/build/manual smoke pass.
Tests required: Focused backend review tests; frontend static workflow test; `make test`; `make lint`; frontend build; backend/frontend health curls; `make down`; clean git status.
Risks: Auth is still a dev placeholder, so teacher_id is provided by client input until real auth lands; FinalGrade currently stores only current state, while audit logs preserve action history.
Status: Done

TASK-ID: TA-W1-018
Title: Result export and assessment summary
Owner: Hermes
Priority: P0
Dependencies: TA-W1-017
Files affected: apps/api/app/api/routes/final_grades.py, apps/api/app/schemas.py, apps/api/app/services/final_grade_service.py, apps/api/tests/test_final_grade_review_api.py, apps/web/lib/api.ts, apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Let teachers view assessment-level review progress and download final-grade results as a safe Excel workbook.
Implementation notes: Adds assessment summary and dynamic XLSX final-grade export endpoints using existing openpyxl dependency. Export includes pending answer regions with blank final-grade columns, latest AI suggestion fields, reviewed final-grade state, and student feedback. It excludes password_hash, raw_response_json, secrets, and provider internals. Frontend review page shows summary counts and an XLSX download link through the central API client. No CSV, student portal, payment, real auth, batch real grading, or TA-W1-019 work.
Acceptance criteria: Summary returns correct counts; XLSX endpoint returns correct content type, headers, approved/edited/rejected rows, pending rows, and safe field set; missing assessment returns 404; frontend exposes summary and export controls; tests/lint/build/manual export smoke pass.
Tests required: Focused backend export/review tests; frontend static workflow test; `make test`; `make lint`; frontend build; backend/frontend health curls; `make down`; clean git status.
Risks: Auth remains dev-mode; export is current-state only with action history preserved in AuditLog; CSV export intentionally deferred.
Status: Done

TASK-ID: TA-W1-019
Title: End-to-end teacher workflow validation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-018
Files affected: Temporary ignored runtime data only; no committed code changes.
Goal: Validate the teacher workflow end to end after result export and assessment summary work.
Implementation notes: Ran a mixed API + health-check workflow using synthetic non-student data only, mock provider, zero real Codex calls, and exactly one grading call during validation. Verified upload, page/image serving, answer-region crop, mock GradeSuggestion persistence, review queue suggested/finalized states, FinalGrade approval, assessment summary, safe XLSX export, tests, lint, frontend build, health checks, and clean git status. No code changes were required.
Acceptance criteria: Workflow completes with created synthetic records; export includes one reviewed row and no forbidden raw provider JSON/password fields; required tests/lint/build/health checks pass; known Next dev cache issue after build is resolved by frontend restart and recorded.
Tests required: `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; mixed API workflow smoke; `make test`; `make lint`; frontend build; frontend health retry after restart if needed; `make down`; clean git status.
Risks: Single synthetic validation proves pipeline integration only, not grading quality or production auth behavior.
Status: Done

TASK-ID: TA-W1-019A
Title: Record end-to-end validation checkpoint
Owner: Hermes
Priority: P0
Dependencies: TA-W1-019
Files affected: BACKLOG.md, docs/VALIDATION_LOG.md
Goal: Record the successful TA-W1-019 validation in project history without changing product code.
Implementation notes: Documentation/backlog-only checkpoint. Records baseline commit, workflow shape, synthetic IDs, review states, summary/export results, verification commands, known Next dev cache restart issue, and that no code changes or validation commit were generated during TA-W1-019 itself.
Acceptance criteria: BACKLOG marks TA-W1-019 done; docs/VALIDATION_LOG.md contains the TA-W1-019 checkpoint; no product code changes are made; requested tests/lint pass; checkpoint commit is created.
Tests required: `git status --short`; `make test`; `make lint`; `git status --short`.
Risks: Documentation may drift if future validation runs are not appended.
Status: Done

TASK-ID: TA-W1-020
Title: Demo hardening and developer workflow reliability
Owner: Hermes
Priority: P0
Dependencies: TA-W1-019A
Files affected: docs/DEMO_RUNBOOK.md, Makefile, README.md, BACKLOG.md
Goal: Make the local demo path and verification workflow clearer and safer for developer use.
Implementation notes: Added a demo runbook covering prerequisites, startup, migrations, health checks, full teacher workflow steps, mock-provider-only warnings, XLSX export verification, shutdown, and known troubleshooting cases. Added a non-destructive `make verify` target that assumes services are already running and runs health, frontend health, tests, and lint. README points to the runbook. No smoke-e2e script was added.
Acceptance criteria: Runbook exists; `make verify` does not start/stop Docker, reset the DB, run real Codex, or perform cleanup; required Docker, migration, health, verify, frontend build, restart-after-build health, shutdown, and final git status checks pass.
Tests required: `git status --short`; `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; `make frontend-health`; `make verify`; `docker compose exec -T frontend npm run build`; restart frontend and recheck health if needed; `make down`; `git status --short`.
Risks: `make verify` requires already-running services and applied migrations; frontend health can fail immediately after production build until the frontend container is restarted.
Status: Done

TASK-ID: TA-W1-021
Title: Week-1 checkpoint report and next-track decision
Owner: Hermes
Priority: P0
Dependencies: TA-W1-020
Files affected: docs/WEEK_1_CHECKPOINT.md, BACKLOG.md
Goal: Record the Week-1 checkpoint, completed capabilities, limitations, verified slice, known issues, verification status, next track options, and selected next track.
Implementation notes: Documentation/checkpoint only. Selected Demo/UI polish as the next track before auth or batch grading because it improves the already-verified vertical slice with lower architectural risk and no real-provider dependency.
Acceptance criteria: `docs/WEEK_1_CHECKPOINT.md` exists; BACKLOG marks TA-W1-021 done; TA-W1-022 is present as pending; no product code is changed; tests and lint pass.
Tests required: `git status --short`; `make test`; `make lint`; `git status --short`.
Risks: Checkpoint can drift if later work changes capabilities without updating docs.
Status: Done

TASK-ID: TA-W1-022
Title: Demo UI polish for Week-1 vertical slice
Owner: Hermes
Priority: P0
Dependencies: TA-W1-021
Files affected: apps/web/**, BACKLOG.md, possibly docs/DEMO_RUNBOOK.md
Goal: Improve the existing mock-provider teacher demo flow without adding auth, real Codex grading, student portal, payment, or batch grading.
Implementation notes: Keep the work frontend/demo-focused. Improve clarity of navigation, assessment/review screens, mock-provider safety labels, and review/export flow. Do not start real-provider grading or batch workflows.
Acceptance criteria: Browser demo is clearer; mock/provider safety is visible; review/export path is easier to follow; existing tests/lint/build pass.
Tests required: Frontend workflow checks, `make test`, `make lint`, frontend build, and clean git status.
Risks: UI polish could accidentally expand into feature work; keep scope tight and mock-provider-only.
Status: Done

TASK-ID: TA-W1-022A
Title: Fix demo teacher selection and submission cleanup UX
Owner: Hermes
Priority: P0
Dependencies: TA-W1-022
Files affected: apps/api/app/api/routes/submissions.py, apps/api/app/services/storage.py, apps/api/tests/test_submission_upload_api.py, apps/web/components/DemoTeacherSelector.tsx, apps/web/lib/demoTeacher.ts, apps/web/lib/api.ts, apps/web/components/UsersClient.tsx, apps/web/components/CoursesClient.tsx, apps/web/components/AssessmentDetailClient.tsx, apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Improve demo usability by selecting a current demo teacher, using that teacher automatically for course creation and review actions, allowing safe cleanup of wrong submissions, and clarifying that browser demo grading stays mock-provider-only.
Implementation notes: Added localStorage-backed current demo teacher selection on Users, Courses, Assessment, and Review screens. Removed raw teacher_id entry from course creation and final-grade actions. Added assessment-scoped DELETE for submissions with safe related-row cleanup and best-effort storage cleanup that ignores unsafe stored paths. Added frontend delete button with confirmation. Added Codex/mock safety note in assessment and review UI.
Acceptance criteria: Teacher selection is visible and persistent; missing teacher shows “Select a demo teacher first.”; approve/edit/reject use selected teacher_id automatically; submission delete is assessment-scoped and refreshes the list; mock grading remains browser-demo default; Codex CLI integration is described but not enabled in UI.
Tests required: `git status --short`; `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; focused backend tests; frontend static tests; `make test`; `make lint`; frontend build; `make down`; `git status --short`.
Risks: This is still dev-mode identity, not real auth. Submission deletion is hard-delete for demo cleanup and uses safe path handling; future production cleanup should likely move to an authenticated/authorized policy.
Status: Done

TASK-ID: TA-W1-022B
Title: Fix submission upload file selection UX
Owner: Hermes
Priority: P0
Dependencies: TA-W1-022A
Files affected: apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/workflow-ui.test.mjs, apps/api/tests/test_submission_upload_api.py, BACKLOG.md
Goal: Fix the assessment-page upload bug where a selected JPG could still leave the UI in the “Choose a PDF or image file before uploading” state and no submission appeared.
Implementation notes: Upload submit now falls back to the form file input if React state has not caught up, file selection clears the stale missing-file error, accepted extensions explicitly include .jpg/.jpeg, the selected file name is displayed, and the upload button is disabled until both student_identifier and file are present. Successful upload clears the form/file/error state and refreshes submissions. Added a no-question guidance note under Answer regions without blocking uploads.
Acceptance criteria: JPG/JPEG/PNG/PDF are accepted; selecting a valid file clears the missing-file error; upload shows loading state and backend errors clearly; successful upload creates exactly one submission and shows the page link; no real Codex/auth/batch/student/payment work added.
Tests required: `git status --short`; `make up`; `docker compose exec -T backend alembic upgrade head`; `make health`; focused JPG upload tests; frontend static tests; `make test`; `make lint`; frontend build; `make down`; `git status --short`.
Risks: This remains a lightweight static/frontend verification rather than a browser automation test; a future Playwright/Vitest setup would give stronger coverage for DOM event timing.
Status: Done

TASK-ID: TA-W1-022C
Title: Add visible assessment export navigation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-022B
Files affected: apps/web/components/AssessmentDetailClient.tsx, apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs
Goal: Make the review/export path obvious from the assessment detail page.
Implementation notes: Added Review & export final grades link, direct Download final grades (.xlsx) link, review-page summary export button, and no-final-grades helper text.
Acceptance criteria: Assessment detail and review pages expose visible XLSX export navigation; backend export remains unchanged; no auth/student/batch/real Codex work added.
Tests required: frontend static tests, make test, make lint, frontend build.
Risks: Static verification only; no full browser click automation.
Status: Done

TASK-ID: TA-W1-023
Title: Basic auth and teacher identity foundation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-022C
Files affected: apps/api/app/api/routes/auth.py, apps/api/app/core/auth.py, apps/api/app/api/routes/courses.py, apps/api/app/api/routes/final_grades.py, apps/api/app/core/config.py, apps/api/app/main.py, apps/api/app/schemas.py, apps/api/tests/test_auth_api.py, apps/api/tests/test_final_grade_review_api.py, apps/web/app/login/page.tsx, apps/web/app/register/page.tsx, apps/web/components/AppShell.tsx, apps/web/components/CoursesClient.tsx, apps/web/components/AssessmentReviewClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, .env.example, BACKLOG.md
Goal: Replace primary dev-mode teacher identity dependence with basic teacher register/login/session flow while keeping scope tight.
Implementation notes: Added PBKDF2 password hashing, simple HS256 JWT token creation/validation using JWT_SECRET_KEY, /auth/register, /auth/login, /auth/me, and frontend-only compatible /auth/logout. Course creation can use authenticated teacher without teacher_id while preserving legacy dev teacher_id path. Final-grade approve/edit/reject use authenticated teacher when a bearer token is present while preserving legacy teacher_id fallback for existing tests/dev paths. Frontend adds login/register pages, localStorage dev-only token storage, current teacher header display, logout, auth-aware course creation, and auth-aware review actions.
Acceptance criteria: Password hashes are not exposed; login/me work; course creation and review actions use logged-in teacher in the primary frontend flow; missing/invalid tokens return 401 on auth-aware paths; no student portal/OAuth/payment/batch/real Codex work added.
Tests required: git status; make up; alembic upgrade; make health; focused auth/review tests; frontend static tests; make test; make lint; frontend build; make down; final git status.
Risks: Token storage is localStorage and explicitly dev-only; broad backend endpoint protection is intentionally deferred; legacy public/dev endpoints remain for compatibility.
Status: Done

TASK-ID: TA-W1-024
Title: Batch mock grading and review queue improvements
Owner: Hermes
Priority: P0
Dependencies: TA-W1-023
Files affected: apps/api/app/api/routes/grading.py, apps/api/app/schemas.py, apps/api/app/services/grading_service.py, apps/api/tests/test_grading_api.py, apps/web/components/AssessmentReviewClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Improve multi-answer-region workflow with assessment-level batch mock grading, clearer review queue filtering, and safer progress/status feedback.
Implementation notes: Added POST /assessments/{assessment_id}/grade-all-mock, which validates the assessment, grades only answer regions with no existing GradeSuggestion, forces the BrainAdapter mock provider regardless of configured provider, returns graded/skipped/failed counts plus created suggestion IDs/errors, and does not create FinalGrade rows. Added review-page batch mock grading button, mock-only warning, batch result summary, status filter controls, and status counts for all/ungraded/suggested/finalized/approved/edited/rejected.
Acceptance criteria: Batch mock grading handles multiple ungraded answer regions; existing suggested/finalized regions are skipped by default; endpoint returns 404 for missing assessment; real provider/Codex batch grading is not called or enabled; no raw_response_json is exposed in batch response; no student portal/payment/TA-W1-025 work added.
Tests required: git status; make up; alembic upgrade; make health; focused backend batch tests; frontend static tests; make test; make lint; frontend build; make down; final git status.
Risks: Batch runs synchronously and intentionally avoids a larger async worker system; frontend filter is client-side only; real-provider batch grading remains disabled/deferred.
Status: Done

TASK-ID: TA-W1-025
Title: Batch review UX polish and status clarity
Owner: Hermes
Priority: P0
Dependencies: TA-W1-024
Files affected: apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Improve review queue usability for multiple submissions after batch mock grading while keeping grading mock-only.
Implementation notes: Added clearer review item overview cards with visible status labels, student/question/status/AI mock score/final score fields, cropped answer image link, next-item navigation, batch workflow helper text, clearer empty-filter state, and quick actions wording for approve/edit/reject.
Acceptance criteria: Review queue items are easier to scan; status labels are visually/textually distinct; batch workflow helper and empty-filter message exist; export remains visible; logged-in teacher requirement remains clear; UI remains mock-only with no real Codex batch grading, student portal, payment, or advanced UI expansion.
Tests required: git status; make up; alembic upgrade; make health; frontend static tests; make test; make lint; frontend build; make down; final git status.
Risks: Verification remains mostly static plus manual smoke; no backend changes expected.
Status: Done

TASK-ID: TA-W1-026
Title: Human browser demo acceptance checklist
Owner: Hermes
Priority: P0
Dependencies: TA-W1-025
Files affected: docs/HUMAN_DEMO_ACCEPTANCE_CHECKLIST.md, BACKLOG.md
Goal: Provide a structured human-founder browser checklist for deciding whether the current app is internally demo-ready and ready for one trusted teacher.
Implementation notes: Added a documentation-only checklist covering login/register through XLSX export, pass/fail checkboxes, screenshots to capture on failure, demo data examples, known limitations, stop conditions, and final decision prompts.
Acceptance criteria: Checklist includes exact browser flow, pass/fail markers, failure screenshot guidance, known limitations, demo data, stop conditions, and final decision section. No product code changed, no real Codex grading run, and no TA-W1-027 work started.
Tests required: git status; make test; make lint; final git status.
Risks: Checklist quality still depends on a human running the browser flow and recording the result.
Next task suggestion: If the checklist finds blockers, do TA-W1-027A: fix acceptance blockers. If it passes, do TA-W1-027B: prepare teacher pilot script.
Status: Done

TASK-ID: TA-W1-027A
Title: Batch final-grade approval and product feedback backlog
Owner: Hermes
Priority: P0
Dependencies: TA-W1-026
Files affected: apps/api/app/api/routes/final_grades.py, apps/api/app/schemas.py, apps/api/app/services/final_grade_service.py, apps/api/tests/test_final_grade_review_api.py, apps/web/components/AssessmentReviewClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md, docs/PRODUCT_ROADMAP.md
Goal: Improve review workflow so teachers can select multiple suggested items and approve them together while keeping teacher review in control.
Implementation notes: Added authenticated POST /assessments/{assessment_id}/final-grades/approve-selected with grade_suggestion_ids summary response, assessment scoping, current logged-in teacher identity, FinalGrade upsert behavior per answer region, and audit logging through the existing final-grade save path. Added review-queue checkboxes, select-all-visible suggested items, clear selection, selected count, approve selected action, batch approval result summary, and refresh after approval. Recorded future question-paper extraction and voice command assistant ideas in docs/PRODUCT_ROADMAP.md. No OCR/question extraction, voice command, real Codex grading, real provider batch grading, student portal, or payment work added.
Acceptance criteria: Selected batch approval succeeds for suggested items; missing/out-of-assessment suggestions are skipped with clear summary errors; missing auth returns 401; duplicate FinalGrade rows are avoided; frontend selection works with existing filters and only suggested not-finalized items are selectable; mock-only warning and export remain visible; future feature ideas are recorded as not implemented now.
Tests required: git status; make up; alembic upgrade; make health; focused backend batch-approve tests; frontend static tests; make test; make lint; frontend build; make down; final git status.
Risks: Batch approval currently approves selected latest suggestion IDs with no per-item teacher comment; future richer bulk-edit comments remain deferred.
Status: Done

TASK-ID: TA-W1-027B
Title: Prepare trusted teacher pilot materials
Owner: Hermes
Priority: P0
Dependencies: TA-W1-027A
Files affected: docs/TRUSTED_TEACHER_PILOT_SCRIPT.md, docs/PILOT_FEEDBACK_FORM.md, BACKLOG.md
Goal: Prepare documentation-only materials for showing the current app to one trusted teacher and collecting structured feedback.
Implementation notes: Added a trusted-teacher pilot script covering product positioning, current limitations, mock grading, disabled Codex CLI browser-demo explanation, and the full teacher demo flow from register/login through XLSX export. Added a pilot feedback form focused on workload reduction, usefulness, confusion, batch approval risk, review control, trust, manual answer-region acceptability, question-paper import, voice command, export needs, privacy/security concerns, minimum classroom feature set, recommendation, and willingness to pay. No product code changed, no OCR/question extraction, no voice command, no real Codex grading, and no TA-W1-028 work started.
Acceptance criteria: Pilot script and feedback form exist with requested sections; backlog records TA-W1-027B as Done and next decision options are listed.
Tests required: git status; make test; make lint; final git status.
Risks: Feedback quality depends on choosing a trusted teacher and using non-sensitive demo data.
Next decision options: TA-W1-028A: fix pilot-feedback blockers; TA-W1-028B: question paper import planning; TA-W1-028C: real grading quality evaluation dataset; TA-W1-028D: UI polish from teacher feedback.
Status: Done

TASK-ID: TA-W1-028B
Title: Question paper import planning and prototype
Owner: Hermes
Priority: P0
Dependencies: TA-W1-027B
Files affected: apps/api/app/models.py, apps/api/alembic/versions/0003_question_import_jobs.py, apps/api/app/api/routes/question_imports.py, apps/api/app/services/question_import_extractor.py, apps/api/app/services/storage.py, apps/api/app/schemas.py, apps/api/app/main.py, apps/api/tests/test_question_import_api.py, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/workflow-ui.test.mjs, docs/PRODUCT_ROADMAP.md, BACKLOG.md
Goal: Add a safe prototype foundation for uploading question paper PDF/images, extracting draft questions, and creating real Questions only after teacher review/confirmation.
Implementation notes: Added QuestionImportJob persistence and migration, local safe question-paper upload storage, mock deterministic extraction for simple PDF text patterns, draft question JSON schema, question import create/detail/accept endpoints, frontend upload/draft-edit/select/accept flow, and roadmap status update. The prototype keeps manual question creation available, keeps voice command deferred, and does not enable real Codex extraction or real Codex grading by default.
Acceptance criteria: Uploading a PDF/image question paper creates an import job and draft questions; draft questions are not saved as real Questions until accepted; selected/edited drafts create normal Questions; missing assessment and unsupported file errors are handled; frontend shows draft extraction warning, draft editing, selection, and create-selected flow; no frontend direct Codex/LLM calls.
Tests required: git status; make up; alembic upgrade; make health; focused question import tests; frontend static tests; make test; make lint; frontend build; make down; final git status.
Risks: Current extractor is deterministic/mock and best-effort; real OCR/document understanding and sub-question handling need later evaluation before production use.
Status: Done

TASK-ID: TA-W1-029A
Title: Codex CLI question paper extraction provider
Owner: Hermes
Priority: P0
Dependencies: TA-W1-028B
Files affected: .env.example, apps/api/app/core/config.py, apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/api/routes/question_imports.py, apps/api/app/services/question_import_extractor.py, apps/api/alembic/versions/0004_question_import_provider_warnings.py, apps/api/tests/test_question_import_codex_provider.py, apps/api/tests/test_question_import_api.py, apps/api/tests/test_migrations.py, apps/api/tests/test_models_metadata.py, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Add a controlled Codex CLI question-paper extraction provider for teacher-reviewed draft question imports while keeping mock/simple extraction as the default.
Implementation notes: Added QUESTION_IMPORT_PROVIDER and CODEX_QUESTION_EXTRACTION_ENABLED settings, an explicit codex_cli_question_extractor provider behind a safe factory, strict Codex JSON/schema validation, provider warnings persistence, image routing through the Codex CLI image flag when enabled, sanitized provider errors, and frontend notes warning that default extraction is mock/simple and real Codex extraction must be explicitly enabled. No automatic Question creation, no grading-provider behavior changes, no voice command, and no real extraction default enablement.
Acceptance criteria: Mock extractor remains default; requested Codex provider is rejected unless explicitly enabled; fake Codex runner output is schema-validated; invalid JSON/schema and subprocess failures fail cleanly; image uploads can route to enabled provider; drafts remain teacher-reviewed and accept endpoint remains the only path that creates real Questions.
Tests required: git status; make up; alembic upgrade; make health; focused question import/provider tests; frontend static tests; make test; make lint; frontend build; optional one real Codex smoke if safe/auth available; make down; final git status.
Risks: Real Codex smoke was blocked by local Codex usage limit, so the real external call path is implemented and fake-runner tested but not live-verified in this task.
Status: Done

TASK-ID: TA-W1-029B
Title: Unblock Codex CLI question extraction smoke in isolated workdirs
Owner: Hermes
Priority: P0
Dependencies: TA-W1-029A
Files affected: .env.example, apps/api/app/core/config.py, apps/api/app/services/question_import_extractor.py, apps/api/tests/test_question_import_codex_provider.py, BACKLOG.md, docs/VALIDATION_LOG.md
Goal: Allow the Codex CLI question extraction provider to run from an isolated safe workdir without broad repository context while preserving explicit opt-in and teacher review.
Implementation notes: Added CODEX_CLI_SKIP_GIT_REPO_CHECK, kept it default false, and added the Codex exec --skip-git-repo-check flag only when explicitly enabled. The provider still sends prompts through stdin, keeps image flag behavior unchanged, rejects danger-full-access, keeps provider errors sanitized, and does not change grading behavior or enable real extraction by default. Controlled real smoke used an isolated /tmp Codex workdir and a synthetic non-student PNG question paper.
Acceptance criteria: Command includes --skip-git-repo-check when enabled and omits it by default; focused Codex provider and question import tests pass; full tests/lint/build pass; exactly one real Codex question extraction smoke returns draft questions requiring review; no real Question rows exist before accept; accept creates real Question rows only after confirmation.
Tests required: git status; safe no-repo Codex OK check; make up; alembic upgrade head; make health; focused Codex provider/question import tests; frontend static tests; make test; make lint; frontend build; controlled one real Codex smoke; make down; final git status.
Risks: Real extraction quality still needs teacher review and broader evaluation before production use; this smoke validated only one synthetic image case.
Status: Done

TASK-ID: TA-W1-030
Title: Question extraction evaluation dataset
Owner: Hermes
Priority: P0
Dependencies: TA-W1-029B
Files affected: apps/api/packages/evaluation/question_import_evaluation.py, apps/api/tests/test_question_import_evaluation.py, BACKLOG.md
Goal: Build a backend-focused evaluation harness and dataset format to measure question-paper extraction quality before trusting it for real teacher use.
Implementation notes: Added a question import evaluation module with JSON/JSONL dataset loading, expected-question schema, provider runner over the existing question import extractor abstraction, mock-safe default behavior, explicit two-step real Codex guard requiring QUESTION_IMPORT_EVAL_ALLOW_REAL_PROVIDER=true plus --allow-real-provider, max-real-cases enforcement, metrics calculation, and JSON/Markdown artifact writing under an output directory. No automatic Question creation, no real grading, no voice command, and no browser default real extraction changes were added.
Acceptance criteria: Dataset loader supports JSON and JSONL; metrics cover case count, expected/extracted counts, question-count match rate, question-number match rate, exact text match rate, normalized text similarity average, marks match rate, needs-review rate, provider-warning count, and parse-failure count; real Codex eval is rejected unless explicitly enabled and capped; report artifacts are written; tests avoid real Codex calls.
Tests required: git status; make up; alembic upgrade head; make health; focused question extraction eval tests; make test; make lint; frontend build; optional one synthetic real Codex eval if safe/auth available; make down; final git status.
Risks: Evaluation metrics are simple string/marks comparisons and should be expanded with teacher-curated datasets before production trust decisions.
Status: Done

TASK-ID: TA-W1-031
Title: Real grading quality dataset expansion
Owner: Hermes
Priority: P0
Dependencies: TA-W1-030
Files affected: apps/api/packages/evaluation/grading_evaluation.py, apps/api/tests/test_grading_evaluation.py, docs/GRADING_EVALUATION.md, docs/GRADING_QUALITY_NOTES.md, BACKLOG.md
Goal: Create a small controlled grading-quality dataset and run limited real Codex grading evaluation across correct, partial, wrong, blank, and irrelevant answers.
Implementation notes: Added optional grading-eval case metadata for answer type and generated fixture reference, a five-case synthetic non-student dataset helper that creates PNG answer fixtures plus database records, and metric breakdowns for answer type, severe errors, over-scoring, and under-scoring. Ran mock evaluation and a capped real Codex CLI grading evaluation on five synthetic cases only. No production batch grading, browser default real grading, UI changes, question extraction, voice command, or TA-W1-032 work was added.
Acceptance criteria: Synthetic dataset includes fully correct, partially correct, wrong, blank, and irrelevant answer cases; mock-mode tests pass; real Codex eval runs only with explicit opt-in and max-real-cases 5; generated artifacts remain under ignored `/tmp` or storage paths; summary docs record the tiny/synthetic nature and avoid accuracy overclaims.
Tests required: git status; make up; alembic upgrade head; make health; focused grading eval tests; mock evaluation; capped real Codex eval if auth/quota available; make test; make lint; frontend build; make down; final git status.
Risks: Dataset is tiny and synthetic; the result is a signal that the scoring path can distinguish simple cases, not evidence of classroom grading accuracy. Wrong-answer expected score/rubric calibration needs teacher curation.
Status: Done

TASK-ID: TA-W1-032
Title: Teacher-curated evaluation protocol
Owner: Hermes
Priority: P0
Dependencies: TA-W1-031
Files affected: docs/TEACHER_CURATED_EVAL_PROTOCOL.md, docs/EVAL_DATASET_TEMPLATE.jsonl, BACKLOG.md
Goal: Create a safe teacher-curated evaluation protocol for collecting real grading examples and comparing AI suggestions against teacher marks.
Implementation notes: Added documentation-only protocol covering purpose, data/privacy rules, dataset size targets, case categories, required fields, metrics, pilot go/no-go thresholds, review process, reporting format, and privacy/security notes. Added a JSONL template with three synthetic example rows: correct, partial, and wrong. No product code was changed, no real Codex grading was run, and no TA-W1-033 collection work was started.
Acceptance criteria: Protocol includes teacher-control and privacy rules; template contains three synthetic rows; backlog marks TA-W1-032 done and records TA-W1-033 as the next recommended task.
Tests required: git status --short; make test; make lint; git status --short.
Risks: Protocol quality still depends on later teacher-curated case collection and strict anonymization before using real classroom artifacts.
Status: Done

TASK-ID: TA-W1-033
Title: Collect first 20 teacher-curated grading evaluation cases
Owner: Human/Hermes
Priority: P0
Dependencies: TA-W1-032
Files affected: To be decided; likely ignored evaluation artifacts plus optional sanitized docs updates.
Goal: Collect the first 20 teacher-curated grading evaluation cases under the TA-W1-032 protocol.
Implementation notes: Use anonymized, synthetic, or consented examples only. Keep teacher marks as ground truth. Do not commit sensitive answer images or raw student data. Do not change production grading behavior during collection.
Acceptance criteria: 20 cases exist with required fields, category coverage is recorded, privacy/anonymization status is documented, and no sensitive artifacts are committed.
Tests required: Validate dataset shape; run approved evaluation only after data is reviewed; keep git status clean except approved sanitized files.
Risks: Privacy/anonymization errors or unrepresentative cases could make the dataset unsafe or misleading.
Status: Partial/Pending

TASK-ID: TA-W1-033B
Title: Stage teacher-marked answer-sheet evaluation cases
Owner: Hermes
Priority: P0
Dependencies: TA-W1-032, TA-W1-033
Files affected: docs/GRADING_QUALITY_NOTES.md, BACKLOG.md; ignored local dataset `/tmp/ta_teacher_eval_cases/teacher_marked_correct_cases_q1_q20.jsonl`
Goal: Stage a safe teacher-marked evaluation dataset draft from the provided anonymized marking metadata while separating image-backed cases from metadata-only pending-image cases.
Implementation notes: Created 20 JSONL rows for Q1–Q20 under `/tmp/ta_teacher_eval_cases/`; copied Q1–Q8 answer images to ignored `/tmp/ta_teacher_eval_cases/crops/`; marked Q9–Q20 with `answer_image_path = null` and `image_status = missing_image_pending`; recorded anonymization confirmation and full-score teacher marks. No product code changed, no real Codex grading run, and no raw answer images/crops committed.
Acceptance criteria: Q1–Q20 rows exist; expected scores do not exceed max scores; rubric marks sum to max score; answer types and anonymization status are present; Q1–Q8 image-backed paths exist locally; Q9–Q20 are marked pending image; notes document limits and remaining human data needs.
Tests required: git status --short; JSONL validation; make test; make lint; git status --short.
Risks: Dataset is all full-score correct answers and supports correct-answer evaluation only; it still needs mixed-quality teacher-curated cases and matching answer images for Q9–Q20 before broader grading-quality evaluation.
Status: Done

TASK-ID: TA-W1-033C
Title: Evaluate teacher-marked image-backed correct cases
Owner: Hermes
Priority: P0
Dependencies: TA-W1-033B
Files affected: docs/GRADING_QUALITY_NOTES.md, BACKLOG.md; ignored local artifacts under `/tmp/ta_teacher_eval_033c_storage` and `/tmp/ta_teacher_eval_033c_artifacts`
Goal: Run a limited real Codex grading evaluation on the 8 image-backed teacher-marked correct cases and record results without overclaiming grading accuracy.
Implementation notes: Used only Q1–Q8 from `/tmp/ta_teacher_eval_cases/teacher_marked_correct_cases_q1_q20.jsonl`; did not use Q9–Q20 pending-image rows; ran existing grading evaluation harness with `provider_mode=codex_cli`, `allow_real_provider=true`, `max_real_cases=8`, and image input enabled. No product UI/code changed, no batch production grading run, and no raw images/crops/eval artifacts committed.
Acceptance criteria: Report case_count, exact_match_rate, within_1_mark_rate, mean_absolute_error, false_confident_error_count, severe_error_count, over/under score counts, by-answer-type breakdown, per-case results, artifact paths, caveats, and required test/lint status.
Tests required: git status --short; verify dataset/crops; safe Codex CLI OK check; real Codex eval capped at 8 Q1–Q8 cases; make test; make lint; git status --short.
Risks: All evaluated cases are correct/full-score only; this does not establish accuracy on wrong, partial, blank, irrelevant, or messy teacher-marked answers.
Status: Done

TASK-ID: TA-W1-034A
Title: Original document grading evaluation preparation and limited smoke
Owner: Hermes
Priority: P0
Dependencies: TA-W1-033C
Files affected: docs/GRADING_QUALITY_NOTES.md, BACKLOG.md; ignored local inputs/artifacts under `/tmp/ta_original_doc_eval/`; local app storage under ignored `data/`.
Goal: Determine whether the current app can grade selected answer regions from real/original documents using the existing question/rubric/answer-region/Codex evaluation pipeline.
Implementation notes: Copied the three provided original PDFs into ignored `/tmp/ta_original_doc_eval/input/`, rendered page images/contact sheets, performed a visible privacy pass, created a controlled assessment through the app/API path, uploaded Script-1 and Script-2 through the submission upload endpoint, manually created 3 full-page answer regions only, prepared teacher-score eval cases, passed a safe no-repo Codex OK check, and ran the existing grading evaluation harness with `provider_mode=codex_cli`, `allow_real_provider=true`, image input enabled, and `max_real_cases=3`. No production batch grading, no automatic final grades, no browser default real grading, and no product code changes.
Acceptance criteria: Original documents are inventoried; privacy/anonymization status is reported; 3–5 selected cases are staged with teacher expected scores; real Codex grading runs only if safe auth check passes; metrics/per-case results and artifact paths are recorded; required checks pass; raw PDFs/images/crops are not committed.
Tests required: git status --short; make up; docker compose exec -T backend alembic upgrade head; make health; safe Codex CLI OK check; capped real Codex eval on 3 cases; make test; make lint; docker compose exec -T frontend npm run build; make down; git status --short.
Risks: Smoke used manually staged broad/full-page regions and only 3 cases. The partial Script-2 case was over-scored by 2.5 marks, so this confirms pipeline operability but not grading reliability. Tighter region mapping, better question/rubric extraction, anonymization review, and more mixed teacher-marked cases remain manual.
Status: Done

TASK-ID: TA-W1-035A
Title: Define grading workflow modes
Owner: Hermes
Priority: P0
Dependencies: TA-W1-034A
Files affected: docs/GRADING_WORKFLOW_MODES.md, docs/PRODUCT_ROADMAP.md, BACKLOG.md
Goal: Define product architecture and roadmap for Fully Automated, Semi-Automated, and Custom / Controlled grading modes before implementation.
Implementation notes: Created a planning-only workflow-modes document covering inputs, outputs, automation level, teacher confirmation points, risk, current support, missing capabilities, recommended build order, safety rules, data model/API/UI/evaluation implications, and Tough/General/Easy marking policy design. Updated product roadmap with the three-mode sequence and kept teacher review mandatory. No product code changed, no ZIP upload or answer-region auto-detection implemented, no voice command work, and no grading run performed.
Acceptance criteria: Documentation clearly defines all three modes; explains Custom / Controlled first, Semi-Automated second, Fully Automated last; records that fully automated grading is not proven reliable; adds next implementation proposal and future tasks.
Tests required: git status --short; make test; make lint; git status --short.
Risks: This is architecture/roadmap only; implementation still needs careful gates so product behavior does not accidentally auto-finalize or imply reliable full automation.
Status: Done

TASK-ID: TA-W1-035B
Title: Custom controlled grading run wizard
Owner: Hermes
Priority: P0
Dependencies: TA-W1-035A
Files affected: apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/services/storage.py, apps/api/app/api/routes/grading_runs.py, apps/api/app/main.py, apps/api/alembic/versions/0005_grading_runs.py, apps/api/tests/test_grading_runs_api.py, apps/api/tests/test_models_metadata.py, apps/api/tests/test_migrations.py, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/app/assessments/[assessmentId]/grading-run/page.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Implement the first workflow mode: a Custom / Controlled grading wizard that guides teachers through question, solution, rubric, script import, confirmation, controlled grading, review, and export.
Implementation notes: Added a `grading_runs` table/model for `custom_controlled` runs with teacher ownership, workflow status, notes, and safe relative PDF material paths. Added authenticated grading-run API routes to create/list/read/update runs and upload question/solution/rubric PDFs. Added a frontend wizard page that starts a run, uploads materials, shows step/status state, links to existing question/rubric/script/answer-region/review/export flows, and warns that teacher confirmation is required. Did not implement ZIP upload, automatic answer-region detection, fully automated mode, semi-automated mode, voice command, automatic final grading, or default real Codex batch grading.
Acceptance criteria: Wizard requires teacher confirmation of questions/model answers/rubrics/marking policy before grading; all AI results go to teacher review; final grades require approval; existing export remains based on finalized grades.
Tests required: git status --short; make up; docker compose exec -T backend alembic upgrade head; make health; focused grading-run tests; frontend static tests; make test; make lint; docker compose exec -T frontend npm run build; manual smoke; make down; git status --short.
Risks: This is a workflow organizer over existing manual/controlled grading flows. Region creation remains manual, grading reliability is unchanged, and real Codex batch grading remains default-off.
Status: Done

TASK-ID: TA-W1-035C
Title: Browser-triggered single Codex grading smoke path
Owner: Hermes
Priority: P0
Dependencies: TA-W1-035B
Files affected: apps/api/app/api/routes/grading.py, apps/api/app/core/config.py, apps/api/app/schemas.py, apps/api/app/services/grading_service.py, apps/api/tests/test_browser_codex_grading_api.py, apps/web/components/AssessmentReviewClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Add a safe dev-only browser path to run exactly one real Codex CLI grading call for one selected answer region and verify the result appears as a GradeSuggestion in teacher review.
Implementation notes: Added guarded `POST /answer-regions/{answer_region_id}/grade-codex-dev`, requiring an authenticated teacher token and `CODEX_BROWSER_GRADING_ENABLED=true`. The endpoint constructs a Codex CLI adapter explicitly, grades only the requested answer region, returns a sanitized response without `raw_response_json`, and persists only a GradeSuggestion/GradingJob with `needs_review=true`; it never creates FinalGrade. Added review-page button text `Real Codex grade this answer` with controlled-testing warning, login gating, loading/error state, and review-queue refresh. Kept mock grading button/path unchanged and did not expose real Codex batch grading.
Acceptance criteria: Browser UI can trigger one backend-mediated Codex CLI call for a selected answer region when explicitly enabled; disabled flag returns 403; missing auth returns 401; provider errors are sanitized; teacher review remains mandatory; no frontend direct Codex/LLM calls; no automatic final grade is created.
Tests required: git status --short; make up; docker compose exec -T backend alembic upgrade head; make health; focused backend tests; frontend static tests; make test; make lint; docker compose exec -T frontend npm run build; manual one-call smoke if Codex auth/quota is available; make down; git status --short.
Risks: The Docker backend image still does not include Codex CLI, so live browser use requires a dev backend runtime where `codex` is installed and `CODEX_BROWSER_GRADING_ENABLED=true`. This is a single-answer smoke path only, not production/batch real grading.
Status: Done

TASK-ID: TA-W1-035D
Title: Codex-enabled dev backend runtime documentation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-035C
Files affected: docs/CODEX_DEV_RUNTIME.md, docs/DEMO_RUNBOOK.md, Makefile, BACKLOG.md
Goal: Document how to run a dev setup where the browser can trigger real Codex grading through a host backend without adding Codex to production Docker or enabling real grading by default.
Implementation notes: Added a dedicated Codex dev runtime runbook that distinguishes Docker-only normal demo mode from host-backend Codex dev mode. Documented exact commands for Docker Postgres/Redis, safe no-repo Codex OK probe, host env exports, Alembic migration, host Uvicorn backend, frontend options, and one-answer browser smoke. Added low-risk Makefile helpers `codex-ok` and `backend-host-dev`; neither changes Docker images nor enables real grading by default. Linked the new runbook from the demo runbook.
Acceptance criteria: Docs explain that Docker backend cannot see host Codex, host backend can call installed/authenticated Codex, `CODEX_BROWSER_GRADING_ENABLED=true` is required only for dev smoke, teacher review remains mandatory, no real batch grading is documented, and troubleshooting covers command-not-found, auth/quota, trusted directory, Docker visibility, and missing env flag.
Tests required: git status --short; make test; make lint; git status --short.
Risks: Live browser Codex use still depends on local host Codex CLI installation/auth/quota and a host backend process. This is documentation/runtime guidance only; grading reliability is unchanged.
Status: Done

TASK-ID: TA-W1-035E
Title: Fix controlled grading upload auth and fetch handling
Owner: Hermes
Priority: P0
Dependencies: TA-W1-035D
Files affected: apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/lib/api.ts, apps/api/tests/test_frontend_upload_auth_static.py, BACKLOG.md
Goal: Fix the custom controlled grading material upload path so authenticated upload requests use the stored bearer token, failed auth shows a clear teacher-facing message, backend fetch failures are reported clearly, and the wizard refreshes material state after successful upload.
Implementation notes: Kept backend auth unchanged. Added frontend request handling for custom auth error messages and network/Failed-to-fetch failures. Applied the controlled grading upload auth message to grading-run create/list/read/update/material upload calls, kept FormData uploads free of manual multipart Content-Type headers, and refreshed the controlled grading run state after materials upload succeeds. Added static regression tests for auth token usage, safe FormData handling, clear error messages, successful upload refresh, and no direct frontend Codex/LLM calls.
Acceptance criteria: Controlled grading material upload sends the Authorization bearer token when available; invalid or missing auth returns a clear login-again message from 401 responses; backend-unreachable fetch failures report the configured backend URL; FormData upload does not manually set multipart Content-Type; successful material upload refreshes displayed state; backend auth is not weakened; no real Codex grading is run.
Tests required: git status --short; python -m pytest apps/api/tests/test_frontend_upload_auth_static.py; make test; make lint; docker compose exec -T frontend npm run build if stack is running, otherwise documented frontend build command; git status --short.
Risks: This improves frontend error handling only; it does not change backend authorization policy or add new grading workflow features.
Status: Done

TASK-ID: TA-W1-036A
Title: Browser workflow truth audit and fix
Owner: Hermes
Priority: P0
Dependencies: TA-W1-035E
Files affected: Makefile, apps/api/app/api/routes/grading.py, apps/api/app/services/grading_service.py, apps/api/packages/brain/codex_cli_provider.py, apps/api/tests/test_browser_codex_grading_api.py, apps/api/tests/test_codex_cli_provider.py, apps/api/tests/test_frontend_upload_auth_static.py, apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Audit the real browser/API workflow and fix only the blockers preventing normal mock grading, custom controlled grading uploads, and one browser-triggered Codex grading call in documented host-backend Codex mode.
Implementation notes: Verified the active browser runtime was Docker backend/frontend on localhost. Fixed `backend-host-dev` to use the repo virtualenv Python, enable `CODEX_CLI_SKIP_GIT_REPO_CHECK`, and use writable host storage under `/tmp/teacher-assistant-host-data` instead of Docker-owned `data/`. Passed the skip-git-repo-check setting into `CodexCliProvider`. Replaced misleading review-page copy that implied all review actions were mock-only, preserved the separate batch mock path, and made Docker/mock-only Codex unavailability explicit. Changed disabled Codex browser grading and missing Codex CLI failures to clear teacher-facing messages while keeping auth, single-answer scope, GradeSuggestion-only persistence, sanitized response, and mandatory teacher review.
Acceptance criteria: Docker demo mock grading still works; Docker/backend-unavailable Codex path returns a clear unavailable message; custom controlled material uploads work with auth and FormData; host-backend Codex mode runs exactly one browser-equivalent `POST /answer-regions/{answer_region_id}/grade-codex-dev`; persisted suggestion uses `model_provider=codex_cli`; no FinalGrade is auto-created; frontend has no direct Codex/LLM calls.
Tests required: pwd; git status --short; git rev-parse HEAD; git log --oneline -8; docker compose ps; host/backend health checks; focused backend/static tests; Docker mock/API smoke; make codex-ok; host-backend Codex API smoke; host custom controlled upload smoke; make test; make lint; npm run build; git diff --check; git status --short.
Risks: Codex grading quality is still limited because image input is disabled in the current Codex CLI mode, so the real Codex smoke produced a conservative zero-score suggestion from metadata/rubric only. This task verifies operability, not grading quality or full automation.
Status: Done

TASK-ID: TA-W1-036B
Title: Custom controlled grading run end-to-end validation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-036A
Files affected: docs/VALIDATION_LOG.md, BACKLOG.md
Goal: Validate the full custom controlled grading workflow end-to-end using the current app, with exactly one real Codex grading call, teacher review, and XLSX export.
Implementation notes: Validation-only task. Used synthetic non-student fixtures because no sample PDFs were present in the repository. Started infra, passed `make codex-ok`, ran host-backend Codex dev mode plus frontend, created teacher/course/assessment/custom grading run, uploaded question/solution/rubric PDFs, refreshed the run and confirmed material paths persisted, created one question/rubric, uploaded one script image, manually created one answer region, triggered exactly one `grade-codex-dev` call, verified `model_provider=codex_cli` and `needs_review=true`, confirmed no FinalGrade before teacher action, manually edited/finalized, exported XLSX, and verified workbook safety fields.
Acceptance criteria: Material uploads persist after refresh; one real Codex GradeSuggestion is created with teacher review required; no batch real Codex grading is run; no FinalGrade is auto-created; teacher review creates a FinalGrade; XLSX export succeeds and omits raw provider JSON/password hashes; services shut down cleanly.
Tests required: git status --short before/after; make up-infra; make codex-ok; host backend/frontend readiness; validation smoke; make test; make lint; npm run build; service shutdown; docs-only commit.
Risks: Codex image input is disabled, so the real Codex suggestion scored conservatively from metadata/rubric context. This validates workflow operability and review/export gates, not grading quality or TA-W1-037 automation.
Status: Done

TASK-ID: TA-W1-036
Title: Semi-automated question/rubric confirmation workflow
Owner: Hermes
Priority: P1
Dependencies: TA-W1-035B
Files affected: TBD
Goal: Add a semi-automated workflow where AI drafts question discretization, model answers, and rubrics, then teacher confirmation gates batch grading.
Implementation notes: Future task only.
Acceptance criteria: Grading cannot start until teacher confirms/edit drafts and marking policy.
Tests required: TBD.
Risks: Draft quality must be evaluated before broad use.
Status: Pending

TASK-ID: TA-W1-037A
Title: Enable image input for browser-triggered Codex grading smoke
Owner: Hermes
Priority: P0
Dependencies: TA-W1-036B
Files affected: Makefile, apps/api/packages/brain/codex_cli_provider.py, apps/api/tests/test_codex_cli_provider.py, docs/CODEX_DEV_RUNTIME.md, docs/VALIDATION_LOG.md, BACKLOG.md
Goal: Enable and validate image input for exactly one browser/backend Codex grading smoke so the provider can see the cropped answer image.
Implementation notes: Confirmed installed Codex CLI `codex-cli 0.128.0` supports `-i, --image <FILE>`. Kept image input default-off, made `make backend-host-dev` allow an explicit `CODEX_CLI_IMAGE_INPUT_ENABLED=true` override, and documented host-backend image-input mode. Updated the Codex CLI provider to pass `--image <absolute crop path>` only when image input is enabled and an answer image path exists; otherwise it omits the image flag and records `image_input_disabled`. Ran one synthetic non-student browser/backend dev endpoint smoke with image input enabled: answer_region_id `2647`, grade_suggestion_id `1782`, score `5.00`, confidence `0.9900`, `needs_review=true`, review_flags `teacher_review_required`, `codex_cli_provider`, `image_input_used`; no FinalGrade was auto-created.
Acceptance criteria: Image flag included when enabled/supported; image flag omitted when disabled or no image path exists; no real Codex calls in unit tests; host backend can opt into `CODEX_CLI_IMAGE_INPUT_ENABLED=true`; Docker/demo mode remains default-off; browser button remains single-answer only; one real synthetic smoke uses image input and still requires teacher review.
Tests required: `codex --version`; `codex exec --help`; focused provider tests; `make up-infra`; local Alembic migration; `make codex-ok`; host backend with `CODEX_CLI_IMAGE_INPUT_ENABLED=true`; frontend readiness; one real image-input `grade-codex-dev` smoke; `make test`; `make lint`; `npm run build`; clean shutdown; final `git status --short`.
Risks: This proves the CLI image-input path and review gate on one synthetic answer only; it is not a grading-quality evaluation, batch grading feature, auto-finalization, voice command, or TA-W1-038.
Status: Done

TASK-ID: TA-W1-037B
Title: Real original-script Codex image-input grading evaluation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-037A
Files affected: docs/GRADING_QUALITY_NOTES.md, BACKLOG.md
Goal: Run a capped real-original-script evaluation using Codex CLI image input on selected original answer crops and compare against teacher marks.
Implementation notes: Re-staged original/sample inputs under ignored `/tmp/ta_original_doc_eval_image_input/`, rendered script pages, and created three manually tightened answer crops including the previous problematic `orig_s2_p07_q1c` case. Ran the existing grading evaluation path with `provider=codex_cli`, `TA_EVAL_ALLOW_REAL_PROVIDER=true`, `CODEX_CLI_IMAGE_INPUT_ENABLED=true`, and `max_real_cases=3`. All suggestions recorded `image_input_used`, `needs_review=true`, and `teacher_review_required`; verified no FinalGrade rows were created. Metrics: case_count 3, exact_match_rate 0.3333, within_1_mark_rate 1.0, mean_absolute_error 0.50, false_confident_error_count 0, severe_error_count 0, over_score_count 1, under_score_count 1, average_confidence 0.8433, needs_review_rate 1.0. The previous problematic case improved from 9.5 vs expected 7.0 to 8.0 vs expected 7.0, but remained an over-score.
Acceptance criteria: Real image-input eval runs on at most 3–5 selected original-script crops; raw docs/crops/artifacts remain ignored; no batch production grading or auto-finalization; metrics and per-case results are recorded; teacher review remains mandatory.
Tests required: git status --short; make up-infra; make codex-ok; capped real-provider image-input eval; focused eval tests if code changed; make test; make lint; git status --short.
Risks: This is only a 3-case manually selected/tight-crop quality smoke. It does not prove production grading reliability, automatic answer-region detection, fully automated grading, or marking policy calibration.
Status: Done

TASK-ID: TA-W1-037
Title: Fully automated ZIP grading prototype
Owner: Hermes
Priority: P1
Dependencies: TA-W1-036, TA-W1-038
Files affected: TBD
Goal: Prototype highest-risk workflow using question PDF plus ZIP scripts after lower-risk workflows and quality gates exist.
Implementation notes: Future task only. Do not claim reliability until evaluated on mixed original teacher-marked cases.
Acceptance criteria: All AI results still require teacher review and final approval.
Tests required: TBD.
Risks: Highest risk because extraction, rubric drafting, script processing, answer detection, mapping, and grading errors compound.
Status: Pending

TASK-ID: TA-W1-038
Title: Marking policy calibration
Owner: Hermes
Priority: P1
Dependencies: TA-W1-035A
Files affected: TBD
Goal: Calibrate and evaluate Tough, General, and Easy rubric interpretation policies across mixed teacher-marked cases.
Implementation notes: Superseded by Phase-2 functional-body tasks `TA-W2-005` and `TA-W2-006`; keep as historical W1 placeholder only.
Acceptance criteria: Every grading run records policy; evaluation reports metrics by policy; teacher review remains mandatory.
Tests required: TBD.
Risks: Policy prompts may shift scores unpredictably without calibration.
Status: Pending

## Phase 2 — Functional body first

Program direction: do not rush launch or UX polish. Build the full usable teacher grading body first, with Custom Controlled Mode as the safest first complete workflow. AI suggestions remain review-required and never auto-finalize grades.

TASK-ID: TA-W2-001
Title: Functional body reset and unified grading workflow foundation
Owner: Hermes
Priority: P0
Dependencies: TA-W1-037B
Files affected: docs/FUNCTIONAL_BODY_EXECUTION_PLAN.md, BACKLOG.md
Goal: Create the execution structure for the three-mode grading product and reset the backlog around full functional-body milestones.
Implementation notes: Documentation/backlog-only task. Audited the current implementation against Fully Automated, Semi-Automated, and Custom Controlled modes; defined usable V0; mapped current support and missing backend/frontend pieces; set build order; chose TA-W2-002 as the next implementation task. No grading behavior, ZIP upload, fully automated mode, UI polish, or real Codex grading was implemented.
Acceptance criteria: Functional-body plan exists; backlog contains TA-W2-001 through TA-W2-011; next task is TA-W2-002; safety rules remain explicit; tests/lint pass; docs-only commit.
Tests required: git status --short; make test; make lint; git status --short.
Risks: This is execution structure only; it does not make the Custom Controlled workflow fully smooth yet.
Status: Done

TASK-ID: TA-W2-002
Title: Custom Controlled Mode completion audit
Owner: Hermes
Priority: P0
Dependencies: TA-W2-001
Files affected: docs/CUSTOM_CONTROLLED_MODE_AUDIT.md, BACKLOG.md
Goal: Audit the current Custom Controlled flow from login through XLSX export and identify exact blockers preventing it from being the first complete usable V0 workflow.
Implementation notes: Completed audit at `docs/CUSTOM_CONTROLLED_MODE_AUDIT.md`. Current status is partial: backend/API foundations exist for custom run creation, material upload, individual script upload, manual answer regions, mock grading, teacher review, selected approval, and XLSX export. Main blockers are missing derived workflow status, missing confirmation gates, material uploads not linked to canonical questions/rubrics, no run-scoped grading/export/status dashboard, manual status as source of truth, no ZIP ingestion, and no marking policy. No real Codex grading, ZIP upload, full automation, grading behavior change, or UI polish was implemented.
Acceptance criteria: End-to-end Custom Controlled path is audited with evidence; missing pieces are categorized backend/frontend/status/data; next fixes are scoped for TA-W2-003; no raw artifacts committed.
Tests required: git status --short; make up-infra; alembic upgrade head; focused API-equivalent audit tests; make test; make lint; git status --short.
Risks: Audit confirms product-code changes are required in TA-W2-003 before Custom Controlled Mode is a cohesive V0 workflow.
Status: Done

TASK-ID: TA-W2-003
Title: Custom Controlled Mode full usable workflow fix
Owner: Hermes
Priority: P0
Dependencies: TA-W2-002
Files affected: apps/api/alembic/versions/0006_grading_run_confirmations.py, apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/api/routes/grading_runs.py, apps/api/tests/test_grading_runs_api.py, apps/web/lib/api.ts, apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Fix the smallest set of backend/frontend/status issues so Custom Controlled Mode is usable end-to-end from login to XLSX export with rough UI.
Implementation notes: Use `docs/CUSTOM_CONTROLLED_MODE_AUDIT.md` as the source. Recommended order: (1) add derived Custom Controlled status/checklist with material/question/rubric/submission/region/suggestion/final/export readiness; (2) stop treating manual status as the source of truth; (3) turn the Custom Controlled page into a rough dashboard with blockers/counts/next actions; (4) add minimal teacher confirmation tracking for questions/rubrics without parsing solution/rubric PDFs; (5) gate UI grading actions on readiness; (6) add one full end-to-end API test from run start through export. Keep manual answer-region mapping. Do not add ZIP upload, fully automated mode, semi-automated mode, marking policy behavior, real batch Codex, answer-region auto-detection, or UX polish.
Acceptance criteria: Teacher can login, create course/assessment, start Custom Controlled run, upload materials, confirm questions/rubrics, upload one script, create answer region, run mock grading suggestion, verify no auto-final grade, review/approve, and export XLSX; dashboard clearly shows blockers and ready states.
Tests required: focused Custom Controlled status/workflow tests; existing grading-run/grading/review tests; make test; make lint; frontend build if relevant; mock-only manual or API smoke; git status --short.
Risks: Scope creep into ZIP/automation/polish must be avoided; confirmation tracking must not imply AI-quality guarantees.
Status: Done

TASK-ID: TA-W2-004
Title: ZIP script upload and batch submission ingestion
Owner: Hermes
Priority: P0
Dependencies: TA-W2-003
Files affected: apps/api/app/api/routes/submissions.py, apps/api/app/schemas.py, apps/api/tests/test_submission_upload_api.py, apps/api/tests/test_grading_runs_api.py, apps/web/lib/api.ts, apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md
Goal: Add safe ZIP ingestion for multiple student scripts and create Submission/Page records without committing raw files.
Implementation notes: Support ZIP as ingestion only; do not auto-grade or auto-map regions. Validate file types, path traversal, size/count limits, and per-file error reporting. Uses assessment-scoped upload endpoint and existing submission/page extraction path.
Acceptance criteria: Teacher can upload a ZIP of scripts; valid PDFs/images become submissions/pages; rejected files are reported; raw uploaded content stays in storage only; Custom Controlled workflow state counts ZIP-imported submissions.
Tests required: backend upload tests, path traversal tests, full tests/lint/build if frontend changes.
Risks: ZIP handling can introduce path traversal and resource exhaustion risks.
Status: Done

TASK-ID: TA-W2-005
Title: Marking policy model: Tough/General/Easy
Owner: Hermes
Priority: P0
Dependencies: TA-W2-003
Files affected: apps/api/alembic/versions/0007_marking_policy.py, apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/api/routes/grading_runs.py, apps/api/app/services/grading_service.py, apps/api/app/services/final_grade_service.py, apps/api/tests/test_grading_runs_api.py, apps/api/tests/test_migrations.py, apps/api/tests/test_models_metadata.py, apps/api/tests/test_final_grade_review_api.py, apps/web/lib/api.ts, apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/components/AssessmentReviewClient.tsx, apps/web/tests/workflow-ui.test.mjs
Goal: Persist marking policy on grading runs and suggestions so every workflow records Tough, General, or Easy.
Implementation notes: Added model/schema/API/UI support only; scoring prompt behavior remains unchanged until TA-W2-006. Mock grading now records policy metadata/flag for propagation tests.
Acceptance criteria: Teacher can select policy for a grading run; policy is stored and visible; suggestions record policy metadata; default is safe and explicit; export includes marking_policy.
Tests required: migration/model/API/frontend static tests; make test; make lint.
Risks: Must avoid silently changing score behavior before prompt calibration.
Status: Done

TASK-ID: TA-W2-006
Title: Marking policy-aware Codex grading prompt
Owner: Hermes
Priority: P0
Dependencies: TA-W2-005
Files affected: apps/api/packages/brain/adapter.py, apps/api/packages/brain/codex_cli_provider.py, apps/api/packages/brain/mock_provider.py, apps/api/packages/brain/openai_provider.py, apps/api/packages/brain/prompt_registry.py, apps/api/packages/brain/provider_base.py, apps/api/packages/evaluation/grading_evaluation.py, apps/api/app/services/grading_service.py, apps/api/tests/test_brain_adapter_contract.py, apps/api/tests/test_grading_evaluation.py
Goal: Pass marking policy into mock/Codex grading prompt metadata and evaluate Tough/General/Easy behavior.
Implementation notes: Added explicit policy instructions for Tough/General/Easy in grading prompts, propagated marking_policy through BrainAdapter/provider interfaces, ensured Codex CLI prompts request marking_policy review flags without image-data fabrication, and added evaluation-run/report policy metadata. Real provider runs remain capped/explicit by existing evaluation guardrails.
Acceptance criteria: Grading prompt/provider output records policy; evaluation artifacts report policy; no auto-finalization; no default real batch grading.
Tests required: provider/prompt tests, evaluation tests, capped smoke only if approved, make test, make lint.
Risks: Prompt policy may shift scores unpredictably without calibration.
Status: Done

TASK-ID: TA-W2-006A
Title: Marking policy calibration smoke
Owner: Hermes
Priority: P0
Dependencies: TA-W2-006
Files affected: docs/GRADING_QUALITY_NOTES.md, BACKLOG.md
Goal: Run a capped real Codex smoke to check whether Tough / General / Easy marking policies affect grading in the expected direction.
Implementation notes: Ran two synthetic non-student cases across three policies for six real Codex calls total. Scores were identical across policies for both cases, so monotonic order held but no meaningful score separation was observed. Policy metadata/review flags were recorded and no FinalGrade was created.
Acceptance criteria: Real calibration result recorded honestly; no batch grading; no auto-finalization; artifacts kept out of git.
Tests required: make test; make lint.
Risks: Policy prompt exists, but behavior is not meaningfully calibrated on simple rubric-separated cases.
Status: Done

TASK-ID: TA-W2-007
Title: Semi-automated question/model/rubric confirmation flow
Owner: Hermes
Priority: P1
Dependencies: TA-W2-005
Files affected: TBD
Goal: Build the confirmation gate where AI-drafted questions/model answers/rubrics become teacher-confirmed canonical grading materials before grading.
Implementation notes: Extend existing question import foundation. Do not start fully automated grading. Drafts remain drafts until teacher accepts/edits.
Acceptance criteria: Grading cannot start until question discretization, model answers, rubrics, and marking policy are confirmed.
Tests required: backend confirmation tests, frontend static/tests, make test, make lint, build.
Risks: Draft quality may be poor; UI must make teacher authority clear.
Status: Pending

TASK-ID: TA-W2-008
Title: Controlled batch Codex grading with review gates
Owner: Hermes
Priority: P1
Dependencies: TA-W2-005, TA-W2-006, TA-W2-004
Files affected: TBD
Goal: Add tightly controlled batch real Codex grading for confirmed/mapped answer regions with explicit limits, logging, and review gates.
Implementation notes: Real batch grading stays disabled by default and must require explicit enablement, case limits, provider readiness, and teacher review. Mock batch remains the safe default.
Acceptance criteria: Batch real Codex cannot run accidentally; every suggestion is logged, policy-tagged, review-required, and failure-tolerant.
Tests required: guardrail tests, provider-error tests, capped smoke only if approved, make test, make lint.
Risks: Cost/quota, provider errors, and quality risk.
Status: Pending

TASK-ID: TA-W2-008A
Title: TA-W2-008A browser validation closeout
Owner: Hermes
Priority: P1
Dependencies: TA-W2-008
Files affected: BACKLOG.md, docs/VALIDATION_LOG.md
Goal: Record the completed TA-W2-008A browser validation workflow, including mock-grade review, teacher approval, XLSX export, and clean repository state.
Implementation notes: Verified the live Teacher Assistant app at assessment #5242 / Demo Midterm Review, confirmed the review queue and mock suggestion flow, verified `needs_review=true`, observed manual teacher approval, confirmed XLSX export download, and kept the repo clean at commit `6d8e5f1`. No product code changed.
Acceptance criteria: TA-W2-008A is recorded as complete; browser validation evidence is documented; no auto-finalization is claimed; no new product task is started.
Tests required: Documentation update only; no code tests required.
Risks: None beyond stale status if the closeout record is omitted.
Status: Done

TASK-ID: TA-W2-009
Title: Answer-region mapping improvement
Owner: Hermes
Priority: P1
Dependencies: TA-W2-003, TA-W2-004
Files affected: apps/api/app/api/routes/grading_runs.py, apps/api/app/schemas.py, apps/api/tests/test_grading_runs_api.py, apps/web/components/AssessmentDetailClient.tsx, apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/lib/api.ts
Goal: Improve answer-region mapping workflow before fully automated mode, starting with assisted/manual improvements rather than unchecked automation.
Implementation notes: Added mapping workflow refinements and related UI/API support so teachers can map/confirm regions more reliably while keeping teacher confirmation as the source of truth.
Acceptance criteria: Teacher can map/confirm regions more reliably; mapping status is visible; grading only runs on confirmed/mapped regions.
Tests required: answer-region tests, frontend checks, manual smoke, make test, make lint.
Risks: Auto-detection errors can poison grading; keep teacher confirmation.
Status: Done

TASK-ID: TA-W2-010
Title: Answer-region suggestion prototype
Owner: Hermes
Priority: P1
Dependencies: TA-W2-009
Files affected: apps/api/app/api/routes/answer_regions.py, apps/api/app/schemas.py, apps/api/tests/test_answer_regions_api.py, apps/web/components/AssessmentDetailClient.tsx, apps/web/lib/api.ts
Goal: Prototype draft answer-region suggestions in the API and UI without auto-persisting them.
Implementation notes: Added an answer-region suggestion path that surfaces draft suggestions for teacher review and keeps manual creation/review as the durable source of truth.
Acceptance criteria: Teacher can request suggestions, inspect the draft result, and manually decide whether to create a real answer region; suggestions remain review-only.
Tests required: answer-region tests, frontend checks, manual smoke, make test, make lint.
Risks: Suggestion quality may vary; do not auto-apply drafts.
Status: Done

TASK-ID: TA-W2-011
Title: UX redesign after full functional body works
Owner: Hermes
Priority: P2
Dependencies: TA-W2-003, TA-W2-004, TA-W2-005, TA-W2-007, TA-W2-008, TA-W2-009
Files affected: BACKLOG.md, docs/VALIDATION_LOG.md
Goal: Redesign and polish UX only after the full functional body works end-to-end.
Implementation notes: Professional UI/UX polish is explicitly deferred until core workflows are functional and verified.
Acceptance criteria: Redesigned workflow improves clarity without weakening safety gates or hiding teacher review requirements.
Tests required: frontend tests/static checks, build, manual workflow smoke.
Risks: Premature polish can distract from functional blockers.
Status: Done

TASK-ID: TA-W2-012
Title: Reserved numbering slot
Owner: Hermes
Priority: P2
Dependencies: None
Files affected: none
Goal: Reserve the TA-W2-012 slot for a future docs/task entry if needed.
Implementation notes: Intentionally skipped to preserve numbering continuity; no product work is associated with this slot.
Acceptance criteria: The numbering gap is explicitly documented instead of being ambiguous.
Tests required: none
Risks: None
Status: Reserved

TASK-ID: TA-W2-013
Title: Semi-automated grading-run mode
Owner: Hermes
Priority: P1
Dependencies: TA-W2-011
Files affected: apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/api/routes/grading_runs.py, apps/api/alembic/versions/0008_semi_automated_mode.py, apps/api/tests/test_grading_runs_api.py, apps/api/tests/test_migrations.py, apps/web/lib/api.ts, apps/web/components/CustomControlledGradingRunClient.tsx, apps/web/components/AssessmentDetailClient.tsx, apps/web/tests/workflow-ui.test.mjs
Goal: Add semi_automated grading-run mode support across API, workflow state, UI, and tests without changing product scope.
Implementation notes: Preserve custom_controlled flow; semi_automated uses question-paper-only uploads and mode-aware labels/links.
Acceptance criteria: Semi_automated mode is creatable and visible, workflow state is mode-aware, UI labels/entry point adapt, focused tests and full checks pass.
Tests required: focused grading-run tests, frontend workflow test, make test, make lint, frontend build, migration check.
Risks: Mode-specific branching can break existing custom controlled flow; keep check constraints and UI labels aligned.
Status: Done

TASK-ID: TA-W2-014C
Title: Custom controlled browser validation closeout
Owner: Hermes
Priority: P1
Dependencies: TA-W2-013
Files affected: BACKLOG.md, docs/VALIDATION_LOG.md
Goal: Record the completed TA-W2-014C-final browser validation workflow, including Docker recovery, browser smoke, mock-grade review, teacher approval, XLSX export, and clean repository state.
Implementation notes: Verified the live Teacher Assistant app after Docker runtime restoration, confirmed the review queue and mock suggestion flow, verified `needs_review=true`, observed manual teacher approval, confirmed XLSX export download, and kept the repo clean. Browser auth was flaky, so API registration plus token injection fallback was used after recording the browser-auth failure. No product code changed.
Acceptance criteria: TA-W2-014C-final is recorded as complete; browser validation evidence is documented; the auth caveat is captured; no new product task is started from the validation record.
Tests required: Documentation update only; no code tests required beyond doc sanity checks.
Risks: None beyond stale status if the closeout record is omitted.
Status: Done

TASK-ID: TA-W2-015
Title: Browser auth flow reliability fix
Owner: Hermes
Priority: P1
Dependencies: TA-W2-014C
Files affected: apps/web/app/login/page.tsx, apps/web/app/register/page.tsx, apps/web/lib/api.ts, apps/web/components/**, apps/api/app/api/routes/auth.py, apps/api/tests/**, BACKLOG.md
Goal: Investigate and fix the browser register/login reliability issue that forced API registration plus token injection fallback during TA-W2-014C-final.
Implementation notes: First reproduce the browser auth flake, then identify whether the issue is form submission, token persistence, redirect timing, or API response handling. Keep the change small and targeted; do not expand scope into unrelated auth features.
Acceptance criteria: Browser register/login succeeds reliably in the live UI without fallback in the controlled validation path; failure mode is documented if a product-side fix is deferred.
Tests required: targeted auth flow smoke, frontend checks, backend/API auth tests if changed, git diff --check, and any existing repo checks needed for the touched files.
Risks: Token persistence and redirect race conditions can create flaky validation results if not handled carefully.
Status: Done

TASK-ID: TA-W2-016A
Title: Single real Codex grading validation record
Owner: Hermes
Priority: P1
Dependencies: TA-W2-015
Files affected: docs/VALIDATION_LOG.md, docs/CODEX_DEV_RUNTIME.md, BACKLOG.md
Goal: Record the successful TA-W2-016A controlled validation of exactly one real Codex grading call and keep the scope documented as one selected answer region only.
Implementation notes: Documentation/backlog-only record. `make codex-ok` passed after forcing the Codex model to `gpt-5.5`; the default `gpt-5.3-codex` was rejected under the current ChatGPT-backed login. Host backend was started with Codex dev flags, exactly one real grading call was run against `POST /answer-regions/4281/grade-codex-dev`, the endpoint returned `201 Created`, a `GradeSuggestion` was created with `model_provider=codex_cli`, `needs_review=true`, and `image_input_used`, no `FinalGrade` was created afterward, no auto-finalization occurred, and the host backend was stopped afterward while Postgres and Redis stayed running.
Acceptance criteria: BACKLOG marks TA-W2-016A done; validation log contains the same evidence; runtime docs include the `gpt-5.5` compatibility note; no product code is changed; the record clearly states single-region only and not batch or fully automated grading.
Tests required: `git diff --check`; `make lint`; `make down` if no further runtime is needed; final git status review.
Risks: This proves the real Codex path for one selected answer region only and does not prove grading quality or batch automation.
Status: Done

TASK-ID: TA-W2-018A
Title: Real Codex answer-region suggestion smoke record
Owner: Hermes
Priority: P1
Dependencies: TA-W2-016A
Files affected: docs/VALIDATION_LOG.md, BACKLOG.md
Goal: Record the completed real Codex answer-region suggestion smoke so future work has a durable validation record.
Implementation notes: Documentation/backlog-only record. Real Codex answer-region suggestion smoke succeeded only when `CODEX_CLI_MODEL=gpt-5.5` was explicitly set. Call count: 2. Direct provider smoke on a blank synthetic page returned no suggestions, then a synthetic API smoke on a bordered page returned exactly 1 draft suggestion via `codex_cli_answer_region_suggester` with `needs_review=true` and confidence `0.96`. The draft stayed draft-only; no `AnswerRegion`, `GradeSuggestion`, or `FinalGrade` was created by the suggestion endpoint. Root cause: runtime model selection, not provider code. The default `gpt-5.3-codex` is rejected under the current ChatGPT-backed login.
Acceptance criteria: Validation log contains the same evidence; no product code is changed; the result is clearly marked as completed validation, not a product feature rollout.
Tests required: `git diff --check`; final git status review.
Risks: This validates only the answer-region suggestion smoke path and does not imply broader production readiness.
Status: Done

TASK-ID: TA-W2-018B
Title: Expert-review-adjusted recovery plan and supervision context
Owner: Hermes
Priority: P1
Dependencies: TA-W2-018A
Files affected: BACKLOG.md, docs/VALIDATION_LOG.md, docs/CODEX_DEV_RUNTIME.md, docs/PROJECT_SUPERVISION_CONTEXT.md
Goal: Record the expert-review-adjusted one-week recovery plan and create a durable supervision context handoff for future LLM supervisors.
Implementation notes: Documentation-only record. Capture the founder’s corrected product direction, the expert synthesis, the verified TA-W2-018A result, the current non-ready gaps, the one-week recovery plan, the next task sequence, and the pre-pilot gates. Do not implement TA-W2-019/020/021/022A here.
Acceptance criteria: The supervision context document exists and is durable; the runtime note captures the explicit supported Codex model requirement; the backlog clearly shows the next sequence after this task.
Tests required: `git diff --check`; `make lint`; final git status review.
Risks: If the backlog omits the next sequence, future supervisors may lose the intended recovery order.
Status: Done

TASK-ID: TA-W2-019
Title: Marking policy calibration fix
Owner: Hermes
Priority: P1
Dependencies: TA-W2-018B
Files affected: apps/api/packages/brain/prompt_registry.py, apps/api/packages/evaluation/marking_policy_calibration.py, apps/api/tests/test_brain_adapter_contract.py, apps/api/tests/test_openai_provider.py, apps/api/tests/test_codex_cli_provider.py, apps/api/tests/test_marking_policy_calibration.py, docs/VALIDATION_LOG.md, docs/GRADING_QUALITY_NOTES.md, BACKLOG.md
Goal: Fix marking policy calibration so the same synthetic answer and rubric produce a meaningful toughness gradient (`tough < general < easy`).
Implementation notes: Introduced one shared policy-instruction source, made Tough/General/Easy instructions concrete and operational, and added a deterministic synthetic calibration harness. Do not expand into unrelated grading changes.
Acceptance criteria: Synthetic test cases show a meaningful score delta across Tough/General/Easy.
Tests required: targeted calibration tests, relevant backend/provider checks, repo checks for touched files.
Risks: If calibration is still weak on real provider runs later, downstream validation and teacher trust will remain limited.
Status: Done

TASK-ID: TA-W2-020
Title: Playwright E2E smoke suite
Owner: Hermes
Priority: P1
Dependencies: TA-W2-019
Files affected: apps/web/**, apps/api/**, tests/**, BACKLOG.md
Goal: Add a minimal Playwright E2E smoke suite covering auth, Custom Controlled mock flow, and no-FinalGrade-before-approval.
Implementation notes: Keep the suite tiny and deterministic; use stable browser selectors, a synthetic submission fixture, and a demo-teacher selector for approval. Avoid real Codex and keep the export check lightweight.
Acceptance criteria: Auth, mock flow, and approval gating are exercised end to end in automated smoke tests; the no-FinalGrade-before-approval invariant is asserted.
Tests required: Playwright smoke, frontend workflow/static test, frontend build/lint, backend tests touched by the suite, and git diff checks.
Risks: UI timing and selector instability can make the smoke flaky if not constrained tightly.
Status: Done

TASK-ID: TA-W2-021
Title: Mode gating / ghost-mode clarity
Owner: Hermes
Priority: P1
Dependencies: TA-W2-020
Files affected: docs/**, apps/web/**, apps/api/**, BACKLOG.md
Goal: Make unsupported or non-ready modes clearly gated and reduce misleading “ghost mode” behavior in the product surface and docs.
Implementation notes: Custom Controlled remains the only teacher-ready path. Semi-Automated is blocked by default behind an explicit backend flag and hidden from the normal assessment page; Fully Automated is rejected with a clear error message until it is genuinely built and validated. Preserve the historical mode/migration scaffolding.
Acceptance criteria: The mode surface is explicit about readiness; Semi-Automated is not usable from the normal teacher flow by default; Fully Automated is unavailable/rejected; hidden/unsupported behavior is not misleading.
Tests required: targeted mode-gating checks and any docs or UI checks touched by the change.
Risks: If mode labels stay ambiguous, teachers may misinterpret what is production-ready.
Status: Done

TASK-ID: TA-W2-022A
Title: Privacy baseline documentation and deletion endpoint
Owner: Hermes
Priority: P1
Dependencies: TA-W2-021
Files affected: docs/**, apps/api/**, apps/web/**, BACKLOG.md
Goal: Establish a privacy baseline with documentation, deletion support, and artifact/storage warnings.
Implementation notes: Added `docs/PRIVACY_BASELINE.md`, expanded ignore rules for local sensitive artifacts, and added authenticated `DELETE /assessments/{assessment_id}/test-data` for owner-only cleanup. The endpoint removes assessment test/grading rows while preserving the assessment shell, attempts best-effort local file cleanup, and returns counts without exposing absolute private paths. No encryption, retention policy, or production compliance was added.
Acceptance criteria: Privacy guidance is documented, a deletion endpoint exists where appropriate, artifact/storage warnings are documented, and tests prove owner deletion, cross-teacher rejection, dependent-row cleanup, no FinalGrade creation, and no private path exposure in normal deletion responses.
Tests required: targeted endpoint/docs checks plus repo checks for touched files.
Risks: This is still an internal/local privacy baseline only; real teacher/private-document rehearsal still requires founder approval and careful scope limits.
Status: Done


TASK-ID: TA-W2-022B
Title: Founder real-document grading rehearsal
Owner: Hermes
Priority: P1
Dependencies: TA-W2-022A
Files affected: none committed
Goal: Run a small founder-approved real-document rehearsal under manual controlled constraints.
Implementation notes: Ran 3 real Codex grading calls on founder-approved local reference material, but the quality evaluation is invalidated because canonical grading units were set up ambiguously/wrongly as Question 2-style labels while the founder-confirmed paper answers Question 1.
Acceptance criteria: Superseded by TA-W2-022C; do not use this rehearsal as grading-quality evidence.
Tests required: N/A for committed code.
Risks: Wrong question labels/max marks make real grading meaningless.
Status: Invalidated

TASK-ID: TA-W2-022C
Title: Canonical grading unit confirmation
Owner: Hermes
Priority: P1
Dependencies: TA-W2-022B
Files affected: apps/api/app/api/routes/questions.py, apps/api/app/api/routes/question_imports.py, apps/api/app/services/final_grade_service.py, apps/api/tests/**, apps/web/components/**, apps/web/e2e/support.ts, docs/**, BACKLOG.md
Goal: Prevent wrong question/rubric setup before real grading by supporting explicit canonical grading-unit labels/max marks and showing a founder/teacher confirmation table.
Implementation notes: Use a flat grading-unit representation via existing Question rows (`question_no` as labels such as `1(a)(i)`, `total_marks` as max marks). Add duplicate-label validation, label+marks display in answer-region/review/export surfaces, and a canonical confirmation table before questions/rubrics are confirmed. No real Codex.
Acceptance criteria: Labels like `1(a)(i)` are supported, duplicate labels in one assessment are rejected, answer-region and review surfaces show label + max marks, export includes label/max marks, no FinalGrade is auto-created, and E2E mock flow still asserts teacher approval gating.
Tests required: focused backend grading-unit/export tests, frontend static workflow test, make e2e, make test, make lint, frontend build, git diff checks.
Risks: This is still a flat model; a richer hierarchy can wait until the product needs it.
Status: Done


TASK-ID: TA-W2-022D
Title: Corrected founder real-document grading retest with canonical units
Owner: Hermes
Priority: P1
Dependencies: TA-W2-022C
Files affected: none committed
Goal: Rerun a tiny founder-approved real-document rehearsal using confirmed canonical Question 1 grading units.
Implementation notes: Created a fresh assessment and confirmed canonical units before grading. Ran exactly 3 Codex answer-region suggestion calls and 3 real Codex grading calls on `1(a)(i)`, `1(b)(i)`, and `1(c)(i)`. No batch, no whole-script grading, no approve/edit/export, no FinalGrade auto-created, needs_review stayed true.
Acceptance criteria: Technical corrected canonical-unit flow works; grading-quality comparison remains review-required.
Tests required: Runtime/manual controlled founder rehearsal only; no code changes.
Risks: Quality blocker found: `1(b)(i)` was under-credited by Codex (3/6 vs founder fair 6/6).
Status: Partial — technically successful, grading-quality blocked

TASK-ID: TA-W2-023
Title: Improve handwritten math grading prompt
Owner: Hermes
Priority: P1
Dependencies: TA-W2-022D
Files affected: apps/api/packages/brain/prompt_registry.py, apps/api/packages/brain/codex_cli_provider.py, apps/api/packages/evaluation/marking_policy_calibration.py, apps/api/tests/**, docs/**, BACKLOG.md
Goal: Improve real handwritten math/stat grading prompt and deterministic calibration so near-correct Bayes/statistics work receives appropriate credit instead of severe under-scoring.
Implementation notes: Added shared handwritten math/stat guidance to grading prompts, included it in Codex/OpenAI prompt paths, preserved Tough/General/Easy policy behavior, and expanded the fake calibration harness with synthetic Bayes/stat cases.
Acceptance criteria: Prompt includes canonical-unit/max-mark grounding, rubric/model-answer grounding, math/stat credit guidance, conceptual/arithmetic/presentation distinction, teacher review/no-FinalGrade language, and synthetic Bayes compact-working case targets 5–6/6 instead of 3/6.
Tests required: Focused prompt/provider tests, calibration harness tests, make test, make lint, frontend build only if frontend touched, git diff checks.
Risks: This is deterministic prompt/harness calibration only; a small founder real-document retest is still needed to verify real Codex behavior after the prompt fix.
Status: Done


TASK-ID: TA-W2-023B
Title: Bayes-specific rubric grounding and score-band guidance
Status: Done
Added: 2026-06-03T00:16:25+06:00
Scope:
- Add Bayes/probability 6-mark score-band guidance to the shared handwritten math/stat grading prompt.
- Preserve marking policy, strict JSON, teacher-review, no-FinalGrade, answer-region, canonical-unit, auth, and workflow behavior.
- Add deterministic calibration coverage for a near-full-credit Bayes answer with compact/unclear numerator/final expression.
Validation plan:
- Focused prompt/provider/calibration tests.
- Deterministic fake calibration harness.
- `make test`, `make lint`, `git diff --check`.
- Optional real Codex retest for `1(b)(i)` region `5120` was skipped because the required test-suite cleanup removed the TA-W2-023A DB row before retest.
Notes:
- Triggered by TA-W2-023A: `1(b)(i)` improved `3/6 -> 4/6` but remained below founder fair `6/6`.
- Teacher observation remains blocked until real retest is acceptable or demo framing is narrowed to conservative human-in-loop draft suggestions.

TASK-ID: TA-W2-024
Title: Answer-region crop/context audit for real grading quality
Status: Done / grading-quality blocked
Added: 2026-06-03T00:53:02+06:00
Scope:
- Audit the actual `1(b)(i)` crop against the full rendered script page.
- Add minimal AI-grading-only padded crop context where crop/context is inadequate.
- Run at most one real Codex grading retest after crop/context is verified or improved.
Outcome:
- Original crop was too tight at bottom/right; a 10% padded grading-context crop recovers more denominator/result evidence while preserving original region coordinates.
- Implemented `ANSWER_REGION_GRADING_CROP_PADDING_RATIO` default `0.10`, clamped to page bounds, with separate `artifacts/grading_context/...` images and `grading_crop_padded` metadata.
- One real Codex retest on `1(b)(i)` still returned `4/6` vs founder fair `6/6`; no FinalGrade was created.
Risks:
- Remaining issue should be treated as real-model conservative scoring limitation for now; do not continue prompt/crop churn on this case without a new founder-approved direction.

TASK-ID: TA-W2-025
Title: Pre-grading evidence packet gate
Owner: Hermes
Priority: P1
Dependencies: TA-W2-024
Files affected: apps/api/app/api/routes/grading.py, apps/api/app/schemas.py, apps/api/app/services/grading_service.py, apps/api/tests/test_grading_api.py, apps/web/components/AssessmentDetailClient.tsx, apps/web/lib/api.ts, apps/web/tests/workflow-ui.test.mjs, BACKLOG.md, docs/VALIDATION_LOG.md, docs/GRADING_QUALITY_NOTES.md, docs/PROJECT_SUPERVISION_CONTEXT.md
Goal: Add an auditable pre-grading evidence packet/readiness gate so grading quality is blocked on confirmed evidence before any provider/job execution.
Implementation notes: Added `GET /answer-regions/{answer_region_id}/grading-evidence-packet`, evidence packet schemas, readiness blockers/warnings, a backend grading readiness gate that returns 400 before provider/job execution when the packet is not ready, and frontend review-card checklist display that disables Mock Grade until the packet is ready. Teacher/founder must confirm the exact question, solution/model answer, rubric, and answer mapping before real grading. This addresses the founder principle that grading quality depends first on confirmed evidence, not question-specific prompt hacks. No real Codex, autonomous loop, batch grading, teacher observation, approval, export, or private artifacts were run/committed.
Acceptance criteria: Evidence packet reports the bounded assessment/submission/page/answer-region context, canonical grading unit, question evidence, solution/model answer evidence, rubric evidence, student answer crop/context evidence, blockers, and warnings; missing active rubric or image/context blocks grading before provider/job execution; the evidence endpoint and blocked path create no FinalGrade; frontend shows readiness and keeps Mock Grade disabled until ready; required backend/frontend/E2E checks pass.
Tests required: `python -m pytest tests/test_grading_api.py -q`, full backend tests / `make test`, `node apps/web/tests/workflow-ui.test.mjs`, `make e2e`, `make lint`, `cd apps/web && npm run build`, `git diff --check`.
Risks: Confirmation statuses are currently `unknown` until the real teacher/founder confirmation workflow is fully validated with real documents. Teacher observation remains blocked until the evidence-packet flow is validated with real documents.
Status: Done
TASK-ID: TA-W2-026
Title: Multi-segment answer evidence and continuation gate
Owner: Hermes
Priority: P0
Dependencies: TA-W2-025
Files affected: apps/api/app/models.py, apps/api/app/schemas.py, apps/api/app/api/routes/answer_regions.py, apps/api/app/services/grading_service.py, apps/api/app/services/answer_region_processing.py, apps/api/alembic/versions/0009_answer_region_segments.py, apps/api/tests/**, apps/web/**, docs/**, BACKLOG.md
Goal: Support one logical grading unit with multiple ordered page segments and block/warn when page-bottom continuation is unconfirmed.
Implementation notes: Manual controlled mode only. No real Codex, no batch real grading, no teacher observation. Keep AnswerRegion as logical unit and add AnswerRegionSegment for ordered crops.
Acceptance criteria: Evidence packets include segment metadata and continuation status; near-bottom regions block grading until full-answer confirmation; multi-segment grading uses all confirmed segments/composite context; no FinalGrade auto-creation.
Tests required: Focused answer-region/evidence-packet/grading tests, frontend static workflow test, make test, make lint, git diff --check, web build if frontend touched, make down after services.
Risks: This is a deterministic first gate; OCR/next-label detection remains future work.
Status: Done

TASK-ID: TA-W2-027
Title: Prepare controlled teacher workflow observation
Owner: Hermes
Priority: P0
Dependencies: TA-W2-026
Files affected: docs/TEACHER_OBSERVATION_PLAN.md, docs/GRADING_QUALITY_NOTES.md, docs/PROJECT_SUPERVISION_CONTEXT.md, docs/VALIDATION_LOG.md, BACKLOG.md
Goal: Prepare a safe in-person teacher workflow observation plan using the validated `1(b)(i)` multi-segment case, without conducting the observation or making production accuracy claims.
Implementation notes: Docs only. Manual controlled mode only. Do not enable autonomous loop, start teacher observation, run new real Codex calls, run batch grading, auto-grade the whole script, approve/edit/export private real data, delete test data, commit private artifacts, auto-finalize grades, or weaken auth.
Acceptance criteria: Observation plan documents purpose, framing, what to show, what not to claim, exact demo flow, privacy warnings, teacher questions, stop conditions, founder wording, and follow-up tasks. Quality/supervision docs record that the previous `4/6` was invalid due to incomplete evidence and the multi-segment retest produced `6/6` with draft-only review-required status.
Tests required: `git status --short`, docs lint if available, `make lint`, `git diff --check`, final `git status --short`. Full test not required because no code changed.
Risks: Observation could be misread as a teacher pilot or accuracy proof; wording must repeatedly state early controlled prototype, draft-only AI suggestion, teacher final authority, and evidence completeness gate.
Status: Done

TASK-ID: TA-W2-028
Title: Conduct teacher observation and record feedback
Owner: Founder/Hermes
Priority: P1
Dependencies: TA-W2-027
Files affected: docs/TEACHER_OBSERVATION_FEEDBACK.md or founder-approved equivalent
Goal: Conduct the controlled in-person teacher workflow observation and record non-private workflow/trust feedback.
Implementation notes: Do not conduct without founder approval. Do not run new real Codex calls, batch grading, export, finalization, or private-data actions unless explicitly approved in-session. Stop on any privacy, evidence, instability, or automation-risk condition.
Acceptance criteria: Feedback records teacher views on grading-unit clarity, evidence packet, multi-page confirmation, draft suggestions, review/edit/export flow, trust/distrust factors, UI confusion, and privacy concerns. No private identifiers or artifacts are committed.
Tests required: Manual safety checklist; final `git status --short`.
Risks: Session drift into pilot/accuracy claim, private-data exposure, or unapproved finalization/export.
Status: Pending

TASK-ID: TA-W2-029
Title: Post-observation improvement plan
Owner: Hermes
Priority: P1
Dependencies: TA-W2-028
Files affected: docs/**, BACKLOG.md, optionally scoped code files if founder approves implementation
Goal: Convert teacher observation feedback into a prioritized improvement plan before any broader pilot.
Implementation notes: Planning first. Separate workflow improvements, trust/explanation improvements, privacy fixes, UI confusion, and grading-quality validation. Do not implement code without a bounded approved task.
Acceptance criteria: Plan identifies issues, priority, safety impact, acceptance criteria, required tests, and whether each item is docs-only, UI, backend, privacy, or grading-quality validation.
Tests required: Docs review; code tests only if later implementation is approved.
Risks: Over-expanding from one observation into broad product claims or unapproved automation.
Status: Pending

TASK-ID: TA-MAP-001
Title: Design next-generation multi-segment answer-region suggestion contract
Owner: Hermes
Priority: P0
Dependencies: TA-W2-026
Files affected: docs/ANSWER_REGION_MAPPING_ALGORITHM.md, apps/api/app/schemas.py, apps/api/tests/test_answer_region_mapping_contract.py, BACKLOG.md
Goal: Define the draft-only multi-segment answer-region mapping contract before implementation of a business-grade mapper.
Implementation notes: Added a design document for a staged review-first mapping algorithm and introduced schema-level contracts for draft suggestion groups, ordered suggestion segments, continuation risk, and acceptance requests. Added deterministic schema contract tests only. No real Codex/OpenAI providers, batch grading, export, finalization, autonomous loop, DB migration, acceptance endpoint, or frontend implementation was added.
Acceptance criteria: Draft suggestion groups can represent one logical answer with ordered segments across one or more pages; suggestions remain review-only and do not create AnswerRegion/GradeSuggestion/FinalGrade rows; acceptance request shape can carry one logical question answer with ordered segments and full-answer confirmation; continuation-risk states are explicit; backend tests document the contract.
Tests required: `python -m pytest tests/test_answer_region_mapping_contract.py -q`; `git diff --check`; `make lint`; focused DB-backed tests only if Postgres is safely available.
Risks: This task defines the contract and minimal schemas only. Persistence, acceptance endpoint, deterministic CV/layout mapper, and teacher-facing segment review UI remain future work.
Status: Done
