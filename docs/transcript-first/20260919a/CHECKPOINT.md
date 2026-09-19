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
   Acceptance items 1, 2, 3 and part of 5 are covered by automated checks.

## Next step (smallest useful unit)

Slice 2 — the separately versioned assignment layer (`answer_evidence_assignments`) carrying the
distinct states `ANSWER_PRESENT｜NO_ANSWER_FOUND｜UNREADABLE｜AMBIGUOUS｜MISSING_PAGE｜PROCESSING_FAILED`,
projected into the legacy `mapping_status` rather than widening
`ck_answer_region_mappings_status`. Acceptance test for that state must assert on the new field,
not on `mapping_status`, or it passes vacuously.

## Private evidence locations

Command transcripts for this run live in the session scratchpad directory (baseline and
post-slice pytest output, web build log, disposable-cluster log). Nothing in them is committed.

## Resumption rules

Resume only this authorized run with the remaining budgets above. This checkpoint is not
authorization for a new run, a new corpus, or a scheduled repeat.
