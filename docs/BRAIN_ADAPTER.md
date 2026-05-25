# Brain Adapter provider configuration

TA-W1-011 adds one real provider path: OpenAI-compatible chat completions. The mock provider remains the default and still requires no API key.

## Environment variables

Set these in `.env` for local development. Do not commit `.env`.

```env
BRAIN_PROVIDER=mock
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_BASE_URL=
```

Behavior:

- `BRAIN_PROVIDER=mock` uses the deterministic mock provider and ignores OpenAI settings.
- `BRAIN_PROVIDER=openai` enables the OpenAI-compatible provider and requires `OPENAI_API_KEY`.
- `OPENAI_MODEL` is optional; the backend defaults to `gpt-4o-mini` if omitted.
- `OPENAI_BASE_URL` is optional; when omitted, the provider uses `https://api.openai.com/v1`.

## Safety rules

- All provider calls go through `packages/brain` and `BrainAdapter`.
- Route handlers and grading services must not directly call OpenAI-compatible APIs.
- Provider output is validated against the existing `GradeSuggestionOutput` schema before persistence.
- Provider errors are sanitized before being stored in `GradingJob.error` or returned by the API.
- API keys are never stored in the database and should never be logged.
- Real provider output is still only a `GradeSuggestion`; teacher review and `FinalGrade` remain required.

## Image input status

Image input is deferred for this provider path. The real OpenAI-compatible v1 prompt is text-only and explicitly tells the model not to claim handwriting/image understanding. Cropped answer images are still verified by the existing grading service, but not transmitted to the provider in TA-W1-011.
