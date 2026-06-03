# Grading Quality Notes

## TA-W2-027 — Controlled teacher observation readiness framing

Recorded at: 2026-06-03

### Updated quality interpretation
The previous `1(b)(i)` `4/6` result is invalid as a grading-quality benchmark because the evidence was incomplete: the graded region covered page 3 while the answer continued onto page 4 before `1(b)(ii)`.

The controlled multi-segment retest for `1(b)(i)` used page 3 plus the page 4 continuation, full-answer confirmation, and a `multi_segment_composite` grading context. The real Codex draft score was `6/6`, matching the founder fair score `6/6`, with confidence `0.88`, `needs_review=true`, and no `FinalGrade` created.

### Quality gate rule
Evidence completeness is now a primary quality gate. Do not judge grading quality unless the exact canonical grading unit, active rubric/model answer, and complete answer evidence are confirmed first. Incomplete crops, missing page continuations, wrong labels, or ambiguous max marks invalidate grading-quality conclusions.

### Observation implication
Teacher observation may now be prepared only as a controlled workflow/trust observation. It must not be framed as a production accuracy proof, public pilot, fully automated grading demo, or batch-grading validation.


## TA-W2-026 — Multi-segment answer evidence and continuation gate

Recorded at: 2026-06-03

### Root cause/classification
The latest one-call real grading attempt for `1(b)(i)` must be treated as invalid for quality benchmarking: `answer_region_id=5552` covered only one rectangle on page 3 while the student answer continued onto page 4 before `1(b)(ii)`. The failure class is answer-region capture / multi-page answer evidence, not primarily prompt quality.

### Product correction
A canonical grading unit may require multiple ordered answer segments. Real grading readiness must therefore validate segment completeness and continuation risk before provider execution.

### Implementation summary
- Added persistent `AnswerRegionSegment` support linked to existing `AnswerRegion` rows.
- Existing single-page regions remain backward-compatible through a primary segment.
- Evidence packets now report `segment_count`, `pages_covered`, ordered segment metadata, `continuation_check_status`, `next_page_context_available`, and full-answer confirmation state.
- A deterministic page-bottom heuristic marks possible continuation and blocks grading until teacher/founder full-answer confirmation is recorded.
- Multi-segment grading uses a local composite grading-context image with ordered segment labels, stored only in ignored local artifacts.

### Safety result
No real Codex was run in TA-W2-026. No teacher observation was started. The blocked path creates no `GradingJob`, `GradeSuggestion`, or `FinalGrade`. Teacher observation remains blocked until multi-segment evidence is validated with the full page 3 + page 4 `1(b)(i)` answer.


## TA-W2-025 — Evidence-first grading gate

Recorded at: 2026-06-03T10:05:27+06:00

### Quality finding

Before real grading, the product must prove the bounded grading evidence is correct: exact canonical grading unit, question text, solution/model answer, active rubric, and student answer crop/context. The founder principle is that grading quality depends first on confirmed evidence and mapping, not question-specific prompt hacks.

### Product/code change

Added an auditable pre-grading evidence packet endpoint and reused it as a backend readiness gate before grading provider/job execution. If the packet is not ready, grading returns HTTP 400 before creating a `GradingJob`, invoking Codex/OpenAI/mock providers, or creating downstream grading records.

### Required confirmation before real grading

Teacher/founder must confirm the exact question, solution/model answer, rubric, and student-answer mapping before any real grading run is quality-evaluable. Current confirmation fields remain `unknown` until the real-document evidence-packet flow is validated.

### Safety result

No real Codex was run, no batch grading was run, and focused tests cover that the evidence packet endpoint and blocked grading path create no `FinalGrade`. Teacher observation remains blocked until this evidence-packet flow is validated with real documents.

## TA-W2-024 — Crop/context audit and padded grading context

Recorded at: 2026-06-03T00:53:02+06:00

### Crop/context diagnosis

For the `1(b)(i)` Bayes answer, the original crop was too tight at the bottom/right. It captured much of the Bayes setup and denominator expansion, but cut off visible denominator arithmetic/result context. A 10% padded crop captured more complete visual evidence, including the denominator result, without adding excessive unrelated content.

The full rendered page still did not clearly show a completed posterior division/final value, so the issue is mixed: crop/context quality was a real contributor, but not the whole explanation for the remaining under-credit.

### Product/code change

AI grading now uses a separate padded, clamped grading-context crop by default (`ANSWER_REGION_GRADING_CROP_PADDING_RATIO=0.10`). Original answer-region coordinates and the stored teacher crop remain unchanged for audit/display. Grade suggestions record `grading_crop_padded` and safe relative metadata for the grading context image.

### Real Codex retest

One real Codex retest was run after the context fix. The previous TA-W2-023C score was `4/6`; the padded-context retest also returned `4/6`, while founder fair remains `6/6`. `needs_review=true` was preserved and no `FinalGrade` was created.

### Recommendation

Stop additional prompt/crop attempts on this case for now. Frame Codex as a conservative draft reviewer: useful for workflow validation and draft feedback, but teacher edit/final authority is necessary. Teacher observation should remain blocked for grading-accuracy demo purposes; if used at all, it should be framed only as workflow feedback.

## TA-W2-023B — Bayes/probability score-band grounding

Recorded at: 2026-06-03T00:16:25+06:00

### Quality finding from TA-W2-023A

The TA-W2-023 handwritten math/stat prompt improved two checked areas but did not fully solve Bayes under-crediting. In TA-W2-023A, `1(b)(i)` moved from `3/6` to `4/6`, while founder fair remained `6/6`. Codex recognized Bayes theorem and denominator expansion but still treated unclear numerator/final simplification as enough to keep the answer at mid-credit.

### Prompt/rubric grounding fix

The shared math/stat guidance now includes explicit 6-mark Bayes/probability score bands:

- `5-6`: Bayes or equivalent conditional-probability formula, target/evidence events, correct denominator/total-probability expansion, and plausible numerator/substitution or posterior value/expression, with no conditional-probability reversal. Messy handwriting, compressed arithmetic, or imperfect notation alone should not reduce a conceptually correct answer to mid-credit.
- `3-4`: correct formula but one important missing/unclear component, such as a missing denominator branch, numerator not tied to the target event, absent final arithmetic with unclear substitution, or recoverable event confusion.
- `0-2`: wrong conditional direction, no Bayes/conditional setup, unsupported numeric answer, or major conceptual mismatch.

### Deterministic calibration

The fake calibration adds a synthetic Bayes score-band target case: correct formula/events/denominator with compact or slightly unclear numerator/final expression and no conceptual reversal. Expected fake score: `5.5/6`, `needs_review=true`, no `FinalGrade`.

### Remaining caveat

This code/harness update still needs a capped one-region real retest on `1(b)(i)` before deciding whether teacher-observation rehearsal is safe. The optional TA-W2-023B retest was skipped because answer region `5120` was no longer present after required test-suite database cleanup.


## TA-W2-023 — Handwritten math/stat grading prompt grounding

Recorded at: 2026-06-02T23:00:47+06:00

### Root cause / quality diagnosis

TA-W2-022D proved the corrected canonical-unit workflow works technically, but exposed a grading-quality problem: Codex under-credited mathematically correct or near-correct handwritten work. The serious miss was `1(b)(i)`, where Codex scored `3/6` while the founder fair mark was `6/6`.

Corrected TA-W2-022D comparison:

| Subpart | Codex | Founder fair | Absolute error | Judgment |
| --- | ---: | ---: | ---: | --- |
| `1(a)(i)` | 2/6 | 3/6 | 1 | slightly too strict / acceptable-ish |
| `1(b)(i)` | 3/6 | 6/6 | 3 | too strict / serious miss |
| `1(c)(i)` | 4/5 | 4/5 | 0 | acceptable |

### Prompt/rubric grounding fix

The shared grading prompt now explicitly tells providers to grade against the exact canonical grading unit and max marks, use the active rubric/model answer as primary evidence, award credit for correct setup/formula/substitution/final answer, and avoid over-penalizing messy handwriting or imperfect notation when the mathematical intent is clear.

For probability/Bayes/statistics, the prompt now specifically calls out substantial credit for correct formula and numerator/denominator event identification, compressed arithmetic with a present result/setup, and the difference between conceptual errors, arithmetic slips, notation/presentation issues, incomplete working, and correct setup with missing final simplification.

### Remaining caveat

No real Codex calibration was run in TA-W2-023. The deterministic harness protects the intended prompt behavior, but a small founder real-document retest is still required before teacher in-person observation.


## TA-W2-022C — Canonical grading-unit correction before real retest

Recorded at: 2026-06-02T21:06:01+06:00

### Finding

TA-W2-022B's founder real-document rehearsal must not be treated as grading-quality evidence. The real grading calls were made against an ambiguous/wrong canonical setup: reported labels like `2(a)(i)`, `2(b)(i)`, and `2(c)(i)` did not match the founder-confirmed material, which is Question 1.

### Correct structure to use before any real retest

- Whole sub-question totals: `1(a)=10`, `1(b)=12`, `1(c)=13`.
- Subpart totals: `1(a)(i)=6`, `1(a)(ii)=4`, `1(b)(i)=6`, `1(b)(ii)=6`, `1(c)(i)=5`, `1(c)(ii)=4`, `1(c)(iii)=4`.

### Rule for future quality runs

A real grading run is not quality-evaluable unless the canonical grading-unit table is explicitly confirmed first and the run clearly states whether it is grading a whole sub-question (`1(a)`) or a subpart (`1(a)(i)`) with the correct max marks.

## TA-W2-019 — Marking policy calibration prompt and harness update

Recorded at: 2026-06-02T08:00:00+06:00

### Scope

- Policy prompt update: shared Tough/General/Easy guidance now uses one source of truth.
- Deterministic harness: synthetic non-student examples only; fake mode is the default.
- Real provider calibration: not run in this task.
- Production/batch grading: not run.

### Synthetic calibration cases and fake scores

|| Case | Scenario | Tough | General | Easy |
|| --- | --- | ---: | ---: | ---: |
|| A | Correct final answer, weak/no working | 3.0 | 5.0 | 7.0 |
|| B | Partially correct method with one wrong step | 2.0 | 4.0 | 6.0 |
|| C | Mostly complete answer with minor notation issue | 7.0 | 8.0 | 9.0 |

### Result

- `tough <= general <= easy`: true for every synthetic case.
- Meaningful separation: true on the controlled synthetic set.
- Final grade creation: none.
- Real Codex calls: 0 in this task.

### Interpretation

This is a prompt-and-test calibration fix, not a claim about real classroom data. The harness is useful for regression checks and documentation, but future real-provider calibration is still needed before making stronger quality claims about live grading behavior.

## TA-W1-031 — Tiny synthetic grading-quality evaluation

Recorded at: 2026-05-29T10:04:17Z

### Scope

- Dataset type: tiny synthetic non-student grading-quality set.
- Case count: 5.
- Answer types: correct, partial, wrong, blank, irrelevant.
- Real provider: Codex CLI through the existing Brain Adapter / GradingService path.
- Real-provider cap used: `--max-real-cases 5`.
- Browser default real grading: not enabled.
- Production/batch grading: not run.

### Generated artifacts

Generated case JSONL and evaluation reports were written under ignored temporary paths:

- Dataset: `/tmp/ta_w1_031_grading_cases.jsonl`
- Mock eval JSON/Markdown: `/tmp/ta_w1_031_mock_eval/grading-eval-20260529T100030Z.*`
- Real Codex eval JSON/Markdown: `/tmp/ta_w1_031_codex_eval/grading-eval-20260529T100417Z.*`

Generated PNG answer fixtures were stored under ignored `data/artifacts/answer_regions/...` paths.

### Per-case real Codex result

| Case | Answer type | Expected | Codex score | Absolute error | Confidence | Needs review |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `synthetic_grading_01_correct` | correct | 5.00 | 5 | 0.00 | 0.98 | true |
| `synthetic_grading_02_partial` | partial | 3.00 | 3 | 0.00 | 0.93 | true |
| `synthetic_grading_03_wrong` | wrong | 1.00 | 0 | 1.00 | 0.98 | true |
| `synthetic_grading_04_blank` | blank | 0.00 | 0 | 0.00 | 0.95 | true |
| `synthetic_grading_05_irrelevant` | irrelevant | 0.00 | 0 | 0.00 | 0.99 | true |

### Real Codex metrics

- `case_count`: 5
- `exact_match_rate`: 0.8
- `within_1_mark_rate`: 1
- `mean_absolute_error`: 0.20
- `false_confident_error_count`: 0
- `average_confidence`: 0.966
- `needs_review_rate`: 1
- `severe_error_count`: 0
- `over_score_count`: 0
- `under_score_count`: 1

### Interpretation

This does **not** establish production grading accuracy. It only shows that, on a tiny synthetic set, the real Codex grading path can score simple correct/partial/blank/irrelevant cases as expected and stayed within one mark for the deliberately wrong case. Teacher-curated classroom samples are still required before trusting grading quality.

## TA-W1-033B — Teacher-marked correct-answer evaluation cases staged

Recorded at: 2026-05-29T21:21:18 local session source PDFs.

### Scope

- Dataset type: teacher-marked correct-answer evaluation draft from provided anonymized marking metadata.
- Dataset path: `/tmp/ta_teacher_eval_cases/teacher_marked_correct_cases_q1_q20.jsonl`.
- Case count: 20 teacher-marked cases, Q1–Q20.
- Teacher score status: all cases are full-score correct answers (`expected_score = 5`, `max_score = 5`).
- Anonymization: teacher/founder confirmation says the answer-sheet image contains no student name, roll number, ID number, school name, address, phone number, email address, or other private identifying information.
- Real provider grading: not run.
- Production code: not changed.

### Image-backed status

- Q1–Q8: image-backed local answer crops staged under `/tmp/ta_teacher_eval_cases/crops/`.
- Q9–Q20: metadata-only rows with `answer_image_path = null` and `image_status = missing_image_pending` because matching answer images/pages were not part of the provided instruction set.
- Generated images/crops were not committed.

### Validation

Validated the JSONL shape locally:

- Q1–Q20 rows exist.
- `expected_score <= max_score` for every row.
- Rubric criterion marks sum to `max_score` for every row.
- `answer_type` is present for every row.
- Anonymization confirmation is present for every row.
- Q1–Q8 image-backed paths exist locally.
- Q9–Q20 are marked `missing_image_pending`.

### Interpretation

This staged set is useful for checking correct-answer recognition and rubric/schema handling. It is **not** a complete grading-quality dataset because all rows are correct full-score answers. Partial, wrong, blank, irrelevant, mixed-quality, and hard real classroom cases are still needed before broader grading-quality claims.


## TA-W1-033C — Real Codex evaluation on Q1–Q8 teacher-marked correct cases

Recorded at: 2026-05-29T22:02:08 local session source PDF.

### Scope

- Evaluation type: limited real Codex grading evaluation on the 8 image-backed teacher-marked correct cases only.
- Input dataset: `/tmp/ta_teacher_eval_cases/teacher_marked_correct_cases_q1_q20.jsonl` filtered to Q1–Q8.
- Answer crops: `/tmp/ta_teacher_eval_cases/crops/q01.png` through `q08.png`.
- Temporary storage root: `/tmp/ta_teacher_eval_033c_storage`.
- Evaluation artifacts:
  - JSON: `/tmp/ta_teacher_eval_033c_artifacts/grading-eval-20260529T161405Z.json`
  - Markdown: `/tmp/ta_teacher_eval_033c_artifacts/grading-eval-20260529T161405Z.md`
- Provider path: existing grading evaluation harness with `provider_mode = codex_cli`, `allow_real_provider = true`, `max_real_cases = 8`, and Codex CLI image input enabled.
- Production code/UI: not changed.
- Production/batch grading: not run.
- Raw images/crops/eval artifacts: not committed.

### Metrics

- `case_count`: 8
- `exact_match_rate`: 1
- `within_1_mark_rate`: 1
- `mean_absolute_error`: 0.00
- `false_confident_error_count`: 0
- `severe_error_count`: 0
- `over_score_count`: 0
- `under_score_count`: 0
- `needs_review_rate`: 1
- `average_confidence`: 0.99
- `by_answer_type.correct.case_count`: 8
- `by_answer_type.correct.exact_match_rate`: 1
- `by_answer_type.correct.within_1_mark_rate`: 1
- `by_answer_type.correct.mean_absolute_error`: 0.00

### Per-case result

| Case | Expected | Codex score | Absolute error | Confidence | Needs review | Review flags |
|---|---:|---:|---:|---:|---|---|
| teacher_marked_correct_q01 | 5 | 5 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q02 | 5 | 5.0 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q03 | 5 | 5.0 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q04 | 5 | 5 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q05 | 5 | 5.0 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q06 | 5 | 5.0 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q07 | 5 | 5 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |
| teacher_marked_correct_q08 | 5 | 5 | 0.00 | 0.99 | true | teacher_review_required, codex_cli_provider, image_input_used |

### Interpretation

This run only supports the narrow claim that the real Codex CLI grading path matched the teacher full-score labels on these 8 image-backed correct-answer cases. It does **not** prove grading accuracy on partial, wrong, blank, irrelevant, messy, or broader classroom cases. TA-W1-033 remains Partial/Pending until mixed-quality teacher-curated cases and missing Q9–Q20 images are collected.

## TA-W1-034A — Original document grading evaluation smoke

Recorded at: 2026-05-30T06:20:04Z local session source PDFs.

### Scope

- Evaluation type: limited original-document smoke using founder-provided real PDFs, not AI-synthetic examples.
- Input PDFs copied to ignored `/tmp/ta_original_doc_eval/input/`:
  - `Section-A_question_solution_and_rubric.pdf` — 13 rendered pages.
  - `script-1.pdf` — 13 rendered pages.
  - `Script-2.pdf` — 17 rendered pages.
- Rendered page images and contact sheets were kept under ignored `/tmp/ta_original_doc_eval/pages/` and `/tmp/ta_original_doc_eval/artifacts/contact_sheets/`.
- Privacy/anonymization check: contact-sheet inspection found no obvious student name, roll/ID, phone/email, or private institution details in the selected smoke pages; full production use still needs explicit anonymization review.
- Production/batch grading: not run.
- Final grades: not created.
- Browser default real Codex grading: not enabled.
- Product code/UI: not changed.
- Raw PDFs/page images/crops/eval artifacts: not committed.

### Selected smoke cases

| Case | Source | Page | Question label | Expected teacher score | Codex score | Absolute error | Confidence | Needs review |
|---|---|---:|---|---:|---:|---:|---:|---|
| `orig_s1_p04_q2a` | `script-1.pdf` | 4 | `S1-P4-Q2(a)` | 10.00 / 10.00 | 9.25 | 0.75 | 0.84 | true |
| `orig_s1_p05_q2b` | `script-1.pdf` | 5 | `S1-P5-Q2(b)` | 10.00 / 10.00 | 10.0 | 0.00 | 0.91 | true |
| `orig_s2_p07_q1c` | `Script-2.pdf` | 7 | `S2-P7-Q1(c)` | 7.00 / 10.00 | 9.5 | 2.50 | 0.82 | true |

### Metrics

- `case_count`: 3
- `exact_match_rate`: 0.3333333333333333333333333333
- `within_1_mark_rate`: 0.6666666666666666666666666667
- `mean_absolute_error`: 1.083333333333333333333333333
- `false_confident_error_count`: 1
- `severe_error_count`: 1
- `over_score_count`: 1
- `under_score_count`: 1
- `needs_review_rate`: 1
- `average_confidence`: 0.8566666666666666666666666667
- `by_answer_type.correct.case_count`: 2; exact match 0.5; within 1 mark 1; MAE 0.375
- `by_answer_type.partial.case_count`: 1; exact match 0; within 1 mark 0; MAE 2.50

### Artifact paths

- Stage manifest: `/tmp/ta_original_doc_eval/artifacts/original_doc_smoke_stage_manifest.json`
- Eval dataset: `/tmp/ta_original_doc_eval/artifacts/original_doc_smoke_cases.json`
- Real Codex eval JSON: `/tmp/ta_original_doc_eval/artifacts/grading_eval/grading-eval-20260530T061922Z.json`
- Real Codex eval Markdown: `/tmp/ta_original_doc_eval/artifacts/grading_eval/grading-eval-20260530T061922Z.md`

### Interpretation

The current app can ingest the original PDFs, render real script pages, create manually controlled full-page answer regions, and run the existing Codex CLI grading evaluation path on a capped 3-case smoke set. The run also exposed a quality limitation: the partial teacher-marked case was over-scored by 2.5 marks with confidence 0.82, so teacher review remains mandatory and broader original-document grading remains manual/controlled until better question/rubric extraction, tighter region mapping, and more mixed teacher-marked cases are evaluated.

## TA-W1-037B — Original-script Codex image-input grading evaluation

Recorded at: 2026-05-31T07:42:35Z local run.

### Scope

- Evaluation type: capped real-original-script grading evaluation using Codex CLI image input.
- Input workspace: `/tmp/ta_original_doc_eval_image_input/`.
- Re-staged original/sample inputs from ignored/local data paths into `/tmp/ta_original_doc_eval_image_input/input/`:
  - `question.pdf`, `solution.pdf`, `rubric.pdf`
  - `script-1.pdf` — 13 rendered pages.
  - `Script-2.pdf` — 17 rendered pages.
- Selected answer crops were tightened manually from rendered page images and copied under ignored `/tmp/ta_original_doc_eval_image_input/storage/artifacts/answer_regions/`.
- Real provider settings: `provider=codex_cli`, `TA_EVAL_ALLOW_REAL_PROVIDER=true`, `CODEX_CLI_IMAGE_INPUT_ENABLED=true`, `max_real_cases=3`.
- All three GradeSuggestion rows recorded `teacher_review_required`, `codex_cli_provider`, and `image_input_used`.
- Final grades: not created; verified `final_grade_count = 0` after the eval.
- Production/batch grading, UI changes, auto-finalization, fully automated grading, and TA-W1-038: not run.
- Raw PDFs/page images/crops/eval artifacts: not committed.

### Selected image-input cases

| Case | Source | Page | Question label | Expected teacher score | Codex score | Absolute error | Confidence | Needs review | Review flags | Crop note |
|---|---|---:|---|---:|---:|---:|---:|---|---|---|
| `orig_s1_p04_q2a_image_input` | `script-1.pdf` | 4 | `2(a)` | 10.00 / 10.00 | 9.5 | 0.50 | 0.86 | true | `teacher_review_required`, `codex_cli_provider`, `image_input_used` | tightened crop around full Q2(a) answer and teacher mark |
| `orig_s1_p05_q2b_image_input` | `script-1.pdf` | 5 | `2(b)` | 10.00 / 10.00 | 10.0 | 0.00 | 0.95 | true | `teacher_review_required`, `codex_cli_provider`, `image_input_used` | tightened crop around full Q2(b) answer and teacher mark |
| `orig_s2_p07_q1c_image_input` | `Script-2.pdf` | 7 | `1(c)` | 7.00 / 10.00 | 8.0 | 1.00 | 0.72 | true | `teacher_review_required`, `codex_cli_provider`, `image_input_used` | tightened crop around the previous problematic partial-credit answer |

### Metrics

- `case_count`: 3
- `exact_match_rate`: 0.3333333333333333333333333333
- `within_1_mark_rate`: 1
- `mean_absolute_error`: 0.50
- `false_confident_error_count`: 0
- `severe_error_count`: 0
- `over_score_count`: 1
- `under_score_count`: 1
- `needs_review_rate`: 1
- `average_confidence`: 0.8433333333333333333333333333
- `by_answer_type.correct.case_count`: 2; exact match 0.5; within 1 mark 1; MAE 0.25
- `by_answer_type.partial.case_count`: 1; exact match 0; within 1 mark 1; MAE 1.00

### Artifact paths

- Stage manifest: `/tmp/ta_original_doc_eval_image_input/artifacts/stage_manifest.json`
- Eval dataset: `/tmp/ta_original_doc_eval_image_input/artifacts/original_script_image_input_cases.json`
- Real Codex image-input eval JSON: `/tmp/ta_original_doc_eval_image_input/artifacts/grading_eval/grading-eval-20260531T074059Z.json`
- Real Codex image-input eval Markdown: `/tmp/ta_original_doc_eval_image_input/artifacts/grading_eval/grading-eval-20260531T074059Z.md`
- Crops: `/tmp/ta_original_doc_eval_image_input/crops/` and `/tmp/ta_original_doc_eval_image_input/storage/artifacts/answer_regions/`

### Comparison to TA-W1-034A

The same previous problematic case, `orig_s2_p07_q1c`, improved from Codex 9.5 vs expected 7.0 (`absolute_error=2.50`, confidence 0.82, false-confident/severe over-score) to Codex 8.0 vs expected 7.0 (`absolute_error=1.00`, confidence 0.72, no false-confident flag). This is an improvement on that selected crop, but it is still an over-score and still requires teacher review.

### Interpretation

This run proves real Codex CLI image input can be used by the existing grading evaluation path on selected original-script crops, and all evaluated suggestions remained review-only. Quality improved versus the earlier no-browser-image-input/problematic case, but the sample is only three manually selected/tightened crops; it does **not** prove production grading reliability, batch grading readiness, automatic answer-region detection, or fully automated grading readiness.

## TA-W2-006A — Marking policy calibration smoke

Recorded at: 2026-05-31T11:36:07Z.

### Scope

- Evaluation type: small controlled synthetic marking-policy calibration smoke.
- Real provider: Codex CLI provider, text-only synthetic prompts, image input disabled.
- Real Codex calls: 6 total.
- Cases: 2 synthetic non-student cases × 3 policies (`tough`, `general`, `easy`).
- Artifacts: ignored temporary path `/tmp/ta_w2_006a_policy_calibration/`.
- Production/batch grading: not run.
- Final grades: not created.
- Product code/UI: not changed during this smoke.
- Raw generated artifacts: not committed.

### Cases and scores

| Case | Tough | General | Easy | `tough <= general <= easy` |
|---|---:|---:|---:|---|
| Partial derivative answer missing `+2` term | 3 / 5 | 3 / 5 | 3 / 5 | yes |
| Correct final linear-equation answer with no working | 3 / 5 | 3 / 5 | 3 / 5 | yes |

### Observed behavior

- The required monotonic relation held, but only because all three policies produced identical scores for both cases.
- The policy was recorded correctly in review flags for every run: `marking_policy:tough`, `marking_policy:general`, and `marking_policy:easy`.
- All runs kept `needs_review = true` and included `teacher_review_required`.
- Feedback wording differed only slightly across policies. It did not materially change scoring on these two simple rubric-separated examples.

### Interpretation

This smoke confirms that policy metadata reaches the real Codex grading path and is recorded in outputs. It does **not** show meaningful score calibration between Tough, General, and Easy. The tested rubrics had clearly separable criteria, so Codex awarded criterion marks deterministically. Before treating policy as a reliable scoring control, use more ambiguous partial-credit cases or tighten the prompt/rubric design so policy can affect borderline evidence without changing maximum marks or teacher-review requirements.
