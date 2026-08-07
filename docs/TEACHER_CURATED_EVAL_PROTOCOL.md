# Teacher-Curated Grading Evaluation Protocol

TA-W1-032 defines a safe process for collecting real teacher-curated grading examples and comparing AI grading suggestions against teacher marks. This is a documentation/process protocol only; it does not enable production grading, real-provider batch grading, or automatic final marks.

## 1. Purpose

- Measure whether AI grading suggestions are useful enough to support a teacher review workflow.
- Compare AI suggestions against teacher/reference marks.
- Identify disagreement patterns before trusting the grading path with classroom data.
- Keep teacher judgement as the authority for final marks.
- Avoid using evaluation results as production accuracy claims until the dataset is large, representative, and teacher-approved.

## 2. Data rules

- Use anonymized synthetic samples, consented samples, or teacher-curated samples only.
- Remove student names, roll numbers, IDs, phone numbers, addresses, institution identifiers, and other sensitive personal data where possible.
- Do not commit raw student answer images, raw scans, or sensitive evaluation artifacts to git unless they have been explicitly sanitized and approved for repository storage.
- Store unsanitized evaluation artifacts outside git, preferably under ignored local artifact/export paths.
- Keep only safe metadata, templates, and documented protocols in git.
- If screenshots/examples are used in reports, include them only when allowed and sanitized.

## 3. Minimum dataset targets

- First target: 20 teacher-curated cases.
- Next target: 50 teacher-curated cases.
- Later target: 100+ cases across courses, question types, handwriting quality levels, and answer-quality categories.

A tiny synthetic dataset can validate the pipeline, but it is not enough for production trust.

### Local PaddleOCR + Qwen pilot gate

The first local-provider teacher pilot is blocked until at least 20 mixed curated cases have completed the full draft-evidence and grading review path. Use this minimum allocation:

- 3 correct
- 3 partial
- 3 wrong
- 2 blank
- 2 irrelevant
- 3 difficult-handwriting
- 2 formula-heavy
- 2 multi-step-work cases

Record PaddleOCR draft text, warnings, teacher-edited confirmed text, review flags, and teacher/reference score for every case. Record a Qwen structured suggestion for each of the 18 nonblank grading-ready cases. The two blank cases must be confirmed as blank, refused before dispatch, and recorded as `not_called_blank_safety_gate`; sending placeholder text to Qwen would invalidate the run. Difficult handwriting and formula cases must measure OCR transcription quality separately from grading quality; a teacher correction can make grading accurate without proving OCR accurate.

The local pilot remains blocked if any case shows:

- a severe false-confident grading error
- systematic or repeated over-scoring of blank/irrelevant answers
- automatic grade finalization or an unapproved export
- Qwen grading unconfirmed OCR/manual text
- cross-teacher access to OCR, dispatch, review, or export data
- a hidden provider call, cloud call, fallback provider, or automatic provider retry
- an uncertain worker outcome being retried automatically

The report must name the local provider/model aliases, Paddle versions/models/device, prompt version, call cap, and whether Qwen and CPU OCR stayed healthy concurrently. Passing this gate permits only a supervised Custom Controlled pilot; it does not activate Semi-Automated or Fully Automated modes.

The canonical local harness is `packages.evaluation.local_curated_evaluation`. It enforces the ordered states `prepared`, `ground_truth_locked`, `ocr_completed`, `ocr_confirmed`, `grading_completed`, `review_completed`, and `reported`, with `invalid` as an irreversible terminal state. Its operator workflow and conservative thresholds are documented in `LOCAL_CURATED_EVAL_RUNBOOK.md`.

## 4. Case categories

Each pilot dataset should include examples from these categories:

- `correct`: answer is essentially correct and should receive full or near-full marks.
- `partial`: answer contains useful work but misses steps, reasoning, units, or final result.
- `wrong`: answer attempts the question but earns low/no marks under the rubric.
- `blank`: no meaningful answer is present.
- `irrelevant`: answer content is unrelated to the question.
- `hard_to_read_handwriting`: answer is difficult to read and may require teacher judgement.
- `multiple_step_solution`: solution quality depends on intermediate reasoning.
- `formula_only_answer`: answer gives formulas/results without enough reasoning.
- `conceptual_answer`: answer is explanatory rather than numeric.

## 5. Per-case required fields

Each curated case should preserve enough context to make disagreement analysis possible:

- `case_id`: stable unique identifier.
- `course`: course, subject, or topic label.
- `question_text`: the exact question text or sanitized equivalent.
- `model_answer`: expected/model answer, if available.
- `rubric`: marking criteria used by the teacher.
- `expected_score`: teacher/reference score.
- `max_score`: maximum score for the question/case.
- `teacher_notes`: optional explanation of the mark and expected reasoning.
- `answer_type`: one of the category labels above.
- `answer_image_path` or `answer_region_id`: sanitized image reference or existing app answer-region ID.
- `anonymization_status`: e.g. `synthetic`, `anonymized`, `consented`, or `needs_review_before_git`.

## 6. Evaluation metrics to track

Minimum summary metrics:

- `exact_match_rate`: AI score exactly equals teacher/reference score.
- `within_1_mark_rate`: AI score is within one mark of teacher/reference score.
- `mean_absolute_error`: average absolute difference between AI and teacher/reference score.
- `false_confident_error_count`: high-confidence AI suggestions that are meaningfully wrong.
- `severe_error_count`: cases where score error is large enough to be dangerous for classroom use.
- `over_score_count`: AI score is higher than teacher/reference score.
- `under_score_count`: AI score is lower than teacher/reference score.
- `by_answer_type_breakdown`: metrics grouped by answer category.

Optional qualitative fields:

- disagreement reason
- teacher correction note
- prompt/model version
- image/readability issue
- rubric ambiguity

## 7. Go/no-go thresholds for pilot use

For early pilot use, the goal is not full automation. The goal is to decide whether AI suggestions are worth showing to a teacher.

Minimum go/no-go rules:

- No severe false-confident errors in a small pilot set.
- A high `needs_review` rate is acceptable and expected.
- Teacher must approve final marks.
- AI score must never directly become the final score.
- Any over-scoring pattern on weak, irrelevant, or blank answers is a stop condition for broader use.
- Any privacy/anonymization uncertainty is a stop condition for repository storage.

## 8. Review process

Use this order for every curated evaluation run:

1. Teacher marks first.
2. AI grades second.
3. Compare results.
4. Discuss disagreements with the teacher.
5. Record whether the issue is rubric ambiguity, unreadable handwriting, prompt weakness, model weakness, or dataset-quality weakness.
6. Update rubric or prompt only after analysis; do not tune blindly against one case.
7. Keep final marks teacher-controlled.

## 9. Reporting format

Each evaluation report should include:

- summary metrics
- per-case disagreements
- screenshots/examples only if allowed and sanitized
- prompt/model version
- provider name and configuration
- dataset size and category distribution
- privacy/anonymization status
- explicit limitation statement: evaluation results are not production accuracy claims

## 10. Privacy and security notes

- Do not expose student identity in prompts, logs, reports, screenshots, or committed artifacts.
- Do not upload non-consented student data to external AI providers.
- Do not commit real answer images unless explicitly sanitized and approved.
- Keep API keys, provider responses, raw prompts with sensitive text, and runtime artifacts out of git.
- Prefer synthetic or fully anonymized examples until consent and data-handling rules are clear.

## 11. Next step after this protocol

TA-W1-033 should collect the first 20 teacher-curated grading evaluation cases using this protocol. The first collection pass should focus on safe, anonymized or synthetic/consented examples and should not change production grading behavior.
