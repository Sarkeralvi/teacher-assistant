# Universal Brain Adapter

Teacher Assistant keeps every model-dependent operation behind `packages/brain`.
Domain workflows ask for a capability; they do not branch on Gemini, OpenAI, Qwen,
or a particular model name. The selected provider publishes one runtime contract:

- canonical provider name and configured model;
- execution location (`mock`, `local`, `cloud`, or `cli`);
- supported capabilities;
- image transport mode; and
- an optional application-managed local-model phase.

Provider output remains draft assistance. It is schema-validated, marked for review,
and cannot create a final grade without the existing teacher approval workflow.

## Built-in providers

| Provider | Location | Configuration | Capabilities |
| --- | --- | --- | --- |
| `mock` | mock | Default; no credentials | Deterministic grading and document-import fixtures |
| `gemini` | cloud | Universal `BRAIN_*` values or legacy `GEMINI_*` aliases | Grading; image/document capabilities when image input is enabled |
| `openai` | cloud by default | Universal `BRAIN_*` values or legacy `OPENAI_*` aliases | Grading; image/document capabilities when image input is enabled |
| `openai_compatible` | local or cloud | Universal model and base URL; cloud endpoints require a key | Same generic structured-output and optional image contracts as `openai` |
| `codex_cli` | CLI | `CODEX_CLI_*`, with universal model/timeout overrides | Grading |
| `llama_cpp_qwen` | managed local | Universal overrides or legacy `LOCAL_QWEN_*` | Text grading and OCR-text reference/mapping/preparation |
| `llama_cpp_qwen38` | managed local | Universal overrides or legacy `LOCAL_QWEN38_*` | Grading and visual reference/mapping/transcription/repair |

Aliases `fake` and `openai-compatible` resolve to their canonical provider names.
There is no automatic provider fallback: an unavailable or incapable provider fails
safely before the workflow treats output as evidence.

## Universal configuration

Put secrets in an ignored `.env`, never in source control. Every non-mock provider
requires the global real-provider authorization switch.

```env
BRAIN_PROVIDER=mock
BRAIN_ALLOW_REAL_PROVIDERS=false

BRAIN_MODEL=
BRAIN_API_KEY=
BRAIN_BASE_URL=
BRAIN_ENDPOINT_TYPE=auto
BRAIN_TIMEOUT_SECONDS=120
BRAIN_IMAGE_INPUT_ENABLED=
BRAIN_STRUCTURED_OUTPUT_MODE=json_schema
BRAIN_VERIFY_MODEL_ON_START=false
```

`BRAIN_ENDPOINT_TYPE` accepts `auto`, `local`, or `cloud` for HTTP providers.
`auto` classifies loopback URLs as local and other URLs as cloud. Local
OpenAI-compatible endpoints may omit `BRAIN_API_KEY`; cloud endpoints may not.
`json_schema`, `json_object`, and `prompt_only` are the supported structured-output
modes, allowing servers with different OpenAI-compatible feature levels to use the
same workflow contracts.

The active profile also has provider-neutral operational values:

```env
BRAIN_MANAGED_LOCAL_PHASE=
BRAIN_JOB_TIMEOUT_SECONDS=
BRAIN_MODEL_SHA256=
BRAIN_AUX_MODEL_SHA256=
```

Only set `BRAIN_MANAGED_LOCAL_PHASE=Qwen` or `Qwen38` when this application owns
that local model's lease and lifecycle. An ordinary local server should leave it
blank.

Product authorization is independent of the provider, model, and endpoint:

```env
BRAIN_REFERENCE_EXTRACTION_ENABLED=false
BRAIN_SCRIPT_PREPARATION_ENABLED=false
BRAIN_SINGLE_ANSWER_GRADING_ENABLED=false
BRAIN_VISUAL_PREPARATION_ENABLED=false
BRAIN_TRANSCRIPTION_ENABLED=false
BRAIN_THINKING_REPAIR_ENABLED=false
BRAIN_GRADING_ENABLED=false
BRAIN_BULK_EVALUATION_ENABLED=false
```

Blank optional gates inherit their legacy equivalent where one exists. Explicit
`true` or `false` is preferred for new installations.

### Gemini example

```env
BRAIN_PROVIDER=gemini
BRAIN_ALLOW_REAL_PROVIDERS=true
BRAIN_MODEL=gemini-2.0-flash
BRAIN_API_KEY=replace-in-local-env
BRAIN_ENDPOINT_TYPE=cloud
BRAIN_IMAGE_INPUT_ENABLED=true
BRAIN_STRUCTURED_OUTPUT_MODE=json_schema

BRAIN_REFERENCE_EXTRACTION_ENABLED=true
BRAIN_SCRIPT_PREPARATION_ENABLED=true
BRAIN_SINGLE_ANSWER_GRADING_ENABLED=true
BRAIN_VISUAL_PREPARATION_ENABLED=true
BRAIN_TRANSCRIPTION_ENABLED=true
BRAIN_THINKING_REPAIR_ENABLED=true
BRAIN_GRADING_ENABLED=true
```

Enable only workflows for which the teacher has approved the data boundary. Every
teacher action that sends reference or student evidence to a cloud provider requires
explicit cloud-transfer confirmation: document/question import, reference extraction,
mapping, transcription or repair, single or cohort/batch draft grading, and bulk
evaluation.

### Local OpenAI-compatible example

```env
BRAIN_PROVIDER=openai_compatible
BRAIN_ALLOW_REAL_PROVIDERS=true
BRAIN_MODEL=my-local-model
BRAIN_BASE_URL=http://127.0.0.1:9000/v1
BRAIN_ENDPOINT_TYPE=local
BRAIN_API_KEY=
BRAIN_IMAGE_INPUT_ENABLED=true
BRAIN_STRUCTURED_OUTPUT_MODE=json_object
```

Changing the model or moving this endpoint to another host does not require domain,
route, worker, or frontend changes. If it becomes a cloud endpoint, set
`BRAIN_ENDPOINT_TYPE=cloud` and provide `BRAIN_API_KEY`.

## Runtime behavior

- `BRAIN_PROVIDER` selects the active/default provider shown by `/brain/status`.
- A controlled workflow may explicitly select a registered provider in its request.
  The policy still validates the requested provider, exact expected model, feature
  gate, and required capability before execution.
- The frontend reads provider, model, location, capabilities, and readiness from the
  status response. It does not infer authorization from a provider name.
- Generic grading routes are `/answer-regions/{id}/grade-brain` and
  `/assessments/{id}/grade-approved-brain`. Legacy local-Qwen routes remain aliases.
- The legacy no-body `/answer-regions/{id}/grade` and `/grade-async` routes remain
  deterministic mock compatibility paths. Supplying the universal request body to
  `/grade` delegates to `/grade-brain`; real provider calls never infer authorization
  from ambient server configuration.
- Provider/model/location metadata is persisted with runs and drafts for auditability.
- Local managed providers retain their durable lease checks. Generic local and cloud
  HTTP providers do not pretend to own a local model process.

## Capability contract

The current capability names are:

```text
grading
question_pdf_extraction
rubric_pdf_extraction
ocr_reference_extraction
ocr_answer_mapping
ocr_answer_preparation
visual_reference_extraction
visual_mapping
visual_transcription
transcription_repair
```

Services call the shared adapter contract and reject unsupported tasks. Visual
providers share canonical Pydantic request/result normalization, so Gemini,
OpenAI-compatible APIs, and local multimodal endpoints produce the same internal
question, rubric, mapping, transcription, repair, and grading shapes.

## Adding a provider

A provider extension does not require workflow changes:

1. Implement `BrainProvider` methods for the capabilities the provider supports.
2. Declare an exact `frozenset[BrainCapability]`, execution location, model, and
   image-input mode.
3. Write a factory returning `ProviderBuildResult`.
4. Register the factory with `register_brain_provider`, optionally with aliases.
5. Add contract tests for configuration, capability refusal, output validation,
   secret sanitization, and status metadata.

A capability-only provider does not need a dummy grading implementation. Callers
receive a clear configuration error if a provider advertises a capability but does
not implement its method.

## Compatibility settings

`OPENAI_*`, `GEMINI_*`, `CODEX_CLI_*`, `LOCAL_QWEN_*`, and `LOCAL_QWEN38_*` remain
supported so existing installations continue to work. Universal `BRAIN_*` values
take precedence where applicable. Historical database columns, audit event names,
and local-Qwen endpoint aliases are also retained; they are compatibility labels,
not routing decisions in new code.

Codex CLI keeps its existing safety checks: read-only sandbox by default, approval
policy `never`, bounded subprocess timeout, exact JSON validation, and refusal of
`danger-full-access`. Image input is used only when the installed CLI advertises an
image option.

## Safety invariants

- `BRAIN_ALLOW_REAL_PROVIDERS=false` prevents all non-mock provider initialization.
- No provider call occurs merely from loading a page or status endpoint.
- Grade-affecting output is validated against internal schemas and always requires
  teacher review.
- API keys and image data are excluded from persistence and logs; provider errors
  redact configured secrets, common key formats, authorization values, and image
  data URLs.
- Cloud evidence transfer requires the workflow's explicit confirmation before any
  reference or student artifact is sent to the provider.
- Bulk execution remains opt-in, bounded, sequential where required, and cannot
  auto-finalize grades.
- Provider selection never bypasses ownership, evidence-readiness, rubric-integrity,
  call-limit, or audit checks.
