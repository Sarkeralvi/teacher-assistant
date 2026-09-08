# Founder Pilot Rehearsal — Readiness Protocol

Companion to `docs/FOUNDER_PILOT_REHEARSAL.md`. That document is the rehearsal
sequence. This one is what must be settled *before* the sequence is scheduled,
so that decisions are made in writing rather than improvised during a live,
teacher-supervised run.

Prepared 2026-09-08 at commit `29502c5`. Nothing in this document authorizes a
provider call, an upload, an export, or a stack operation.

---

## 1. Claim boundary — what a rehearsal `PASS` may and may not claim

A completed rehearsal is evidence about **procedure**, on a sample of one. It is
not evidence about accuracy. This section must be signed before the run, not
after, so that a pass cannot be reinterpreted once it exists.

### A rehearsal `PASS` may claim

- The Custom Controlled sequence completes end to end with every teacher gate
  present and in the documented order.
- Each phase ran as a separate task with fresh context, and mapping,
  transcription, and full-answer confirmations were separately performed.
- No retry, fallback, cloud call, or `FinalGrade`-before-approval occurred in
  this run.
- The approved-only export excluded pending and rejected rows in this run.

### A rehearsal `PASS` may NOT claim

- **Anything about transcription accuracy.** n = 1 packet. The project holds
  only 6 unique handwriting images in total and one prior teacher-signed
  single-image transcription smoke.
- **Anything about grading accuracy or mark quality.** That is the 20-case
  curated gate's job, and only a teacher-signed `PASS` from that gate can speak
  to it.
- **Any calibration of the Bulk Supervised confidence thresholds** (mapping and
  transcription auto-pass at `0.90`, grading clean at `0.80`). Those remain
  chosen, not calibrated; the one recorded real over-score in project history
  occurred at `0.82` confidence, which clears the clean-grading threshold.
- **That escalation thresholds are validated.** They remain PROVISIONAL.
- **Readiness for a broader teacher pilot.** `docs/FOUNDER_PILOT_REHEARSAL.md`
  states this directly: a successful rehearsal is necessary but does not replace
  the signed curated quality evaluation.

### Gate independence

The rehearsal and the 20-case curated quality gate test different things and
neither substitutes for the other. Both must be satisfied. A rehearsal `PASS`
does not shorten, weaken, or partially discharge the curated gate.

### Sign-off

> I have read the claim boundary above and agree that a rehearsal `PASS` claims
> only what Section 1 permits.
>
> Founder/teacher: ____________________   Date: ____________

---

## 2. Failure handling — decided before the run

`docs/FOUNDER_PILOT_REHEARSAL.md` enumerates what fails a rehearsal but does not
name a legal recovery state. Without one, an operator improvises under time
pressure, which is exactly how a no-retry rule gets broken. The following is the
decision to be confirmed by the founder before scheduling.

**Default rule: abort and log. There is no resume, and no same-run retry.**

| Event | Action |
|---|---|
| Local Qwen3.8 call fails cleanly (timeout, HTTP error, lease refused) | Stop. Record the phase, run/job IDs, timing, and sanitized error. Do **not** re-issue the call. The rehearsal ends as ABORTED, not FAILED — abort is not a quality verdict. |
| Model returns an unfaithful transcript | Not an abort. This is a valid teacher rejection inside the documented sequence: reject the draft, do not correct it, and follow the runbook's reject path. |
| `[unclear correction]` appears in a transcript | Not an abort. Teacher decides reject or accept-as-shown under the normal transcript gate. Record which. |
| Mapping geometry wrong | Not an abort. Reject the mapping; a re-map is a documented teacher action, not a provider retry. Record the count of mapping attempts. |
| Hash mismatch at any confirmation | Stop. This is an integrity event. Record and end the run as ABORTED. Do not confirm. |
| Machine bugchecks mid-run | Run is ABORTED and is **not resumable**. The next attempt starts from a fresh assessment. Record the bugcheck as data (per the machine's known stability fault); do not silently restart. |
| Any pending draft exists when the run aborts | Leave it pending. Do not approve, export, or delete to "clean up". |

**Restart policy.** A new attempt after an abort uses a new assessment and a new
run ID. Nothing from the aborted run is reused, and no artifact from an aborted
run may be cited as rehearsal evidence.

> Confirmed by: ____________________   Date: ____________

---

## 3. Preflight — startup path and storage root

The repository has a recorded incident of this exact class: a hand-started API
used storage root `E:\data` while the pilot runtime used
`E:\teacher-assistant\data`, producing database records for reference PDFs the
worker could not find. Rehearsal day is precisely when someone starts something
by hand. Verify, do not assume.

1. Confirm the stack was started only by the supported launcher
   (`scripts\pilot\Start-TeacherPilot.ps1`), and that no ad-hoc Uvicorn process
   is running.
2. Confirm all six services report ready via
   `scripts\pilot\Get-TeacherPilotStatus.ps1 -RequireAll`: PostgreSQL,
   Redis/RQ, backend, RQ worker, frontend, and loopback-only Qwen3.8.
3. Confirm the API's effective storage root is `E:\teacher-assistant\data` and
   record the value observed, not the value expected.
4. Confirm `COHORT_MODEL_GRADING_ENABLED=false`.
5. Confirm the worktree is clean and record the commit hash.
6. Confirm no previous draft, job, or final grade exists for the rehearsal
   assessment.
7. Run the Qwen3.8 preflight from `docs/LOCAL_AI_RUNBOOK.md`; confirm only
   Qwen3.8 is resident and that PaddleOCR and Qwen3.6 are not.

Each item is recorded as an observed value in the evidence record
(`docs/templates/REHEARSAL_EVIDENCE_RECORD.md`), not as a tick.

---

## 4. Per-phase pass/fail criteria

The founder should be checking a list, not judging live. Each criterion below is
either observable in the UI, in a database record, or in the Qwen server log.
Where an exact artifact location is not yet pinned, it is marked **[locate
before the run]** — resolve it during preflight rather than mid-run.

### Phase 1 — Reference extraction

- Exactly one Qwen3.8 visual call is made. Call count observed in the Qwen log.
- Thinking/reasoning is off for that call.
- Every extracted question, solution, mark, and rubric criterion is compared
  against the source before any confirmation.
- Only accurate references are confirmed; a partial confirmation is recorded as
  such.

### Phase 2 — Mapping

- Mapping is a separate call with fresh context.
- Teacher confirms **geometry only**. Confirming a region must not mark any
  transcript text as confirmed — verify this in the record, since the
  non-transitivity of confirmations is a stated safety property.

### Phase 3 — Transcription

- One transcription call for one confirmed region, fresh context.
- Displayed draft is compared against the source image before the hash is
  confirmed.
- Confirming the transcript must not set full-answer coverage. Coverage is a
  separate, explicit confirmation.
- Any `[unclear correction]` marker is recorded with its case, without copying
  the surrounding answer text.

### Phase 4 — Grading

- Grading receives **text only**. No image reaches the grading call.
  **[locate before the run]** — identify where this is observable (request
  payload log or dispatch record) so it is checked, not assumed.
- Fresh context; exactly one grading call.
- The result is a **pending suggestion**: `needs_review` true, no `FinalGrade`
  row, and a zero cost estimate.
- Review flags include local-provider, image-input-disabled, and
  teacher-review-required markers.

### Phase 5 — Teacher decision and export

- Approval, edit, or rejection is performed manually by the teacher.
- If exporting, the approved-only XLSX contains no pending or rejected rows —
  verified by opening it, not by trusting the filter.

### Whole-run criteria

- Total provider calls equal the sum of the per-phase calls above. Any extra
  call fails the run.
- Retry count zero, fallback count zero, cloud call count zero.
- No `FinalGrade` exists at any point before the teacher's explicit approval.
- Phase order matches the documented sequence.

---

## 5. Guardrail verification — performed 2026-09-08, code reading only

Item raised in review: *"any violation fails the rehearsal" needs enforcement,
not just a rule.* What was checked, and what was found.

**Enforced in code (verified):**

- `apps/api/app/core/config.py:197` — `cohort_provider_retry_count` is
  constrained `ge=0, le=0`. A non-zero retry count cannot be configured; the
  settings model rejects it.
- `apps/api/app/core/config.py:193` — `cohort_model_grading_enabled` defaults to
  `False`.
- `apps/api/app/services/grading_dispatch_service.py:257` — a heartbeat-expired
  in-flight item is marked `uncertain` with the message *"Worker heartbeat
  expired during a provider call; no retry is allowed"*. It is not re-dispatched.
- `apps/api/packages/evaluation/local_curated_evaluation.py` — the curated gate's
  `GradingRunResult` pins `retry_count`, `fallback_call_count`, and
  `cloud_call_count` as `Literal[0]`, so a run recording any of them fails
  validation rather than being reported.

**Documented but not asserted by a test (residual gap):**

- `apps/api/packages/brain/llama_cpp_qwen38_vision_provider.py:22-23` states
  zero-retries and no-provider-fallback as a **docstring invariant**. A search of
  that module found no retry loop, which is good evidence, but absence of a loop
  is not a test that would fail if one were added later. Treat this as an
  unasserted invariant.

**Grep caution for future readers:** matches for `fallback` in
`apps/api/packages/brain/policy.py` are `_coalesce` settings defaults
(`policy.py:296-297`), i.e. "use this default when the setting is unset". They
are not a provider fallback path. Do not read them as one.

**Not covered by this verification:** the silent-failure case. A misclassified
cancellation in final-intent transcription produces a plausible transcript, not
an error. No guard fires, and the teacher confirms text that looks correct.
Nothing in the retry/fallback machinery addresses this; only the teacher's
image-versus-draft comparison does. This is the reason the transcript gate
cannot be rushed.

---

## 6. Curated quality gate — state as of 2026-09-08

The 2026-08-31 handoff and the historical `TA-LOCAL-005` backlog entry state
that the 20-case curated gate "is not runnable because its OCR stage is not
rewired". **That claim is contradicted by the code at commit `29502c5`.**

Evidence, from `apps/api/packages/evaluation/local_curated_evaluation.py`:

- `:28` — `PROTOCOL_VERSION = "local-curated-qwen38-vision-v2"`.
- `:302-335` — `OcrCaseResult` pins `provider: Literal["llama_cpp_qwen38"]`,
  `model: Literal["qwen3.8-27b-q4km"]`, `profile:
  Literal["qwen38_verbatim_visual"]`, `reasoning_mode: Literal["off"]`.
- `:2559` — `run_ocr_stage` exists and is wired to that path.
- `docs/LOCAL_CURATED_EVAL_RUNBOOK.md` §3 documents a live
  `run-ocr --allow-local-ocr --max-ocr-calls 20` invocation.

**Rewired is not the same as runnable, and runnability was not verified.** The
one available non-provider check —
`apps/api/tests/test_local_curated_evaluation_integration.py` — could not
execute: it errored at setup with
`sqlalchemy.exc.OperationalError: (psycopg.errors.ConnectionTimeout) connection
timeout expired` against `teacher_assistant_test`, because the pilot stack is
not running and starting it was not authorized. No `prepare` or `run-ocr` was
executed. The gate's real runnability is therefore **still unconfirmed** — but
the stated *reason* for it being unrunnable is stale and should not be repeated.

### Open contradiction, recorded not resolved

`docs/LOCAL_CURATED_EVAL_RUNBOOK.md` §4 instructs a Qwen3.8 text-grader run:

```
run-grading --run-id $candidateRunId --allow-local-qwen --max-qwen-calls 18 --expected-model qwen3.8-27b-q4km
```

That command will be refused. `local_curated_evaluation.py:3651` rejects any
`expected_model` outside `SUPPORTED_GRADING_MODELS`, which at `:33` is
`("qwen3.6-35b-a3b-q4km",)` only. The CLI's `--grading-model` choices at `:4659`
are likewise restricted to that tuple, and the integration test collects a single
parameter, `[qwen3.6-35b-a3b-q4km]`.

Two readings are equally consistent with the source and this was **not**
adjudicated here:

1. The runbook is stale — Qwen3.8 grading was retired from executable contracts
   (as the comment at `:34-36` asserts), and §4's Qwen3.8 arm should be removed.
2. The guard is wrong — the comment at `:30-32` says the Qwen3.6/Qwen3.8 grading
   bake-off is still undecided, and `_operator_asset_metadata` (`:2113-2118`) and
   the settings check (`:1859-1866`) both still accept `qwen3.8-27b-q4km`, so
   `prepare` will pin a model that `run-grading` then refuses.

Either way, running the gate as documented will hard-fail partway through, after
teacher ground-truth signing and after 20 visual calls have been spent. **Resolve
this before the curated gate is next attempted.** The decision is the founder's.

---

## 7. What is still open

- Items 1 and 2 above require founder signatures; they are unsigned as written.
- The curated gate's runnability is unverified (Section 6).
- The runbook/guard contradiction is unresolved (Section 6).
- The Qwen3.8 vision provider's zero-retry invariant is unasserted (Section 5).
- The working branch is 130 commits ahead of `origin/master` and unpushed, on a
  machine with a documented stability fault. A bugcheck can destroy both a
  rehearsal run and the unpushed work. Pushing requires explicit authorization.
