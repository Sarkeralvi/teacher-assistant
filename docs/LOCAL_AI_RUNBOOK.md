# Windows Local AI Runbook

This runbook operates the local Qwen and PaddleOCR integration for the Custom Controlled workflow. Both services are disabled by default, bind only to loopback, and must be started explicitly. Normal API startup and page loads never start a model.

## Safety contract

- Qwen receives teacher-confirmed text only. Answer-image bytes and local image paths are not sent to Qwen.
- PaddleOCR output is draft evidence until a teacher confirms an immutable baseline or one candidate per automatically detected band.
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
  -OcrLayoutModelPath '<PP-DocLayoutV3-directory>' `
  -OcrTextDetModelPath '<PP-OCRv6_medium_det-directory>' `
  -OcrTextRecModelPath '<PP-OCRv6_medium_rec-directory>'
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

The Qwen process uses the pinned model alias, offline mode, disabled reasoning, one parallel slot, 32K context, GPU/hybrid offload, and API-key protection. The PaddleOCR sidecar loads PaddleOCR-VL, PP-DocLayoutV3, PP-OCRv6 medium detection, and PP-OCRv6 medium recognition once and accepts one image request at a time. Enhanced rescue runs use the explicit `OcrGpu` phase; starting Qwen stops OCR first, so both phases cannot compete for VRAM. Startup fails closed on a model/device mismatch.

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
2. Upload complete scripts. PaddleOCR maps answer regions and Qwen links those regions to finalized questions; the teacher confirms the mapping.
3. Compare the direct PaddleOCR baseline reading with the prepared answer image. Approve it only when faithful.
4. If it is not faithful, choose **None of these readings match — Enhanced local OCR**. The GPU phase detects at most six ordered bands and spends at most eight OCR calls total.
5. Select exactly one faithful PP-OCRv6 or PaddleOCR-VL reading for every band. Do not select the closest reading when none is correct; reject the run and upload a clearer complete page.
6. Separately choose **Confirm displayed image is the full answer**. Candidate confirmation alone deliberately leaves grading blocked.
7. Choose **Grade confirmed answer with local Qwen**. Phase switching stops OCR before Qwen starts; Qwen receives the finalized question, solution, active rubric, and server-assembled confirmed text only.
8. Review the pending draft suggestion. Only explicit teacher approval may create a final grade.

Cohort grading remains disabled until the curated gate passes. When later enabled, verify the preflight counts and model alias, keep the call cap at 25 or lower, and inspect failed/uncertain items without automatic retry.

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
