# Brain Adapter provider configuration

TA Agent keeps grading model access behind `packages/brain` and `BrainAdapter`. The mock provider remains the default and requires no keys. OpenAI-compatible chat completions remain available when explicitly configured with an API key. TA-W1-013 adds a local `codex_cli` provider that shells out to authenticated Codex CLI via `codex exec` and does not require `OPENAI_API_KEY`.

## Environment variables

Set these in `.env` for local development. Do not commit `.env`.

```env
BRAIN_PROVIDER=mock

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
- `BRAIN_PROVIDER=openai` enables the OpenAI-compatible provider and requires `OPENAI_API_KEY`.
- `BRAIN_PROVIDER=codex_cli` enables local Codex CLI execution and does **not** require `OPENAI_API_KEY`.
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
- The provider does not implement OCR, automatic answer detection, or autonomous final grading.
