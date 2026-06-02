# Privacy Baseline

This document defines the minimum privacy and data-safety baseline for founder/internal testing of the Teacher Assistant project. It is not external production compliance.

## Scope and status

- Current intended use: founder/internal local testing and controlled demonstrations only.
- External teacher production deployment is not approved by this baseline.
- Real teacher documents or non-anonymized student data must not be uploaded unless the founder explicitly approves that specific test.
- Custom Controlled is the active teacher-ready workflow. AI suggestions remain draft/review artifacts, not final grades.

## Sensitive data handling rules

Treat all of the following as sensitive because they may contain student handwriting, marks, names, IDs, or teacher comments:

- uploaded PDFs, images, scripts, and ZIP files;
- rendered submission pages;
- answer-region crops;
- grading exports such as XLSX files;
- screenshots, Playwright artifacts, videos, traces, and temporary evaluation outputs;
- raw model/provider responses if real AI grading is used later.

Do not commit any PDFs, scripts, crops, rendered pages, exports, screenshots, videos, traces, or generated artifacts to git. Use ignored local storage or `/tmp` for synthetic and real-document rehearsals.

## Teacher authority and AI output

- Teacher remains the final authority.
- AI suggestions are not final grades.
- A `GradeSuggestion` must remain review-required until a teacher approves, edits, or rejects it.
- A `FinalGrade` must only be created by explicit teacher action.

## Deleting assessment test data

Use the authenticated API endpoint:

```http
DELETE /assessments/{assessment_id}/test-data
Authorization: Bearer <teacher-token>
```

Only the teacher who owns the assessment's course can delete that assessment's test data. Other teachers receive `404` so ownership information is not exposed.

The endpoint keeps the assessment record itself but removes local test/grading data associated with it:

- submissions;
- submission pages;
- answer regions;
- grading jobs;
- grade suggestions;
- final grades;
- grading runs and their material file references;
- question-import jobs;
- questions and rubrics created for the test workflow.

Physical file cleanup is best-effort. The endpoint attempts to delete stored submission uploads, rendered pages, answer-region crops, grading-run materials, and question-import files/directories under the configured local storage root. API responses report only counts and a file-delete error count; they must not expose absolute private storage paths.

## Git and artifact safety

The repository ignore rules cover local storage and generated artifacts, including:

- `data/uploads/`
- `data/artifacts/`
- `data/exports/`
- rendered pages, crops, evaluation outputs, and temporary local data under `data/`
- Playwright `test-results/` and reports
- local/private PDFs, Office files, images, and generated document artifacts

Tracked synthetic fixtures, if any, must remain tiny and clearly non-private.

## Not implemented yet

This baseline does not provide:

- encryption at rest;
- robust multi-tenant production isolation;
- a formal retention policy;
- audit-grade compliance;
- production privacy/legal review;
- external teacher production deployment approval.

Before any real teacher/private-document rehearsal, the founder must explicitly approve the exact documents, scope, and maximum number of pages/regions to be processed.
