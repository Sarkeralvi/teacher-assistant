# Grading Quality Notes

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

