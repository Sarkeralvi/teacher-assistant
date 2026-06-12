# Non-Synthetic Data Policy

Custom Controlled V0 is founder-demo ready with synthetic data only. External teacher pilot use is blocked until this policy is approved and implemented operationally.

## Scope

Non-synthetic data includes any real student script, answer image/PDF, page crop, student name, student identifier, school/class metadata, teacher-uploaded assessment containing real student work, or exported grade workbook derived from real submissions.

## Current status

- Synthetic/demo data: allowed for founder-supervised demos.
- Real student data: not allowed yet.
- External teacher pilot: not allowed yet.
- Public launch: not allowed.

## Approval gate for any real data

Before any non-synthetic data enters the system, the founder must approve all of the following in writing:

1. exact teacher/pilot cohort
2. exact assessment(s)
3. exact allowed file types
4. maximum number of scripts/pages
5. data owner/contact
6. retention window
7. deletion date or deletion trigger
8. provider/model usage permission, if any
9. export recipient(s)
10. incident contact and stop condition

If any item is missing, treat the data as not approved.

## Minimum handling rules

- Store real data only in the configured app storage root, never in git.
- Never commit scripts, crops, exports, provider prompts, provider outputs, screenshots, or real identifiers.
- Use least-privilege teacher access: a teacher may view only their own courses/assessments/submissions/exports.
- Keep GradeSuggestions as draft assistance only; do not represent them as final grades.
- Do not call a provider/model unless the teacher/founder explicitly authorized that exact assessment and call scope.
- Do not use mock/batch grading in a real pilot.
- Do not use AI/OCR mapping on real scripts unless separately approved.

## Required before external pilot

- Authenticated teacher sessions for all review/export paths.
- Owner checks on all course/assessment/review/export endpoints.
- Data deletion runbook tested on a disposable non-sensitive fixture.
- Provider usage policy accepted by founder and teacher.
- Export safety check confirms approved FinalGrades only.
- DB reset/destructive test commands removed from demo/operator commands.

## Stop conditions

Stop the pilot immediately if:

- data is uploaded without approval scope
- cross-teacher access is observed or suspected
- provider calls happen outside approved single-packet scope
- GradeSuggestion is treated as final grade
- export includes draft/unapproved rows
- deletion cannot be verified
- DB reset/destructive test command is run against demo data

## Current blocker classification

Critical blockers before external pilot:

- authenticated owner enforcement must cover all review/export/final-grade endpoints
- privacy/retention/deletion workflow must be operationally approved and tested
- DB-resetting tests must be clearly separated from demo/operator commands
