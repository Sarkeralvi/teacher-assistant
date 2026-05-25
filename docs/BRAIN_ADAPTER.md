# Brain Adapter provider configuration

TA-W1-011 added one real provider path: OpenAI-compatible chat completions. TA-W1-012 adds optional cropped answer-region image input for that provider. The mock provider remains the default and still requires no API key.

## Environment variables

Set these in `.env` for local development. Do not commit `.env`.

```env
BRAIN_PROVIDER=mock
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_BASE_URL=
OPENAI_IMAGE_INPUT_ENABLED=false
```

Behavior:

- `BRAIN_PROVIDER=mock` uses the deterministic mock provider and ignores OpenAI settings.
- `BRAIN_PROVIDER=openai` enables the OpenAI-compatible provider and requires `OPENAI_API_KEY`.
- `OPENAI_MODEL` is optional; the backend defaults to `gpt-4o-mini` if omitted.
- `OPENAI_BASE_URL` is optional; when omitted, the provider uses `https://api.openai.com/v1`.
- `OPENAI_IMAGE_INPUT_ENABLED=false` is the default safe mode; no image bytes/data URLs are sent.
- `OPENAI_IMAGE_INPUT_ENABLED=true` sends the cropped answer-region PNG/JPEG as a base64 `data:image/...` URL in the OpenAI-compatible chat-completions message content.

## Safety rules

- All provider calls go through `packages/brain` and `BrainAdapter`.
- Route handlers and grading services must not directly call OpenAI-compatible APIs.
- Provider output is validated against the existing `GradeSuggestionOutput` schema before persistence.
- Provider errors are sanitized before being stored in `GradingJob.error` or returned by the API.
- API keys are never stored in the database and should never be logged.
- Image base64 is never stored in the database and should never be logged.
- Real provider output is still only a `GradeSuggestion`; teacher review and `FinalGrade` remain required.

## Image input status

Image input is optional and disabled by default. When enabled for `BRAIN_PROVIDER=openai`, the Brain Adapter safely resolves the existing cropped `AnswerRegion.image_path` under the configured local storage root, validates that the file is a PNG/JPEG, encodes it as a data URL, and sends that data URL to the provider request. Raw local file paths are not sent to the provider as image content.

When image input is disabled, the prompt explicitly says image input is disabled and the model must not claim handwriting/image understanding.
