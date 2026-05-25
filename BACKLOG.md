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
Goal: Create a clean monorepo scaffold for Next.js frontend, FastAPI backend, root packages, PostgreSQL, Redis, local storage directories, and baseline health/boundary tests.
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
Title: Design teacher review and final approval flow
Owner: Hermes
Priority: P0
Dependencies: TA-W1-005, TA-W1-008
Files affected: docs/REVIEW_APPROVAL_FLOW.md, BACKLOG.md
Goal: Define how teachers inspect, edit, approve, and audit final grades.
Implementation notes: Include UX states and backend state transitions.
Acceptance criteria: Final grade requires explicit teacher action.
Tests required: Manual architecture review.
Risks: Accidental auto-approval.
Status: Pending

TASK-ID: TA-W1-010
Title: Define Excel export contract
Owner: Hermes
Priority: P1
Dependencies: TA-W1-009
Files affected: docs/EXPORT_SPEC.md, BACKLOG.md
Goal: Specify export columns, source records, and restrictions.
Implementation notes: Export final grades only, not raw suggestions. Implementation later uses openpyxl.
Acceptance criteria: Export contract is deterministic and auditable.
Tests required: Manual review.
Risks: Exporting unapproved suggestions.
Status: Pending

TASK-ID: TA-W1-011
Title: Create audit event examples and policy
Owner: Hermes
Priority: P0
Dependencies: TA-W1-005
Files affected: docs/AUDIT_POLICY.md, BACKLOG.md
Goal: Define append-only audit events for AI calls, teacher review, grade approval, exports.
Implementation notes: Include correlation IDs and prompt/model policy references.
Acceptance criteria: Every grade-affecting action has an audit event.
Tests required: Manual review.
Risks: Weak traceability.
Status: Pending

TASK-ID: TA-W1-012
Title: Week 1 architecture review and week 2 planning
Owner: Hermes
Priority: P1
Dependencies: TA-W1-002 through TA-W1-011
Files affected: docs/WEEK_1_REVIEW.md, docs/WEEK_2_PLAN.md, BACKLOG.md
Goal: Verify boundaries, risks, and next implementation sequence.
Implementation notes: Include human decision list.
Acceptance criteria: Week 2 tasks are sequenced and realistic.
Tests required: All implemented tests pass before review.
Risks: Moving to features before foundation is stable.
Status: Pending
