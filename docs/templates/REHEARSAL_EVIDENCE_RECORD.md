# Rehearsal Evidence Record — fill-in template

Copy this file for each attempt. Fill it **during** the run, field by field, not
from memory afterwards. Every field is either an observed value or `n/a`; an
empty field means the run is not fully recorded.

**Do not copy raw student or synthetic answer text into this record.** Reference
answers by case/region ID and by hash only. Use synthetic or founder-authorized
material only.

Companion documents: `docs/FOUNDER_PILOT_REHEARSAL.md` (the sequence),
`docs/FOUNDER_PILOT_REHEARSAL_READINESS.md` (claim boundary, abort rules,
per-phase criteria).

---

## 0. Run identity

| Field | Value |
|---|---|
| Attempt date (UTC) | |
| Operator | |
| Founder/teacher present | |
| Commit hash (`git rev-parse HEAD`) | |
| Worktree clean at start (`git status --short` empty) | |
| Claim boundary signed (Readiness §1) | |
| Abort policy confirmed (Readiness §2) | |

## 1. Preflight observations (Readiness §3)

| Check | Observed value |
|---|---|
| Stack started by `Start-TeacherPilot.ps1` only | |
| Ad-hoc Uvicorn process present? | |
| PostgreSQL ready | |
| Redis/RQ ready | |
| Backend ready | |
| RQ worker ready | |
| Frontend ready | |
| Qwen3.8 ready, loopback only | |
| Effective API storage root (observed, not assumed) | |
| `COHORT_MODEL_GRADING_ENABLED` | |
| PaddleOCR resident? | |
| Qwen3.6 resident? | |
| Prior draft/job/final grade for this assessment? | |

## 2. Identifiers

| Field | Value |
|---|---|
| Assessment ID | |
| Submission ID | |
| Question ID(s) | |
| Answer region ID(s) | |
| Run ID(s) | |
| Job ID(s) | |
| Grading dispatch run/item ID | |
| Grade suggestion ID | |

## 3. Hashes

| Artifact | SHA-256 |
|---|---|
| Question source | |
| Solution / model answer source | |
| Rubric source | |
| Answer script image(s) | |
| Confirmed transcript text | |
| Export file (if produced) | |

## 4. Phase log

One row per provider call, in the order the calls actually happened.

| # | Phase | Provider | Model | Reasoning mode | Fresh context? | Started (UTC) | Duration | Outcome |
|---|---|---|---|---|---|---|---|---|
| 1 | reference extraction | | | | | | | |
| 2 | mapping | | | | | | | |
| 3 | transcription | | | | | | | |
| 4 | grading | | | | | | | |
| 5 | *(unplanned — investigate)* | | | | | | | |

Total provider calls: ______   Expected: ______   Match? ______

## 5. Teacher gates

| Gate | Decision | Time (UTC) | Notes (no answer text) |
|---|---|---|---|
| Reference accuracy confirmed | | | |
| Mapping geometry confirmed (geometry only) | | | |
| Transcript hash confirmed | | | |
| Full-answer coverage separately confirmed | | | |
| Grade suggestion approved / edited / rejected | | | |

Confirm explicitly: did confirming the mapping leave transcript text
**unconfirmed**? ______
Did confirming the transcript leave coverage **unconfirmed**? ______

## 6. Safety counters

| Counter | Value | Required |
|---|---|---|
| Retries | | 0 |
| Provider fallbacks | | 0 |
| Cloud calls | | 0 |
| `FinalGrade` rows before teacher approval | | 0 |
| `needs_review` on the suggestion | | true |
| Cost estimate | | 0 |
| Review flags present (local provider / image input disabled / teacher review required) | | all three |
| Images reaching the grading call | | none |

## 7. Anomalies

Record each anomaly with phase, time, and sanitized error text. No answer
content.

| # | Phase | Time (UTC) | What happened | Action taken (per Readiness §2) |
|---|---|---|---|---|
| | | | | |

`[unclear correction]` markers, by region ID (no surrounding text): __________

## 8. Export

| Field | Value |
|---|---|
| Export produced? | |
| Pending rows present? (must be none) | |
| Rejected rows present? (must be none) | |
| Verified by opening the file? | |

## 9. Outcome

Result: `COMPLETE` / `ABORTED` / `FAILED (violation)` — circle one.

If ABORTED or FAILED, state which rule (Readiness §2 or §4) applied: __________

**Claim boundary reminder.** A `COMPLETE` result claims only what Readiness §1
permits. It says nothing about transcription accuracy, grading accuracy,
threshold calibration, or readiness for a broader teacher pilot.

Operator signature: ____________________   Date: ____________

Founder/teacher signature: ____________________   Date: ____________
