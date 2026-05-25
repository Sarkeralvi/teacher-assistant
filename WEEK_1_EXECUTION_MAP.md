# WEEK 1 EXECUTION MAP

## Principle
Week 1 is not a rushed MVP. It is the foundation week: project operating system, architecture contracts, data model skeleton, test strategy, and thin vertical proof of boundaries. No production grading automation shortcut is allowed.

## Realistically Build in Week 1
- repository scaffold
- documentation baseline
- domain contracts and schemas
- Brain Adapter interface with fake provider only
- Grading Engine contract with deterministic fixture tests
- basic API skeleton if stack is chosen
- audit event model draft
- CI/test/lint setup

## Design Only in Week 1
- full OCR pipeline
- handwritten answer extraction strategy
- provider/model selection
- deployment architecture
- teacher review UX details
- privacy/data retention policy
- evaluation dataset design

## Do Not Touch Yet
- real external LLM provider integration
- real student data uploads
- production OCR
- payment/subscription features
- complex role management
- lecture generation
- assignment generation
- analytics dashboards beyond evaluation metric definitions

## Day 1 Deliverables
- Project constitution
- Architecture document
- Brain Adapter spec
- Grading Engine spec
- Development protocol
- Week 1 execution map
- Initial backlog

Acceptance criteria:
- all required docs exist
- no production code written
- module boundaries are explicit
- Brain Adapter-only LLM rule is clear

## Day 2 Deliverables
- repository scaffold decision
- tech stack proposal
- initial package/app structure
- test runner and lint/format baseline
- CI placeholder or local verification script

Acceptance criteria:
- project can install dependencies or run baseline checks
- no direct LLM dependency in app modules
- task IDs and branch naming used

## Day 3 Deliverables
- initial database/entity design draft
- domain schema definitions for courses, assessments, rubrics, submissions, grading suggestions, final grades, audit events
- migration strategy proposal

Acceptance criteria:
- schemas map to documented architecture
- final grade and suggestion are separate entities
- audit fields exist for grade-affecting actions

## Day 4 Deliverables
- Brain Adapter interface implemented with fake provider only
- structured output validator
- cost/audit log shape
- fixture tests for valid/invalid adapter outputs

Acceptance criteria:
- no real provider API used
- invalid structured output fails safely
- tests prove callers do not need provider-specific SDKs

## Day 5 Deliverables
- Grading Engine contract implementation using fake Brain Adapter
- rubric validation
- grading suggestion output schema
- confidence/warning behavior for low-quality inputs

Acceptance criteria:
- grading suggestion is not final grade
- teacher review required flag exists
- fixture tests cover scoring, schema validation, and low confidence

## Day 6 Deliverables
- Review/approval flow design
- final grade entity/service skeleton or pseudocode
- Excel export contract design
- audit trail examples

Acceptance criteria:
- final grade requires explicit teacher action
- export reads final grades only
- audit trail shows AI suggestion and teacher decision

## Day 7 Deliverables
- architecture review
- backlog cleanup
- risk register
- week 2 proposal
- demo of fake-provider grading boundary if implemented

Acceptance criteria:
- no architecture violations
- tests pass
- human decisions needed are listed
- week 2 work is sequenced and not overpromised
