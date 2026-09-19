# Transcript-first workflow audit — run `20260919a`

Baseline commit: `f08552962f9276dacdbb3ad2c47c38356a2aad9b`
Branch: `codex/transcript-first-20260919a` (isolated worktree; original checkout untouched)
Audit scope: the vertical path *complete script → durable faithful transcript → question-specific
evidence → teacher review → draft grading → teacher approval → final-grade export*.

All claims below cite a file and line at the baseline commit, or a recorded command result.

## 0. Authorization state

`APPROVED_REAL_SCRIPT_SCOPE` and `APPROVED_PROVIDER_MODEL_SCOPE` arrived as unfilled
placeholders. A repository-wide search for an existing explicitly approved rehearsal manifest
(`APPROVED_REAL_SCRIPT_SCOPE`, `APPROVED_PROVIDER_MODEL_SCOPE`, `rehearsal manifest`,
`REHEARSAL_MANIFEST`, case-insensitive, whole repo) returned no matches. The second configured
working directory contains four unhashed, unlisted source documents and one archive; that is file
access, not an approved manifest, and §1 forbids selecting arbitrary uploads.

**Status: `REAL_REHEARSAL_BLOCKED`.** Consequences, fixed for this run:

| Outcome | Verdict |
| --- | --- |
| `ENGINEERING_VERIFIED` | in progress — the only outcome achievable this run |
| `REAL_REHEARSAL_VERIFIED` | `BLOCKED` (no approved corpus or model scope) |
| `QUALITY_VALIDATED` | `NOT_EVALUATED` (depends on the real rehearsal) |
| `TEACHER_RELEASE_APPROVAL` | `NOT_EVALUATED` |

Zero product-provider requests have been made. Remaining budget is untouched: 200 total / 120
vision / 40 text-mapping / 40 draft-grading, USD 20.

## 1. Baseline delta in the original checkout

The original checkout carries four staged, uncommitted files (`BACKLOG.md`,
`apps/api/packages/brain/profiles.py`, `apps/api/tests/test_brain_profiles.py`,
`docs/VALIDATION_LOG.md`). They were neither stashed, reset, nor committed. This run works from a
clean worktree at the recorded HEAD, so that delta is **absent here**.

Content: `legacy_profile_settings` returns settings unchanged for `antigravity_gemini`, so generic
`BRAIN_*` overrides stop replacing the dedicated Antigravity model. Dependency assessment: the
transcript-first architecture does **not** depend on it. One caveat — its test imports
`LocalScriptPageReadService._validate_authorization`, so any new test that exercises page-read
authorization *under the Antigravity profile* would exercise pre-fix behaviour in this worktree.
No inclusion instructions requested; no such test will be added here.

## 2. Measured baseline (clean worktree, before any implementation)

Working directory `apps/api`, interpreter `E:\teacher-assistant\.venv\Scripts\python.exe`
(the worktree shares `.git`, not `.venv`; the shared interpreter was verified to import
`fastapi 0.141.1` / `sqlalchemy 2.0.51` on CPython 3.12.10).

| Command | Result |
| --- | --- |
| `python -m ruff check .` | exit 1 — one pre-existing `I001` at `packages/brain/universal_vision.py:1`. Out of scope; not fixed. |
| `python -m pytest -q` | recorded in §6 of the final report once complete. |

`tests/conftest.py:1` pins `DATABASE_URL` to a `*_test` database and refuses to run outside one,
so the backend suite is already gated onto a disposable target.

## 3. Capability table

Verdict vocabulary: `IMPLEMENTED` (code exists and is reachable), `AUTOMATED_TESTED` (an
automated check executes the behaviour), `REAL_REHEARSED` (exercised on an authorized real
script), `PARTIAL`, `BROKEN`, `UNVERIFIED`.

| capability | implementation | reachable UI/API path | automated checks | real-script evidence | verdict | blocker |
| --- | --- | --- | --- | --- | --- | --- |
| One vision call per source page | `local_script_page_read.py:488` `_read_pages` loops pages, one `adapter.read_page` each | `POST /submissions/{id}/question-node-mappings/run` → `answer_regions.py:1184` when `policy.page_read_enabled` | `tests/test_local_script_page_read.py` | none this run | `AUTOMATED_TESTED` | — |
| Page-read is the default path | gated by `LOCAL_QWEN38_PAGE_READ_ENABLED` / `ANTIGRAVITY_GEMINI_PAGE_READ_ENABLED`, both `default=False` (`core/config.py:301`, `:330`); otherwise `LocalScriptPreparationService` runs (`answer_regions.py:1195`) | same route | `test_answer_region_mapping_api.py:977` covers the disabled branch | none | `PARTIAL` | mapping-then-transcription remains the default, exactly as the work order suspected |
| **Durable source transcript** | **none.** `_read_pages` returns `outputs: list[VisualPageTranscriptOutput]` in memory (`local_script_page_read.py:495`); nothing persists it. No `script_transcript`-like table exists — `app/models.py` declares `answer_regions`, `answer_region_ocr_runs/_bands/_candidates/_segments/_mappings` and `reference_page_ocr_runs`, the last restricted to `question_paper｜solution｜rubric` (`alembic/versions/0024_model_lease_page_evidence.py:133`) | n/a | n/a | n/a | `BROKEN` | the central requirement is unimplemented |
| Restart safety of completed page reads | `prepare()` holds every output in memory and commits once at `local_script_page_read.py:271` | n/a | none | n/a | `BROKEN` | a crash after page *n* discards *n* paid reads |
| Transcript cache / reuse across remap | `prepare()` calls `_read_pages` unconditionally (`:148`). `repair_unconfirmed_only` is *rejected* with page-read enabled (`answer_regions.py:1175`), so every re-prep is a full replace and re-reads every page | same route | `test_answer_region_mapping_api.py:998` asserts the rejection | n/a | `BROKEN` | violates "never reread a successful page merely because a user remapped an answer or changed a rubric" |
| Question assignment versioned separately from source text | assignment and transcript are produced and written in one operation: `assemble()` (`:279`) feeds `_create_mapping` and `_create_transcription_artifact` inside a single `prepare()` | n/a | n/a | n/a | `BROKEN` | no separately versioned assignment record |
| Assignment driven by labels, not boxes | `assemble()` groups by canonical `question_label` casefold (`:300`, `:352`) and carries a null-label block to the nearest preceding label (`:334`); explicitly documented model-free (`:286`) | — | `tests/test_local_script_page_read.py` | none | `IMPLEMENTED` | — |
| Evidence is geometry-independent | `_create_transcription_artifact` raises `"Cannot create a transcript without answer geometry"` when `mapping.answer_region is None` (`:608`), and text is stored on `AnswerRegionOcrRun.draft_text`, reachable only through a crop-backed `AnswerRegion` | — | — | — | `BROKEN` | box-first dependency is structural: no geometry ⇒ no stored transcript |
| Distinct evidence states | `prepare()` computes `blocked｜uncertain｜not_found` (`:177`), then `_create_mapping` coerces `not_found` → `blocked` (`local_script_preparation.py:2069-2071`) because `ck_answer_region_mappings_status` admits only `mapped｜uncertain｜blocked｜teacher_confirmed` (`models.py:1019`) | UI reads `mapping_status` | existing mapping tests | none | `BROKEN` | `NO_ANSWER_FOUND`, `UNREADABLE`, `AMBIGUOUS`, `MISSING_PAGE`, `PROCESSING_FAILED` collapse into `blocked`; a genuine blank is reported as a blocker and is indistinguishable from a failure |
| Complete-coverage proof before declaring a blank | `_detect_unassigned_content` raises a submission-wide hard blocker for any ink outside every band (`:451`) | — | `tests/test_local_script_page_read.py` | none | `IMPLEMENTED` | strong control, but it blocks the whole submission rather than scoping the unresolved state |
| Whole-script transcript review UI | none. `apps/web/components/` has no transcript component; `AssessmentDetailClient.tsx` surfaces per-question `ocr_draft_text` only | `/assessments/[id]/review` | `apps/web/tests/workflow-ui.test.mjs` | none | `BROKEN` | teacher cannot review the script transcript as one document |
| Transcript / mapping editing with revision history | not present in the page-read path | — | — | — | `BROKEN` | — |
| Actual provider/request count surfaced | `calls_used` returned (`:275`) and audit-logged as `visual_page_read_call_count` (`:252`); `AnswerRegionOcrRun.call_limit/calls_used` deliberately set to `0` on this path (`:670`) | audit log only | — | none | `PARTIAL` | not surfaced in the teacher UI |
| Every AI grade needs review / no auto-finalization | separate `GradingJob`/`GradeSuggestion`/`FinalGrade` tables (`models.py:1070`, `:1096`, `:1256`) | grading routes | existing grading tests | none | `UNVERIFIED` for this run | not re-verified yet; no grading call made |
| Multi-provider parity claims | adapters for Antigravity Gemini, llama.cpp Qwen3.8, Codex CLI, Claude CLI, Gemini, OpenAI-compatible (`packages/brain/`) | profile selector | contract tests incl. `test_brain_adapter_contract.py:75` | none | `UNVERIFIED` per provider | one working model is not parity; labels retained |

## 4. Answer to the work order's discriminating question

> Determine whether this is genuinely transcript-first or merely a combined box-mapping/transcription response.

**It is the latter.** `LocalScriptPageReadService` merges two provider calls per page into one and
is a real improvement on call count, but the reusable artifact it was supposed to create does not
exist. The provider's page transcript lives only in a local variable; what reaches the database is
still the box-first triple `AnswerRegion` → `AnswerRegionOcrRun` → `AnswerRegionMapping`, written
per question, keyed to geometry, and rebuilt from scratch — with fresh vision calls — on every
re-preparation. Do not duplicate this service. The missing behaviour is **persistence,
versioning and reuse of the page transcript**, plus the distinct evidence states that a persisted
transcript makes expressible.

## 5. Architecture decision

Add a source-evidence layer *beneath* the existing mapping layer rather than replacing it.

1. `script_transcripts` — one row per (submission, transcription-relevant settings fingerprint):
   model, provider, prompt version, schema version, preprocessing, source manifest hash, status.
2. `script_page_transcripts` — one row per (transcript, submission page): page order, source image
   SHA-256, `is_blank_page`, terminal state (`succeeded｜unreadable｜failed`), provider request
   provenance, committed **immediately after each successful page call**.
3. `script_transcript_blocks` — verbatim block text, reading order, observed heading text, raw
   label as returned, `label_source`, confidence, auxiliary bbox, unresolved markers.
4. `answer_evidence_assignments` — separately versioned question ↔ ordered block-span mapping,
   with an explicit state from `ANSWER_PRESENT｜NO_ANSWER_FOUND｜UNREADABLE｜AMBIGUOUS｜MISSING_PAGE｜PROCESSING_FAILED`.

`AnswerRegionMapping` and its CHECK constraint stay untouched for compatibility with existing
records; it becomes a projection of the assignment layer. Geometry degrades to navigation
metadata. `prepare()` splits into `transcribe()` (cache-aware, page-durable, vision) and
`assign()` (deterministic, no vision), so a remap or rubric change re-runs only `assign()`.

Rollback: the migration is additive with a working `downgrade()`; disabling the new settings flag
restores the baseline path exactly.

## 6. Prioritized acceptance checklist

1. A page transcript survives process death: kill after page *n*, re-run, only pages *n+1…* are read.
2. Re-running preparation with an unchanged source and unchanged transcription settings performs **zero** vision requests.
3. Changing the rubric or remapping an answer performs zero vision requests.
4. Changing a source page invalidates that page's transcript and the dependent assignments and suggestions.
5. `NO_ANSWER_FOUND` is emitted only with complete processed page coverage and no unresolved material; a failed read yields `PROCESSING_FAILED`, a missing page `MISSING_PAGE`, and neither awards zero.
6. Cross-page, non-adjacent and out-of-order answers resolve to ordered block spans; every quote resolves exactly to a stored span.
7. Unassigned writing stays visible and named, not silently attached to the nearest heading.
8. The teacher can read the whole-script transcript as one document beside the source pages.
9. Budget is enforced at the dispatch boundary; duplicate dispatch under double-click, concurrent workers and restart cannot double-spend or duplicate suggestions.
10. No provider response, retry or API shortcut can finalize a real grade without explicit teacher action.
