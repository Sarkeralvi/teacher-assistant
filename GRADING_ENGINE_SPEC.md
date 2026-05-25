# GRADING ENGINE SPEC

## Purpose
The Grading Engine creates explainable grade suggestions from student answers, rubrics, and assessment context. It does not create final grades.

## Stack Alignment
The Grading Engine is Python domain code using Pydantic schemas for inputs/outputs and pytest fixture tests. It may be called by FastAPI services or RQ workers. It must call AI functionality only through the Brain Adapter interface.

## Rubric Schema
```yaml
rubric_id: string
version: integer
total_points: number
criteria:
  - criterion_id: string
    title: string
    description: string
    max_points: number
    levels:
      - level_id: string
        label: string
        points: number
        descriptor: string
```

Rules:
- total criteria points must equal assessment question points.
- historical grading records reference immutable rubric versions.
- rubric edits create new versions.

## Grading Input Schema
```yaml
grading_request_id: string
assessment_id: string
question_id: string
submission_id: string
student_answer:
  text: string
  source_artifact_ids: [string]
rubric:
  rubric_id: string
  version: integer
  criteria: []
context:
  course_id: string
  question_text: string
  expected_answer_notes: string|null
policy:
  brain_policy_id: string
```

## Grading Output Schema
```yaml
grading_suggestion_id: string
suggested_score: number
max_score: number
confidence: number
criterion_results:
  - criterion_id: string
    suggested_points: number
    selected_level_id: string|null
    evidence: [string]
    feedback: string
warnings: [string]
requires_teacher_attention: boolean
brain_audit_ref: string
created_at: timestamp
```

## Confidence Score
Confidence is an operational signal, not correctness proof. Low confidence, OCR uncertainty, schema repair, fallback model use, missing evidence, or rubric ambiguity must set `requires_teacher_attention = true`.

## Teacher Review Requirement
Every grading suggestion must pass through teacher review before becoming final. The UI must show the suggested score, evidence, confidence, warnings, and allow teacher edit/approval.

## Suggestion vs Final Grade
- Suggested grade: produced by Grading Engine, editable, not official.
- Final grade: approved by teacher, stored through Review Module, exportable.

The system must never export unapproved suggestions as final grades.

## Audit Log Requirement
For each suggestion and final grade, record rubric version, input artifacts, Brain Adapter audit reference, teacher review action, edits, approval time, and final score.

## Evaluation Metrics
Track at minimum:
- agreement between AI suggestion and teacher final grade
- average absolute score delta
- low-confidence frequency
- teacher override rate by question/rubric criterion
- schema validation failure rate
- retry/fallback rate
- processing latency and cost per submission
