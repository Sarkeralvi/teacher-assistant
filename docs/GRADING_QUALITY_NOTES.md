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
