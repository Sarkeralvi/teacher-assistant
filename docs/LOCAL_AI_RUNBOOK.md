# Windows Local AI Runbook

This runbook operates the local Qwen and PaddleOCR integration for the Custom Controlled workflow. Both services are disabled by default, bind only to loopback, and must be started explicitly. Normal API startup and page loads never start a model.

## Safety contract

- Qwen receives teacher-confirmed text only. Answer-image bytes and local image paths are not sent to Qwen.
- PaddleOCR output is draft evidence until a teacher edits and confirms it.
- OCR confirmation updates `manual_answer_text`; it does not confirm a complete answer or make evidence grading-ready.
- Question-to-answer mapping remains manual or teacher-confirmed.
- Cohort grading is sequential, draft-only, stop-on-first-provider-failure, capped at 25 calls, and has zero automatic retries.
- There is no cloud, Codex, mock, or alternate-provider fallback.
- No model action creates a `FinalGrade`; review and approval remain mandatory.
- Docker stays mock-only for this milestone. Run local models and the API on the Windows host.

## One-time local configuration

Do not put machine paths or keys in committed files. Create the ignored `.env.local-ai` file with placeholders replaced by paths on the current machine:

```powershell
.\scripts\local-ai\Initialize-LocalAiConfig.ps1 `
  -QwenBinaryPath '<llama-server.exe>' `
  -QwenModelPath '<qwen-gguf>' `
  -OcrPythonPath '<python.exe-with-paddleocr-3.7.0>' `
  -OcrVlModelPath '<PaddleOCR-VL-1.6-directory>' `
  -OcrLayoutModelPath '<PP-DocLayoutV3-directory>'
```

The initializer creates separate random API keys. It enables the two local services but intentionally leaves `COHORT_MODEL_GRADING_ENABLED=false`. It refuses to overwrite an existing file.

If Windows blocks repository scripts under the machine execution policy, invoke them with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> ...`. This override applies only to that child process and does not change the machine policy.

## Preflight and startup

Run preflight before every startup:

```powershell
.\scripts\local-ai\Test-LocalAiPreflight.ps1
```

Preflight verifies the binary, GGUF, local OCR model files, Paddle imports/versions, and that ports 8080 and 8090 are free. It does not load either model.

Start both loopback services explicitly:

```powershell
.\scripts\local-ai\Start-LocalAi.ps1
```

The Qwen process uses the pinned model alias, offline mode, disabled reasoning, the reasoning parser required by Qwen 3.6 strict JSON grammars, one parallel slot, 32K context, GPU/hybrid offload, and an API key inherited through its environment. PaddleOCR loads its two local models once on CPU and accepts one image request at a time. The sidecar hides CUDA before importing the GPU-enabled Paddle wheel and disables PaddleX's optional GPU capability probe, preventing it from opening a competing CUDA context. Startup fails closed and stops newly launched processes if either health check fails.

To stop only the recorded and executable-verified processes:

```powershell
.\scripts\local-ai\Stop-LocalAi.ps1
```

Logs and PID files are under ignored `.local-ai/`. Never commit that directory.

## Start the host API with local settings

The API reads process environment variables (and `.env`), while model services use `.env.local-ai`. Import the ignored configuration into the same PowerShell session before starting the API:

```powershell
. .\scripts\local-ai\Common.ps1
Import-LocalAiEnvironment -Path .\.env.local-ai
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir apps\api --host 127.0.0.1 --port 8000
```

For OCR drafting and local reference extraction, keep `BRAIN_ALLOW_REAL_PROVIDERS=true`, `LOCAL_QWEN_ENABLED=true`, and `LOCAL_OCR_ENABLED=true`. To authorize safe cohort model execution, explicitly change the ignored local setting to `COHORT_MODEL_GRADING_ENABLED=true`, then restart/reload the host API environment. `COHORT_PROVIDER_RETRY_COUNT` must remain `0`.

Authenticated `GET /local-ai/status` reports enabled/available state and model names. It never returns keys or filesystem paths.

## Teacher workflow

1. Upload and teacher-confirm reference materials, canonical questions, model answers, and exactly one active rubric per question.
2. Upload scripts and create/confirm answer-region mappings manually.
3. On an answer region, choose **Draft text with local PaddleOCR**.
4. Inspect warnings, edit the OCR draft, and explicitly confirm the edited text.
5. Separately confirm full-answer evidence/continuation and rebuild evidence preparation and the grading queue.
6. On the Custom Controlled grading-run page, verify all four local-Qwen safety indicators.
7. Select one question and a call cap from 1 to 25, confirm draft-only authorization, and run preflight.
8. Review fresh/refused/existing/stale/active counts and authorize only the selected calls.
9. Monitor persistent dispatch progress. Stop prevents the next call but does not interrupt the current one. Resume runs only never-started items.
10. Inspect failed or uncertain items manually. Never retry an uncertain item automatically.
11. Use the existing review queue to edit/approve/reject suggestions. Export includes approved final grades only.

## Bounded synthetic acceptance smoke

Use synthetic/non-student material only:

1. Verify authenticated model and OCR health.
2. OCR one synthetic PNG/JPEG and inspect normalized text, Markdown, ordered blocks, warnings, and CPU device metadata.
3. Run one strict structured Qwen grading request and verify the exact alias, JSON schema, zero cost, token/latency metadata, and review flags.
4. Run two synthetic students through OCR draft, teacher text confirmation, evidence confirmation, queue rebuild, local cohort dispatch, review, approval, and approved-only XLSX export.
5. Confirm both services remain healthy together and that OCR uses CPU while Qwen uses GPU/hybrid offload.

The repeatable two-student smoke is skipped during ordinary CI. Run it only against an isolated disposable PostgreSQL database whose name ends in `_test`; the test clears that database before and after execution:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://<test-user>@127.0.0.1:<test-port>/teacher_assistant_test'
$env:RUN_LOCAL_AI_HOST_SMOKE = '1'
Push-Location apps\api
..\..\.venv\Scripts\python.exe -m pytest tests\test_local_ai_host_smoke.py -q -s
Pop-Location
```

Do not begin a teacher pilot until the 20-case gate in `TEACHER_CURATED_EVAL_PROTOCOL.md` passes.

## Failure handling

- Service unreachable or model mismatch: show the failure and stop; do not fall back.
- Malformed Qwen JSON: fail the item and stop the dispatch.
- OCR warning/blank output: keep it as an unconfirmed draft for teacher review.
- Evidence or rubric changed after queue creation: refuse the item and rebuild the queue after teacher review.
- Worker heartbeat expires during a call: mark the item `uncertain`; do not retry it automatically.
- Any cross-teacher visibility, automatic finalization, hidden provider call, unconfirmed OCR use, or blank/irrelevant over-scoring pattern blocks the pilot.
