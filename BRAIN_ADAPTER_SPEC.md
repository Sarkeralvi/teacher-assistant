# BRAIN ADAPTER SPEC

## Purpose
The Brain Adapter is the only allowed boundary between the product and external LLM providers. It converts product requests into provider calls and converts provider responses into validated internal results.

## Stack Alignment
The Brain Adapter is implemented in the FastAPI/Python backend/worker codebase using Pydantic schemas for request/result contracts. Provider SDKs, HTTP clients for LLM APIs, model names, prompt files, retry/fallback policy, and cost accounting are allowed only inside Brain Adapter provider/policy modules.

Forbidden direct callers:
- Next.js frontend
- FastAPI routes
- domain services
- worker jobs outside Brain Adapter calls
- Grading Engine internals except through the adapter interface
- export, storage, document processing, and review modules

## Provider Abstraction
Expose internal interfaces such as:

```text
BrainAdapter.generateStructured(request) -> StructuredBrainResult
BrainAdapter.generateFeedback(request) -> FeedbackResult
BrainAdapter.extractAnswerEvidence(request) -> EvidenceResult
```

Provider implementations may use OpenAI, Anthropic, Google, local models, or future providers, but callers only see internal request/result contracts.

## Model Policies
Model selection is policy-driven, not hard-coded in domain modules. Policies define:
- task type: grading, extraction, feedback, rubric assist
- allowed providers/models
- max cost per request/job
- timeout limits
- privacy constraints
- fallback chain
- structured output schema required

## Structured Output Rules
1. Every grade-affecting response must use a declared Pydantic schema.
2. Responses must be validated before leaving the adapter.
3. Invalid output triggers repair/retry according to policy.
4. If validation still fails, return a typed failure, not partial trusted output.
5. Raw provider text may be retained only in audit-safe storage.

## Cost Logging
Each provider call must log:
- provider and model
- policy name/version
- prompt version
- token/input/output usage where available
- estimated and actual cost where available
- assessment/submission/job correlation IDs
- success/failure status

## Retry and Fallback
Retries must be bounded, observable, and policy-controlled. Fallback to another model/provider is allowed only if the fallback satisfies privacy, schema, and task policy. Retried or fallback responses must remain linked in the audit trail.

## Prompt Versioning
Prompts are versioned artifacts. Each AI result records the prompt ID/version, schema version, and policy version. Prompt changes require tests or fixture evaluations before use in grade-affecting flows.

## Audit Logging
The adapter emits audit records for request metadata, policy decisions, provider selected, validation status, errors, retries, fallback, cost, and output references. The adapter must not decide final grades.

## Week 1 Implementation Constraint
Week 1 may implement only fake/deterministic provider behavior. No real external LLM provider integration until contracts, tests, audit policy, and Human approval are complete.
