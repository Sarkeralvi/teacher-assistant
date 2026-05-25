# ARCHITECTURE

## High-Level System Architecture
The product is a modular web application using Next.js App Router frontend, FastAPI backend, PostgreSQL database, Redis + RQ worker queue, local filesystem storage behind a storage adapter, and a custom Brain Adapter for all LLM access.

```text
Teacher Browser
  -> Next.js App Router Frontend
  -> FastAPI Backend API
      -> Domain Modules
      -> PostgreSQL via SQLAlchemy 2.x
      -> Alembic migrations
      -> Storage Adapter -> Local filesystem v0 -> S3/MinIO later
      -> Redis Queue
          -> RQ Worker Services
              -> Document Processing: PyMuPDF, Pillow, OpenCV
              -> Grading Engine
              -> Export Engine: openpyxl
              -> Brain Adapter -> External LLM Providers
```

## Locked Tech Stack
See `TECH_STACK_DECISION.md`. Do not replace stack components without Human approval.

- Frontend: Next.js App Router, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, Pydantic, SQLAlchemy 2.x, Alembic
- Database: PostgreSQL
- Worker/Queue: Redis + RQ
- Storage: local filesystem v0 behind storage adapter
- AI: custom Brain Adapter only
- Documents/images: PyMuPDF, Pillow, OpenCV
- Export: openpyxl
- Dev: Docker Compose, Makefile
- Tests: pytest backend; minimal frontend tests Week 1

## Components

### Frontend
Owns teacher-facing UX: course setup, assessment setup, rubric editing, upload flow, grading review, final approval, and export download. Must use backend APIs only. Must never call LLM providers directly. Must never decide final grades automatically.

### Backend API
Owns FastAPI routes, request validation, domain orchestration, permissions, persistence coordination, and API contracts. Must never embed provider-specific LLM calls. Must never store uploaded files only in transient memory.

### Worker Services
Own asynchronous RQ jobs: scan processing, PDF page extraction, image preprocessing, OCR orchestration, AI-assisted grading, report generation, and Excel export. Must be idempotent where practical. Must never bypass domain/audit rules.

### Storage
Owns raw uploads, extracted artifacts, generated exports, and optional preview images through a storage adapter interface. v0 implementation is local filesystem. Future implementations may target S3/MinIO without changing domain modules. Storage must never be treated as the source of truth for grades.

### Database
Owns canonical PostgreSQL records: users, courses, assessments, questions, rubrics, submissions, grading suggestions, teacher reviews, final grades, job status, and audit logs. SQLAlchemy 2.x models define persistence. Alembic owns migrations. Database must preserve grade history.

### Brain Adapter
Owns all external LLM provider access, model selection, structured output validation, retries, fallback, cost logging, prompt versioning, and AI audit records. Must never approve grades.

### Export Engine
Owns Excel export generation through openpyxl. Must only export approved final grades, never raw grading suggestions.

## Module Boundaries

### Course Module
Owns courses, sections/classes, teacher ownership, and course-level settings. Must never know OCR or LLM provider details.

### Assessment Module
Owns assessments, questions, point values, rubric links, due/metadata fields. Must never grade submissions directly.

### Rubric Module
Owns rubric schemas, criteria, levels, points, validation, and versioning. Must never mutate historical rubrics used by past grading records.

### Submission Module
Owns student submissions, uploads, scan status, extracted answer references, and linkage to assessment questions. Must use Storage Adapter for files. Must never finalize grades.

### Document Processing Module
Owns PDF page extraction with PyMuPDF and image preprocessing with Pillow/OpenCV. Must never grade answers or call LLM providers directly.

### Grading Engine Module
Owns grading input assembly, rubric application, AI suggestion interpretation, confidence scoring, and grading output schema. Must never call providers except through Brain Adapter. Must never write final grades.

### Review Module
Owns teacher review, edits, comments, approval, override reasons, and final grade creation. Must never hide AI uncertainty from teachers.

### Export Module
Owns Excel exports and export audit records. Must use openpyxl. Must never recompute final grades independently.

### Audit Module
Owns append-only audit events for AI calls, teacher actions, grade changes, exports, and policy versions. Must never allow destructive edits to audit history.
