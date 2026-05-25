# PROJECT CONSTITUTION

## Product Mission
Build an independent AI-powered Teacher Assistant that helps teachers create courses and assessments, define questions and rubrics, process scanned handwritten answers, receive AI-assisted grading suggestions, review and approve final grades, and export results. The system exists to improve teacher workflow quality and speed without replacing teacher judgment.

## Non-Negotiable Rules
1. Teacher control is mandatory for grading decisions.
2. The product must run independently of Hermes or any builder agent/tool.
3. No application module may call external LLM APIs directly except the Brain Adapter.
4. All AI outputs are suggestions until reviewed and approved by a teacher.
5. Student work, rubrics, grades, and audit records are owned by the institution/teacher, not the AI provider.
6. Every grade-affecting action must be auditable.
7. No feature is done without tests and acceptance evidence.
8. Prefer boring, durable architecture over fast fragile shortcuts.

## Runtime Independence Rule
Hermes is the active builder/controller. Hermes may use internal tools while building, but no builder agent or tool may become a runtime dependency. The deployed product must start, run, grade, export, and operate without Hermes or any builder tool present.

## AI/LLM Dependency Rule
All LLM access goes through the Brain Adapter. Product code must depend on internal interfaces, not provider SDKs. Provider choice, model choice, retry policy, cost logging, prompt versions, structured-output validation, and audit logging belong inside the Brain Adapter layer.

## Teacher-in-Control Grading Rule
The grading engine may produce grade suggestions, feedback drafts, confidence scores, and evidence references. It must never write final grades directly. A final grade requires explicit teacher approval or teacher edit.

## Data Ownership Rule
Teachers/institutions own all uploaded scans, extracted text, rubrics, grading records, exports, and audit logs. The system must support deletion/export policies and must not send data to external providers except through approved Brain Adapter flows.

## Quality Rule
Correctness, traceability, and maintainability outrank speed. Architecture must keep module boundaries clear. Shortcut code that bypasses boundaries is rejected even if it works locally.

## Testing Rule
Every implemented feature needs automated tests before being marked done. Required minimums: unit tests for domain logic, integration tests for API flows, fixture-based tests for grading schemas, and regression tests for fixed defects.

## Auditability Rule
The system must record who did what, when, using which rubric, which prompt/model/policy version, what AI suggestion was made, what teacher changed, and what final grade was approved.
