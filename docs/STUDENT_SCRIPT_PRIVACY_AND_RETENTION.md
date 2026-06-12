# Student Script Privacy and Retention

This document defines the privacy and retention guardrails required before any external teacher pilot uses real student scripts.

## Status

Real student scripts are not approved for current Custom Controlled V0 demos. Founder demos must use synthetic/demo data only.

## Data classes

| Data class | Examples | Pilot status |
|---|---|---|
| Student work | scanned scripts, PDFs, crops, answer regions | blocked until approved |
| Student identifiers | names, roll numbers, registration numbers, class metadata | blocked until approved |
| Assessment content | question papers, model answers, rubrics | allowed only if teacher/founder approved |
| AI/provider artifacts | prompts, contexts, raw responses, GradeSuggestions | blocked unless provider policy approved |
| Final records | approved FinalGrades and export workbooks | allowed only after teacher approval |

## Storage rules

- Store uploaded scripts and crops under the configured local storage root only.
- Never place real student files under source-controlled paths.
- Never commit real scripts, crops, screenshots, exports, logs, prompts, raw provider JSON, or identifiers.
- Keep generated crops/evidence packets covered by the same retention window as source scripts.
- Keep exports under teacher-controlled download/handling only; do not commit or share through repo artifacts.

## Retention rules

Default until a pilot-specific agreement exists:

- Real student source files: delete within 7 days after pilot review, or sooner on teacher/founder request.
- Crops/segments/evidence packets: delete with the source files.
- Draft GradeSuggestions/provider artifacts: delete with the assessment unless explicit audit retention is approved.
- Approved FinalGrades: retain only for the agreed teacher/pilot audit period.
- Synthetic demo data: may be kept for reproducible demos, but must remain clearly labeled synthetic.

## Deletion requirements

A deletion operation must remove or verify removal of:

- submissions
- submission pages
- answer regions
- answer region segments/crops
- GradeSuggestions
- GradingJobs
- FinalGrades
- grading queues/evidence prep runs associated with the assessment
- uploaded files and generated artifacts
- exports stored on disk, if any

Deletion report must include:

- assessment id
- submission count deleted
- file/artifact paths deleted or missing
- GradeSuggestion/FinalGrade/GradingJob counts before and after
- unresolved deletion errors

## Access requirements

- Teachers may access only their own courses, assessments, submissions, review queues, final grades, and exports.
- Admin/founder access, if added, must be explicit and audited.
- Unauthenticated review/export access is not acceptable for external pilot.
- Payload-supplied `teacher_id` must not override authenticated identity.

## Provider privacy requirements

Before any provider/model use with real student scripts:

- founder approves the exact provider and model
- teacher approves use of provider assistance
- exact packet count/call count is bounded
- provider prompt/context excludes unnecessary identifiers
- provider response is stored as draft GradeSuggestion only
- raw provider output is not exported to teacher final-grade spreadsheets

## Current audit finding

External pilot remains blocked until privacy/retention operations are approved and ownership enforcement covers all review/export/final-grade routes. Existing synthetic demo records are acceptable only for founder demos.
