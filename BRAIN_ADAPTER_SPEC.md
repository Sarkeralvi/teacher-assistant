# Brain Adapter Specification

## Purpose

The Brain Adapter is the only model/provider boundary in Teacher Assistant. Product
code supplies provider-neutral inputs and requests a capability; the adapter selects
the configured implementation and returns validated internal results.

The abstraction covers provider identity, model identity, local/cloud/CLI location,
image transport, structured-output behavior, optional model verification, and local
lease ownership without leaking those choices into grading or evidence workflows.

## Required architecture

- Provider factories are registered by canonical name in `packages/brain/adapter.py`.
- `BrainProviderRuntime` exposes provider, model, execution location, image mode,
  capabilities, and optional managed-local phase.
- `BrainPolicy` combines runtime capabilities with explicit product feature gates.
- Routes, services, workers, and the frontend make decisions from this contract, not
  from provider-name conditionals. Provider-name checks are allowed only inside
  compatibility/configuration adapters for historical behavior.
- Pydantic schemas are the trust boundary for all evidence- or grade-affecting output.

Direct provider SDK, HTTP, or CLI calls outside `packages/brain` are forbidden.
Application services may orchestrate adapter methods but must not implement a second
provider selection layer.

## Capabilities

Providers declare the exact subset they implement: grading, question/rubric PDF
extraction, OCR reference extraction, OCR answer mapping/preparation, visual
reference extraction, visual mapping, visual transcription, and transcription
repair. A feature executes only when both its product gate and provider capability
are present.

Unsupported capabilities fail explicitly. The system does not silently switch
providers, models, transports, or evidence sources.

## Configuration and selection

The universal profile is `BRAIN_PROVIDER`, `BRAIN_MODEL`, `BRAIN_API_KEY`,
`BRAIN_BASE_URL`, `BRAIN_ENDPOINT_TYPE`, `BRAIN_TIMEOUT_SECONDS`,
`BRAIN_IMAGE_INPUT_ENABLED`, `BRAIN_STRUCTURED_OUTPUT_MODE`, and
`BRAIN_VERIFY_MODEL_ON_START`. Provider-specific variables are compatibility
fallbacks.

Every non-mock provider requires `BRAIN_ALLOW_REAL_PROVIDERS=true`. Requests pin the
expected provider/model where the workflow needs a durable authorization boundary.
Execution records persist the resolved canonical provider and model.

HTTP endpoint location is explicit or derived from the URL. Loopback is local; a
non-loopback HTTP endpoint defaults to cloud. Cloud OpenAI-compatible endpoints
require a key. A managed-local phase is separate from location and may be used only
for application-owned Qwen/Qwen38 lease switching.

## Output and audit rules

1. Validate structured output before it leaves the adapter.
2. Treat malformed or incomplete output as a typed failure, never partial evidence.
3. Persist provider, model, prompt/profile version, relevant input hashes, latency,
   and token/cost metadata where available.
4. Sanitize provider failures before API responses, job errors, or audit storage.
5. Never persist API keys, authorization headers, base64 image input, or private raw
   artifacts in logs.
6. Mark all model grading as draft assistance requiring teacher review.

Retries, if a workflow permits them, must be bounded and auditable. There is no
implicit cross-provider fallback.

## Data boundary

Provider location is part of the runtime contract. Every workflow that sends
reference or student artifacts to a cloud provider must enforce explicit
transfer consent before starting its provider call. Selection of a cloud-capable
provider alone is not consent; this includes import, reference extraction,
mapping, transcription/repair, and draft-grading workflows.

Ownership, packet readiness, canonical page order, continuation state, rubric
integrity, and provider call caps are validated independently of model quality.

## Extension contract

To add a provider, implement only its supported `BrainProvider` methods, declare
capabilities/runtime metadata, return it from a `ProviderBuildResult` factory, and
register that factory. Existing domain services must remain unchanged. A provider
integration is complete only with configuration, capability, schema-validation,
error-redaction, and no-call-on-refusal tests.

See `docs/BRAIN_ADAPTER.md` for built-in provider configuration and examples.
