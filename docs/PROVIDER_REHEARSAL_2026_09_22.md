# Provider rehearsal checkpoint — 2026-09-22

## Scope and result

User requested an end-to-end real-script rehearsal with every brain provider.
The active bounded scope is one existing 23-page submission and its confirmed
references, private copies, sequential providers, at most 200 model requests and
USD 20 additional paid usage, draft-only grading after teacher evidence review.
No automatic finalization or teacher confirmation is authorized.

This is **not yet an all-provider end-to-end PASS**. Local Qwen completed the
real source-read stage. The product path has since been rebuilt so a new bulk
run reads pages into the durable transcript, derives evidence assignments, and
grades those assignments without requiring mapping crops or a second OCR pass.
Cloud runs remain blocked by the privacy and credential prerequisites below.

Baseline: `7237be0abd6e2a80c0a7cbe60817842fd5ae68e5`.
Implementation branch: `codex/provider-rehearsal-20260921`.
The main checkout and the previous worktree's uncommitted fix remain untouched.

## Provider matrix

| Profile | Configured model | Real result |
|---|---|---|
| llama_cpp_qwen38 | qwen3.8-27b-q4km | All 23 page reads persisted; prepare and transcript-review routes HTTP 200. Teacher review/coverage unresolved; no grade created. |
| antigravity_gemini | gemini-3.8-flash-high | Offline parser fix verified; real cloud rehearsal awaits source privacy confirmation. |
| codex_cli | gpt-5.5 | Offline profile-handoff regression fixed; real cloud rehearsal awaits source privacy confirmation. |
| claude_cli | sonnet | Offline profile-handoff regression fixed; real cloud rehearsal awaits source privacy confirmation. |
| openai_compatible | Qwen/Qwen3.8-27B | Configured; real cloud rehearsal awaits source privacy confirmation and bounded pricing verification. |
| openai | gpt-4o-mini | Missing provider-specific API key; image capability also disabled in current configuration. |
| gemini | gemini-2.0-flash | Missing provider-specific API key; image capability also disabled in current configuration. |
| llama_cpp_qwen | qwen3.6-35b-a3b-q4km | Disabled legacy profile; lacks visual page-read capability. Cannot claim this transcript-first path works with it. |
| mock | mock-grader-v1 | Excluded from real-provider claims. |

CLI installation/configuration readiness does not establish successful live
authentication, model availability, or inference. Model aliases are the observed
configuration, not verified claims about vendor offerings.

## Fixes

1. Antigravity now reads populated `structured_output`, falling back to legacy
   response text. Empty structured metadata with valid legacy text still works.
   A missing or invalid payload cannot be treated as a blank source page.
2. The mapping HTTP route now passes its selected profile adapter into both
   preparation services. Previously it validated the profile but discarded the
   adapter during construction, allowing legacy configuration reconstruction to
   lose the chosen model/profile.
3. Regression tests cover the adapter handoff, structured-output precedence,
   missing output, strict validation, and explicit blank-page output.
4. New bulk runs require `visual_page_read`; mapping-only profiles are rejected
   before dispatch. Bulk items now move `read -> grading` from the saved
   `AnswerEvidenceAssignment`. Transcript-only preparation creates no legacy
   mapping, crop region, or region OCR rows.
5. Transcript grading disables image input even for image-capable graders and
   sends the stored assigned text. Existing grade/final-grade foreign keys use
   a zero-geometry compatibility anchor; that row is not grading evidence.
6. Review now shows each complete protected source page beside its transcript.
   A teacher can correct text, move a block to a canonical question, resolve a
   cross-page continuation, or classify a page as answer content/non-answer.
   Provider output remains unchanged beside every teacher override.
7. Cover/non-answer pages remain stored but are excluded from assignment.
   Unassigned writing stays visible; no-answer, unreadable, ambiguous,
   missing-page and page-read-failed outcomes remain distinct.

## Verification

- Backend `python -m ruff check .`: PASS after the final unused-test cleanup.
- Backend `python -m pytest -q`: **823 passed, 6 skipped**;
  2 existing deprecation warnings. Disposable test database only.
- `git diff --check`: PASS (Windows newline conversion notices only).
- Real local run: actual FastAPI route through TestClient, real PostgreSQL,
  real storage, real local model and model lease. **Not** a live browser/worker
  end-to-end demonstration.
- Local provider requests: **23**, all returned and persisted.
- Re-prepare with a one-call ceiling and dispatch instrumented to fail if
  invoked: HTTP 200, total request count still **23**.
- Source files: hashes of all **26** copied files still match originals.
- Real GradeSuggestion/FinalGrade records in the rehearsal database: **0/0**.
- Paid cloud usage: **0 requests / USD 0**.

All real content, raw provider responses, page images, private manifests,
transcripts and the HTML review stay in ignored `.local-ai/rehearsal/`.
The test XML and private call ledger are there too. Do not commit that directory.

## Earlier observed blocker and product resolution

Local Qwen returned no answer blocks for page 1. The independent coverage check
found ink on that page and blocked all 15 legacy mappings. Assignment states:
13 ambiguous, 1 unreadable, 1 no-answer-found. These state labels are model-derived
draft evidence, not teacher-validated conclusions.

The private review established that page 1 contains no student answer writing,
but it does contain direct student identifiers and institution branding. The
new review control can classify it as non-answer without deleting its text or
pretending it was blank. No readiness or teacher-review gate was bypassed.

That review decision does not make the original page safe to send to a cloud
vision provider. A cloud visual rehearsal still requires an anonymized source
artifact or a product-level redaction gate that is proven to remove identifiers
from the actual image payload. Grading from the saved transcript is text-only,
but creating a provider-specific cloud transcript would still upload page images.

## Runtime notes

The machine rebooted between turns. No bugcheck was found in the last two days;
the interrupted earlier full-suite outcome was unavailable and was rerun.
The supported pilot launcher restored the normal app on ports 3000/8000.

Local-model startup initially failed because Windows PowerShell inherited a
module search path without its built-in modules (`Get-FileHash` unavailable).
Adding `$PSHOME/Modules` to that launch process's `PSModulePath` resolved it.
No global environment setting changed. Observed VRAM stayed below 11,000 MiB.

## Resume

1. Read the private budget ledger; do not rerun the successful 23-page read.
2. Obtain the pending source-anonymization and page-1 evidence decisions.
3. Resolve coverage through a reviewed, auditable product path; do not fabricate
   a confirmation or replace missing evidence with blank output.
4. Continue the configured cloud providers only after privacy prerequisites,
   provider authentication, and an enforceable cost bound are established.
5. OpenAI/Gemini API require local credential configuration. Never paste keys
   into a task or log. The prior handoff reported exposed keys; rotation remains
   an owner follow-up and has not been verified here.
6. Obtain teacher confirmation of each relevant evidence version before its
   one authorized draft grade. Keep finalization/export approval separate.
7. Do not mark the request complete until every requested provider has a real
   result or the user explicitly accepts identified unavailable profiles.
