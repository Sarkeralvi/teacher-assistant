# Decision: Claude (Anthropic API) is the production model; v2 refactor

- **Date:** 2026-11-07
- **Status:** Accepted by the founder (plan approved in session on 2026-11-07)
- **Plan:** "Teacher Assistant v2: Claude API, one-click local app, calibrated trust"
- **Rollback point:** tag `v1-local-qwen-final` (commit `8df1b13`, pushed to `origin`)

## Context

v1 was built around a local Qwen3.8-27B vision model on a single 12 GB GPU. That
model's speed (28–55 s per page read, about 78 s per grade, one call at a time) and
its memory limits drove most of the system's complexity: a GPU lease and phase
machine, six local services, 133 settings, nine model profiles, three batch
orchestrators and a deliberately fine-grained teacher gate at every evidence step.
The host also has a recorded hardware stability fault. After about 330 commits
there was still no teacher-signed accuracy evidence and no completed end-to-end
rehearsal.

## Decisions

1. **The Anthropic API (Claude) is the sole production model provider.** The
   default model is `claude-opus-5-5` for every stage. A cheaper model may replace
   it for a stage only with eval evidence on the founder's marked scripts and the
   founder's approval.
2. **Full scanned pages are sent, including the cover/identity page.** This
   reverses the earlier loopback-only, no-cloud and identifier-minimisation rules
   for the founder's own exams.
3. **The app runs on the founder's Windows PC for one user.** No hosting.
4. **One combined teacher review.** Claude reads and drafts grades without a
   separate transcript gate. The teacher reviews page image, transcript and
   proposed marks together; editing a transcript re-grades that answer. This
   replaces the September 2026 transcript gate. Nothing is final without explicit
   teacher approval.
5. **Trust is measured, not assumed.** Only two founder-marked scripts exist, so
   they serve as a smoke test. Trust policy (for example, when "approve all
   unflagged" may be used) is set from blind calibration-mode marking during the
   first real exam.
6. **Retries.** Transient transport failures (429, 529, 5xx, network, timeouts)
   are retried automatically by one layer only. Content-level failures (refusal,
   truncation, schema violation, unexpected serving model) are never retried
   automatically; they become exceptions for the teacher.
7. **Refusal fallback.** For grading only, Anthropic's server-side refusal fallback
   may serve a request from another Claude model. Such a draft is flagged
   (`served_by_fallback_model:<model>`) and its confidence capped. Evidence tasks
   (page reads, reference extraction, assignment) fail closed instead.
8. **Development mode.** Agent-driven development loops are allowed inside the
   approved phase gates: tests first, full checks, independent review,
   founder demo, founder-approved commit. Paid API calls made by an agent (evals,
   walkthroughs) still need a cost estimate and the founder's OK per run.

## Unchanged invariants

- Teacher final authority: no `FinalGrade` without an explicit teacher action.
- No auto-finalisation; approved-only export; unresolved students export as
  `INCOMPLETE`.
- No student text, prompts or raw provider responses in logs, commits or exports.
- The provider SDK is imported only inside `apps/api/packages/brain`.
- The API key lives only in the gitignored local environment file and the
  server process; it is never sent to the browser or written to logs.

## Anthropic data handling, verified 2026-11-07

Checked against Anthropic's live documentation before any real script is sent:

- **Training:** "Retained data is never used for model training without your
  express permission." ([API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention))
- **Default retention (commercial API):** inputs and outputs are deleted
  automatically on Anthropic's backend within 30 days of receipt or generation,
  with exceptions for longer-retention services the customer controls (such as
  the Files API), agreed arrangements such as zero data retention, legal
  requirements and Usage Policy enforcement.
  ([How long do you store my organization's data?](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data))
- **Zero data retention (ZDR):** available only by arrangement with Anthropic, not
  by default. Message Batches, the Files API and code execution are stateful and
  are not covered by ZDR.
- **Flagged content:** inputs and outputs flagged by automated trust-and-safety
  systems may be kept for up to 2 years (classification scores up to 7 years),
  even under ZDR.
- **Covered Models:** Claude Fable 5/5.1 and Mythos 5/5.1 require 30-day retention.
  `claude-opus-5-5` is not on that list.

Implications for this project: the v2 runtime uses the standard Messages API
(no Files API, no Batches in the current plan), so default 30-day deletion
applies unless the founder obtains ZDR. If Message Batches ("Economy" mode) is
added later, its retention must be reviewed again.

## Founder actions

- Create two API keys in separate Console workspaces, each with its own monthly
  spend limit: `dev-evals` for eval runs and `app` for daily use. Check each
  workspace's rate-limit tier.
- Put the keys in the gitignored local environment file (`ANTHROPIC_API_KEY` for
  the app, `ANTHROPIC_EVAL_API_KEY` for evals) together with
  `BRAIN_PROVIDER=anthropic`, `BRAIN_ALLOW_REAL_PROVIDERS=true` and
  `ANTHROPIC_ENABLED=true`.
- Decide whether institutional rules on student data require more than this
  record (for example consent, ZDR, or a data-processing agreement).
