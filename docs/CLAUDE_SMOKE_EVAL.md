# Claude smoke eval against your own marks (v2 Phase 1)

This runs Claude (Anthropic API) through the real Bulk Supervised pipeline on the sample
exam in `E:\Question, solution, rubric and scripts` and compares every draft grade with
your own mark for that question part. It is a smoke test: two scripts are enough to debug
prompts and measure cost and speed, not to decide when AI marks can be trusted. Trust is
set later from calibration-mode marking on a real exam.

You run the commands yourself, in your own PowerShell window. Each paid step first prints
an estimate and stops; it sends nothing until you add `--yes`. A hard dollar cap stops the
run before any call that would go past it.

## Before you start (one time)

1. In the Anthropic Console, create a workspace named `dev-evals` with a monthly spend
   limit, and an API key in it. Keep your `app` workspace key separate.
2. Add these lines to `E:\teacher-assistant\.env` (the gitignored local environment file):

   ```text
   ANTHROPIC_EVAL_API_KEY=<the dev-evals key>
   ```

   For the app itself (not needed for the eval) add:

   ```text
   BRAIN_PROVIDER=anthropic
   BRAIN_ALLOW_REAL_PROVIDERS=true
   ANTHROPIC_ENABLED=true
   ANTHROPIC_API_KEY=<the app key>
   ```

3. Put your marks in `E:\Question, solution, rubric and scripts\marks.csv`:

   ```text
   script_file,student_id,part_label,mark
   <file name of the student PDF>,<student id>,1(a),3.5
   ```

   One row per student per question part. `script_file` is the PDF's name inside
   `Scripts-flat.zip`.

## Step 1: draft the blueprint (one Claude call)

From `E:\teacher-assistant\apps\api`:

```powershell
..\..\.venv\Scripts\python.exe scripts\eval_against_teacher_marks.py extract --exam-dir "E:\Question, solution, rubric and scripts" --out "E:\Question, solution, rubric and scripts\eval-runs\blueprint" --env-file E:\teacher-assistant\.env
```

Read the estimate. To send, run the same command with `--yes` added at the end.

Open `eval-runs\blueprint\blueprint.draft.json`. For every question part, check the
question number, marks, model answer and each rubric criterion against the PDFs. Correct
anything wrong (criterion marks must add up to the question's marks) and save the result as
`eval-runs\blueprint\blueprint.confirmed.json`.

If your part labels differ from the blueprint's (for example `1a` versus `1(a)`), the
runner matches them loosely. Anything it still cannot match goes into a small JSON file,
`{"your label": "blueprint label"}`, passed as `--label-map`.

## Step 2: run the scripts and compare

```powershell
..\..\.venv\Scripts\python.exe scripts\eval_against_teacher_marks.py run --exam-dir "E:\Question, solution, rubric and scripts" --blueprint "E:\Question, solution, rubric and scripts\eval-runs\blueprint\blueprint.confirmed.json" --blueprint-draft "E:\Question, solution, rubric and scripts\eval-runs\blueprint\blueprint.draft.json" --marks "E:\Question, solution, rubric and scripts\marks.csv" --out "E:\Question, solution, rubric and scripts\eval-runs\run-144dpi" --env-file E:\teacher-assistant\.env
```

Read the estimate, then add `--yes` (and `--max-cost-usd 5` or similar to set your own
cap). The run creates a throwaway database, reads every page, assigns answers, confirms
each transcript in code (labelled eval-only), drafts grades, compares them with your marks,
and deletes the throwaway database.

Optional resolution comparison: repeat Step 2 with `--render-dpi 220` and
`--out ...\eval-runs\run-220dpi`.

## What you get

In the `--out` folder (outside the repository; it contains student marks, keep it
private):

- `summary.json`: exact matches, within half a mark, mean absolute error, over- and
  under-scored parts, whether the large misses were flagged for review, blueprint
  corrections, and calls, tokens, cost and latency per stage. No student text.
- `per_part.csv`: one row per student and part with your mark, Claude's draft, the
  difference, confidence and review flags.
- `calls.jsonl`: one metadata line per Claude call (no text).

To get help reading the result, tell Claude where `summary.json` is.

## Safety notes

- The runner refuses any database whose name does not end in `_test`, refuses an output
  folder inside the repository, uses only `ANTHROPIC_EVAL_API_KEY`, and creates no final
  grade.
- Only the `ANTHROPIC_*` names it needs are read from `--env-file`; values are never
  printed.
