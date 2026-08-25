# Supervised Teacher Rehearsal

This rehearsal proves the Custom Controlled workflow end to end. It is not unattended marking. Every extraction, mapping, transcript, and grade remains a draft until the teacher performs its specific confirmation.

## Prerequisites

- Reviewed commit and clean worktree.
- Backend tests/Ruff, migrations, frontend checks/build, sidecar tests, and PowerShell parser checks pass.
- PostgreSQL, Redis/RQ, backend, worker, and frontend are healthy.
- The exact question, solution/model-answer, rubric, and small complete script are teacher approved.
- No previous draft/job/final grade exists for the rehearsal assessment.
- `COHORT_MODEL_GRADING_ENABLED=false`.

Start the host stack; this must not start a local model:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Start-TeacherPilot.ps1 -RebuildFrontend
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll
```

Run all three local preflights from `docs/LOCAL_AI_RUNBOOK.md`.

## Rehearsal sequence

1. Start a Custom Controlled run.
2. Upload question, solution/model-answer, and rubric once.
3. Authorize local draft extraction. The managed worker must run PaddleOCR first and Qwen3.6 second.
4. Compare every extracted question, solution, mark, and rubric criterion with the source. Confirm only accurate canonical references.
5. Upload one complete answer script. Do not crop answers.
6. Choose **Prepare scripts locally**. Review every Paddle-derived region and continuation, then confirm geometry only.
7. Choose **Create direct PaddleOCR transcript** for one confirmed region. Compare the exact displayed draft with the source image.
8. If faithful, confirm its hash. If not, reject it and choose **Request Qwen3.8 vision rescue**. Confirm a rescue only if it is verbatim; otherwise stop and upload a clearer page.
9. Separately confirm the displayed image contains the full answer.
10. Choose **Grade confirmed answer with local Qwen**. Qwen3.6 must receive text only and create one pending draft suggestion.
11. Review and approve, edit, or reject the suggestion manually.
12. Export approved-only XLSX and verify pending/rejected rows are absent.

Record assessment/submission/question/region/run/job IDs, commit hash, source/evidence/rubric hashes, each provider/model, phase order, call counts, teacher decision, and export result. Do not copy raw student text into audit notes.

## Required observations

- PaddleOCR, Qwen3.6, and Qwen3.8 are never resident concurrently.
- Normal references and mapping make zero Qwen3.8 calls.
- Qwen3.8 runs only after a teacher rejection and explicit rescue action.
- Mapping confirmation does not confirm transcript text.
- Transcript confirmation does not confirm full-answer coverage.
- Grading stays disabled until both evidence gates pass.
- No retry/fallback/cloud call occurs.
- No `FinalGrade` appears before teacher approval.

Any violation is a failed rehearsal. A successful rehearsal is necessary but does not replace the signed curated quality evaluation required for a broader teacher pilot.
