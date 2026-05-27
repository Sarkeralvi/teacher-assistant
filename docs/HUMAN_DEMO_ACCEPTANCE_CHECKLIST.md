# Human Demo Acceptance Checklist

Manual browser checklist for deciding whether the current Teacher Assistant app is demo-ready.

Use this checklist after the local stack is running and healthy. Record pass/fail directly in a copy of this file or in the demo notes.

## Scope and rules

- Browser app: `http://localhost:3000`
- Use synthetic/demo data only. Do not upload real student work.
- Browser grading path is **mock grading only**.
- Do **not** run real Codex grading during this checklist.
- Do **not** start TA-W1-027 until this checklist has a final decision.

## Known limitations to disclose during the demo

- [ ] Mock grading only in browser.
- [ ] Real Codex backend is integrated but is not the browser default.
- [ ] Auth is basic/dev-ready, not production-grade.
- [ ] Answer regions are created manually by crop coordinates.
- [ ] No OCR.
- [ ] No automatic answer detection.
- [ ] No student portal.

## Demo data examples

Use values like these to keep the demo repeatable:

- Teacher name: `Demo Teacher`
- Teacher email: `demo.teacher+<date>@example.com`
- Password: `demo-password-123`
- Course code: `DEMO-101`
- Course title: `Demo Teacher Assistant Course`
- Department: `Demo Department`
- Semester: `Spring 2026`
- Assessment title: `Demo Midterm Review`
- Assessment type: `quiz`
- Total marks: `10`
- Question number: `1`
- Question text: `Explain the steps in the mock grading workflow.`
- Model answer: `Upload a submission, create an answer region, run mock grading, review the suggestion, and export final grades.`
- Rubric total marks: `10`
- Rubric criteria:
  - `workflow` / `Workflow steps` / max marks `6`
  - `clarity` / `Clarity` / max marks `4`
- Student identifiers:
  - `STU-001`
  - `STU-002`
  - `STU-003`
- Student names:
  - `Demo Student One`
  - `Demo Student Two`
  - `Demo Student Three`
- Upload file: a small synthetic JPG/PNG/PDF containing a few lines of fake answer text.
- Example crop coordinates if the image is roughly 600x300:
  - `x=10`
  - `y=10`
  - `width=350`
  - `height=180`

## Pre-flight

- [ ] App is running at `http://localhost:3000`.
- [ ] Backend health is OK at `http://localhost:8000/health`.
- [ ] Browser is a normal human-visible browser window.
- [ ] No real Codex grading has been enabled for this run.
- [ ] Synthetic upload file is ready.

If failed, screenshot:
- Browser error page or failed health response.
- Terminal/service error if visible.

## Browser flow checklist

### 1. Register or login

1. Open `http://localhost:3000`.
2. Go to `Register`.
3. Register a demo teacher using the demo data above.
4. Confirm the UI shows the current teacher in the header.
5. If the teacher already exists, go to `Login` and login with the same credentials.

Pass/fail:
- [ ] Pass — teacher can register or login.
- [ ] Pass — current teacher is visible in the header.
- [ ] Pass — logout/login navigation is understandable.
- [ ] Fail — teacher cannot register.
- [ ] Fail — teacher cannot login.
- [ ] Fail — current teacher is not visible after auth.

What to screenshot if failed:
- Register/login form with the error message.
- Header area after login/register.
- Browser console only if an obvious frontend error is visible.

Stop condition:
- Stop if teacher cannot login.

### 2. Create a course

1. Go to `Courses`.
2. Create a course with the demo course data.
3. Confirm the course appears in the course list.
4. Open the course detail page.

Pass/fail:
- [ ] Pass — course can be created without entering a raw `teacher_id`.
- [ ] Pass — course appears in the list.
- [ ] Pass — course detail page opens.
- [ ] Fail — course creation fails.
- [ ] Fail — course does not appear after creation.

What to screenshot if failed:
- Course form with entered values.
- Any error message.
- Course list after submit.

### 3. Create an assessment

1. On the course detail page, create an assessment.
2. Use the demo assessment title/type/marks.
3. Open the assessment detail page.

Pass/fail:
- [ ] Pass — assessment can be created.
- [ ] Pass — assessment appears under the course.
- [ ] Pass — assessment detail page opens.
- [ ] Fail — assessment creation fails.
- [ ] Fail — assessment is missing from the course page.

What to screenshot if failed:
- Assessment form and error message.
- Course detail page after submit.

### 4. Create a question and rubric

1. On the assessment detail page, create the demo question.
2. Open the question detail page.
3. Create an active rubric with the demo criteria.
4. Confirm the rubric is shown and marked active.

Pass/fail:
- [ ] Pass — question can be created.
- [ ] Pass — rubric can be created.
- [ ] Pass — rubric criteria and total marks are understandable.
- [ ] Fail — question creation fails.
- [ ] Fail — rubric creation fails.
- [ ] Fail — rubric editor is confusing or misleading.

What to screenshot if failed:
- Question form and error message.
- Rubric editor with entered criteria.
- Any validation message.

### 5. Upload submissions

1. Return to the assessment detail page.
2. Upload at least one synthetic JPG/PNG/PDF submission.
3. Prefer uploading three submissions for batch-review confidence.
4. Confirm each uploaded submission appears in the submissions list.
5. Open at least one uploaded page image link.

Pass/fail:
- [ ] Pass — JPG/PNG/PDF upload works.
- [ ] Pass — uploaded submission appears once, not duplicated.
- [ ] Pass — page image link opens.
- [ ] Fail — submission upload fails.
- [ ] Fail — uploaded file does not appear.
- [ ] Fail — upload creates duplicates from one click.
- [ ] Fail — page image cannot be opened.

What to screenshot if failed:
- Upload form with selected file name.
- Error message after upload.
- Submissions list after upload.
- Broken page image response if image link fails.

Stop condition:
- Stop if submission upload fails.

### 6. Create answer regions manually

1. In the assessment detail page, choose an uploaded submission page.
2. Select the demo question.
3. Enter crop coordinates.
4. Click `Create answer region`.
5. Confirm the cropped image link appears.
6. Repeat for each uploaded submission if testing batch flow.

Pass/fail:
- [ ] Pass — answer region can be created.
- [ ] Pass — cropped image opens and shows the intended area.
- [ ] Pass — multiple answer regions can be created for multiple submissions.
- [ ] Fail — answer region cannot be created.
- [ ] Fail — crop validation is unclear.
- [ ] Fail — cropped image is missing or wrong.

What to screenshot if failed:
- Page/question/crop coordinate fields.
- Error message after creating the region.
- Cropped image result or broken image page.

Stop condition:
- Stop if answer region cannot be created.

### 7. Run browser mock grading

1. Go to the assessment review page from `Review & export final grades`.
2. Confirm the warning says mock grading only / no real Codex calls.
3. Click `Batch mock grade ungraded answers`.
4. Confirm the batch result shows graded/skipped/failed counts.
5. Confirm review cards show mock/suggested scores and `needs_review`.

Pass/fail:
- [ ] Pass — mock-only warning is visible.
- [ ] Pass — batch mock grading succeeds.
- [ ] Pass — graded count matches the number of ungraded answer regions.
- [ ] Pass — suggestions are clearly not final grades.
- [ ] Fail — mock grading fails.
- [ ] Fail — UI suggests real Codex ran in the browser path.
- [ ] Fail — suggestions appear final without teacher review.

What to screenshot if failed:
- Review page before clicking batch grading.
- Batch result panel.
- Any error message.
- One review card showing the grading status.

Stop condition:
- Stop if mock grading fails.

### 8. Filter and inspect review queue

1. Use the review queue filter.
2. Check `All statuses`, `suggested`, `ungraded`, and `finalized`.
3. Confirm the cards are scannable: student identifier, question number, status label, mock score, final score if finalized.
4. Use `Next item to review` if visible.
5. Open a cropped answer image from a review card.

Pass/fail:
- [ ] Pass — filters are understandable.
- [ ] Pass — suggested items appear after mock grading.
- [ ] Pass — empty filters show a clear empty state.
- [ ] Pass — cropped image links open from review cards.
- [ ] Fail — filter counts/statuses are confusing.
- [ ] Fail — review cards are not enough for a teacher to inspect.

What to screenshot if failed:
- Filter dropdown state.
- Review card with status label.
- Empty filter state.
- Cropped answer image link/result.

### 9. Approve, edit, and reject final grades

For at least one suggestion:

1. Add an optional teacher comment.
2. Click `Approve AI suggestion`.
3. Confirm the item becomes finalized/approved.

If there are multiple suggestions, also test:

4. Change final score and click `Edit score and save final grade`.
5. Click `Reject suggestion` on another item.
6. Confirm the summary counts update.

Pass/fail:
- [ ] Pass — approve works.
- [ ] Pass — edit score works.
- [ ] Pass — reject works.
- [ ] Pass — finalized status and summary counts update.
- [ ] Pass — logged-in teacher remains required/visible.
- [ ] Fail — approve fails.
- [ ] Fail — edit fails.
- [ ] Fail — reject fails.
- [ ] Fail — final grade state is unclear.

What to screenshot if failed:
- Review action area before clicking.
- Error message after action.
- Current FinalGrade panel.
- Assessment summary counts.

Stop condition:
- Stop if approve/edit/reject fails.

### 10. Export XLSX

1. Ensure at least one final grade exists.
2. Click `Export final grades (.xlsx)` or `Download final grades (.xlsx)`.
3. Confirm the `.xlsx` file downloads.
4. Open the workbook.
5. Confirm it contains the reviewed final-grade row(s).
6. Confirm no unsafe internals are visible, such as password hashes or raw provider JSON.

Pass/fail:
- [ ] Pass — XLSX downloads.
- [ ] Pass — workbook opens.
- [ ] Pass — reviewed final grades are present.
- [ ] Pass — no password hashes or raw provider JSON are present.
- [ ] Fail — export fails.
- [ ] Fail — workbook does not open.
- [ ] Fail — expected final-grade rows are missing.
- [ ] Fail — unsafe internals appear in export.

What to screenshot if failed:
- Export button area.
- Browser download failure.
- Opened workbook or error dialog.
- Missing/unsafe workbook columns if visible.

Stop condition:
- Stop if export fails.

## Stop conditions summary

Stop the demo-readiness pass immediately if any of these occur:

- [ ] Teacher cannot login.
- [ ] Submission upload fails.
- [ ] Answer region cannot be created.
- [ ] Mock grading fails.
- [ ] Approve/edit/reject fails.
- [ ] Export fails.

If a stop condition occurs, record:

- Failed step number.
- Exact user action before failure.
- Screenshot(s).
- Browser URL.
- Visible error text.
- Whether refresh/retry changed the result.

## Final decision section

### Demo-ready internally?

- [ ] Yes
- [ ] No
- Notes:

### Ready to show one trusted teacher?

- [ ] Yes
- [ ] No
- Notes:

### Must-fix issues before teacher demo

List blockers only. If none, write `None`.

1.
2.
3.

## Next task recommendation

- If any stop condition or serious UX blocker fails: `TA-W1-027A: fix acceptance blockers`.
- If the checklist passes and only minor/non-blocking notes remain: `TA-W1-027B: prepare teacher pilot script`.
