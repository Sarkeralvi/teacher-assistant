# Supervised Teacher Rehearsal

This is a founder/teacher-supervised rehearsal for the Custom Controlled
workflow. It is not unattended marking. Every model output remains a draft;
the teacher is the only actor who may confirm evidence, approve a grade, or
create a `FinalGrade`.

The active local design is:

1. RapidOCR reads printed reference pages first; Qwen3.8 vision reads only
   escalated reference pages without thinking; Qwen3.6 correlates question,
   solution, and rubric drafts.
2. Qwen3.8 vision maps complete handwritten script pages and performs a fresh,
   non-thinking, verbatim visual transcription of each teacher-confirmed answer
   region. Teachers do not crop or type a replacement transcript.
3. The selected local text grader receives only the final question, model
   answer, active rubric, marking policy, and teacher-confirmed transcript.
   It never receives student images.
4. A Qwen3.6/Qwen3.8 model lease is mandatory before every inference request.
   A busy, missing, or mismatched lease fails before the request is sent.

PaddleOCR is retired from active teacher workflows. Historical records remain
readable but are not silently upgraded or approved.

## Prerequisites

Do not begin the rehearsal until all are true:

- Git is clean and the reviewed commit is recorded.
- Backend tests, Ruff, migrations, frontend checks, and PowerShell parser
  checks pass for that commit.
- The 20-case source evaluation has a signed `PASS`, not merely a working UI.
- The text-grader bake-off has a signed report recommending Qwen3.6 or Qwen3.8.
- The teacher has approved the exact rehearsal materials and understands that
  a non-faithful visual transcription blocks grading rather than being edited.
- The pilot host stack is healthy and no unexpected prior draft, job, or final
  grade exists for the rehearsal assessment.

Run the Windows host preflight from the repository root:

```powershell
git status --short
git rev-parse HEAD
.\scripts\pilot\Start-TeacherPilot.ps1 -RebuildFrontend
.\scripts\pilot\Get-TeacherPilotStatus.ps1
.\scripts\local-ai\Test-LocalAiPreflight.ps1 -Mode Qwen38
```

Start Qwen3.8 only immediately before a visual stage. The app itself must not
start a model:

```powershell
.\scripts\local-ai\Start-LocalAi.ps1 -Mode Qwen38
```

## Teacher workflow

Use one small, teacher-approved rehearsal assessment first. Upload the question
paper, solution/model answer, and rubric once in the reference-material step.
Do not upload the same file again in separate legacy panels.

### 1. Prepare and confirm references

1. Start one Custom Controlled run.
2. Upload question, solution/model-answer, and rubric files once.
3. Authorize local reference extraction.
4. Wait for the persistent progress state. Do not refresh/re-submit to retry.
5. Review every draft question, model answer, mark allocation, and rubric
   criterion against the original source material.
6. Confirm the canonical references only when accurate. Any uncertain/missing
   solution or rubric blocks grading.

Reference extraction is draft-only. It is not evidence that the final grading
configuration understands a student answer.

### 2. Prepare complete answer scripts

1. Upload the complete answer script once. Do not crop individual answers.
2. Choose **Prepare mappings with local Qwen3.8**.
3. Review the full-page mapping previews. Confirm each question-to-region
   mapping only if it covers the complete visible answer, including any
   continuation page.
4. If unassigned ink or a missing question warning appears, stop and correct
   the source script/mapping before transcription. Do not grade a partial
   region.

### 3. Confirm verbatim visual evidence

For each confirmed region:

1. Choose **Draft text with local Qwen3.8**.
2. Compare the displayed transcript with the displayed source image.
3. Confirm the exact hash-pinned transcript only when it faithfully preserves
   the student’s actual writing, including mistakes, decimals, fractions,
   complement/intersection notation, units, and crossed-out work.
4. Separately confirm that the displayed image/segments contain the complete
   answer.

If any critical text is wrong, choose **Reject transcription**. Grading must
remain blocked. The fallback is a clearer complete-page upload, not a manual
crop or a teacher-written student answer.

### 4. Create one local grading draft

Only after both the mapping and full-answer evidence gates are confirmed:

1. Verify the active rubric and canonical model answer are still visible.
2. Verify the local status badge identifies the recommended text model and
   shows it is available.
3. Choose **Grade confirmed answer with local Qwen** for one answer region.
4. Watch the persistent job state; it must remain a single draft suggestion.
5. Inspect the provider/model label, score, criterion breakdown, confidence,
   review flags, and evidence hash.

The result must contain `needs_review`, `teacher_review_required`,
`image_input_disabled`, and `local_provider`. It must have no `FinalGrade`.

### 5. Teacher review and export

1. Review and, if needed, edit the draft score/comment.
2. Explicitly approve or reject it.
3. Confirm a `FinalGrade` appears only after approval.
4. Export approved-only XLSX and verify that unapproved drafts do not appear.

## Cohort rehearsal (only after the one-answer run succeeds)

Use at most two synthetic/approved packets. The teacher must explicitly create
the queue, inspect question-wise preflight, choose the provider/model, set a
call limit no higher than 25, and confirm draft-only execution. Dispatch is
sequential and stops on the first provider failure. Stop requests prevent the
next call but do not interrupt the current call.

Do not enable cohort model grading in normal pilot configuration merely to run
this rehearsal. Use the reviewed, explicitly authorized configuration and
record its call cap, provider/model, and queue/grading-run IDs.

## Hard stop conditions

Stop the rehearsal and report the result if any of the following occurs:

- local service is unavailable, has a model alias mismatch, or is not
  loopback/managed;
- a model starts automatically from page load or app startup;
- lease acquisition fails, a model phase changes under another active job, or a
  provider call is retried/falls back;
- mapping is incomplete, unassigned ink is reported, or continuation is
  unresolved;
- the visual transcript is non-faithful, blank content is hallucinated, or a
  teacher would need to type/crop a repair;
- references, evidence, or rubric hashes change after confirmation;
- an unconfirmed transcript or student image reaches the text grader;
- a draft is automatically approved/finalised, or export includes a draft;
- a cross-teacher access check fails.

## Rehearsal record

Record only IDs, hashes, provider/model names, call counts, timing, teacher
sign-offs, and export row counts. Do not record raw student text, local paths,
API keys, or source image data in chat, Git, audit payloads, or the rehearsal
summary.
