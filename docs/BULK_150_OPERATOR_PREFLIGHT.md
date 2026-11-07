# Bulk Supervised: 150-student operator preflight and review protocol

- Recorded at: 2026-10-11; updated 2026-10-12 after the fix wave (see "Purpose and status")
- Baseline: branch `rescue/paddle-qwen36-hybrid`, HEAD `8a25268` plus the uncommitted fix-wave diff in the working tree (4 production files, nothing committed)
- Companion document: `docs/BULK_150_READINESS.md` (defect register and the strict GO/NO-GO gate in its section 8)
- Subject: one controlled run of about 150 student scripts through the existing Bulk Supervised ZIP workflow, one provider call at a time
- Verdict: **NO-GO** (2026-10-11, unchanged on 2026-10-12)

This checklist describes what the code and the probes show actually happens at `8a25268` plus the
fix-wave diff. Where it disagrees with `docs/BULK_SUPERVISED_RUNBOOK.md`, this document is the one
built from tests.

## Purpose and status

**Status: NO-GO as of 2026-10-11, unchanged on 2026-10-12.** The system is not ready for a real
150-student run. This checklist is for the founder-supervised rehearsal, and for a later real run
only after the unmet gates in `docs/BULK_150_READINESS.md` are closed. Following it does not make
an unready system ready. Every step below that depends on a known defect says so and names the test
that proves it.

**Update, 2026-10-12 (after the fix wave).** This checklist was revised after three waves of fixes
that changed four production files (about 400 lines, each tied to a strict-xfail or a new regression
test) and the tests. There is no migration, no config, default or limit change, no dependency, and no
change to approval semantics, thresholds or `COHORT_MODEL_GRADING_ENABLED`. What changed for the
operator:

- Several "accepted silently, check by hand" intake items are now refused with a named message (B.2).
- Some failure states behave differently, and a few workarounds changed (C.3, C.5, D.3, D.4).
- Intake now refuses ZIPs that were accepted before: duplicate member names, a second `manifest.csv`, a
  file and a folder with one name, a manifest row with a non-empty surplus cell (B.2), and an authorised
  call limit below pages + items (B.3). A re-upload of an active archive now only returns the existing
  run: it enqueues nothing and is not a recovery action (C.3).
- Mid-run reference edits now pause the run instead of being graded silently (A.7, D.3).

The verdict stays **NO-GO**. The fix wave closed many defects, but the five gates below are unchanged,
and high-severity defects remain open. The approval wave (RC-01 to RC-05: stale review hash after one
per-item finalisation, a run stuck in `review_ready`, a non-atomic approve-clean, a superseded draft
offered as clean, a refusal that names no draft) was deliberately not fixed: it changes approval-path
behaviour and needs founder review first. The per-item approve and approve-selected routes remain the
working workaround (D.3 rows 8 to 10). 47 strict-xfail cases remain, each a proven defect that still
exists (final run on 2026-10-12: 1188 passed, 13 skipped, 47 xfailed, 0 failed; see the evidence
index). Nothing here makes the system ready.

Five gates cannot pass without a founder decision or an authorised model call. Engineering work
alone does not close them. All five are **unchanged** by the fix wave:

| # | Gate item | Why it stays open | Evidence |
|---|---|---|---|
| 1 | Real-model wall-clock is unmeasured | Every capacity number was measured with an in-process fake provider, so it is pipeline overhead only. 600 page reads plus 900 gradings on one llama.cpp slot dominate the real time and were never timed. Closing this needs an authorised, bounded, timed model run. | `test_bulk150_scale.py::test_headline_150_students_x_4_pages_x_6_questions` (PE-1, measures overhead only); PE unprobed item 1 |
| 2 | The bulk path skips the CPU ink-coverage check | A block the model silently omits reaches a clean graded draft with no code and no warning (PC-1). A page falsely called blank in the middle of an answer is accepted (PC-1b). The fix, and the threshold calibration on real scans, need real scans and a founder decision on the extra teacher work false positives add. | `test_bulk150_evidence.py::test_a_block_the_model_omitted_leaves_a_signal_before_grading` (strict xfail) |
| 3 | Mid-call kill recovery | A worker killed between `reserve_page` and its result leaves the page `dispatched`; since 2026-10-13 (wave C) Resume turns a claim older than max(900 s, the job timeout) into `unknown_outcome`, the reconcile route settles it, and a second Resume re-reads only that page (RC-37 fixed). After a hard kill mid-grade the `GradingJob` no longer blocks the answer for good, but the retry waits until the dead worker's lease expires (up to 1,800 s after the last heartbeat for the managed-local pilot, up to 3,600 s for an unmanaged provider); since 2026-10-12 the pause names the student and question and says when to resume, instead of a raw `UniqueViolation` text, and a job still `queued` (it never reached the provider) is closed at once (D.3 row 13). A kill between the two commits that create and link a job can still leave an unlinked active job that blocks that answer permanently (D.4 DE-5). True `kill -9`, RQ job timeouts and a second worker were not exercised. | `test_bulk150_harness_smoke.py::test_a_killed_worker_can_be_recovered_by_a_teacher` (passes since wave C); `test_bulk150_recovery.py::test_w11_a_hard_killed_managed_job_stays_open_until_its_lease_expires` (pins the wait); PB unprobed (a)(d) |
| 4 | Call-budget exhaustion is a dead end | When the authorised call limit is spent with work left, resume refuses, the limit cannot be raised, a new run is impossible, nothing is approvable and the export is 409 (PB-7a, PE-9). The fix wave only mitigates it: intake now refuses a limit below pages + items (B.3), and a run authorised for exactly its calls now finishes. Since 2026-10-13 (wave C) the teacher can raise a paused run's call limit ("I authorise this new call limit", audited `bulk_evaluation_call_limit_raised`, capped at the server ceiling) and then Resume (RC-48 fixed). | `test_bulk150_recovery.py::test_pb7_a_run_that_runs_out_of_calls_continues_after_the_teacher_raises_the_limit` |
| 5 | The workflow needs about 150 transcript reviews (the 900 per-item resume clicks are gone since 2026-10-13 (wave C)) | "Release all reviewed scripts to grading" starts grading for every script whose transcript review is confirmed, in one action, and names what it left out (RC-68 fixed). The 150 reviews remain. | `test_bulk150_scale.py::test_one_release_action_starts_grading_for_every_reviewed_script_and_only_those` |

These are founder decisions. This document records the current behaviour and never encodes a
preferred policy for any of them:

- the 720-page, 2,000-call and 180-submission ceilings;
- (decided 2026-10-12) teacher-edited final grades ARE exported as final, labelled `EDITED`; rejected drafts are labelled `REJECTED` and stay incomplete;
- (decided 2026-10-12) bulk approve requires a per-student summary and an explicit confirmation (E.7);
- the 0.80 grading-clean and 0.90 mapping/transcription thresholds;
- the workflow of about 150 transcript reviews (the resume clicks are replaced by one release action);
- whether intake should detect content-level wrong-student pages;
- whether the new intake refusal of a call limit below pages + items (B.3) stays. It is a behaviour change: an upload accepted before with a small limit is now refused. It is easy to revert (about 10 lines in `create_from_zip`);
- the reference-freeze rule (A.7, D.3). A run now pauses when the references change and there is no re-baseline path: the only ways on are to restore the edit exactly or to start a new run. Founder sign-off is recommended.

### How to use this checklist

- Tick each box only after observing the stated result yourself. Copy the observed value into section H.
- If a step cannot be confirmed, stop. Do not proceed on an assumption.
- A row marked "known defect" means the product will not protect you. The manual check is the protection.
- "Not verified" means the evidence files do not show it. Do not read it as "safe".

### Evidence keys

Probe ids (PA-, PB-, PC-, PD-, PE-) and the smoke/poison test names refer to the proven-gap tests in
`apps/api/tests/test_bulk150_*.py`. These files are untracked at `8a25268`. A test marked
"strict xfail" asserts the correct behaviour and fails today, so it is proof the defect exists. A
"pinned" test passes and records current behaviour that a founder decision may change. A
"refuted" probe is a passing regression test showing the suspected gap does not exist. Code anchors
are repo-relative path plus function name because line numbers drift while fixes land.
Re-check every "known defect" row against `docs/BULK_150_READINESS.md` after any fix lands.

After the 2026-10-12 fix wave a test marked "fixed" below was a strict xfail and now passes: it is a
regression test for a defect that no longer exists. Only the 47 test cases still marked "strict xfail"
prove a live defect. A test that was converted or renamed is cited by its current name.

## A. Before the day

### A.1 Authority and data scope

- [ ] The founder has authorised this exact bounded scope in writing: the students, the question count, the call limit and the model. Provider output is draft-only; no final grade exists without a teacher approval (verified: no code path creates a `FinalGrade` without a teacher HTTP action, PA-5 refuted).
- [ ] If the scripts are real student work: data owner, retention window, deletion path and export rules are documented before upload (`docs/BATCH_SAFE_AND_TEACHER_PILOT_GATE.md`, "Data scope"; `docs/STUDENT_SCRIPT_PRIVACY_AND_RETENTION.md`).
- [ ] A founder or approved observer is present for the run (`docs/BATCH_SAFE_AND_TEACHER_PILOT_GATE.md`, "Observation and control").
- [ ] `COHORT_MODEL_GRADING_ENABLED` is `false`. The bulk workflow does not use that flag, and it must stay `false` unless the separately documented evaluation gate is authorised.

### A.2 Machine stability

The host has a recorded, unresolved stability fault (bugchecks). Treat a reboot during a multi-hour
run as an expected event, not an edge case. Section D covers what a reboot leaves behind, and several
of those states have no in-product exit.

- [ ] Run `E:\ai\qwen-bridge\stability-watch.ps1` and read its verdict. (The script exists; its output was not captured by the analysis.)
- [ ] `scripts\pilot\Ready-TeacherAssistant.ps1` prints a bugcheck count for the last 7 days (its "Host stability" section). Zero is required to start. The script prints "A long unattended run on this host may not complete" when the count is above zero.
- [ ] Peak VRAM stays below 11,000 MiB (operator notes, not a repo document). Do not start any second model process during the run.
- [ ] Nothing else heavy runs on the machine for the duration (browsers with many tabs, another model, builds).
- [ ] No wall-clock estimate for the run exists. Do not promise one. The only measured time is pipeline overhead with a fake provider: 183 s for 150 students x 4 pages x 6 questions (final run, 2026-10-12, after the fix wave: intake 2.2 s, page-read drain 23.1 s, teacher gate 3.3 s, 900 resume calls 33.6 s, grading drain 112.3 s, approve-clean 7.9 s, export 0.4 s). The same harness measured 241 s on 2026-10-11 before the fixes; the two runs are not a controlled comparison. Real model time is in neither figure. It is the first thing the rehearsal must measure (gate item 1).

### A.3 Services and queue

Run from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireCore
```

- [ ] `PostgreSQL`, `Redis/RQ`, `Backend`, `RQ worker` and `Frontend` all show `Ready = True`. `-RequireCore` exits 1 if any is not ready.
- [ ] `-RequireAll` additionally exits 1 unless a local model phase is already loaded, and the pilot starts with the model off on purpose. A non-zero `-RequireAll` before the run is therefore expected. The model is started inside the upload request (`BulkEvaluationService._assert_enabled`, via `hold_brain_execution`). Read the table, not only the exit code.
- [ ] The status script reports no "unsafe or unmanaged local AI listener". It exits 1 when it finds one.
- [ ] Memurai Developer, the Redis-compatible queue, stops itself after ten continuous days (`docs/WINDOWS_TEACHER_PILOT_RUNTIME.md`). Note its uptime. Restart it before the day if it is near that limit; a queue loss mid-run needs a manual Resume or Recover (D.3 row 6; PB-10).
- [ ] Exactly one worker exists. The documented runtime is one sequential RQ `SimpleWorker`, which serialises units. The duplicate-grading and cross-quarantine races (PB-9a, PB-9c) were demonstrated in-process only, and true multi-process timing was not exercised. Never start a second worker.

### A.4 Freeze the sources: no edits during a run

`scripts\pilot\Start-TeacherPilot.ps1` restarts the API and the worker whenever any file under `app/`,
`packages/` or `alembic/`, or `.env`, or `.env.local-ai`, is newer than the running process. It does not
check for an active bulk run before 2026-10-13. Since 2026-10-13 (wave C) it does: while a bulk run is active it
leaves the worker and the loaded model running (it still restarts the API) unless
`-AllowRestartDuringBulkRun` is passed (RC-56). A forced restart force-kills the worker and its
descendants; the next worker start pauses any run whose heartbeat is stale with "Interrupted: the worker
stopped ..." (RC-57), and Resume continues it.

- [ ] No code, `.env` or `.env.local-ai` edit happens between the start of upload and the end of the run.
- [ ] No `git checkout`, `git pull`, `git stash` or branch switch happens during the run. They change file times.
- [ ] Other coding agents (Claude, Codex, Antigravity) are closed.
- [ ] `Ready-TeacherAssistant.ps1` calls `Start-TeacherPilot.ps1`. Treat it as a start. Do not run it during a run.
- [ ] `Stop-TeacherPilot.ps1` is not run during a run. It force-kills after a 30 s graceful deadline.

### A.5 Effective configuration

The live `.env.local-ai` and `.env` were never read by the analysis. The launcher loads
`.env.local-ai` first, then `.env`, as process environment (`scripts\pilot\Common.ps1`,
`Import-PilotEnvironment`). `Ready-TeacherAssistant.ps1` prints raw lines from those files, not the
effective values, and does not print `BULK_MAX_PAGES` or any timeout. Measure the effective values:

```powershell
# Run in a throwaway PowerShell window: it loads the pilot environment, secrets included, into this process only.
# Prints numbers and booleans only. Not executed by the author of this document (no environment access).
$repo = 'E:\teacher-assistant'
. "$repo\scripts\pilot\Common.ps1"
$paths = Get-PilotPaths
Import-PilotEnvironment -Paths $paths
Set-Location "$repo\apps\api"
& $paths.ApiPython -c "from app.core.config import get_settings; from packages.brain.profiles import legacy_profile_settings; s=get_settings(); e=legacy_profile_settings(s,'llama_cpp_qwen38'); print('bulk_max_submissions',s.bulk_max_submissions); print('bulk_max_pages',s.bulk_max_pages); print('bulk_max_archive_bytes',s.bulk_max_archive_bytes); print('bulk_max_provider_calls',s.bulk_max_provider_calls); print('cohort_model_grading_enabled',s.cohort_model_grading_enabled); print('heartbeat_stale_seconds',s.cohort_dispatch_heartbeat_timeout_seconds); print('qwen38_timeout_configured',s.local_qwen38_timeout_seconds); print('qwen38_timeout_effective',e.local_qwen38_timeout_seconds)"
```

| Setting | Code default / schema maximum | `.env.example` and old runbook | Measured under the pilot layering (2026-10-11, lead) | Needed for 150 students |
|---|---|---|---|---|
| `BULK_MAX_SUBMISSIONS` | 180 / 180 (`config.py`, `le=180`) | 50 | 180 | 150 or more |
| `BULK_MAX_PAGES` | 720 / 720 (`le=720`) | 500 | 720 | total pages in the ZIP, at most 720 |
| `BULK_MAX_ARCHIVE_BYTES` | 1 GiB | not set | 1 GiB | ZIP size |
| `BULK_MAX_PROVIDER_CALLS` | 1800 / 2000 (`le=2000`, DB CHECK) | 2000 | 2000 | more than the need in B.3, at most 2000 |
| `COHORT_MODEL_GRADING_ENABLED` | `false` | `false` | `false` | `false` |
| Heartbeat stale threshold | 600 s | 600 s | 600 s | informational (see C.5) |

- [ ] The printed values match the "needed" column. If `BULK_MAX_SUBMISSIONS` or `BULK_MAX_PAGES` is the `.env.example` value (50 and 500), 150 students are refused before any script is rendered (PE-13).
- [ ] Without `BULK_MAX_PROVIDER_CALLS` in the environment the server ceiling is 1800 while the upload form pre-fills 2000, so a default first submission is refused with "Requested provider calls exceed the bulk server ceiling" (PE-14, strict xfail). Lower the number in the form or fix the environment before the day.

**Effective per-call timeout (fixed 2026-10-13, RC-54).** The effective timeout is now
`min(LOCAL_QWEN38_TIMEOUT_SECONDS, 1500)`: the generic `BRAIN_TIMEOUT_SECONDS` no longer replaces it, and
1,500 s keeps a call shorter than the 1,800 s model lease. The A3 rehearsal (2026-10-13) measured page
reads of 28-55 s and a grading call of 78 s, so set `LOCAL_QWEN38_TIMEOUT_SECONDS=600` in `.env` unless a
real script needs more (with today's `.env` value of 1800 the effective timeout becomes 1,500 s).
History (2026-10-11): `LOCAL_QWEN38_TIMEOUT_SECONDS` was configured as 1800, but the effective timeout
for the `llama_cpp_qwen38` profile was 600 s.
`BRAIN_MODEL`, `BRAIN_API_KEY` and `BRAIN_BASE_URL` are set, so `legacy_profile_settings`
(`apps/api/packages/brain/profiles.py`) overwrites `local_qwen38_timeout_seconds` with
`BRAIN_TIMEOUT_SECONDS`, which is 600. A long page read can therefore time out at 600 s and be recorded
`unknown_outcome`. An `unknown_outcome` page is never retried automatically. The `.env` comment says
`BRAIN_MODEL` is deliberately not set, which contradicts the layered result.

- [ ] `qwen38_timeout_effective` is printed and written into section H. If it is 600, any single call longer than 10 minutes becomes an `unknown_outcome` that needs the teacher (D.3 row 4).
- [ ] Do not change the timeout, any `BRAIN_*` value or any other `.env` value during a run (A.4). Changing it is an engineering decision made before the day, with the trade-off that a longer timeout lets a hung call hold the single model slot longer.

### A.6 Disk space

Student files live under the storage root the pilot launcher sets to `data\` inside the repository
(`uploads\` and `artifacts\`). Check free space on that drive only; do not browse the folders.

Where the bytes go:

| Stage | Location | Size basis |
|---|---|---|
| Upload spool | system temp directory (framework behaviour, **not verified**) | up to 1 ZIP |
| Staged ZIP | `uploads\bulk_staging\bulk-<id>.zip` | 1 ZIP; removed when intake ends, and a partial copy is removed when the staging write itself fails (full disk). Left behind after a hard kill, or when Windows holds the file locked at deletion, and nothing logs the locked case (F.4) |
| Student originals | `uploads\submissions\<submission id>\original-*.pdf` for PDF students | about the PDF bytes, up to 1 ZIP in total |
| Rasterised pages | `artifacts\pages\submission_<id>\page_NNNN.png` | pages x size per page |
| Grading context and database growth | `artifacts\grading_context\...`, PostgreSQL | **not measured** (the 150-student fake run issued 149,998 SQL statements after the fix wave, 143,696 before it) |

Measured sizes (synthetic pages; real scans are larger):

- PDF layout: about 0.9 MiB stored per synthetic page in the ZIP (30 students gave a 105.6 MiB ZIP).
- PDF layout on disk after import: 145 pages took 262.55 MiB (PE-5 metrics), about 1.8 MiB per page for the PDF copy plus the PNG. The 0.9 MiB used for `s` below is an inference from these two measurements (about 0.9 for the PDF, about 1.8 for PDF plus PNG), not a direct measurement of the PNG.
- Image-folder layout: 5.6 KiB per synthetic page, because those pages were mostly-white 480x640 PNGs. This is a floor, not a forecast. Image pages are re-encoded to PNG at native resolution with no downscale, so a phone photo can become a PNG of many MiB (estimate from the critic, not measured).

Formula (peak during intake, then steady state):

```text
peak   = 2 x Z  +  Zpdf  +  P x s            (spool + staged ZIP + originals + pages)
steady = Zpdf   +  P x s   +  database and grading context (not measured)
Z      = ZIP bytes             Zpdf = bytes of PDF students inside it
P      = total pages           s    = MiB per rasterised page (0.9, inferred from synthetic pages)
```

Worked example for 150 students x 4 pages, PDF layout, synthetic sizes: Z about 528 MiB (150 / 30 x
105.6), P = 600, P x s about 540 MiB, so peak about 2.1 GiB and steady about 1.0 to 1.1 GiB. Real scans
multiply the terms that carry `s` (and `Z`).

- [ ] Measure `s` on three real pages first: rasterise or export them at the real resolution and read the PNG size. Replace 0.9 with the measured value.
- [ ] Free space on the data drive is at least `peak` plus a margin the operator chooses (the margin is a policy choice, not measured). A full disk during staging no longer leaves a partial `bulk-<id>.zip` behind (fixed; `test_a_failed_staging_write_leaves_no_partial_archive`), but a hard kill or power loss still can (F.4).
- [ ] Free space on the PostgreSQL volume is also adequate. Its growth per run is not measured.

### A.7 Reference materials, before the ZIP

- [ ] Every question has a finalised question, model answer and active rubric (the form shows "References: Finalized"). Intake checks only that a model answer and an active rubric exist.
- [ ] Question labels are unique ignoring case. Labels differing only by case (`Q1` and `q1`) are accepted at creation and at intake, then stop the run after the first script's pages were read (PC-5h, strict xfail).
- [ ] Each question's total marks equals its rubric maximum. On the bulk path a draft whose `max_score` differs from the question's `total_marks` is now quarantined: the item becomes an `exception` with code `provider_contract_failure` and the warning `Draft grade maximum mismatch: expected X, got Y`, the draft stays stored for inspection and is excluded from bulk approval (fixed: `test_a_wrong_maximum_is_quarantined_with_a_visible_code_and_warning`). The individual approve and edit routes are not covered: `FinalGradeService._save_final_grade` still bounds a grade only by the draft's own maximum, so a draft scored 10 of 10 on a 5-mark question can still be finalised as 10 marks through "Open individual grade review" (PA-7, bulk path only fixed). Do not approve a wrong-scale draft. E.5 repeats the spot check.
- [ ] **Do not edit the question text, model answer, rubric or marks once the run is started.** Before each grading unit the run now compares the current reference bundle (every question's label, text, model answer and marks, and the active rubric id, version and JSON) with the hash recorded at authorisation. On a mismatch it pauses with "Reference materials (questions, model answers or rubrics) changed after this run was authorised; restore them or start a new run", makes no provider call and spends no budget (fixed: `test_a_reference_edit_pauses_the_run_before_any_further_provider_call`). There is no re-baseline path (D.3 row 14). Re-uploading or re-extracting the reference PDFs reopens the confirmation and pauses the run the same way. Two halves of PC-2 remain open: drafts graded before the edit stay offered as clean for bulk approval (PC-2b, strict xfail), and a marks edit after grading is finalised against the old marks (PC-2c, strict xfail). An edit of the model answer, question text or rubric made after the last item was graded is caught only at the irreversible step, where `approve-clean` refuses with a 409 (`test_a_reference_edit_after_grading_is_refused_at_finalization`); a marks edit is not caught there at all.

## B. ZIP preparation rules

### B.1 Layout rules the intake enforces

Each rule refuses the whole ZIP before any student is created (`BulkEvaluationService._inspect_archive`).

| Rule | Outcome if broken |
|---|---|
| One root-level PDF per student, or one top-level folder per student | the unit is the student; a root PDF's identifier is the file name without `.pdf`; a folder keeps its full name as the identifier (`Md. Karim` stays `Md. Karim`, no longer `Md`) |
| A folder holds either one PDF or numbered images, never both | refused: "mixes PDF and image pages" |
| A folder with more than one PDF | refused 409 naming the folder, with both remedies (PD-2c, refuted) |
| Images are `.png`, `.jpg`, `.jpeg`; scripts are `.pdf` | any other file type is refused ("Unsupported ZIP entry"); `.heic`, `.tif`, `.docx`, `.txt` all fail. Only `__MACOSX` content, `.DS_Store`, `Thumbs.db` and any member whose file name starts with `._` (AppleDouble) are skipped |
| No images directly at the ZIP root | refused ("Root-level images are ambiguous") |
| No folders inside a student folder | refused ("no nested folders") |
| Image pages are ordered naturally by file name (`2` before `10`) | page order is the natural sort of file names |
| `manifest.csv` at the ZIP root only, UTF-8, header with `source`, `student_identifier`, `student_name` | other dialects (semicolons, capitalised or spaced headers, Windows-1252) are refused, never half-read (PD-4h, refuted) |
| A manifest `source` that is not in the ZIP | refused, naming up to 5 offenders and "and N more" (PD-4e2, fixed) |
| Duplicate identifiers (compared ignoring case) | refused, naming the identifier and both sources (PD-4e1, fixed) |
| Identifiers that already exist in the assessment | refused naming up to 5 (PD-3b, refuted) |
| Path parts that are empty, `.`, `..` or contain `:`; absolute paths | refused ("unsafe member path") |
| ZIP-level encryption, a member over 100 MiB, more than 4 GiB uncompressed, a member ratio over 100:1 | refused |
| More than 1,000 non-folder entries | refused ("ZIP contains more than 1,000 entries"); ignorable entries (`__MACOSX`, `.DS_Store`, `Thumbs.db`, `._` files) no longer count toward the 1,000 (fixed: `test_sidecars_do_not_count_toward_the_entry_cap`, `test_the_entry_cap_counts_only_entries_that_are_not_ignorable_metadata`); 1,001 real entries are still refused |
| More than `BULK_MAX_SUBMISSIONS` students, or archive over `BULK_MAX_ARCHIVE_BYTES` | refused before rendering |
| More than `BULK_MAX_PAGES` pages in total | refused only **after** the cohort was rasterised, see B.3 |

Per-student page count is not limited by intake except through the cohort total.

### B.2 What intake now refuses, and what it still accepts silently

The fix wave (2026-10-12) moved many cases from "accepted silently" to "refused with a named
message". The first table lists them. The second table lists what is still accepted silently: the
manual check is the only protection there.

**What intake now refuses, and the message you will see**

Each refusal is HTTP 409 and refuses the whole ZIP: nothing is imported, no submission or run is kept
and the student files already written are removed. `<source>` is the PDF path for a root-level PDF
and the student folder for a folder (an image folder, or a folder holding one PDF). Names echoed in
the "Could not import", "twice", file-and-folder and manifest-line messages are cut at 200
characters; older messages (for example "Unsupported ZIP entry") still echo the whole name.

| Cause | Message pattern | What to do |
|---|---|---|
| Two members with one path (a duplicated PDF, a duplicated page in a folder, a duplicated `manifest.csv`; backslash and `./` spellings count as the same path) | `ZIP contains the member <path> twice` | rebuild the ZIP so each path occurs once. Names that differ only by case are not this refusal: they reach the duplicate-identifier row below |
| A second manifest in another case (`Manifest.csv` plus `manifest.csv`) | `ZIP contains more than one manifest.csv` | keep exactly one `manifest.csv` at the root |
| A root file and a folder with the same name (`A.pdf` and `A.pdf/`) | `ZIP contains both the file 'A.pdf' and the folder 'A.pdf/'; rename one so each script is a single student` | rename one. A root `A.pdf` with a folder `A` is caught later as a duplicate identifier (`A`). The refusal compares exact spellings: a root `a.pdf` with a folder `A.pdf/` is not caught by it and, read from the code and not tested, imports as two students (`a` and `A.pdf`), so keep names distinct ignoring case |
| Password-protected PDF | `Could not import <source>: password-protected PDF. Nothing was imported.` | remove the password and export the PDF again |
| Unreadable or zero-byte PDF | `Could not import <source>: <the decoder's own text>. Nothing was imported.`, for example `Uploaded PDF could not be decoded` or `Uploaded PDF has no pages` | open the file in a viewer; replace it |
| Unsupported compression method (Deflate64) | `Could not import <source>: unsupported ZIP compression method. Nothing was imported.` | rebuild the ZIP with plain Deflate |
| An image above about 179 megapixels | `Could not import <source>: image too large to read safely. Nothing was imported.` (`<source>` is the folder) | downscale the photo |
| A damaged member (bad CRC or a corrupt compressed stream) | `Could not import <source>: damaged ZIP member (CRC/compression). Nothing was imported.`; a damaged manifest gives `Could not import manifest.csv: damaged ZIP member (CRC/compression). Nothing was imported.` | re-create the ZIP from the originals. `Uploaded file is not a valid ZIP archive` now means only that the archive itself cannot be opened |
| A manifest row with a non-empty extra cell (an unquoted comma in a name) | `manifest.csv line N ('<source>') has more columns than the header, for example an unquoted comma in a name; put quotes around any cell that contains a comma` | double-quote every cell that contains a comma. A trailing empty extra cell (`S001.pdf,ID-1,One,`) is still accepted |
| Duplicate student identifiers (compared ignoring case) | `ZIP contains duplicate student identifiers: '<identifier>' is used by both '<source 1>' and '<source 2>'` | rename one source or correct the manifest |
| A manifest `source` that is not in the ZIP | `manifest.csv refers to a source that is not in the ZIP: '<name>', ...` (up to 5 names, then `, and N more`) | correct the `source` column |
| Authorised call limit below pages + items (W10) | `Authorized provider calls (<limit>) are below the minimum this cohort needs (<minimum>: <pages> page reads + <items> gradings). Whole-transcript assignment calls (up to one per script) are extra, so allow some slack above the minimum.` | raise the limit; see B.3 for what the number means and when the cohort must be split |

A bad member is found only when its student is imported, after every earlier student was rendered,
and the call-limit refusal comes after the whole cohort was rendered, so each of these can arrive
minutes late (PD-1e). `test_every_unusable_member_is_refused_with_a_teacher_readable_error` and
`test_an_unusable_member_is_refused_naming_it_and_keeping_the_original_error` pin the member messages;
`test_an_authorisation_below_pages_plus_items_is_refused_with_409_and_nothing_is_kept` pins the call
limit. These refusals are matched by exception type, and two of them by message text. Any other
exception type raised while a member is imported (for example an `EOFError` or a new library error)
still surfaces raw as the opaque 503 "Bulk evaluation could not be started".

**What changed silently, for the better**

- A student folder keeps its full name as the identifier: `Md. Karim`, `S.001` and `Dr. A. Rahman` are now taken as written, and `Md. Karim` and `Md. Rahim` are now two students (they used to collapse to `Md` and be refused as duplicates). Root-level PDFs still lose their `.pdf`. **Data-continuity caution:** if the assessment already holds students imported before this fix under a truncated identifier (`Md`), importing the same cohort again now produces `Md. Karim`, which the "identifiers already exist" check does not match, so the same student can be created twice. This applies only to pilot data imported before 2026-10-12, never to a fresh assessment. Fixing it needs a data migration or a design decision and was not done.
- AppleDouble `._` members are ignored anywhere in the archive (no phantom student, no opaque 503, no "Unsupported ZIP entry") and no longer count toward the 1,000-entry cap.
- EXIF orientation is applied to image pages on import (tags 2 to 8), so a phone photo tagged as rotated is no longer stored sideways (`test_exif_orientation_is_applied_to_the_stored_page`). A photo with no tag or with malformed EXIF is stored unchanged; PDF pages are not touched.

**What intake still accepts silently: check these by hand**

The product does not warn about any row below. Each is proven by a strict xfail unless marked pinned or
refuted. Until a fix lands, the manual check is the only protection.

| Silent acceptance | What happens | Manual check before upload | Evidence |
|---|---|---|---|
| NFC and NFD spellings of one name | two different students, in one ZIP and across re-imports | names are NFC (the script below flags non-NFC) | PD-4b; `test_nfc_and_nfd_spellings_of_one_identifier_are_duplicates`, `test_a_reimport_in_another_unicode_form_is_refused_as_already_existing` (strict xfail) |
| Non-ASCII member names the ZIP writer did not flag as UTF-8 | a Bengali or accented name is stored as mojibake (for example `αªå...`) with no warning | list the non-ASCII names and read them; a ZIP built by Python sets the flag, some desktop zippers do not | PD-4c; `test_a_utf8_name_without_the_utf8_flag_is_not_stored_as_mojibake` (strict xfail) |
| Blank manifest cell or unlisted source | the identifier falls back to the file name stem with no flag; a scan-numbered file then identifies nobody | every source appears in the manifest with a non-blank identifier | PD-4i (pinned: `test_manifest_gaps_fall_back_to_the_file_name_silently`) |
| A manifest row with fewer cells than the header (a short row, for example `S001.pdf,Alice Smith` under a three-column header) | the missing cell is blank, so the identifier or name silently falls back to the file stem. Only a row with a non-empty extra cell is refused. A fix was tried and reverted because it broke a pinned refusal message | every row has exactly the header's column count; no name was pasted with a hidden line break (a U+2028 line separator splits the row) | pinned: `test_manifest_dialects_that_spreadsheets_write_are_refused_never_half_read[line-separator-in-name]` |
| Pages of another student under a file's name | accepted under the file's name; intake is content-blind | cover-page identity spot check in E.2 | PD-5c (pinned) |
| Byte-identical PDFs under two names | two submissions, graded twice, no flag | the script below compares SHA-256 | PD-5b; `test_byte_identical_scripts_under_two_names_are_refused_or_flagged` (strict xfail) |
| Truncated or cut-off PDF | accepted; MuPDF repairs it and renders blank pages; the script is later read as "nothing written" | open every PDF in a viewer to the last page | `test_a_truncated_pdf_is_not_accepted_as_blank_pages` (strict xfail) |
| Page cap and call-limit minimum were checked only after the pages were rendered (fixed since 2026-10-13 (wave C): every PDF is opened, never rendered, and counted first; a damaged/truncated PDF is refused by name) | a cohort over `BULK_MAX_PAGES` (720) is refused only after most of its pages were rasterised and written, inside the one upload request; the call-limit minimum (B.3) is checked after the whole cohort was rendered | **count the pages before upload** (B.3, B.4) and compute the call minimum before you type the limit | RC-17; `test_an_over_cap_cohort_is_refused_before_any_script_is_rendered`, `test_a_single_huge_pdf_is_refused_without_rendering_its_pages` (pass since wave C) |
| A genuine page or script whose file name starts with `._` | ignored like an AppleDouble sidecar: that page silently disappears from the script | no real file name starts with `._` | by design of the `._` rule (`test_the_entry_cap_counts_only_entries_that_are_not_ignorable_metadata` shows `._` pages are dropped) |
| Page order | pages are ordered by the natural sort of the file names (`2` before `10`), so a mis-numbered or mis-named page is accepted in the wrong place | compare each script's page order with the physical script in E.2 | B.1 rule; not probed as a defect |

Failures that still name nothing (the route answers an opaque 503 "Bulk evaluation could not be
started"): an exception type the fix did not map while a member is imported, an overlapped identical
upload (PD-3e), and any failure after the intake committed (C.4). Before the fix wave this list also
held a password-protected PDF, a zero-byte PDF, Deflate64 and a huge image; those are now named in the
first table. After a failure before the commit the route leaves 0 submissions and 0 runs.

- [ ] Open every PDF. None asks for a password, none is empty, none stops before its last page. The product now refuses a password-protected or empty PDF by name, but only after the earlier students were rendered, so the refusal can arrive minutes late; a truncated PDF is still accepted.
- [ ] Build the ZIP with plain Deflate (Windows "Send to > Compressed folder" or 7-Zip with the Deflate method). A Deflate64 member is now refused by name, again only after earlier students were rendered.
- [ ] Rename each file or folder so its name is the intended student identifier, or supply a correct `manifest.csv`.
- [ ] Count the pages of the whole cohort and compute the call minimum (B.3) before upload.

### B.3 Pages and provider-call arithmetic

The 720-page cap allows an average of 4.8 pages per student at 150 students (PD-1d, pinned). Pages
beyond the cap are refused only after the cohort was rasterised: 5 pages x 150 students = 750 pages is
refused after about 725 pages were rendered and written (PE-5, strict xfail). The wasted work is no data
damage, but it costs from about 5 s (cheap synthetic pages) to about 318 s (incompressible worst case)
inside one upload request (PD-1a). A single PDF has no page cap of its own (PD-1b).

Provider calls needed (verified against a real run, PB-7b, `test_pb7_the_call_formula_matches_what_a_real_run_spends`):

```text
need = pages  +  (scripts that have continuation blocks)  +  students x questions
```

| Cohort | Pages | Questions | Continuation scripts | need | Fits ceiling 2000 | Slack at 2000 |
|---|---|---|---|---|---|---|
| 150 students x 4 pages | 600 | 6 | 0 | 1,500 | yes | 500 |
| 150 x 4 | 600 | 7 | 0 | 1,650 | yes | 350 |
| 150 x 4 | 600 | 8 | 0 | 1,800 | yes | 200 (but exactly the default ceiling of 1800) |
| 150 x 4 | 600 | 9 | 0 | 1,950 | yes, only if the ceiling is 2000 | 50 |
| 150 x 4 | 600 | 9 | 150 (every script) | 2,100 | **no** | impossible |
| 150 x 4 | 600 | 10 | 0 | 2,100 | **no** | impossible |

The headline fake-provider run used 150 x 4 x 6, a need of 1,500, and authorised 1,502.

**Intake now refuses a limit below `pages + items` (W10, 2026-10-12).** If the requested call limit is
below the page total plus the item total (`students x questions`), the upload is refused with HTTP 409
and the message in B.2 ("Authorized provider calls (N) are below the minimum this cohort needs ..."),
and nothing is kept. Before the fix such an upload was accepted and could only end in a run that
paused half graded (D.4 DE-6). The rule is an **estimate**, neither a true minimum nor a true need:

- Whole-transcript assignment calls (up to one per script with continuation blocks) are not in it, so a limit that passes can still run out. In the 150 x 4 x 9 row above with every script continuing, `pages + items` is 1,950 and passes a limit of 2,000, while `need` is 2,100.
- A blank answer costs no grading call, so a blank-heavy cohort can be refused although it could finish. The rule counts one grading call per item.
- If `pages + items` is above 2,000 no allowed limit passes. The cohort must be split into separate archives of different students (PB-7b). Whether to split is a founder decision.
- The check runs only after every page was rendered, so it arrives late (B.2). The server-ceiling refusal ("Requested provider calls exceed the bulk server ceiling") comes first and is fast.
- Re-uploading an archive that already has an active run returns that run before this check, so a re-upload with a smaller limit is not refused and keeps the original limit (C.2).
- The refusal is a behaviour change that needs founder acknowledgement (see the decisions list in "Purpose and status"). It is about 10 lines in `create_from_zip` and easy to revert.

- [ ] Compute `need` for this cohort with the real question count. Write it in section H, together with `pages + items`.
- [ ] Authorise `need` plus slack, strictly above `need`. A run authorised for exactly the calls it spends now finishes (fixed: `test_a_run_authorised_for_exactly_the_calls_it_needs_still_finishes`; it used to end `paused` with every item graded and be neither resumable, approvable nor exportable, PE-8), but the slack is still needed: retries and assignment calls spend calls that `pages + items` does not include, and the exhausted-run dead end is unchanged (D.4 DE-6).
- [ ] The slack pays for every retry. A retried read or grading spends calls again. An under-authorised run that passes the new minimum can still pause in grading with every student half graded, and that is a dead end (D.4 DE-6; `test_pb7_a_run_that_runs_out_of_calls_has_a_way_forward`, strict xfail). The call cost of retrying one script's read is **not verified**; budget at least that script's page count.
- [ ] If `need` plus a sensible slack exceeds 2,000, or the pages exceed 720, the cohort cannot run as one archive. Splitting into separate archives of different students works (PB-7b) and also reduces the cost of a dead end (D.4). Whether to split is a founder decision.
- [ ] Failed grading calls are not charged to `calls_used` (`test_a_failed_grading_call_is_charged_to_the_call_budget`, strict xfail), so the counter can understate real model calls (F.2).
- [ ] There is no pre-read blank-page or cover-page filter, so blank sheets and cover pages spend calls like any page (critic M06, not probed).

### B.4 Count and inspect the ZIP before upload

No offline preflight tool exists yet. The script below uses only Windows PowerShell and .NET and
**writes nothing**. It reproduces the intake's layout and limit rules and the by-hand checks in B.2. It
cannot count PDF pages, test CRCs or see the compression method, and it does not replace the real
intake. Since 2026-10-13 the server also opens (never renders) every PDF before anything is imported and refuses, by name, a PDF that is password-protected, undecodable, empty, or that MuPDF can open only after repairing it (typically a truncated download; a few valid scanner files may also be flagged). Such a refusal imports nothing: re-export that one PDF (Print to PDF) or download it again, re-zip, and upload. The page cap and the call minimum are checked on that count, before rendering. Save it as `inspect-cohort-zip.ps1` outside the repository and run it, for example
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\inspect-cohort-zip.ps1 -Zip <zip> -Questions 6 -PdfPages 0 -CallLimit 1700`.
Read every flagged line, and keep its output with the sign-off sheet. The author ran the first version on
2026-10-11 against three synthetic archives only: one poisoned with the intake defects it claims to detect
(all were flagged), one clean 150-student, 600-image cohort (no flags, 0.4 s), and one case-collision archive.
It was not run against a real cohort.

**The script below was revised on 2026-10-12 to match the post-fix intake** (duplicate members, a second
`manifest.csv`, a file and a folder with one name, a non-empty surplus manifest cell and a call limit below
pages + items are now flagged as refusals; `._` files no longer count and no longer flag; a dotted folder
keeps its name; a leading `=` is only noted). The revised text was checked only as a PowerShell parse and one
run against each of two small synthetic archives built in a scratch folder (see the note after the script).
It has not seen a real cohort.

```powershell
# inspect-cohort-zip.ps1 -- read-only inspection of a cohort ZIP before upload. Writes nothing.
# Mirrors the layout and limit rules of BulkEvaluationService._inspect_archive at 8a25268 plus the 2026-10-12 fix-wave diff and the by-hand checks of B.2.
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [int]$Questions = 0,            # questions per script (needed for the call arithmetic)
    [int]$PdfPages = 0,             # total pages of all PDF scripts, counted elsewhere
    [int]$ContinuationScripts = 0,  # scripts whose answers continue across pages (0 if unknown)
    [int]$CallLimit = 0             # the authorised call limit you intend to type (0 = skip that check)
)
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName Microsoft.VisualBasic
$flags = New-Object System.Collections.Generic.List[string]
function Flag([string]$Message) { $script:flags.Add($Message); Write-Host "  !! $Message" -ForegroundColor Yellow }
# Members the intake skips: __MACOSX content, .DS_Store, Thumbs.db and any file name starting with '._'.
function IsIgnorable($Row) { $low = $Row.Name.ToLowerInvariant(); return (($Row.Parts -ccontains '__MACOSX') -or $low -eq '.ds_store' -or $low -eq 'thumbs.db' -or $Row.Name.StartsWith('._')) }

$file = Get-Item -LiteralPath $Zip
$z = [System.IO.Compression.ZipFile]::OpenRead($file.FullName)
try {
    # 1. Files only: the service skips folder markers when it counts entries.
    $rows = @()
    foreach ($e in $z.Entries) {
        if ($e.FullName.EndsWith('/') -or $e.FullName.EndsWith('\')) { continue }
        $p = $e.FullName.Replace('\', '/')
        $parts = $p.Split('/')
        $rows += [pscustomobject]@{ Path = $p; Parts = $parts; Name = $parts[$parts.Count - 1]; Len = $e.Length; Clen = $e.CompressedLength; Entry = $e }
    }
    Write-Host ("archive bytes              : {0:N0}   (limit 1,073,741,824)" -f $file.Length)
    if ($file.Length -gt 1073741824) { Flag 'archive is over 1 GiB' }
    $considered = @($rows | Where-Object { -not (IsIgnorable $_) }).Count
    Write-Host ("file entries (no folders)  : {0}, of which {1} count toward the 1,000 limit (ignorable entries do not)" -f $rows.Count, $considered)
    if ($considered -gt 1000) { Flag 'more than 1,000 countable file entries (refused)' }

    # 2. Duplicate member names are refused ('ZIP contains the member <path> twice'); a duplicated ignorable entry is not.
    foreach ($g in ($rows | Where-Object { -not (IsIgnorable $_) } | Group-Object Path -CaseSensitive | Where-Object { $_.Count -gt 1 })) { Flag "member name appears $($g.Count) times (refused: ZIP contains the member twice): $($g.Name)" }
    foreach ($g in ($rows | Group-Object { $_.Path.ToLowerInvariant() } | Where-Object { $_.Group.Count -gt 1 -and ($_.Group | Select-Object -ExpandProperty Path -Unique).Count -gt 1 })) { Flag "member names differ only by case (not a duplicate member; refused later only if the identifiers collide): $($g.Name)" }

    # 3. Safe paths, ignored members, sidecars.
    $usable = @(); $ignored = 0
    foreach ($r in $rows) {
        $bad = $r.Path.StartsWith('/')
        foreach ($part in $r.Parts) { if ($part -eq '' -or $part -eq '.' -or $part -eq '..' -or $part.Contains(':')) { $bad = $true } }
        if ($bad) { Flag "unsafe member path (refused): $($r.Path)"; continue }
        if (IsIgnorable $r) { $ignored++; if ($r.Name.StartsWith('._')) { Write-Host "  note: '._' file is skipped, not imported (a genuine page with this name would vanish): $($r.Path)" }; continue }
        $usable += $r
    }
    Write-Host ("ignored by intake          : {0}   (__MACOSX, .DS_Store, Thumbs.db, '._' files; they no longer count toward 1,000)" -f $ignored)
    if ($usable.Count -eq 0) { Flag 'no usable members (refused)' }

    # 4. Size limits.
    if ($usable.Count -gt 0) {
        $big = $usable | Sort-Object Len -Descending | Select-Object -First 1
        Write-Host ("largest member             : {0:N0} bytes   (limit 104,857,600)   {1}" -f $big.Len, $big.Path)
        if ($big.Len -gt 104857600) { Flag "member over 100 MiB (refused): $($big.Path)" }
        $total = ($usable | Measure-Object Len -Sum).Sum
        Write-Host ("uncompressed total         : {0:N0} bytes   (limit 4,294,967,296)" -f $total)
        if ($total -gt 4294967296) { Flag 'uncompressed total over 4 GiB (refused)' }
        foreach ($r in $usable) { if (($r.Len / [Math]::Max($r.Clen, 1)) -gt 100) { Flag "compression ratio over 100:1 (refused): $($r.Path)" } }
    }

    # 5. Layout: root PDFs, one folder per student, images or one PDF per folder.
    $supported = '.pdf', '.png', '.jpg', '.jpeg'
    $manifestRow = $null
    $units = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)   # case-sensitive, like the product
    foreach ($r in $usable) {
        if ($r.Parts.Count -eq 1 -and $r.Name.ToLowerInvariant() -eq 'manifest.csv') {
            if ($manifestRow) { Flag "more than one manifest.csv at the root (refused): $($r.Path)" } else { $manifestRow = $r }
            continue
        }
        $ext = [IO.Path]::GetExtension($r.Name).ToLowerInvariant()
        if ($supported -notcontains $ext) { Flag "unsupported file type (the whole ZIP is refused): $($r.Path)"; continue }
        if ($r.Parts.Count -eq 1) {
            if ($ext -ne '.pdf') { Flag "image at the ZIP root (refused): $($r.Path)"; continue }
            if ($units.ContainsKey($r.Path)) { if ($units[$r.Path].Folder) { Flag "both the file '$($r.Path)' and the folder '$($r.Path)/' exist (refused): rename one" }; continue }   # a second root file of the same name is the duplicate member already flagged in step 2
            $units[$r.Path] = @{ Folder = $false; Files = @($r) }
        } elseif ($r.Parts.Count -eq 2) {
            $k = $r.Parts[0]
            if ($units.ContainsKey($k) -and -not $units[$k].Folder) { Flag "both the file '$k' and the folder '$k/' exist (refused): rename one"; continue }
            if (-not $units.ContainsKey($k)) { $units[$k] = @{ Folder = $true; Files = @() } }
            $units[$k].Files += $r
        } else { Flag "folder inside a student folder (refused): $($r.Path)" }
    }

    # 6. manifest.csv (quoted fields are honoured, as in the product).
    $manifest = New-Object System.Collections.Hashtable ([StringComparer]::Ordinal)
    if ($manifestRow) {
        $reader = New-Object System.IO.StreamReader($manifestRow.Entry.Open(), (New-Object System.Text.UTF8Encoding($false)), $true)
        $text = $reader.ReadToEnd(); $reader.Close()
        $tfp = New-Object Microsoft.VisualBasic.FileIO.TextFieldParser((New-Object System.IO.StringReader($text)))
        $tfp.TextFieldType = [Microsoft.VisualBasic.FileIO.FieldType]::Delimited
        $tfp.SetDelimiters(',')
        $tfp.HasFieldsEnclosedInQuotes = $true
        $header = $tfp.ReadFields()
        $line = 1   # counts records, not physical lines; a quoted cell with a line break makes it drift
        foreach ($need in 'source', 'student_identifier', 'student_name') { if ($header -cnotcontains $need) { Flag "manifest.csv header lacks column '$need' (refused)" } }
        while (-not $tfp.EndOfData) {
            $f = $tfp.ReadFields()
            $line++
            if ($f.Count -gt $header.Count) {
                $extra = @($f[$header.Count..($f.Count - 1)] | Where-Object { ([string]$_).Trim() })
                if ($extra.Count -gt 0) { Flag "manifest.csv near line ${line}: a non-empty cell beyond the header's $($header.Count) columns (refused). Quote any name that contains a comma." }
            } elseif ($f.Count -lt $header.Count) { Flag "manifest.csv near line ${line}: a short row, $($f.Count) cells but the header has $($header.Count). The missing cells are blank and the identifier or name silently falls back to the file stem." }
            $h = @{}
            for ($i = 0; $i -lt $header.Count; $i++) { if ($i -lt $f.Count) { $h[$header[$i]] = $f[$i] } else { $h[$header[$i]] = '' } }
            $src = ([string]$h['source']).Replace('\', '/').Trim().TrimEnd('/')
            if (-not $src -or $manifest.ContainsKey($src)) { Flag "manifest.csv has a blank or duplicate source near line ${line} (refused)"; continue }
            $manifest[$src] = $h
        }
        $tfp.Close()
        foreach ($src in $manifest.Keys) { if (-not $units.ContainsKey($src)) { Flag "manifest.csv row for '$src' matches nothing in the ZIP (refused)" } }
    }

    # 7. Students.
    $list = @(); $seen = @{}
    foreach ($key in ($units.Keys | Sort-Object)) {
        $u = $units[$key]
        $pdfs = @($u.Files | Where-Object { $_.Name.ToLowerInvariant().EndsWith('.pdf') })
        $imgs = @($u.Files | Where-Object { -not $_.Name.ToLowerInvariant().EndsWith('.pdf') })
        if ($u.Folder) {
            if ($pdfs.Count -gt 0 -and $imgs.Count -gt 0) { Flag "folder mixes PDF and image pages (refused): $key" }
            if ($pdfs.Count -gt 1) { Flag "folder holds $($pdfs.Count) PDFs (refused, ambiguous): $key" }
        }
        $kind = 'images'; if ($pdfs.Count -gt 0) { $kind = 'pdf' }
        $pages = $imgs.Count
        # Only a root-level PDF loses its extension; a student folder keeps its full name ('Md. Karim' stays 'Md. Karim').
        $default = $key; if (-not $u.Folder) { $default = [IO.Path]::GetFileNameWithoutExtension($key) }
        $id = $default
        $note = ''
        if ($manifestRow) {
            if ($manifest.ContainsKey($key)) {
                $mid = ([string]$manifest[$key]['student_identifier']).Trim()
                if ($mid) { $id = $mid } else { Flag "manifest row for '$key' has a blank identifier; it falls back to '$default'"; $note = 'fallback' }
            } else { Flag "'$key' has no manifest row; its identifier falls back to '$default'"; $note = 'fallback' }
        }
        if ($id.Length -gt 128) { $id = $id.Substring(0, 128) }
        if ($seen.ContainsKey($id.ToLowerInvariant())) { Flag "duplicate student identifier ignoring case (refused): '$id'" }
        $seen[$id.ToLowerInvariant()] = $true
        if ($id -match '^[=+\-@]') { Write-Host "  note: identifier looks like a formula ('$($id[0])...'); the exports now write a leading '=' as text, so read it, do not fix it: $id" }
        if (-not $id.IsNormalized([Text.NormalizationForm]::FormC)) { Flag "identifier is not Unicode NFC (NFC and NFD spellings are different students): '$id'" }
        if ($id -match '[^\u0000-\u007F]') { Write-Host "  non-ASCII identifier, read it for mojibake: $id" }
        $list += [pscustomobject]@{ Source = $key; Kind = $kind; Files = $u.Files.Count; Pages = $pages; Identifier = $id; Note = $note }
    }

    # 8. Byte-identical PDFs under two names.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hashes = @{}
    foreach ($r in ($usable | Where-Object { $_.Name.ToLowerInvariant().EndsWith('.pdf') })) {
        $s = $r.Entry.Open(); $hex = [BitConverter]::ToString($sha.ComputeHash($s)); $s.Close()
        if ($hashes.ContainsKey($hex) -and $hashes[$hex] -ne $r.Path) { Flag "identical PDF bytes under two names: '$($hashes[$hex])' and '$($r.Path)'" } else { $hashes[$hex] = $r.Path }
    }

    # 9. Totals and call arithmetic.
    $students = $list.Count
    $imagePages = ($list | Measure-Object Pages -Sum).Sum
    if ($null -eq $imagePages) { $imagePages = 0 }
    $pages = $imagePages + $PdfPages
    Write-Host ""
    $list | Format-Table Source, Kind, Files, Pages, Identifier, Note -AutoSize
    Write-Host ("students                   : {0}   (BULK_MAX_SUBMISSIONS; 180 is the ceiling)" -f $students)
    Write-Host ("pages                      : {0} = {1} image pages counted here + {2} PDF pages you supplied   (limit 720; 4.8 average at 150)" -f $pages, $imagePages, $PdfPages)
    $pdfCount = @($list | Where-Object { $_.Kind -eq 'pdf' }).Count
    if ($pdfCount -gt 0 -and $PdfPages -eq 0) { Flag "$pdfCount PDF script(s): pass -PdfPages with the total page count or the page total above is a floor" }
    if ($pages -gt 720) { Flag 'page total is over 720; the product refuses it only after rasterising the cohort' }
    if ($Questions -gt 0) {
        $need = $pages + $ContinuationScripts + $students * $Questions
        Write-Host ("provider calls needed      : {0} = pages {1} + continuation scripts {2} + students {3} x questions {4}   (ceiling 2,000; authorise MORE than this)" -f $need, $pages, $ContinuationScripts, $students, $Questions)
        if ($need -ge 2000) { Flag 'need is at or above 2,000: it cannot run as one archive' }
        # The intake refuses (409) a call limit below pages + items. That is an estimate, not a true minimum (B.3).
        $minimum = $pages + $students * $Questions
        Write-Host ("intake minimum (pages + items): {0} = pages {1} + students {2} x questions {3}   (assignment calls and retries are extra)" -f $minimum, $pages, $students, $Questions)
        if ($minimum -gt 2000) { Flag 'pages + items is above 2,000: no allowed call limit passes; split the cohort' }
        if ($CallLimit -gt 0 -and $CallLimit -lt $minimum) { Flag "the call limit $CallLimit is below pages + items $minimum (the intake refuses it with 409)" }
        if ($CallLimit -gt 0 -and $CallLimit -le $need) { Flag "the call limit $CallLimit is not above need $need (B.3 requires slack above need)" }
    } else { Write-Host 'provider calls needed      : pass -Questions to compute pages + continuation scripts + students x questions' }
}
finally { $z.Dispose() }
Write-Host ""
if ($flags.Count -eq 0) { Write-Host 'No flags. This is NOT a green light: PDF integrity, CRCs and content identity are not checked here.' -ForegroundColor Green }
else { Write-Host ("{0} flag(s). Fix each one before upload." -f $flags.Count) -ForegroundColor Yellow }
```

Check of the revised script (2026-10-12), second pass: the script text above was extracted from this file
and run against four archives built by the test harness (`build_zip`, `duplicate_member_zip`,
`macosx_flood_zip`) with known contents. It reported exactly the known figures: a 20-student, 4-page image
cohort as 20 students, 80 pages, need 200 (the harness's own call budget is 200) with no flag; a 6-student
PDF cohort as 6 students, need 60 once `-PdfPages 24` was supplied (without it, the PDF-page flag fires);
a ZIP with 60 page images and 60 `__MACOSX/._` sidecars as 10 students, 60 pages, no flag (sidecars do not
count); and the duplicate-member archive with the duplicate-member flag (the same run first also raised a
misleading "file and folder" flag, which is fixed in the text above). That is four synthetic archives, no
real cohort, and nothing about PDF content. The first-pass check was the PowerShell parser (0 errors) and
one run against each of two small archives of dummy bytes built in a scratch folder. The poisoned one (a
duplicated member, a second `Manifest.csv`, a file `F.pdf` with a folder `F.pdf/`, a manifest row with a
non-empty extra cell, a short manifest row, `._` and `.DS_Store` entries) raised the expected flag for each
and reported the `._` files as skipped. The clean one (two image folders and two ignorable entries) raised no
flag. No real or student data was used, and a flag-free result still proves nothing about PDF content.

What the script cannot see, and what to do instead:

- PDF page counts. A PDF page count needs a PDF library. Use the scanner job log or a PDF viewer's page count per file, sum them, and pass the total as `-PdfPages`. A per-PDF page limit does not exist (PD-1b), so an outlier PDF matters.
- Bad CRCs, encrypted members, Deflate64. .NET does not verify CRCs on read and does not expose the method. If 7-Zip is installed (**not verified on this machine**), `7z t <zip>` tests every member's CRC. Otherwise the real intake reports the failure after rendering.
- Whether a PDF needs a password or was truncated. Open each one.

**No offline preflight CLI exists.** A read-only inspection seam does exist and was demonstrated by
probe PD-6a (`test_inspect_archive_runs_without_a_database_or_storage`):
`BulkEvaluationService(None, settings=..., storage=...)._inspect_archive(zipfile)` runs with no database
and returns the units, the manifest hash and the payload. It reads only the central directory and
`manifest.csv`; inspecting a 150-student, 601-member ZIP took a median of 4.7 ms (PD-6b). A future CLI built
on it must avoid exactly these hazards (PD-6c):

1. Do not omit `storage=`. With `storage=None` the service builds `LocalStorage()` from the process environment and ignores the `Settings` it was given, so a CLI could create and later write into the live `data\` directory.
2. Do not treat a clean inspection as a green light. `_inspect_archive` never opens a member, so it returned 2 units for each of the password-PDF, zero-byte-PDF, bad-CRC, Deflate64 and 196-megapixel-PNG archives. A usable preflight needs its own member pass: open each PDF (`needs_pass`, `page_count`, repaired/truncated), read each image header size, and verify each member's CRC.
3. Do not report only the first problem. `_inspect_archive` is fail-fast, so an operator re-runs it once per fix. Collect all problems.
4. Do not let it diverge from the real intake. A preflight that passes archives the real intake rejects is worse than none; share the member-pass code.
5. Do not give it a database connection or write path. It must be read-only.

## C. Authorisation and start

### C.1 What the teacher confirms

The create route refuses unless all of the following hold (`routes/bulk_evaluations.py` create route;
`BulkEvaluationClient.tsx`, "Start bulk evaluation"):

- a finalised grading run (finalised references) is selected;
- a bulk-capable provider profile and its expected model are selected, and the brain reports ready; for this run that is the local Qwen3.8 profile with the local-only confirmation;
- the confirmation that strict auto-pass rules apply and all scores remain drafts until the teacher approves them;
- the maximum model calls, an integer between 1 and the server ceiling, and since 2026-10-12 not below the cohort's pages + items (B.3), which intake checks after rendering.

- [ ] The "Brain" card shows the intended profile and model and does not say "not ready".
- [ ] The "Maximum model calls" field holds the value chosen in B.3, not the pre-filled 2000.
- [ ] The teacher reads the confirmation text before ticking it. The tick is the authorisation for this run. The later bulk approve does not ask again (E.7).

### C.2 How the call limit is chosen

- [ ] `limit` = `need` (B.3) plus slack, strictly greater than `need`, at most the server ceiling printed in A.5, at most 2,000 (the database CHECK). It must also be at least `pages + items`, or intake refuses the upload (B.2, B.3). That minimum is not `need`: it leaves out assignment calls and retries, so passing it does not make the limit safe.
- [ ] The limit cannot be raised later. It is written once, at intake. Re-uploading the same archive with a different limit silently returns the original run with its original limit and enqueues nothing (PD-3d pinned; PB-7a). The W10 minimum is not applied to that re-upload, because the existing run is returned first.
- [ ] The chosen number and its derivation are written in section H.

### C.3 One upload, one tab, no repeats

The upload is one synchronous request. The browser sends the whole ZIP as a single `fetch` with no
timeout, progress bar or abort. The server stages the ZIP, inspects it, rasterises every page, writes
the files and commits one transaction before it answers 202. The page can sit for minutes with no
sign of progress. The local model can also be started inside this request, and a busy model lease fails
it with "brain provider is unavailable or mismatched".

- [ ] Upload once. Do not reload the page, click again, retry or open a second tab while the request is pending.
- [ ] **One upload at a time.** Two overlapping uploads of the same students, for example a corrected ZIP sent while the first still renders, can still race: they create every student twice and queue two runs, so each student is graded twice (PD-3f, strict xfail: `test_two_overlapping_uploads_of_the_same_students_never_create_a_student_twice`). Do not re-upload to "check".
- [ ] An identical upload that overlaps the first returns 503 "Bulk evaluation could not be started" although the run exists (PD-3e, strict xfail). After any 503, open the run list and look for the run before doing anything else (C.4 lists the three states).
- [ ] **A re-upload of an active archive is not a recovery action.** Re-uploading the same archive against the same reference materials while that run is active (any active status, including `paused`) now returns the existing run (HTTP 202, same body) and enqueues nothing, so it no longer starts a second worker job chain (fixed: `test_pb4_an_idempotent_reupload_does_not_enqueue_another_worker_chain`, `test_pb4_an_idempotent_reupload_with_the_queue_down_leaves_the_existing_run_alone`). It does not revive a dead worker chain, does not un-pause a run and does not finish a `stopping` run. Use Resume or Recover (C.5, D.3) for those. Re-uploading is only safe as a way to find the existing run, and the run list does that better.
- [ ] If the upload answers 503 **after** the work was done, check the assessment's runs before retrying (C.4). A committed run can exist with its files and no worker; a retry returns that run and starts nothing.
- [ ] Use one browser tab. The page polls every 5 s with no in-flight guard, and each poll is several requests; extra tabs multiply them (critic M04, not probed). A sign-in token lasts 480 minutes (`jwt_expire_minutes`); sign in again if it lapses. The worker does not depend on the browser.
- [ ] Record the ZIP's SHA-256 (`Get-FileHash -Algorithm SHA256 <zip>`) in section H. The active-run guard is keyed on it.

### C.4 After the 202

- [ ] The run appears as `#id` with status `queued` or `reading`, the "Scripts" card shows the student count, and "Model calls" shows `0/<limit>` rising.
- [ ] The "Scripts" count equals the number of students in the ZIP. A different number means a silent fold or phantom student (B.2). Stop (G).
- [ ] After a 503 "Bulk evaluation could not be started", open the assessment's run list before doing anything else. Three states are possible:
  1. **No run.** The intake failed before its commit and rolled back, and since the fix wave it also removes the student files it had written (including after a kill). Fix the cause and upload again. Check `uploads\bulk_staging` for a leftover ZIP first (F.4).
  2. **A run `paused` with the error "Bulk worker could not be enqueued".** The intake committed but the queue refused the first job (Redis down). A re-upload no longer rescues it: it returns this run and enqueues nothing. Check Redis (A.3), then press run-level **Resume never-started work**.
  3. **A run `queued` with its students and files but no worker.** The intake committed and a later step raised before the route could enqueue (W07). The student files are kept; before the fix they were deleted. A re-upload does not rescue this either. Wait for the stale window (the heartbeat must be older than 600 s) and then use **Recover interrupted run** (C.5). This path was reasoned from code and **not executed end to end**.

### C.5 Do not click "Recover interrupted run" on a healthy slow call

`Recover interrupted run` appears when the run's last heartbeat is more than 10 minutes old (hard-coded
in `BulkEvaluationClient.tsx`, `heartbeatStale`). The heartbeat is written only at the start and end of a
unit (`run_next`, `_process_read`, `_process_grading`), not per page. A page-read unit reads a whole script, and
the effective call timeout is 600 s (A.5), so a healthy read can leave the heartbeat older than 10 minutes.
The button therefore also appears on a healthy long read. The UI shows no heartbeat time, elapsed time or
ETA; the only on-screen signal is the button itself. The exact `heartbeat_at` is in the run list response
(Network tab of the browser; the UI reads `activeRun.heartbeat_at`).

Pressing it against a live worker is harmful:

- During a page read it is refused, but still pauses the run and kills the worker's chain (PB-6a, strict xfail: `test_pb6_a_refused_recover_during_a_healthy_page_read_does_not_stop_the_worker`).
- During a grading call it is accepted and the in-flight item is marked `uncertain`. The late-landing grade no longer wedges approval: when the grade lands and passes the checks, the `provider_contract_failure` code and its stamp warning are cleared (fixed, PB-6b: `test_pb6_a_late_landing_grade_drops_only_provider_contract_failure_from_the_codes`, `test_pb6_a_late_landing_grade_drops_only_the_recover_stamp_and_keeps_other_warnings`). Any other code or warning on the item is kept. Recover on a healthy slow call is therefore no longer a bulk-approval blocker, but it is still wrong: it marks a live item `uncertain` for no reason and, during a page read, leaves the run paused.
- **Recover and then Resume item while the original call is still running** no longer starts a second provider call (W11). The live job stays open and no new job is created; since 2026-10-12 the run pauses with the item `uncertain` and a message naming the student and question and the time after which to resume (no raw SQL text), and the original call's late landing settles the item once. The next run-level Resume then finishes the run (`test_w11_resume_item_during_a_live_call_never_closes_the_live_job_or_calls_twice`).
- Pressing Recover also **cancels a pending Stop**: run-level resume clears the stop request, so a run the teacher had told to stop carries on (W06 follow-up, still open). Press Stop again after a Recover if the stop is still wanted.

Conservative operator rule derived from PB-6a (not a product guarantee): before pressing Recover,
confirm the run is truly dead.

- [ ] `Get-TeacherPilotStatus.ps1` shows `RQ worker` not ready, or the model server process is idle (no GPU or CPU activity), or the machine was rebooted.
- [ ] The heartbeat has been silent for longer than the 3,600 s job limit the worker chain uses (`worker/jobs.py`), unless the worker is provably dead. On Windows that limit is a soft one, and whether it interrupts a blocked socket read is not verified, so silence beyond it is necessary but not sufficient.
- [ ] Nobody else (another tab, another operator) is pressing buttons on the run.

## D. During the run

### D.1 What to watch

The run page shows: `Run #id · status · stage`; cards for Scripts, Processed packets (x/total),
Model calls (used/limit), Clean drafts and Exceptions; a red box with `run.error` (first 500 characters);
and the exception list as raw snake_case codes. It polls every 5 s, only while the status is active
(not `paused`, `review_ready` or `completed*`). A paused run therefore stops updating on screen: reload the
page to see its current state.

There is no per-student roster, no throughput or ETA, no per-item timeline, no warnings text, and no audit
view. The audit trail is readable only through the database (`docs/PILOT_MONITORING.md`). There is no
notification when a run pauses: any exception in any unit pauses the **whole** run until a person clicks
Resume (`run_next`).

Expected progression:

| Phase | Status / stage | Counters | Operator action |
|---|---|---|---|
| Upload | request pending | none | wait; do nothing |
| Reading | `queued`, then `reading` / `reading` | Model calls rises by the page count of each script read (plus 1 for a script that needs the whole-transcript assignment call) | watch only |
| After reading | `completed_with_exceptions`, clean 0 | every item is an exception `evidence_review_required`; Processed reads total although nothing is graded | transcript review (E) |
| Releasing | `grading` / `grading` after each "Resume Qn grading" click | Model calls rises by 1 per graded item | click per item (E.5) |
| Review | `review_ready` | Clean drafts is the count offered for approval | review and approve (E.7) |
| Done | `completed` or `completed_with_exceptions` | | download (F) |

Watch for these: **Processed packets counts quarantined items as processed**, so "900/900" can mean nothing was graded. The "Exceptions" card is the first thing to read. `run.status` `failed` is never written by the code, so absence of "failed" means nothing.

### D.2 Status meanings

| Status written | Meaning | Normal? |
|---|---|---|
| `queued` | created, first job enqueued | yes, briefly |
| `reading`, `grading` | a unit is running or queued | yes |
| `paused` | a unit raised, the queue failed, the call limit was reached with work left, an in-flight item from an interrupted worker was found, or the reference materials changed after authorisation; `run.error` says which | abnormal; see D.3 and D.4. A paused run now stays paused until a teacher presses Resume or Resume item: a re-upload or a stray queued job no longer un-pauses it |
| `stopping` | Stop was pressed; takes effect at the next unit boundary, after the current call. A pending Stop now survives "Resume item" (D.3 row 5) | yes after Stop |
| `stopped` | Stop took effect | after Stop |
| `review_ready` | no pending work; at least one clean draft. A run that spent exactly its authorised calls now reaches this status instead of stranding `paused` | yes |
| `completed_with_exceptions` | no pending work and no clean draft (first pass, or every draft quarantined, for example as wrong-scale), or approval ran with exceptions left | yes after the first pass |
| `completed` | approval ran and no exception is left | yes |
| `mapping`, `transcribing` | legacy paths, not used by the transcript-first flow | unexpected |

| Item status | Meaning |
|---|---|
| `pending` | not started |
| `running` | a unit has it. After a worker death it can stay `running`; the next unit that would finish the run now marks it `uncertain` and pauses instead of finishing silently (F13, D.3 row 15) |
| `exception` | quarantined by policy, for example `evidence_review_required`, low confidence, or a wrong-scale draft (`provider_contract_failure` with the warning `Draft grade maximum mismatch: expected X, got Y`, D.3 row 16) |
| `uncertain` | interrupted while `running`; always labelled `provider_contract_failure` whatever the cause; never retried automatically. If the interrupted call's grade lands later and passes the checks, that code and its stamp warning are cleared |
| `graded` | a draft exists, not yet a final grade |
| `approved` | a teacher approval created the final grade |

### D.3 Failure states with a supported way forward

| # | Symptom | Likely cause | Safe action | Do NOT |
|---|---|---|---|---|
| 1 | Upload sits for minutes | intake renders every page inside the request (8 to 442 ms per page measured, PD-1a) | wait; `Get-TeacherPilotStatus.ps1` shows the API ready | reload, re-upload, open a second tab |
| 2 | 409 "ZIP exceeds the 720-page bulk limit" (or the 50/500 limits) | page total over the cap, or the `.env.example` limits are live (PE-13) | fix the ZIP or the limits; nothing was imported (PE-5 refused cleanly) | retry unchanged |
| 3 | 409 with a named message ("Could not import ...", "ZIP contains ...", "Authorized provider calls ...", "manifest.csv ..."), or 503 "Bulk evaluation could not be started" | a 409 is a named refusal from the first table in B.2: nothing was imported and the student files already written were removed. A 503 is now only an exception type the intake does not map (for example an `EOFError` from a truncated member, a new library error), an overlapped identical upload (PD-3e), or a failure after the commit (C.4) | for a 409 fix the named member or number and upload again. For a 503 first check the run list for the run (C.4, three states); with no run, nothing was imported and the student files were removed (F.4); bisect the ZIP by member | re-upload at once after a 503 |
| 4 | `paused`, error like "Brain visual page read failed safely: ..." with items `uncertain` | one page read failed or timed out (effective limit 600 s, A.5); the whole run pauses and every running item is marked `uncertain` | read `run.error`; confirm the model server is up; press **Resume never-started work** once. Since 2026-10-13 it revives every read-stage `uncertain` item (a failed page, a failed assignment call, a model unavailable before the first page); pages already read are reused. If it answers "A page-read outcome is unknown and must be reconciled before resuming", the page is `unknown_outcome` (reconcile route exists, audited `script_page_read_reconciled`; whether the UI exposes it is **not verified**) or `dispatched` (DE-1) | press Resume repeatedly; PE-10: a spent read budget spins without progress |
| 5 | `stopping` and stays `stopping`, or a run that went `stopping` then `stopped` after a click on "Resume item" | Stop is honoured at the next unit boundary, so wait for the call to finish. A pending Stop now survives "Resume item": on a paused run the click moves it to `stopping`, the next unit ends it `stopped`, and the item itself is back to `pending` (fixed, PB-5a: `test_pb5_retrying_an_item_does_not_silently_cancel_the_teachers_stop`, `test_pb5_a_stop_pressed_during_a_failing_call_survives_a_later_item_retry`). If Stop was pressed on a `paused` or `review_ready` run no worker exists to settle it, and the run strands `stopping` (PB-5b, strict xfail) | wait for the current call. After a `stopped` caused by a Stop you still want to undo, continue with the run-level **Resume**: it clears the Stop. If nothing is running and the run says `stopping`, wait 10 minutes, then Recover (C.5 rule); Recover also cancels a pending Stop, so press Stop again if it is still wanted | press Stop on an idle `paused` or `review_ready` run (nothing will ever settle it); expect "Resume item" to carry on grading after a Stop (it no longer does) |
| 6 | Resume or "Resume item" answers HTTP 503 "Bulk evaluation could not be resumed" and the run is `paused` with the error "Bulk worker could not enqueue the next unit; resume manually after queue recovery" | the queue was down when the click enqueued (PB-10, fixed: `test_pb10_a_queue_failure_on_a_resume_route_does_not_strand_an_active_run`, `test_pb10_a_queue_failure_on_resume_is_a_visible_503_and_a_later_resume_recovers`); before the fix the answer was 500 and the run was left active with no job. No provider call was made | check Redis with the status script; once the queue is back press the run-level **Resume** again. An "Resume item" click on a run whose own worker chain is still active that hits a dead queue also answers 503 but leaves the run alone (`test_pb10_a_queue_failure_on_item_resume_leaves_an_already_active_run_alone`) | wait for the run to move by itself; click "Resume item" again on the same item (it is already back to `pending`) |
| 7 | Items `exception` with code `unassigned_ink` | the page describes it as "saved transcript needs one whole-document assignment pass" | click **Analyze saved transcript once** (one model call; it spends budget) | skip the transcript review |
| 8 | `approve-clean` answers 409 "Clean draft set changed; refresh before approving" | something changed between loading the approval table and pressing Approve (a per-item decision, a superseded draft). Since 2026-10-12 the run read shows the live hash (PA-1 fixed), so a refresh resolves it | reload the approval table ("Review N clean drafts before approving"), check it again, approve | approve from an old browser tab |
| 9 | `approve-clean` answers 409 "Bulk approval refused; nothing was approved. N draft(s) cannot be finalized: <student> / <question> (draft <id>): ..." | the evidence behind those drafts changed after grading through a path that did not supersede them. Since 2026-10-12 the whole batch is checked first and nothing is written (PA-2a, PA-2d fixed) | for each named draft: reject it, or re-confirm its transcript and "Resume item" to re-grade; then reload the approval table and approve | assume part of the batch was approved (it was not) |
| 10 | Every draft finalised per item | since 2026-10-12 the run completes by itself once nothing is left to decide (PA-1b fixed; audit row `bulk_evaluation_completed_by_individual_review`) and `results.xlsx` downloads | download the bulk workbook as usual | use the assessment-level export instead (it lacks the Exceptions and Run Summary sheets) |
| 11 | A student's row is `INCOMPLETE` although the teacher decided every answer | one of the answers was rejected; a rejection is not a grade (decided policy 2026-10-12; edited grades count and show `EDITED`) | record a score for the rejected answer in individual review if the student should have one | read a `REJECTED` row as a mark of zero |
| 12 | Exceptions list shows a student the transcript page cannot confirm: "Assign every visible writing block to a question before confirming this transcript" | a stray block is unassigned; "Leave unassigned" cannot clear the gate (PC-5f, pinned) | assign it to the question it belongs to, or blank its text, and write down which you did | use "Leave unassigned" on a block after a question's block on the same page (PC-3, E.4) |
| 13 | After a hard kill of a grading call (reboot, force-kill), Recover and then "Resume item" pause the run again with the item `uncertain` and the message "<student> / <question>: an earlier grading call may still be running (a worker stopped mid-call), so it was not sent again. Resume this item after <time UTC>." | the dead worker's `GradingJob` is still `running`. A retry closes it ("Superseded: the earlier attempt did not complete") only when it is provably not live: managed-local, when no unexpired model lease is held under that job (the lease lasts up to 1,800 s after the last heartbeat); unmanaged, when the job is older than the larger of 3,600 s and the provider's job timeout. A job still `queued` never reached the provider and is closed at once. Until then no second job and no second provider call are made and no budget is spent (W11: `test_w11_a_hard_killed_managed_job_stays_open_until_its_lease_expires`, `test_w11_an_unmanaged_job_is_closed_only_once_older_than_the_rq_job_timeout`, `test_w11_a_job_rejected_before_the_provider_is_closed_without_waiting`). A dead worker's unexpired model lease also makes the next provider call pause with "Local model is busy" until it expires (`test_a_dead_holders_lease_blocks_grading_until_it_expires`) | wait until the time in the message. Then press the run-level **Resume**, then **Resume item** on the `uncertain` item; the retry closes the dead job and grades the answer once. Record the kill and the wait in section H | click Resume repeatedly before that time (each press just pauses again); start a second worker; re-upload (it does nothing for a paused run, C.3) |
| 14 | `paused` with the error "Reference materials (questions, model answers or rubrics) changed after this run was authorised; restore them or start a new run" | before each grading unit the run compares the current reference bundle (every question's label, text, model answer and marks, and the active rubric id, version and JSON) with the hash recorded at authorisation. Any difference, including re-extracting or reopening the references, or a bundle that cannot be loaded, pauses the run with no provider call and no spend. There is no re-baseline path (fixed: `test_a_reference_edit_pauses_the_run_before_any_further_provider_call`, `test_references_reopened_for_confirmation_mid_run_pause_the_run_before_the_next_draft`) | restore the edited question, model answer, rubric or marks exactly as they were, then press **Resume** (`test_a_run_paused_by_a_reference_edit_resumes_once_the_reference_is_restored`). If the change was meant, the founder decides whether to start a new run in a fresh assessment, which re-spends every page read. Never edit references mid-run | press Resume without restoring (the next grading unit pauses it again); use "Resume item" on it (it un-pauses and the next unit re-pauses it); assume the drafts graded before the edit are safe (PC-2b) |
| 15 | `paused` with the error "An in-flight item from an interrupted worker was found; use Recover / Resume item", and one or more items `uncertain` | the unit that would have finished the run found an item still `running` (a worker killed mid-call, or a stray unit). The run no longer finishes over it: it marks the item `uncertain` (`provider_contract_failure`) and pauses visibly (fixed: `test_pb8_finishing_a_run_does_not_leave_a_killed_item_running`, `test_pb8_a_finish_over_a_killed_item_pauses_with_a_visible_uncertain_exception`). Nothing is retried automatically | confirm the worker is dead (C.5 rule), press the run-level **Resume**, then **Resume item** on each `uncertain` item. If the item was mid-grade at a hard kill, expect row 13's wait first. If it was a page read, see D.4 DE-1 | treat the run as finished; approve around the item; press Resume while the worker may still be running (with two workers a live item could be flagged, which is why exactly one worker exists) |
| 16 | An item `exception` with the code `provider_contract_failure` and the warning "Draft grade maximum mismatch: expected X, got Y" | the model scored against a maximum other than the question's total marks. The draft stays stored for inspection and is excluded from bulk approval (fixed on the bulk path: `test_a_wrong_maximum_is_quarantined_with_a_visible_code_and_warning`). The individual approve and edit routes are not covered (A.7, PA-7) | read the draft in "Open individual grade review" and do not approve it; check the question's total marks against its rubric maximum (A.7); hand-mark that answer and record it in section H | approve it per item (that route still bounds a grade only by the draft's own maximum); read the code as a provider outage |

Two more behaviours to know on a paused run:

- "Resume item" on one script of a run paused during the **reading** stage behaves like the run-level Resume: it refuses with "A page-read outcome is unknown and must be reconciled before resuming" when a read is `dispatched` or `unknown_outcome`, and it revives **every** script's `failed` page reads, not only the clicked one. The next unit re-reads them, which spends calls for scripts the teacher did not click on. The refusal and the revival are pinned (`test_pb4_resume_item_on_a_run_paused_by_an_unknown_read_outcome_is_refused`, `test_pb4_resume_item_on_a_run_paused_by_a_failed_read_does_not_strand_the_failed_script`); the run-wide reach of the revival is plausible from the code and not demonstrated in a run (W04).
- "Resume item" on a run paused by the call limit or by a reference change un-pauses it and the next unit pauses it again, with one more audit row and no provider call.

### D.4 Known dead ends: no in-product exit

For each state below the product offers no way forward inside this assessment. The workaround is the
honest one. "Fresh assessment" means: create a new assessment, re-finalise the references, and import the
students again. It **re-spends every page read** for the re-imported students (at 10 students the stranded
run spent 70 calls and the re-run needs 100; at 150 students that is hours of real-model time, unmeasured,
PE-9). A new run in the same assessment is refused for students who already exist (PD-3b), and a stopped
or failed run keeps blocking them (PD-3c, pinned). Hand-marking the stranded student outside the system
and leaving the row `INCOMPLETE` is a legitimate lighter exit; record it in section H. Whether a stranded
student can be routed through the older single-script workflow without duplicating records is **not verified**.

| Id | How it shows | Why | Honest workaround | Proof |
|---|---|---|---|---|
| DE-1 (fixed 2026-10-13) | after a worker kill or reboot mid-read, a script's page was left `dispatched` with no exit | Resume now turns a claim older than max(900 s, the job timeout) into `unknown_outcome` (and still refuses). With todays Qwen3.8 settings that is 2,400 s: wait 40 minutes after the crash before pressing Resume; an earlier Resume only answers that the outcome is unknown | reconcile the page as failed (reconcile route), then Resume: only that page is read again | `test_a_killed_worker_can_be_recovered_by_a_teacher` |
| DE-2 | a script's whole-transcript assignment call failed; its items stay `uncertain`; "Resume item" answers "Page-read provider work cannot be retried; create a newly authorized run" | run Resume revives items only for a failed page read; the failed assignment is a known failure that nothing re-runs | no in-product exit: abandon this assessment and re-import into a fresh assessment, which re-spends page reads. Hand-marking that student outside the system is the lighter alternative | `test_a_failed_whole_transcript_assignment_call_can_be_retried` (strict xfail) |
| DE-3 | "model unavailable" before a script's first page read; no page row exists; the run ends `completed_with_exceptions` with that script `uncertain` | same dead end as DE-2; re-import is refused as the students exist | no in-product exit: abandon this assessment and re-import into a fresh assessment, which re-spends page reads. Hand-marking is the lighter alternative | `test_a_model_unavailable_before_a_script_read_can_be_retried` (strict xfail) |
| DE-4 | one hallucinated question label (for example `Q99`) aborts the script after its page was stored `succeeded`; the run pauses; Resume revives nothing | the whole script is stranded for a label the teacher could have corrected | no in-product exit: abandon this assessment and re-import into a fresh assessment, which re-spends page reads. Hand-marking is the lighter alternative | `test_a_hallucinated_question_label_does_not_strand_the_script` (strict xfail) |
| DE-5 | a worker hard-killed in the instant between two commits: the one that creates a grading job and the one that links it to the item. Every later retry of that question pauses with the raw SQL error (`ux_grading_jobs_active_answer_region`) in the red box, with no wait that ever ends | the item does not own the unlinked active job, and the retry closes only the item's own earlier job, never a job it does not own. It fails closed and stays closed. The window is small and was reasoned from code, not reproduced by a kill | no in-product exit for that question: abandon this assessment and re-import into a fresh assessment, which re-spends page reads. Hand-marking that question outside the system is the lighter alternative. Do not confuse it with D.3 row 13, where the same SQL text clears after the wait | `test_f14_a_foreign_active_job_on_the_region_is_left_alone_and_the_unit_fails_visibly` (pins that a job the item does not own is never closed); the kill window itself is not exercised |
| DE-6 (fixed 2026-10-13) | `paused`, "Authorized provider-call limit reached"; items still `pending` | the limit is spent; resume answers "The authorised call limit is exhausted; raise this run's call limit, then resume". Exit: enter a higher limit in "I authorise this new call limit" (at most the server ceiling), then Resume. Before the fix: re-upload returns the same run with its old limit; Stop then re-import is refused; approve answers "not ready for teacher approval"; export is 409. The fix wave narrowed this without removing it: intake now refuses a limit below pages + items (B.3), and a run authorised for exactly its calls finishes (D.2) | no in-product exit: abandon this assessment and re-import into a fresh assessment, which re-spends page reads. Whether the drafts of a paused run can be approved through the individual review page is **not verified**. Authorise strictly above `need` (B.3) | `test_pb7_a_run_that_runs_out_of_calls_continues_after_the_teacher_raises_the_limit`; `test_after_the_authorisation_is_spent_nothing_can_resume_approve_or_export` (pinned) |
| DE-6c | `paused`, "Pages still needing a source read exceed the explicitly authorized page-read call limit"; Resume is accepted but re-pauses; the unread scripts' items are stamped `provider_contract_failure` although no call was made | PE-10 pinned; PE-11 strict xfail | as DE-6; read the stamp as "budget", not "provider" | `test_a_script_refused_for_budget_before_any_provider_call_is_not_blamed_on_the_provider` |
| DE-8 | a corrected ZIP of the same students is refused after a Stop or failure ("student identifier(s) already exist") | submissions are checked regardless of run status (PD-3c, pinned) | fresh assessment | `test_reupload_of_the_same_students_after_a_settled_run_is_refused_naming_them[stopped]` |

**Former dead ends the fix wave closed.** The ids are kept so older notes still resolve. These states have
an exit now, but each one is a different state than before, so read the new row before acting.

| Id | What it was | Now | Where | Test |
|---|---|---|---|---|
| DE-5 (hard kill, not the kill-window case above) | after a hard kill mid-grade, Recover and "Resume item" paused the run with the raw SQL error for good | the retry closes the dead job once it is provably dead and grades once; until then it waits (managed-local up to 1,800 s, unmanaged up to 3,600 s) | D.3 row 13 | `test_a_worker_killed_mid_grading_can_be_regraded` (now passes; its unmanaged fake needs the aged job); `test_w11_a_hard_killed_managed_job_stays_open_until_its_lease_expires` (pins the wait) |
| DE-5b | grading an answer whose text resolved to empty answered 400, left the job `queued`, and the retry then paused with the SQL error | the retry closes that job ("Superseded: the earlier attempt did not complete") and goes on; the reference gate still holds | D.3 row 14 for the reference case | `test_pb2_blank_transcript_text_does_not_strand_the_grading_job`, `test_f14_a_pre_try_rejection_leaves_the_item_pointing_at_the_stranded_job`, `test_pb2_the_retry_supersedes_the_abandoned_job_and_the_reference_gate_still_holds` |
| DE-6b | a run authorised for exactly its need ended `paused` with every item `graded` | the pause fires only while pending or running work remains, so the run ends `review_ready` or `completed_with_exceptions` | D.2 | `test_a_run_authorised_for_exactly_the_calls_it_needs_still_finishes` |
| DE-7 | a run reached `review_ready` or `completed` with an item still `running`, absent from the exception list | the unit that would finish the run marks that item `uncertain` and pauses with "An in-flight item from an interrupted worker was found" | D.3 row 15 | `test_pb8_finishing_a_run_does_not_leave_a_killed_item_running` |
| DE-9 | a stray queued job un-paused a **paused** run and stranded a failed script | `run_next` returns at once for a paused run; only Resume or "Resume item" leave `paused`, and a re-upload enqueues nothing | C.3, D.3 | `test_pb4_a_stray_worker_unit_does_not_un_pause_a_paused_run`, `test_pb4_a_stray_worker_unit_cannot_strand_a_failed_script` |
| DE-10 | a queue failure on a Resume click left an active run with no job (HTTP 500) | HTTP 503 and the run stays `paused`; press Resume again after the queue is back | D.3 row 6 | `test_pb10_a_queue_failure_on_a_resume_route_does_not_strand_an_active_run` |

Timeouts add one more risk: an empty-message `httpx.ReadTimeout` is classified `failed` instead of
`unknown_outcome` (strict xfail, `test_every_kind_of_timeout_is_an_unknown_outcome[httpx-empty-message]`), so
the product treats it as safely retriable although the first attempt may have completed on the model server.
Check the page transcript before retrying a timed-out read.

## E. Teacher review protocol

### E.1 The gate

Grading never starts on unreviewed or stale evidence. Every item is quarantined `evidence_review_required`
after reading until the teacher confirms the script's transcript. The confirmation route requires every page
to have a successful read and a teacher classification, and every visible writing block to be assigned to a
question. It is the only place the review is recorded (`routes/script_transcripts.py`, confirm-review). The
server-side gate cannot be bypassed through the bulk service (PC-6a, refuted). For each script the Exceptions
list shows a card with "1. Review and confirm transcript", which opens that script's transcript page.

### E.2 Per-script checks, in this order

- [ ] **Identity.** Compare the cover page or name area on page 1 with the identifier. Intake is content-blind: a script made of another student's pages is accepted under the file's name (PD-5c, pinned). Also notice any script that looks identical to another (PD-5b).
- [ ] **Orientation, order and page count.** Compare the page images with the physical script. EXIF orientation is now applied to image pages on import (B.2), so a page that is still sideways was saved sideways with no tag, or is a PDF page, which import never rotates. A truncated PDF imports as blank pages, and a page in the wrong place comes from the natural-sort page order (B.2).
- [ ] **Omitted paragraphs.** On every page, compare each paragraph of handwriting with the transcript blocks. The bulk path still has no CPU ink-coverage backstop (RC-11, unchanged by the fix wave, gate item 2), so a block the model silently dropped produces a clean, confident draft with no code and no warning (PC-1, strict xfail: a clean draft at confidence 0.95 built from 2 of 3 blocks). The confidence figure does not warn you; per-block read confidence is stored but never consulted (PC-1d, pinned).
- [ ] **Falsely blank pages.** Any page the model calls blank or non-answer must really be blank. A falsely blank middle page of a multi-page answer is accepted and the question stays "answer present" (PC-1b). A falsely blank **only** page fails closed as `missing_answer` (PC-1c, refuted), so the middle and last pages are where to look.
- [ ] **Ownership.** For each block confirm it belongs to the question it is attached to. The label-based ownership is confirmed by you, not proven by the system. In particular:
  - a model-claimed continuation with no label is blocked until you confirm who owns it (PC-5c, refuted);
  - a label repeated on one page (`Q1`, `Q2`, `Q1`) is merged into one answer with no signal (PC-5d, pinned);
  - blocks returned out of reading order. Since 2026-10-12 the whole-transcript assignment prompt and its validation number the blocks in the store's own saved order, so a provider that ignores top-to-bottom order no longer swaps blocks between questions (fixed, F01: `test_blocks_returned_out_of_reading_order_still_reach_the_right_question`, `test_every_whole_transcript_call_numbers_blocks_in_saved_order_even_on_re_analysis`). **The fix is not retroactive.** A transcript stored before 2026-10-12 with assignment status `complete` keeps whatever ownership it was given, because the transcript fingerprint ignores the numbering. Re-review every such transcript against the page when the provider is known or suspected to have returned blocks out of order. An engineer can audit offline by comparing, for each page, the block order in `raw_output_json` with the persisted block order; this was never run against real data and an agent must not run it against real student data. For a fresh import made after the fix, keep reading each question's resulting evidence text against the page, not only the block list.
- [ ] **Stray marks.** A page number, scribble or margin note needs a decision (E.4).

### E.3 Order of work: transcripts before grading

- [ ] Finish every transcript correction **before** clicking any "Resume Qn grading". A correction after grading supersedes the draft; since 2026-10-12 its item becomes a `stale_evidence` exception (no longer offered for bulk approval, PA-2b fixed) and needs a re-confirmed transcript and "Resume item" (one more model call) or a rejection.
- [ ] A correction that lands while a grading call is in flight leaves a clean draft that is born stale (PC-6d, strict xfail). Do not edit a transcript while its script is grading.
- [ ] After a transcript confirmation, do not edit the reference materials (A.7). A run now pauses at its next grading unit when the reference bundle differs from the one authorised (D.3 row 14), and the only ways on are to restore the edit exactly or to start a new run.
- [ ] If you must correct a graded script's transcript, reject that draft per item, and do not use bulk approve for the run (E.7).

### E.4 "Leave unassigned" and stray blocks

- "Leave unassigned" on a block that **follows a question on the same page** is absorbed by the previous question's evidence (PC-3, strict xfail). The block you meant to exclude gets graded as part of the previous answer.
- On the **first** block of a page it is honoured, but the confirmation then refuses until you assign every block (PC-3 bound; PC-5f).
- The two supported ways past a stray block are to assign it to a question, which is a forced misattribution, or to blank its text, which keeps the model's original text and records an empty edit (PC-5f, pinned). Choose one, and write the student, page and choice in section H. Never leave a stray block "unassigned" and expect it to be excluded.

### E.5 Workload

Expect about 150 transcript reviews. Since 2026-10-13 one press of "Release all reviewed scripts to
grading" replaces the 900 "Resume Qn grading" clicks (RC-68); it releases only scripts whose review is
confirmed and lists what it left out. Release after reviewing a batch of scripts, as often as you like.
Historical (before the fix): Each click enqueues another
chain and refreshes the list (836 KB at 900 items). The 900 resume requests cost 41.1 s of server time in
total on 2026-10-11 and 33.6 s in the final run after the fixes, so the cost is human. Browser behaviour at 900 exception rows was not measured. The workload gate is a
founder decision (gate item 5).

Each approved draft must also be checked:

- [ ] Each draft's maximum equals the question's total marks. On the bulk path the product now checks this: a wrong-scale draft is an `exception` with the warning "Draft grade maximum mismatch" and is excluded from bulk approval (D.3 row 16). The individual approve and edit routes do not check it (PA-7): 10 of 10 on a 5-mark question could still be finalised as 10 marks through "Open individual grade review" and exported as `APPROVED`. Check the maximum on every draft you open there.
- [ ] Feedback matches the evidence, not only the score.

### E.6 Low-confidence drafts and thresholds

The run quarantines a draft whose grade confidence is below the grading-clean threshold (0.80); mapping and
transcription thresholds are 0.90 (measured effective values, 2026-10-11). The thresholds are founder
decisions. Treat confidence as advisory:

- a draft below threshold is an exception; read the evidence and either resume it or grade it by hand;
- a draft above threshold is not proof of completeness (PC-1: 0.95 with a block missing);
- malformed grade output (NaN, `None`, out-of-range confidence, score above maximum) is quarantined, not stored (PC-4b, refuted);
- a draft whose own maximum differs from the question's total marks is quarantined as an exception whatever its confidence (D.3 row 16).

### E.7 Approving

Since 2026-10-12 (founder decision, RC-69) bulk approval is a two-step action. "Review N clean drafts
before approving" loads a per-student table (student, question, draft score / maximum, confidence) of
exactly the drafts that would be finalised. The teacher ticks "I have checked these … draft scores" and
only then can press "Approve N checked drafts", which posts exactly those drafts under the hash of that
view. If anything changes in between (a per-item decision, a superseded draft), the table is discarded
and must be reloaded.

- [ ] Read every row of the table; change anything you disagree with in "Open individual grade review" first, then reload the table.
- [ ] Mixing modes is safe since 2026-10-12: per-item approve, edit or reject before or after the bulk approval no longer wedges the run (PA-1 fixed: the run read shows the live hash), and a run whose drafts were all decided one by one completes by itself (PA-1b fixed).
- [ ] Bulk approve is all-or-nothing (PA-2a fixed). A 409 changes nothing and names every draft that cannot be finalised (student / question / draft id). Reject or resume those, reload the table, approve again.
- [ ] A draft superseded by a transcript correction becomes a `stale_evidence` exception and is never offered (PA-2b fixed). Re-confirm the transcript, then "Resume item" re-grades it (one more model call, which counts against the authorised limit), or reject it. A draft made stale by a reference edit is NOT superseded: it is still in the table, and the approval refuses it by name (D.3 row 9). References must not be edited during a run anyway (A.7).
- [ ] Spot-check each approved grade's maximum against the question total (E.5).
- [ ] A teacher edit is a final grade (exported `EDITED`, counted in totals). A rejection is not a grade: the row is `REJECTED` and the student stays `INCOMPLETE` until a score is recorded (PA-4c, decided policy).

## F. After the run

### F.1 Counts to reconcile

Write each number in section H. The totals must agree; any mismatch is a stop (G).

| Count | Source | Rule |
|---|---|---|
| Students | the ZIP, the "Scripts" card, `Student Totals` rows | all equal |
| Pages | the sum of pages per student in B.4 against stored pages (database count; ask the engineer) | equal |
| Items | `Scripts x questions`; the "Processed packets" denominator | equal |
| Clean drafts + approved + exceptions + still-unreviewed | cards and workbook | sum equals items. If a student is `INCOMPLETE` while `Exceptions` shows 0 for them, suspect an item left `running` or `uncertain` by an interrupted worker (D.3 row 15; the run should have paused, so also check the run is not `paused`) or a rejected draft (PA-4c) |
| Final | `Approved Scores` rows with status `APPROVED` or `EDITED` | equals the teacher's approvals plus edits; no `FinalGrade` may exist before the first teacher decision |
| Model calls | `calls_used` from the card | compare with `need` (B.3); see F.2 |

### F.2 Provider calls versus the ledger

- [ ] Expected `calls_used` = pages + continuation scripts + graded items, plus every retry.
- [ ] `calls_used` can **understate** real model calls: a grading call that raised is never charged (strict xfail `test_a_failed_grading_call_is_charged_to_the_call_budget`). A script refused for budget before any call is stamped as a provider failure although no call was made (PE-11). Take the true model-call count from the model server's own request log if one is kept (**not verified**).
- [ ] If `calls_used` is above the expectation, find the retries. If it is below, find the uncharged failures.

### F.3 Export checks

- [ ] `results.xlsx` has the sheets `Approved Scores`, `Student Totals`, `Exceptions` and `Run Summary`. It contains no raw answer text (PA-4d, refuted).
- [ ] Every `INCOMPLETE` student has a reason: an open exception, an item left `uncertain` or `running` by an interrupted worker (D.3 row 15), a `REJECTED` answer (PA-4c), or a paused run.
- [ ] `EDITED` rows carry the teacher's own score and count in the totals; `REJECTED` rows carry no score (decided policy 2026-10-12). An answer the teacher edited is no longer listed on `Exceptions`.
- [ ] **No cell is a live formula.** Since 2026-10-12 a string cell that starts with `=` (an identifier, a name or the model's feedback) is written as text in both workbooks, the bulk `results.xlsx` and the assessment final-grades export (fixed, F08: `test_pa4a_a_student_label_starting_with_equals_is_not_exported_as_a_formula`, `test_pa4a_model_feedback_is_not_exported_as_a_formula_by_the_assessment_export`, `test_pa4a_neutralize_formula_cells_only_turns_leading_equals_text_into_inert_strings`). A leading `+`, `-` or `@` was never a formula cell in these files (`test_pa4a_control_plus_minus_at_prefixes_stay_inert_text_in_xlsx`). A formula-looking name still deserves a glance: read the names on `Approved Scores` and `Student Totals`, and do not retype one into a cell. The three review workbooks in `packages/evaluation/local_curated_evaluation.py` are not covered; they are not part of this workflow. Keep the independent check below before opening in Excel: copy the `.xlsx` to a scratch folder, rename it `.zip`, expand it, and search the sheets for `<f>` elements:

```powershell
Copy-Item "<results>.xlsx" "<scratch>\results-check.zip"
Expand-Archive -LiteralPath "<scratch>\results-check.zip" -DestinationPath "<scratch>\results-check"
Select-String -Path "<scratch>\results-check\xl\worksheets\*.xml" -Pattern '<f[ >]' | Select-Object -First 5
```

No match is the required result. A match means the neutralisation did not hold for that cell: do not open
the workbook in Excel with editing enabled. The identifier comes from the ZIP and cannot be changed after
import, so record the exception and escalate (G.21).

### F.4 Privacy and cleanup

- [ ] **Look in `uploads\bulk_staging` for a leftover cohort ZIP** after any upload that hit a file-lock error or a hard kill, and after any reboot during an upload. The staged ZIP is removed when intake ends in every in-process exit including a simulated kill (PD-7a, refuted), and a partial copy is removed when staging itself fails (`test_a_failed_staging_write_leaves_no_partial_archive`, `test_the_staged_archive_is_removed_when_staging_itself_refuses`). Two cases still leave `uploads\bulk_staging\bulk-<id>.zip` (up to 1 GiB of student scripts): a hard kill or power loss, and a Windows file lock (antivirus or indexer) on the delete. The locked-file case no longer replaces a successful 202 with a 503, and **nothing is logged** for it (W12, `test_a_locked_staged_archive_never_replaces_the_intake_outcome`). **Nothing ever sweeps that folder** (`test_nothing_in_the_application_ever_sweeps_the_staging_folder`, pinned). List the folder and delete any leftover with the engineer, under the retention rule.
- [ ] A failed or interrupted intake now removes its own student files automatically: the failing student's files and every already-imported student's files, also for a kill or interrupt that unwinds normally (fixed, F03b: `test_a_failed_intake_leaves_no_student_file_on_disk`, `test_an_interrupted_intake_leaves_no_student_file_on_disk`, `test_an_undecodable_image_page_leaves_no_student_file_on_disk`). After the commit a later failure no longer deletes the committed students' files (`test_a_failure_after_the_commit_keeps_the_committed_runs_student_files`; C.4 state 3). A hard kill that skips the clean-up can still leave `uploads\submissions\` and `artifacts\pages\` directories with no database row; check them after a hard kill, with the engineer (that case was reasoned, not exercised).
- [ ] On Windows, a file held open by an antivirus or indexer can still make clean-up leave a directory behind (critic M01, needs a probe). Verify after a refused upload that the directories are gone.
- [ ] The operator's own copies are handled: the source ZIP, the downloaded workbook(s) and any working folder are kept only under the retention rule.
- [ ] Apply `docs/STUDENT_SCRIPT_PRIVACY_AND_RETENTION.md`: real student source files are deleted within 7 days after the review, or sooner on the teacher's or founder's request; crops and evidence packets go with the source files; draft grade suggestions and provider artifacts go with the assessment unless explicit audit retention is approved; approved final grades are kept only for the agreed period.
- [ ] Deleting a submission hard-deletes its final grades, suggestions, jobs and regions, and the delete route does not check for an active bulk run. Stop the run and wait for `stopped` first.
- [ ] Write the deletion report that document requires: assessment id, submissions deleted, file paths deleted or missing, counts of `GradeSuggestion`, `FinalGrade` and `GradingJob` before and after, unresolved deletion errors.

## G. Stop conditions

Stop immediately, press "Stop after current call" if the run is active, and escalate to the founder. Do not
edit code, change the environment or re-upload. The first eleven are the hard stops in
`docs/BATCH_SAFE_AND_TEACHER_PILOT_GATE.md`; the rest are new for bulk.

1. An unexpected provider or model call.
2. A Codex or provider authentication or model failure.
3. Usage-limit or rate-limit uncertainty.
4. Private or unapproved data appears.
5. The teacher cannot tell draft from final state.
6. An evidence packet is incomplete but grading appears possible.
7. Queue stale state is unclear.
8. A duplicate `GradeSuggestion` or an unexpected `FinalGrade` appears.
9. An export includes unapproved draft rows.
10. Cross-teacher data exposure is suspected.
11. Artifact deletion or privacy behaviour is unclear.
12. The "Scripts" count does not equal the number of students in the ZIP (silent fold, phantom student, or a student created twice).
13. A `FinalGrade` exists before the first teacher approval click, or the approved count exceeds the teacher's clicks.
14. `calls_used` differs from the expectation (F.2), or any run is on a model other than the one authorised.
15. A run reaches `review_ready` or `completed` with an item still `running`, or an `INCOMPLETE` student has no exception.
16. A raw SQL error appears in the red error box. After a hard kill it is the expected wait of D.3 row 13 and clears when the window ends. A Recover followed by "Resume item" while the original call is still running gives the same text (C.5). Anywhere else it may be the permanent state of D.4 DE-5, so stop and escalate.
17. `approve-clean` answers 409 for any reason, or an approved grade exceeds its question total.
18. Any unexpected reboot, or the model server, queue or worker stops. A reboot is data: tell the founder rather than retrying (it also starts a clock on the dead ends in D.4).
19. Any source, `.env` or branch change during the run (A.4).
20. Free disk space below the margin chosen in A.6.
21. Any cell in an export is a formula (F.3).
22. A transcript was corrected after its draft existed and bulk approve is still planned (E.3).
23. The run pauses with "Reference materials ... changed after this run was authorised", or any question, model answer, rubric or marks value was edited after authorisation (A.7, D.3 row 14). There is no re-baseline path, so the founder decides between restoring the edit and a new run.

## H. Sign-off sheet

Generic. No student data goes on this sheet. Student ids on paper are identifiers the teacher already holds.

| Field | Value |
|---|---|
| Date |  |
| Operator / observer / teacher |  |
| Assessment id / run id |  |
| ZIP name and SHA-256 |  |
| Students / total pages / questions |  |
| `need`, `pages + items` (B.3) and chosen call limit |  |
| Data class (synthetic or approved real) and written approval ref |  |

| # | Item | Expected | Observed | Initials |
|---|---|---|---|---|
| 1 | Founder authorised exact scope in writing (A.1) | yes |  |  |
| 2 | `COHORT_MODEL_GRADING_ENABLED` | false |  |  |
| 3 | `stability-watch.ps1` verdict, 7-day bugchecks | stable, 0 |  |  |
| 4 | `Get-TeacherPilotStatus.ps1 -RequireCore` | exit 0, all Ready |  |  |
| 5 | Memurai uptime | below ten days |  |  |
| 6 | Source freeze, other agents closed (A.4) | confirmed |  |  |
| 7 | `bulk_max_submissions` | 150 or more |  |  |
| 8 | `bulk_max_pages` | at least total pages |  |  |
| 9 | `bulk_max_provider_calls` and server ceiling | at least limit, at most 2000 |  |  |
| 10 | `qwen38_timeout_effective` | recorded (600 expected) |  |  |
| 11 | Free disk vs `peak` formula (A.6) | free at least peak plus margin |  |  |
| 12 | Question labels unique ignoring case (A.7) | yes |  |  |
| 13 | Question total marks equal rubric maximum (A.7) | yes |  |  |
| 14 | Reference freeze: no question text, model answer, rubric or marks edited after authorisation; the run never paused with "Reference materials ... changed" (A.7, D.3 row 14) | yes, never paused |  |  |
| 15 | B.2 manual checks, one tick per row | all pass |  |  |
| 16 | Preflight script output kept; flagged lines | none unresolved |  |  |
| 17 | PDFs opened to the last page; none password-protected or empty | yes |  |  |
| 18 | Pages counted before upload; `pages + items` and `need` both written in the header (B.3) | recorded |  |  |
| 19 | Authorised call limit above `need` and not below `pages + items`; the intake raised no "Authorized provider calls ... below the minimum" refusal (B.3, C.2) | yes |  |  |
| 20 | One upload, one tab (C.3) | yes |  |  |
| 21 | "Scripts" count equals students in ZIP | equal |  |  |
| 22 | Heartbeat checked before any Recover (C.5) | n/a or confirmed dead |  |  |
| 23 | Transcripts confirmed, identity and omission checks done (E.2); any transcript made before 2026-10-12 re-reviewed for block ownership | all scripts (n/a for a fresh import) |  |  |
| 24 | Stray-block decisions recorded (E.4) | list |  |  |
| 25 | Transcript corrections finished before grading (E.3) | yes |  |  |
| 26 | Approval mode chosen and not mixed (E.7) | per item or bulk, one |  |  |
| 27 | Drafts with "Draft grade maximum mismatch" inspected and none approved; the maximum checked on every draft opened for individual review (D.3 row 16, E.5) | none approved, list |  |  |
| 28 | Dead-end items hand-marked (D.4); any hard kill and the wait before the retry recorded (D.3 row 13) | list |  |  |
| 29 | Counts reconcile (F.1): items, clean, approved, exceptions | equal |  |  |
| 30 | `calls_used` vs expectation (F.2) | explained |  |  |
| 31 | No formula cells in exports (F.3) | none |  |  |
| 32 | `uploads\bulk_staging` listed after every upload, and after any file-lock error or hard kill; leftover staged ZIPs and orphan student files swept (F.4) | folder empty |  |  |
| 33 | Retention path applied, deletion report filed | filed |  |  |
| 34 | Stop conditions encountered (G) | none or listed |  |  |

## Evidence index and items not verified

Not verified, by evidence or by design:

- The live `.env.local-ai` and `.env` contents. Only the effective values the lead measured are quoted, and the A.5 snippet was not executed by the author of this document.
- Real-model wall-clock and per-page latency. No model call was authorised.
- Whether a framework spool copy of the upload exists in the system temp directory.
- The output format of `stability-watch.ps1`.
- Whether the UI exposes the page-read reconcile action, the assessment-level export, or approval of a paused run's drafts through the individual review page.
- The call cost of retrying one script's page read.
- Real scan sizes (all disk numbers are synthetic floors) and PostgreSQL growth per run.
- Browser behaviour with 900 exception rows, and the 5 s poll payload (836 KB at 900 items) under several tabs.
- A real `kill -9`, RQ job-timeout behaviour on Windows, Redis persistence of a queued job after a hard reboot, and cross-student KV-cache isolation in the single-slot model server (critic M09). A stale queued job can no longer un-pause a paused run (D.3, fixed), but whether Redis keeps one across a reboot is not verified.
- Legacy per-region grading routes acting on bulk regions (critic M05).
- The retry-after-hard-kill wait (D.3 row 13) was exercised with simulated kills and aged jobs or leases, never with a real process kill. The lease and job windows (1,800 s, 3,600 s) are taken from the code and the fix-wave results. Two latent fail-opens need a second worker or a call longer than the lease: an expired lease does not prove the call is dead, and the lease is released slightly before the job's final commit.
- A kill between the commit that creates a grading job and the commit that links it (D.4 DE-5): reasoned from code, not reproduced.
- The "committed `queued` run with files but no worker" state (C.4 state 3) and its recovery after the 600 s stale window: reasoned from code, not executed end to end.
- Whether the three-wave fix changes anything on the real model path: every post-fix check ran on an in-process fake provider against a disposable database, and no model, network or service call was made.
- The founder decisions listed under "Purpose and status", including the new call-limit refusal (B.3) and the reference-freeze rule (A.7, D.3 row 14).

**Tests cited since the fix wave (2026-10-12).** These are not strict xfails: they passed in the final run
below, and each guards behaviour this checklist now relies on. The names are exact and live in the files
named above. A pass proves the behaviour only on the fake provider and the disposable database.

| Area | Tests |
|---|---|
| Named intake refusals (B.2) | `test_every_unusable_member_is_refused_with_a_teacher_readable_error`, `test_an_unusable_member_is_refused_naming_it_and_keeping_the_original_error`, `test_a_member_with_a_damaged_compressed_stream_is_named_not_an_opaque_503`, `test_a_damaged_manifest_is_named_as_the_manifest_not_as_an_invalid_zip`, `test_an_unrecognised_failure_while_importing_a_member_still_surfaces_as_itself`, `test_a_duplicated_member_is_refused_naming_it`, `test_a_duplicated_page_inside_a_student_folder_is_refused`, `test_a_duplicated_manifest_is_refused_not_last_one_wins`, `test_a_case_variant_of_manifest_csv_is_refused_not_last_one_wins`, `test_a_root_file_and_a_folder_of_the_same_name_are_refused_naming_both`, `test_an_overlong_name_is_capped_in_the_member_and_folder_refusals`, `test_a_malformed_manifest_row_refusal_names_the_line_and_the_cause`, `test_a_trailing_empty_manifest_cell_is_still_accepted`, `test_a_duplicate_identifier_refusal_names_both_colliding_sources`, `test_an_unknown_manifest_source_refusal_names_every_offender_up_to_five`, `test_an_authorisation_below_pages_plus_items_is_refused_with_409_and_nothing_is_kept`, `test_an_authorisation_of_exactly_pages_plus_items_is_accepted` |
| Identity, sidecars, orientation (B.2) | `test_a_dotted_student_folder_keeps_its_full_name`, `test_an_appledouble_sidecar_is_not_a_student`, `test_names_differing_only_in_case_are_not_a_duplicate_member`, `test_a_file_that_merely_contains_a_dot_underscore_is_not_ignored`, `test_exif_orientation_is_applied_to_the_stored_page`, `test_an_upright_photo_is_stored_pixel_for_pixel_unchanged` |
| Clean-up after a failed intake (F.4) | `test_an_interrupted_intake_leaves_no_student_file_on_disk`, `test_an_undecodable_image_page_leaves_no_student_file_on_disk`, `test_a_failure_after_the_commit_keeps_the_committed_runs_student_files`, `test_a_locked_staged_archive_never_replaces_the_intake_outcome`, `test_nothing_in_the_application_ever_sweeps_the_staging_folder` (pinned) |
| Re-upload, pause and Stop (C.3, D.3) | `test_pb4_an_idempotent_reupload_does_not_enqueue_another_worker_chain`, `test_pb4_an_idempotent_reupload_never_imports_a_second_copy`, `test_pb4_a_stopped_run_is_not_silently_restarted_by_a_reupload`, `test_pb4_a_stray_worker_unit_does_not_un_pause_a_paused_run`, `test_pb4_resume_item_on_a_paused_run_is_the_teachers_explicit_resume`, `test_pb5_transcript_assignment_retry_keeps_a_stop_left_behind_a_pause`, `test_pb5_a_stopping_run_whose_worker_died_is_recoverable_once_its_heartbeat_is_stale` (pins that Recover clears a pending Stop) |
| Reference freeze and wrong scale (A.7, D.3 rows 14 and 16) | `test_a_reference_edit_pauses_the_run_before_any_further_provider_call`, `test_a_run_paused_by_a_reference_edit_resumes_once_the_reference_is_restored`, `test_references_reopened_for_confirmation_mid_run_pause_the_run_before_the_next_draft`, `test_pb2_a_model_answer_edited_mid_run_is_held_by_the_reference_gate_and_never_graded`, `test_a_wrong_maximum_is_quarantined_with_a_visible_code_and_warning`, `test_pa7_a_draft_on_the_wrong_scale_never_becomes_an_approved_final_grade` |
| Hard kill, retry and finishing (D.3 rows 13 and 15) | `test_f14_a_killed_item_records_its_own_job_and_only_that_job_is_closed`, `test_f14_a_foreign_active_job_on_the_region_is_left_alone_and_the_unit_fails_visibly`, `test_w11_resume_item_during_a_live_call_never_closes_the_live_job_or_calls_twice`, `test_w11_managed_local_a_job_rejected_before_the_provider_is_closed_without_waiting`, `test_a_hard_kill_leaves_the_managed_lease_held_by_the_dead_worker`, `test_a_dead_holders_lease_blocks_grading_until_it_expires`, `test_pb8_a_finish_over_a_killed_item_pauses_with_a_visible_uncertain_exception` |
| Recover on a healthy call (C.5) | `test_pb6_a_recover_pressed_during_a_healthy_grading_call_does_not_block_approval`, `test_pb6_a_late_landing_grade_drops_only_provider_contract_failure_from_the_codes`, `test_pb6_a_late_landing_grade_drops_only_the_recover_stamp_and_keeps_other_warnings` |
| Queue failure on resume (D.3 row 6) | `test_pb10_a_queue_failure_on_resume_is_a_visible_503_and_a_later_resume_recovers`, `test_pb10_a_queue_failure_on_item_resume_leaves_an_already_active_run_alone` |
| Exports (F.3) | `test_pa4a_a_student_label_starting_with_equals_is_not_exported_as_a_formula`, `test_pa4a_model_feedback_is_not_exported_as_a_formula_by_the_assessment_export`, `test_pa4a_neutralize_formula_cells_only_turns_leading_equals_text_into_inert_strings`, `test_pa4a_control_plus_minus_at_prefixes_stay_inert_text_in_xlsx` |
| Block order (E.2) | `test_every_whole_transcript_call_numbers_blocks_in_saved_order_even_on_re_analysis`, `test_blocks_returned_in_reverse_order_are_recorded_as_such`, `test_a_script_answered_in_reverse_order_reaches_the_right_questions` |
| Call budget (B.3, D.2) | `test_an_authorisation_below_pages_plus_items_is_refused_at_intake_and_a_lowered_run_pauses`, `test_ten_students_authorised_for_exactly_their_calls_still_reach_review_ready` |

Proven-defect and policy tests are in `apps/api/tests/test_bulk150_approval.py`, `_evidence.py`, `_intake.py`,
`_recovery.py`, `_scale.py`, `_poison_fixtures.py` and `_harness_smoke.py` (support code in `bulk150_harness.py` and
`bulk150_poison.py`). Baseline on 2026-10-11 against a disposable PostgreSQL 17.10 (not the pilot database):
`python -m pytest -q` gave 841 passed, 6 skipped in 93.78 s; `python -m ruff check .` passed; the frontend
`npm run lint` and `node tests/workflow-ui.test.mjs` passed.

**Final run after the fix wave, 2026-10-12.** The lead repeated the run on the same disposable PostgreSQL
17.10 (127.0.0.1:55432, scratch storage) with the tree at the baseline plus the three-wave production diff
and the untracked tests and documents; nothing was committed.

| Check | Result |
|---|---|
| Full backend suite, `python -m pytest -q tests` in `apps/api` | 1188 passed, 13 skipped, 47 xfailed, 0 failed, 2 warnings in 246.88 s. The pre-existing tests are exactly 841 passed and 6 skipped, as at the baseline; the bulk150 files add 347 passed, 7 skipped (the guarded heavy scale tests) and 47 xfailed |
| The same bulk150 files with `--runxfail` | 47 failed, 347 passed, 7 skipped in 166.67 s. The 47 failures are exactly the 47 strict-xfail cases, all `AssertionError`, with 0 precondition failures and 0 unexpected passes, so each remaining xfail still proves a live defect |
| Heavy scale tests (`TA_BULK150_SCALE=1`, `test_bulk150_scale.py`) | 25 passed, 3 xfailed in 443.24 s, including the 150 x 4 x 6 headline, the scaling curve for N = 10 to 80, the PDF layout at 30 students, and kill-between-units at 30 students over 4 plans, whose item-state digest equals the uninterrupted run's |
| `python -m ruff check --no-cache .` in `apps/api` | All checks passed |
| Frontend `npm run lint` (`tsc --noEmit`) and `node tests/workflow-ui.test.mjs` | exit 0 and "frontend workflow static checks passed". No `apps/web` file was touched and `npm run build` was not run |
| Headline 150 x 4 x 6 with the fake provider (pipeline overhead only) | intake 2.151 s; read drain 23.147 s; teacher gate 3.324 s; 900 resume calls 33.605 s; grading drain 112.324 s (901 units, mean 124.6 ms); approve-clean 7.909 s (900 approved); export 0.385 s. Sum of the product phases 182.8 s. 149,998 SQL statements in total (143,696 before the fixes: the new reference-bundle check adds 6 per grading unit). Peak RSS 199.1 MiB. 1,500 calls (600 reads and 900 gradings); 3,600 evidence texts inspected with no cross-student leakage; no `FinalGrade` before the teacher's approve-clean. The item-state digest is identical to the pre-fix runs |

Counts: 47 strict-xfail cases remain (about 95 before the fix wave). Real-model time is in none of these
figures.
