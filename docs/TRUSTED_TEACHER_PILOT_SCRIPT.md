# Trusted Teacher Pilot Script

## Purpose

Show the current Teacher Assistant prototype to one trusted teacher and collect practical workflow feedback before deciding the next build step.

## What this product is

Teacher Assistant is a teacher-controlled grading workflow prototype. It helps a teacher organize courses, assessments, questions, rubrics, uploaded submissions, answer regions, AI/mock grade suggestions, final review decisions, and XLSX export.

The current app is designed around this principle:

> AI may suggest; the teacher decides the final grade.

## What this product is not yet

This is not yet a production classroom system. It is not yet:

- a fully validated AI grading engine
- a student portal
- an LMS integration
- an institutional deployment
- a payment-ready product
- an automatic question-paper understanding system
- a voice-command product
- a replacement for teacher judgment

## Current demo limitations

During the pilot demo, explain these limitations clearly:

- Question and rubric setup is manual.
- Answer-region selection is manual.
- Browser demo grading uses mock grading only.
- AI grading quality is not the focus of this demo.
- Teacher approval is always required before final grades are exported.
- Security, privacy, deployment, and institutional controls are not final.
- Question-paper image/PDF import and voice commands are future ideas only.

## Mock grading explanation

The browser demo uses mock grading so the teacher can evaluate the workflow safely without judging unfinished AI accuracy.

Mock grading means:

- no real Codex or external AI grading call is made from the browser demo
- generated suggestions are placeholders for workflow testing
- every suggestion still requires teacher review
- the teacher can approve, edit, or reject suggestions

## Codex CLI backend integration explanation

The backend has a Brain Adapter design that can route grading through providers, including a Codex CLI provider path developed for controlled backend use.

For this trusted-teacher browser demo:

- Codex CLI grading is disabled
- batch real-provider grading is disabled
- the browser flow stays mock-only
- the pilot is about workflow usefulness, review control, and product direction, not final AI grading quality

## Demo setup reminder

Before starting:

- Use non-sensitive demo data only.
- Do not upload real student data.
- Confirm the teacher understands this is a prototype.
- Keep the “Mock grading only. No real Codex calls.” warning visible.

## Step-by-step teacher demo flow

1. **Register/login**
   - Create or log in as a teacher account.
   - Point out that the app now has a teacher identity/session flow.

2. **Create course**
   - Create a simple demo course.
   - Example: `Physics Demo Course` or `English Quiz Demo`.

3. **Create assessment**
   - Create one assessment under the course.
   - Example: `Quiz 1`.

4. **Create question/rubric manually**
   - Add one question.
   - Add a simple rubric manually.
   - Explain that question-paper image/PDF import is planned but not implemented yet.

5. **Upload multiple submissions**
   - Upload several demo PDF/image submissions.
   - Use non-student sample files only.

6. **Create answer regions manually**
   - Manually create answer regions for the uploaded submissions.
   - Ask whether this is acceptable temporarily or too much work.

7. **Batch mock grade**
   - Use batch mock grading from the review workflow.
   - Explain again that this does not call real Codex/AI in the browser demo.

8. **Select all visible suggested items**
   - Use the “Select all visible suggested items” control.
   - Show that only suggested, not-finalized items are selectable.

9. **Approve selected**
   - Click “Approve selected”.
   - Show the batch approval result summary.
   - Explain that the teacher chooses what gets approved.

10. **Review/edit/reject individual items if needed**
    - Open individual review items.
    - Show approve, edit, and reject options.
    - Ask whether this level of control feels sufficient.

11. **Export XLSX**
    - Export final grades.
    - Open or describe the exported spreadsheet.
    - Ask whether the format matches what the teacher needs.

## What the teacher should focus on

Ask the teacher to judge the workflow, not unfinished AI quality.

Focus areas:

- Is the workflow useful?
- Does it reduce grading workload?
- Is the review burden acceptable?
- Does teacher-controlled final approval build trust?
- Is selected batch approve useful?
- Is selected batch approve risky?
- Is the export format useful?
- Is manual answer-region mapping acceptable temporarily?
- Would question-paper image/PDF import be valuable?
- Would voice command support help?
- What would block real classroom use?

## What the teacher should not judge yet

Do not ask the teacher to judge:

- final AI grading accuracy
- production security readiness
- student portal quality
- LMS integration
- institutional deployment readiness
- payment readiness

## Closing questions

End the pilot by asking:

1. Would you want to try this with a small real assignment after privacy/security safeguards are ready?
2. What is the single biggest blocker?
3. What is the single most useful part?
4. What should be built next?
