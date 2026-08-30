# Bulk Supervised Evaluation

Bulk Supervised is the exception-first cohort workflow built on the existing
Qwen3.8 granular pipeline. It does not enable Semi-Automated or Fully
Automated grading.

## Teacher workflow

1. Open the assessment's **Prepare references** page and finalize the question,
   model answer, and active rubric for every grading unit.
2. Return to the assessment and choose **Evaluate a ZIP of scripts**.
3. Upload either one root PDF per student or one top-level folder per student
   containing naturally ordered images. An optional `manifest.csv` can provide
   `source`, `student_identifier`, and `student_name`.
4. Confirm the local-only, strict-auto-pass, draft-only authorization and start
   the run. Qwen3.8 starts on this explicit action when it is not already loaded.
5. The browser may be closed. Mapping, transcription, verification, and draft
   grading continue as durable one-call RQ jobs.
6. Review the exception inbox. Use **Inspect manuscript** only for ambiguous,
   incomplete, unreadable, or interrupted items, then explicitly resume that
   item.
7. Approve the exact clean-draft snapshot. This teacher action is the only step
   that creates final grades.
8. Download the workbook. A student with any unresolved item is marked
   `INCOMPLETE`; no misleading total is emitted.

## Safety contract

- Qwen3.8 is the only active model. Calls are sequential and lease-protected.
- No provider fallback or automatic provider retry exists.
- Policy verification is recorded as `bulk_policy`; it never impersonates
  teacher confirmation.
- Blank, unreadable, truncated, low-confidence, contradictory, or interrupted
  evidence receives no silent score.
- Raw answer text is absent from audit logs and aggregate exports.
- Student images are never sent to the grading call.
- Every grade is a pending suggestion until exact-snapshot teacher approval.

## ZIP limits

- 50 submissions, 500 pages, 1 GiB archive, and 1,000 entries.
- Root images, nested student folders, mixed PDF/image folders, duplicate
  identifiers, encrypted entries, unsafe paths, and unsafe compression ratios
  are rejected before submissions are created.
- Re-uploading the same active archive/reference pair returns the existing run.

## Recovery

Stop takes effect after the current provider call. Resume processes only work
that never started. If a worker heartbeat expires during a call, that item is
marked `uncertain`; the teacher must inspect and explicitly resume it. The
system never guesses whether the interrupted call completed.
