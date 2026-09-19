# Transcript-first checkpoint — run `20260919a`

Sanitized. Contains no private paths, script identifiers or credentials.

## State

| Field | Value |
| --- | --- |
| Baseline commit | `f08552962f9276dacdbb3ad2c47c38356a2aad9b` |
| Branch | `codex/transcript-first-20260919a` (isolated worktree) |
| Original checkout | preserved; its four staged files untouched |
| Product-provider requests used | **0** of 200 (0 vision, 0 text-mapping, 0 draft-grading) |
| Paid provider spend | **USD 0.00** of 20 |
| Real scripts touched | **none** |
| Rows created outside the disposable test database | **none** |

## Outcomes so far

| Outcome | Verdict |
| --- | --- |
| `ENGINEERING_VERIFIED` | in progress — slice 1 landed, see below |
| `REAL_REHEARSAL_VERIFIED` | `BLOCKED` — both authorization fields arrived unfilled and no approved rehearsal manifest exists in the repository |
| `QUALITY_VALIDATED` | `NOT_EVALUATED` |
| `TEACHER_RELEASE_APPROVAL` | `NOT_EVALUATED` |

## Completed

1. Preflight, isolated worktree, measured clean baseline (`AUDIT.md` §2).
2. Audit with per-capability verdicts and the architecture decision (`AUDIT.md`), committed.
3. **Slice 1 — durable source transcript.** Three additive tables
   (`script_transcripts`, `script_page_transcripts`, `script_transcript_blocks`),
   `ScriptTranscriptStore`, and a rewritten `LocalScriptPageReadService._read_pages` that commits
   each page as it succeeds and serves an unchanged page from the record with no provider request.
   Acceptance items 1, 2, 3 covered by automated checks.
4. **Slice 2 — separately versioned assignment with distinct states.** Two additive tables
   (`answer_evidence_assignments`, `answer_evidence_spans`) and
   `AnswerEvidenceAssignmentService`. Derivation reads only the stored transcript and the canonical
   question structure, so re-deriving costs no provider request. The six states are distinct and
   `no_answer_found` is refused by a CHECK constraint unless coverage is complete with nothing
   unplaced. Acceptance items 4 (partly), 5, 6, 7 covered.

## Acceptance checklist status

| # | Item | Status |
| --- | --- | --- |
| 1 | Page transcript survives process death | covered — durability asserted from a second connection |
| 2 | Unchanged source performs zero vision requests | covered — measured with a counting fake adapter |
| 3 | Remap / rubric change performs zero vision requests | covered — assignment re-derivation issues no request |
| 4 | Changed source invalidates dependent evidence | **partial** — the transcript is superseded; dependent `GradeSuggestion` invalidation is not yet wired |
| 5 | `NO_ANSWER_FOUND` requires complete coverage | covered — service logic plus a database CHECK |
| 6 | Cross-page, non-adjacent, out-of-order spans resolve exactly | covered |
| 7 | Unassigned writing stays visible | covered |
| 8 | Whole-script transcript review UI | **not started** |
| 9 | Budget at dispatch boundary; duplicate dispatch safe | **partial** — budget covered; concurrency/restart reconciliation not yet |
| 10 | No path finalizes a real grade without a teacher | pre-existing gates unchanged; not re-verified this run |

## Next step (smallest useful unit)

Slice 3 — make the assignment layer reachable: have the page-read `prepare()` call
`AnswerEvidenceAssignmentService.assign()` after assembly, project `state` onto the legacy
`mapping_status` via `legacy_mapping_status()`, and expose the whole-script transcript and per-
question evidence state over the API for the review UI (acceptance items 4, 8, 9).

## Private evidence locations

Command transcripts for this run live in the session scratchpad directory (baseline and
post-slice pytest output, web build log, disposable-cluster log). Nothing in them is committed.

## Resumption rules

Resume only this authorized run with the remaining budgets above. This checkpoint is not
authorization for a new run, a new corpus, or a scheduled repeat.
