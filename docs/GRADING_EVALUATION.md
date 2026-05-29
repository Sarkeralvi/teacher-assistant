# Grading Evaluation Harness

TA-W1-015 adds a small backend-only harness for measuring grading behavior before trusting AI grading suggestions.

## Dataset format

Use JSONL for small hand-curated cases. Each line is one case:

```json
{"case_id":"case_001","answer_region_id":277,"question_id":429,"rubric_id":283,"expected_score":"5.00","max_score":"5.00","teacher_notes":"Correct answer with full working."}
```

The same objects may also be stored as a JSON array or under a top-level `cases` key.

Fields:

- `case_id`: stable human-readable case identifier.
- `answer_region_id`: existing cropped answer region to grade.
- `question_id`: expected question for the answer region.
- `rubric_id`: active rubric expected for the question.
- `expected_score`: teacher/reference score.
- `max_score`: maximum score for the case; must match active rubric total marks.
- `teacher_notes`: optional reference notes for later analysis.
- `answer_type`: optional controlled-case label: `correct`, `partial`, `wrong`, `blank`, `irrelevant`, or `unknown`.
- `generated_fixture_reference`: optional relative storage path for synthetic answer images.
- `question_text`, `model_answer`, `rubric`: optional denormalized reference context for reports.

## Tiny synthetic grading-quality dataset

For grading-quality evaluation only, the harness includes a helper that creates five non-student PNG answer fixtures and matching database records:

- fully correct answer
- partially correct answer
- wrong answer
- blank answer
- irrelevant answer

Example dataset creation from an app shell:

```bash
cd apps/api
python - <<'PY'
import json
from pathlib import Path
from app.db.session import SessionLocal
from packages.evaluation.grading_evaluation import create_synthetic_grading_quality_dataset, _jsonable

out = Path('/tmp/ta_w1_031_grading_cases.jsonl')
with SessionLocal() as db:
    cases = create_synthetic_grading_quality_dataset(db)
with out.open('w', encoding='utf-8') as handle:
    for case in cases:
        handle.write(json.dumps(_jsonable(case), sort_keys=True) + '\n')
print(out)
PY
```

Generated PNGs are stored under the ignored local storage artifact tree and should not be committed.

## Running mock evaluation

Default mode is safe mock provider:

```bash
cd apps/api
python -m packages.evaluation.grading_evaluation /path/to/cases.jsonl --provider mock
```

## Running real Codex evaluation

Real provider runs are blocked unless explicitly enabled and capped:

```bash
cd apps/api
TA_EVAL_ALLOW_REAL_PROVIDER=true \
python -m packages.evaluation.grading_evaluation /path/to/cases.jsonl \
  --provider codex_cli \
  --allow-real-provider \
  --max-real-cases 1
```

Do not use this on production/bulk data. Current hard guard defaults to max 5 real cases, and TA-W1-015 policy allows at most one real case unless separately approved.

## Metrics

The harness writes JSON and Markdown artifacts under:

```text
data/exports/grading_evals/
```

Implemented metrics:

- `exact_match_rate`
- `within_1_mark_rate`
- `mean_absolute_error`
- `false_confident_error_count`
- `average_confidence`
- `needs_review_rate`
- `severe_error_count` where absolute error is at least 2 marks
- `over_score_count`
- `under_score_count`
- `by_answer_type` breakdown with count, exact-match rate, within-1-mark rate, mean absolute error, and average confidence

False-confident errors are cases where:

```text
confidence >= 0.8 and absolute_error > 1
```
