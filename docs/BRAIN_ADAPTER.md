# Brain Adapter provider configuration

TA Agent keeps grading and language-model extraction access behind `packages/brain` and `BrainAdapter`. The mock provider remains the default. The active supervised workflow uses loopback-only `llama_cpp_qwen38` for three separately authorized tasks: thinking-disabled visual preparation, thinking-disabled verbatim transcription, and fresh-context text-only draft grading. PaddleOCR and Qwen3.6 remain historical/rollback assets but are disabled and cannot be selected by the teacher workflow.

## Environment variables

Set these in `.env` for local development. Do not commit `.env`.

```env
BRAIN_PROVIDER=mock
BRAIN_ALLOW_REAL_PROVIDERS=false

LOCAL_QWEN_ENABLED=false
LOCAL_QWEN_BASE_URL=http://127.0.0.1:8086/v1
LOCAL_QWEN_MODEL=qwen3.6-35b-a3b-q4km
LOCAL_QWEN_API_KEY=

LOCAL_PADDLE_OCR_ENABLED=false
LOCAL_PADDLE_OCR_BASE_URL=http://127.0.0.1:8090
LOCAL_PADDLE_OCR_API_KEY=
LOCAL_PADDLE_OCR_MODEL=PaddleOCR-VL-1.6
LOCAL_PADDLE_OCR_LAYOUT_MODEL=PP-DocLayoutV3

LOCAL_QWEN38_ENABLED=false
LOCAL_QWEN38_TRANSCRIPTION_ENABLED=false
LOCAL_QWEN38_THINKING_REPAIR_ENABLED=false
LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=false
LOCAL_QWEN38_GRADING_ENABLED=false

OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_BASE_URL=
OPENAI_IMAGE_INPUT_ENABLED=false
OPENAI_TIMEOUT_SECONDS=30

CODEX_CLI_COMMAND=codex
CODEX_CLI_MODEL=gpt-5.5
CODEX_CLI_TIMEOUT_SECONDS=300
CODEX_CLI_SANDBOX=read-only
CODEX_CLI_APPROVAL_POLICY=never
CODEX_CLI_USE_JSON=true
CODEX_CLI_OUTPUT_LAST_MESSAGE=true
CODEX_CLI_IMAGE_INPUT_ENABLED=false
CODEX_CLI_WORKDIR=/home/newton/teacher-assistant
```

Behavior:

- `BRAIN_PROVIDER=mock` uses the deterministic mock provider and ignores OpenAI/Codex settings.
- Every non-mock provider first requires `BRAIN_ALLOW_REAL_PROVIDERS=true`.
- `BRAIN_PROVIDER=openai` enables the OpenAI-compatible provider and requires `OPENAI_API_KEY`.
- `BRAIN_PROVIDER=codex_cli` enables local Codex CLI execution and does **not** require `OPENAI_API_KEY`.
- `BRAIN_PROVIDER=llama_cpp_qwen` additionally requires `LOCAL_QWEN_ENABLED=true`, a loopback HTTP URL, and `LOCAL_QWEN_API_KEY`.
- `llama_cpp_qwen` verifies the exact configured alias through `/v1/models` before completion, sends strict JSON-schema requests with reasoning disabled, records token/latency metadata and zero monetary cost, and never sends answer image bytes or paths.
- `LOCAL_PADDLE_OCR_ENABLED=true` enables only the authenticated loopback client. Every OCR request requires the exclusive `PaddleOcr` database lease and exact OCR/layout model identities.
- Every `llama_cpp_qwen38` inference requires a matching `Qwen38` lease. The optional thinking repair additionally requires `LOCAL_QWEN38_THINKING_REPAIR_ENABLED=true`, uses one explicit call with zero retry/fallback, receives no reference or marking context, and cannot confirm itself.
- `CODEX_CLI_COMMAND` defaults to `codex`; it must exist on `PATH` or provider preflight fails clearly.
- `CODEX_CLI_MODEL` defaults to `gpt-5.5`; keep it explicit so host dev runs do not fall back to an unsupported Codex CLI default model.
- `CODEX_CLI_TIMEOUT_SECONDS` controls subprocess timeout for preflight/execution.
- `CODEX_CLI_SANDBOX=read-only` is the default. `danger-full-access` is refused.
- `CODEX_CLI_APPROVAL_POLICY=never` documents the v1 behavior. `codex exec --help` for the verified local version does not expose `--ask-for-approval`, so the provider does not pass approval flags.
- `CODEX_CLI_USE_JSON=true` may add `--json` for event logging/debug when supported, but grading output is parsed only from `--output-last-message`.
- `CODEX_CLI_OUTPUT_LAST_MESSAGE=true` is required.
- `CODEX_CLI_WORKDIR` is the safe working directory passed to `codex exec --cd`.

## Codex CLI command shape

The v1 provider uses this shape:

```bash
codex exec \
  --cd /home/newton/teacher-assistant \
  --sandbox read-only \
  --output-last-message <temp_output_file> \
  --json
```

The grading prompt is sent via stdin. `--json` is only included when supported and is not authoritative. The provider reads `<temp_output_file>`, expects exact JSON, validates it with the existing `GradeSuggestionOutput` schema, forces `needs_review=true`, and persists through the existing grading service.

## Codex CLI preflight

`codex_cli` checks before grading:

1. `codex` command exists.
2. `codex --version` exits successfully.
3. `codex exec --help` exits successfully.
4. `--output-last-message` is supported.
5. `--cd` is supported.
6. `--sandbox` is supported.
7. image flag support is detected from help output, not assumed.

## Image input status

Image input is optional and disabled by default.

- `OPENAI_IMAGE_INPUT_ENABLED=true` sends cropped answer-region PNG/JPEG as a base64 `data:image/...` URL to the OpenAI-compatible provider.
- `CODEX_CLI_IMAGE_INPUT_ENABLED=false` sends no image to Codex CLI. The prompt explicitly says image input is disabled, and output review flags include `image_input_disabled`.
- `CODEX_CLI_IMAGE_INPUT_ENABLED=true` first requires an image option in `codex exec --help` (for example `--image`/`-i`). If unsupported, the provider fails safely with: `Codex CLI image input is not supported by this installed version.`
- The Codex CLI provider must not fake image understanding by mentioning a local image path in prompt text as if the image was read.

## Safety rules

- All provider calls go through `packages/brain` and `BrainAdapter`.
- Route handlers and grading services must not directly call OpenAI-compatible APIs or Codex CLI.
- Provider output is validated against the existing `GradeSuggestionOutput` schema before persistence.
- Provider errors are sanitized before being stored in `GradingJob.error` or returned by the API.
- API keys are never stored in the database and should never be logged.
- Image base64 is never stored in the database and should never be logged.
- Real provider output is still only a `GradeSuggestion`; teacher review and `FinalGrade` remain required.
- Local Qwen cohort dispatch has no provider fallback or automatic retry and is capped at 25 sequential calls.
- PaddleOCR output remains draft evidence until exact hash confirmation. A teacher rejection may authorize a separate Qwen3.8 forensic transcription; there is no automatic escalation or reconciliation.
- Every PaddleOCR/Qwen3.6/Qwen3.8 inference request fails before HTTP unless the current execution context owns the matching durable model lease.
- No provider implements automatic answer mapping or autonomous final grading.
