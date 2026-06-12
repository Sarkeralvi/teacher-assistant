# Custom Controlled V0 Runbook

Founder-supervised release-candidate runbook for the Teacher Assistant Custom Controlled V0 workflow.

## Status and scope

Custom Controlled V0 is **founder-supervised demo ready only**. It is not approved for a public teacher pilot.

Known good milestone:

- TA-DEMO-006 completed a five-packet synthetic rehearsal.
- Assessment id: `13007`.
- Ready packets: `5`.
- Real Codex single-packet grading calls: `5`.
- Model: `gpt-5.5`.
- GradeSuggestion ids: `4587` through `4591`.
- FinalGrade ids: `2992` through `2996`.
- XLSX export rows: `5` approved final-grade rows.
- Mock grading: no.
- Batch grading: no.

## Hard safety rules

- Use synthetic/demo data unless the founder explicitly approves exact private files.
- Do not run mock grading in the Custom Controlled founder flow.
- Do not run batch grading.
- Do not auto-finalize.
- Do not auto-approve.
- Do not call a provider/model unless the active work order explicitly approves the exact bounded call count.
- Do not use VSCode, Codex as a coding agent, or additional coding agents.
- FinalGrade may be created only after explicit teacher/founder approval.
- Export may include approved FinalGrade rows only.
- Draft GradeSuggestion rows must not be exported as final grades.

## Prerequisites

Run from the repository root:

```bash
cd /home/newton/teacher-assistant
git status --short
git rev-parse HEAD
make health
make frontend-health
```

For a real-provider rehearsal only, additionally verify Codex CLI before the first approved call:

```bash
codex --version
codex login status
```

Do not run a prompt to test the model unless the work order explicitly approves a real provider call.

## Exact Custom Controlled V0 demo flow

Use the browser UI for founder demonstration where possible; API/scripted steps are acceptable for controlled internal rehearsal only.

1. Create an assessment.
2. Add a question/grading unit.
3. Add model answer / solution text.
4. Add an active rubric.
5. Upload synthetic script page(s).
6. Create manual answer region(s)/crop(s).
7. Confirm full evidence only when the crop contains the complete answer.
8. Run evidence prep.
9. Build the grading queue scaffold.
10. Run one real draft grade per approved ready packet.
11. Open teacher review.
12. Teacher reviews, edits if needed, and explicitly approves.
13. Export XLSX.
14. Inspect the XLSX contents, not just the HTTP status.

## Required pass/fail criteria at each step

### Evidence packet preview

Pass only if each target packet shows:

- question/grading-unit label
- max marks
- model answer / solution present
- active rubric present
- student crop/segment present
- `evidence_status = complete`
- continuation resolved
- `ready_for_grading = true`
- blockers empty

Fail/stop if any packet is missing model answer, rubric, crop, complete-answer confirmation, or continuation resolution.

### Evidence prep

Pass only if:

- `ready` equals the expected target packet count
- `blocked = 0`

Fail/stop on any blocked packet.

### Queue scaffold

Pass only if:

- `queued` equals the expected target packet count
- `refused = 0`
- every target queue item has `stale_status = fresh`
- every queue item has `provider_allowed = false` until an explicit single-packet grading call is made

Fail/stop on refused, blocked, stale, or missing queue items.

### Real grading gate

Before each single-packet real Codex call, re-check that packet:

- `ready_for_grading = true`
- model answer present
- active rubric present
- `evidence_status = complete`
- blockers empty
- continuation resolved
- queue item fresh
- no existing GradeSuggestion for that answer region
- call counter is below the approved limit

Run exactly one single-packet provider call for that packet. Stop on first provider failure. Do not retry or use mock fallback without founder approval.

### Draft review gate

Pass only if every created GradeSuggestion:

- links to the intended `answer_region_id`
- has score and max score
- has `needs_review = true`
- includes confidence/feedback/rubric breakdown when returned by the provider

No FinalGrade may exist before explicit teacher/founder approval.

### Teacher approval gate

Pass only if teacher/founder explicitly approves the draft. If editing is part of the rehearsal, verify that edited final score/comment is saved in FinalGrade.

FinalGrade must preserve:

- answer region id
- source GradeSuggestion id
- teacher id
- final score
- teacher comment when provided
- approval status
- timestamp/audit trail when supported

### Export gate

Export only after approval. Pass only if XLSX contains:

- one row per approved FinalGrade
- source GradeSuggestion id
- answer_region_id
- final score, not merely raw AI suggestion score
- approval status `approved`
- teacher comment when present

Draft/unapproved GradeSuggestions must be excluded.

## TA-DEMO-006 reproducible founder-demo path

For the known five-packet synthetic release-candidate run:

- Assessment: `13007`
- Answer regions: `8111`, `8112`, `8113`, `8114`, `8115`
- GradeSuggestions: `4587`, `4588`, `4589`, `4590`, `4591`
- FinalGrades: `2992`, `2993`, `2994`, `2995`, `2996`
- Edited final-score check: answer region `8113` exports as `4.5`

If backend tests reset the dev DB, restore only deterministic synthetic demo records. Do not make additional provider/model calls just to restore inspectability.

## Failure handling

Stop and report if any of these occur:

- missing model answer
- missing rubric
- partial or blank packet
- stale queue item
- provider unavailable
- export attempted before approval
- unexpected GradeSuggestion/FinalGrade/GradingJob count change
- dirty git status before a controlled run

## Verification commands

```bash
git status --short
make health
make frontend-health
```

When code changes:

```bash
make lint
git diff --check
```

Run focused backend tests for evidence prep, queue, grading gates, final grades, and export when behavior changes.

## Release-candidate decision

Founder-supervised demo ready: yes, after TA-DEMO-006.

External teacher pilot ready: no. Remaining blockers include non-synthetic data policy, auth/session hardening, operational runbook maturity, and broader failure-path testing.
