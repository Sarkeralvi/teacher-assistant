# Provider rehearsal report — 2026-09-23

## Scope and claim boundary

The approved rehearsal used one anonymized 23-page real script, the finalized
15-question reference bundle, private isolated databases/storage, sequential
providers, a hard ceiling of 200 model requests, and draft-only grading after
teacher evidence review. No grade approval or finalization was authorized.

The application now follows the transcript-first path in bulk evaluation:

1. read each complete page once into a durable page transcript;
2. derive question evidence from transcript blocks;
3. require a teacher to inspect full pages, classify every page, correct text,
   confirm evidence ownership, and confirm the exact transcript snapshot;
4. grade only the saved, teacher-confirmed text; and
5. leave every result as a review-required draft.

The active implementation branch is `rescue/paddle-qwen36-hybrid`. Private
images, transcripts, provider responses, databases, and review artifacts remain
under ignored `.local-ai/rehearsal/` storage and are not committed.

## Real provider results

| Provider profile | Actual UI + worker result | Calls | Final grades |
|---|---|---:|---:|
| Claude Code CLI (`sonnet`) | 23/23 pages; 15/15 reviewed assignments; 15 drafts; 5 clean and 10 verification disagreements; zero provider failures after retry | 45/60 | 0 |
| Antigravity Gemini CLI (`gemini-3.8-flash-high`) | 23/23 pages; 15/15 reviewed assignments; 15 drafts; 15 clean; zero provider failures | 40/60 | 0 |
| Local Qwen 3.8 Vision (`qwen3.8-27b-q4km`) | 23/23 pages; 15/15 reviewed assignments; 15 drafts; 12 clean and 3 verification disagreements; zero provider failures after parser repair and retry | 38/60 | 0 |
| Codex CLI (`gpt-5.5`) | 23/23 pages; 15/15 reviewed assignments; 14 drafts because Question 9 is confirmed blank; 11 clean, 3 verification disagreements, 1 missing-answer exception; zero provider failures after text-only boundary repair and retry | 37/54 | 0 |
| OpenAI-compatible API (`Qwen/Qwen3.8-27B`, Akash configuration) | **NOT RUN end to end.** Offline profile resolution is ready and advertises `visual_page_read`, `visual_transcription`, and `grading`; a comparable full run needs about 37 calls, while only 17 remain under the approved global ceiling. | 0 | 0 |
| OpenAI API / Gemini API | Not eligible in the active configuration: provider-specific keys and image input are disabled. | 0 | 0 |
| Legacy local Qwen 3.6 | Not eligible for this workflow because it has no visual page-read capability. | 0 | 0 |
| Mock | Excluded from real-provider claims. | 0 | 0 |

The global request accounting is **183/200**: 23 calls from the earlier retained
local-Qwen source-read evidence plus 45 Claude, 40 Antigravity, 38 current local
Qwen, and 37 Codex calls. The remaining allowance is insufficient for a truthful
full Akash rehearsal, so no partial run was presented as end-to-end evidence.

## Teacher review performed on the real script

- Page 1 was inspected and classified as non-answer cover content. Pages 2–23
  were classified as answer content.
- Every displayed evidence owner was confirmed in the product UI.
- Provider-specific transcription defects were corrected while preserving the
  original provider text and revision history.
- Local Qwen pages 6–7 were moved from Question 2 to Question 3 after inspection.
- Ambiguous crossed writing on Questions 5, 7, and 10 was resolved against the
  complete page images where it occurred.
- Question 9 in the Codex transcript remained `no_answer`; it was not converted
  into a fabricated answer or an empty draft.
- Restart/cache durability was exercised. Resuming used the current teacher
  assignment snapshot and did not read pages again.

## Product changes made during the rehearsal

1. Added a persisted transcript-review snapshot and reviewer attribution. Draft
   grading is blocked until the current transcript, page roles, and evidence
   assignments are teacher-confirmed. Any later text, role, or ownership edit
   makes the confirmation stale.
2. Added API and UI controls to classify pages, correct transcript text, move
   blocks between questions, confirm displayed owners, re-derive assignments
   without a provider call, and confirm the reviewed snapshot.
3. Bulk resume now relinks a superseded item to the current evidence assignment,
   records `verification_source=teacher`, clears stale stop state, and refuses
   grading when the review snapshot is stale.
4. Page-read request accounting is cumulative across failures and resumes.
   Unknown outcomes must be reconciled; known failed pages can be retried without
   rereading successful pages.
5. Invalid model-authored block geometry is repaired to a whole-page inspection
   box while keeping the transcript in mandatory review. This prevented useful
   text from being discarded because of a malformed bounding box; geometry is
   not used as grading evidence.
6. Antigravity structured output handling, retry-safe Windows temporary cleanup,
   and explicit blank/failure distinctions were hardened.
7. Claude accepts transcript-only grading even when the profile also supports
   images.
8. Local Qwen safely serializes a structured `detected_answer_summary` object as
   deterministic review text while retaining strict validation of every other
   grade field.
9. Codex now recognizes the transcript-only sentinel even when its profile has
   vision enabled, so it cannot try to open a compatibility image path during
   transcript grading.
10. The UI wording now describes full-page transcription, evidence assignment,
    teacher confirmation, and draft grading rather than region mapping first.

## Failure evidence that led to fixes

- Antigravity returned valid output but a child process temporarily held its
  workspace on Windows; bounded cleanup retries now handle that condition.
- An interrupted Antigravity page was stored as `unknown_outcome` and required
  explicit reconciliation before resume.
- Qwen returned an object for `detected_answer_summary`; the original strict
  string schema safely rejected it, and the narrow normalization now preserves
  the object as sorted JSON review text.
- Codex transcript grading initially tried to stage the compatibility image path
  and paused with `Codex CLI image input file does not exist`. The fixed provider
  omits `--image` for the transcript-only sentinel. The same run resumed and
  ended with zero provider-contract failures.

## Validation

- Backend: `python -m pytest tests -q` from `apps/api` — **834 passed,
  6 skipped**, with two existing deprecation warnings.
- Backend: `python -m ruff check apps/api` — PASS.
- Frontend: `npm run lint` — PASS.
- Frontend: `npm run build` — PASS.
- `git diff --check` — PASS (line-ending notices only).
- The real database assertions above were read directly from the four isolated
  rehearsal databases after the visible UI states showed `review_ready`.
- The normal pilot was rebuilt and restarted from this checkout. PostgreSQL,
  Redis/RQ, API, worker, and frontend all report ready; API `/health` returned
  `status=ok`, frontend `/` returned HTTP 200, and the production database is at
  migration `0039_transcript_review_gate`.
- `COHORT_MODEL_GRADING_ENABLED` remains `false`; local models remain on-demand
  and stopped after deployment.

## Remaining bounded work

One full Akash/OpenAI-compatible rehearsal remains. A no-call preflight resolved
the configured cloud endpoint, exact `Qwen/Qwen3.8-27B` model, 600-second
timeout, JSON-object structured output, required visual capabilities, and
credential readiness without exposing a secret. It requires an explicit
increase of at least 20 requests beyond the current 200-call ceiling (37 expected
calls versus 17 remaining); increasing the ceiling to 225 would also leave five
retry calls. Until that is authorized and completed, the honest
all-configured-provider verdict is **PARTIAL**, with four real provider passes and
Akash unverified end to end.
