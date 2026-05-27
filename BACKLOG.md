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
Status: Pending
