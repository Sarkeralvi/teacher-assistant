# Transcript-first acceptance report — run `20260919a`

Sanitized. No private paths, script identifiers, student content or credentials.

Baseline for the continuation session: `a27c074`. Both worktrees preserved; the original checkout
still holds its four pre-existing staged files, untouched.

## Outcomes, kept separate

| Outcome | Verdict | Evidence |
| --- | --- | --- |
| `ENGINEERING_VERIFIED` | **PASS** | `apps/api`: ruff clean, `alembic upgrade head` clean, **798 passed / 6 skipped / 0 failed**. `apps/web`: `tsc --noEmit` clean, `workflow-ui.test.mjs` passed, `next build` clean, **`npm run e2e` 7 passed / 1 skipped / 0 failed**. |
| `REAL_REHEARSAL_VERIFIED` | **BLOCKED** | Both authorization scope fields remain unfilled; no approved rehearsal manifest exists in the repository. Zero product-provider requests were made in either session. |
| `QUALITY_VALIDATED` | **NOT_EVALUATED** | Depends on the real rehearsal. Synthetic fixtures prove mechanics; they are not handwriting and not grading quality. |
| `TEACHER_RELEASE_APPROVAL` | **NOT_EVALUATED** | No teacher has reviewed this work. |

Budget: **0 of 200** product-model requests (0 vision / 0 text-mapping / 0 draft-grading).
**USD 0.00 of 20.** No real script was opened.

## Acceptance checklist

| # | Item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A page transcript survives process death | **PASS** | `test_each_successful_page_is_committed_with_its_blocks`, `test_a_known_failure_on_a_later_page_...` — both assert from a second database connection that never saw the writing session. |
| 2 | Unchanged source performs zero vision requests | **PASS** | `test_an_unchanged_source_is_reused_without_any_provider_request` with a counting fake adapter; `test_preparing_again_reuses_the_transcript_...` through the real `prepare()`. |
| 3 | Remap / rubric change performs zero vision requests | **PASS** | `test_rederiving_assignment_makes_no_provider_request` asserts the audit row records `provider_request_count = 0`; exercised in the browser against the live stack. |
| 4 | Changing evidence invalidates dependent readiness and drafts | **PASS** | `test_evidence_invalidation.py` (11 cases) over transcript text, rubric, model answer, assignment version and span removal. The queue snapshot now carries the same fingerprint. |
| 5 | `NO_ANSWER_FOUND` requires complete coverage | **PASS** | Service logic plus `ck_answer_evidence_no_answer_requires_coverage`; `test_the_database_refuses_a_blank_claim_without_coverage`. |
| 6 | Cross-page, non-adjacent, out-of-order spans resolve exactly | **PASS** | `test_one_answer_spans_nonadjacent_pages_in_reading_order`, `test_a_continuation_crosses_a_page_break_to_its_owner`. |
| 7 | Unassigned writing stays visible | **PASS** | Returned separately by the evidence API and rendered under its own heading; `test_unplaceable_writing_makes_a_question_ambiguous_not_blank`. |
| 8 | Whole-script transcript review UI | **PASS** | Five API routes plus `ScriptTranscriptReviewClient`, driven end to end in a browser against the live isolated stack (§"Rehearsal" below). |
| 9 | Durable dispatch reservations, concurrency, reconciliation | **PASS** | `test_a_page_already_claimed_by_another_worker_is_not_dispatched_twice`, `test_an_expired_claim_becomes_an_unknown_outcome_not_a_free_retry`, `test_a_timeout_is_not_retried_and_demands_an_explicit_reconciliation`. |
| 10 | Teacher-only finalization, ownership, export gates | **PASS** | Finalization re-checks the evidence fingerprint at the irreversible step; `test_the_gate_holds_even_when_nothing_marked_the_draft_superseded`. Ownership covered by `test_another_teacher_cannot_read_or_correct_the_transcript`. Pre-existing grading and export tests all pass. |

## What changed in this session, and why

**One ownership rule.** `assemble()` and `derive_assignments()` each decided independently which
question owned an unlabelled block. Two rules for one fact can disagree, and the symptom would have
been a crop showing evidence the assignment layer considered unplaced. They now share
`resolve_block_ownership()`, which reads labels, page order and the continuation claim — never
geometry.

**Unlabelled blocks are no longer assumed to continue.** The old rule handed any unlabelled block
to whichever question came last, across page breaks included. Now same-page inheritance uses
observed reading order, a page break requires an explicit `continues_from_previous`, and an unknown
label closes ownership so the blocks after it are not inherited by the question before it.
`answer_evidence_spans.assignment_basis` records which branch attached each block.

**The persisted transcript is the authority.** Every page is reloaded through the store before
assembly, so anything lossy in persistence fails loudly rather than diverging from what a teacher
is later shown. `load_page_output` no longer substitutes a placeholder bbox.

**A failure is no longer one thing.** A rejected request is a known failure and may be read again.
A timeout, a dropped connection or a worker that died holding a claim is `unknown_outcome`: the
provider may have produced and billed output nobody saw. Those pages are excluded from
`pages_needing_read`, preparation refuses rather than redispatching, and only an explicit
reconciliation recording who decided what releases them.

**Drafts are bound to their evidence.** A suggestion pinned its rubric but not its evidence. It now
carries a fingerprint over the transcript, the assignment, the solution and the rubric, re-checked
at finalization rather than trusting an invalidation hook to have been called.

**Corrections do not destroy the record.** `text` stays the verbatim provider output; a correction
becomes `edited_text` plus an appended revision row. Editing in place would have destroyed both the
evidence of what the model produced and the reuse guarantee.

### Two defects the browser found that the tests had not

1. `resolve_span_text` returned the model's text, so a teacher's correction was saved and then
   ignored by everything downstream. Now fixed and covered.
2. A question stayed "could not be read" while displaying the correction that had just resolved it,
   because `unresolved` was a stored flag from the model text. Classification is now derived from
   the text a reviewer actually reads, at derivation time and at read time. Covered by
   `test_resolving_an_unreadable_line_clears_the_unreadable_state`.

## Rehearsal: isolated stack, synthetic evidence

The supported pilot launcher was **not** invoked; every value it would point at the existing
application was overridden. The existing stack was not running and stayed that way — nothing was
listening on 5432, 6379, 8000 or 3000 before, during or after.

| Component | Existing application | This rehearsal |
| --- | --- | --- |
| PostgreSQL | 5432, repository data dir | **55432**, disposable cluster outside the repository, database `teacher_assistant_rehearsal` |
| Redis-compatible | 6379 | **56379**, own data dir |
| Queue namespace | `teacher-assistant-default` | **`transcript-first-rehearsal`** |
| Worker name | `teacher-assistant-windows-pilot` | **`transcript-first-rehearsal-worker`** |
| API | 8000 | **58000** |
| Web | 3000 | **53000** |
| Storage | repository `data/` | scratchpad directory |

The resolved `DATABASE_URL`, Redis URL, queue name and storage root were printed and checked before
the migration ran. `BRAIN_PROVIDER=mock`, `BRAIN_ALLOW_REAL_PROVIDERS=false`,
`COHORT_MODEL_GRADING_ENABLED=false`.

Worker liveness was proved by an enqueue/completion round trip on the isolated queue, not by the
process having started.

Journey driven in a real browser against that stack, with invented evidence only:

1. Logged in through the web app.
2. Read the whole script as one document: 3 of 3 pages, **3 requests actually made** (summed from
   the pages, not inferred), model and provider shown as data, coverage reported incomplete with
   the explicit statement that no question can be reported as unanswered while that is true.
3. Saw three distinct states side by side — `Answer found`, `Could not be read`, `Reading failed` —
   each with the sentence saying what it does *not* mean, and each span labelled with whether its
   question was read from a heading or inherited.
4. Corrected an unreadable line. The model's own text remained available under "What the model
   read"; the revision was recorded; the correction propagated to the question's evidence.
5. Re-derived the assignment: version advanced, **no page was read again**, and the corrected
   question moved from `Could not be read` to `Answer found`.
6. Reconciled the page whose outcome was unknown. The blank note was refused; with a note recorded,
   the page moved to `failed` with the teacher's note appended to the reason.

This is evidence of mechanics on invented data. It is not handwriting, and it says nothing about
grading quality.

## Checks run

Working directory and interpreter recorded for each.

| Dir | Command | Result |
| --- | --- | --- |
| `apps/api` | `python -m ruff check .` | **exit 0** (the pre-existing `universal_vision.py` `I001` is fixed; it is inside this workflow) |
| `apps/api` | `python -m alembic upgrade head` | **exit 0**, head `0036_block_revision` |
| `apps/api` | `alembic downgrade 0030_grading_run_brain_profile` then `upgrade head` | **exit 0** both ways — all six new migrations round-trip |
| `apps/api` | `python -m pytest -q` | **798 passed, 6 skipped, 0 failed** |
| `apps/web` | `npm run lint` | exit 0 |
| `apps/web` | `node tests/workflow-ui.test.mjs` | exit 0 |
| `apps/web` | `npm run build` | exit 0 |
| `apps/web` | `npm run e2e` | **7 passed, 1 skipped, 0 failed** (the skip is the real-provider spec, gated off) |

The session baseline had one failing backend test and one lint error; both are now fixed. The
`npm run e2e` check was unmeasured in the first session and is now measured.

## Limits of this evidence

- No real script, no real provider call, no grading-quality measurement.
- The populated transcript-review journey is covered by API tests and by the recorded browser run.
  The committed Playwright spec guards the route, its ownership boundary and its empty state only,
  because creating a transcript requires a vision provider and none is authorized.
- `answer_region_mappings.mapping_status` is still not narrowed to the six states. The distinction
  lives on the assignment row and in `source_reference.page_read`. Narrowing it would change what a
  teacher sees on the existing workflow and remains a founder decision.
- A page failure still aborts preparation rather than producing partial evidence. Named, not
  defaulted: the durable transcript means no completed page is lost to the abort.
