# Real Teacher Observed Synthetic Pilot Protocol

This protocol is for `TA-PILOT-013`. It prepares a real teacher to watch or try Custom Controlled V0 using tiny synthetic data only.

This is an observed safety session, not a production marking session.

## 1. Scope

The session is limited to:

- one real teacher;
- synthetic/demo data only;
- one assessment;
- one question;
- two student scripts;
- two teacher-confirmed manual answer texts;
- two real draft grading calls maximum;
- one real draft grading call per ready packet;
- teacher review before any approval;
- approved-only export.

No real or high-stakes student marks are allowed in this session.

## 2. What the teacher is allowed to do

The teacher may:

- follow `docs/CUSTOM_CONTROLLED_V0_TEACHER_QUICK_START.md`;
- enter the question text;
- enter the model answer or solution;
- enter the rubric or mark breakdown;
- upload or attach the two synthetic student scripts;
- inspect the evidence packet preview;
- enter or confirm the manual answer text for each answer region;
- run one draft grade for each ready packet, with observer confirmation;
- review the score, feedback, rubric breakdown, and evidence;
- edit or approve only after checking the output;
- export approved final grades.

The teacher should speak aloud when anything is confusing.

## 3. What is forbidden

The following are forbidden during this observed pilot:

- private student data;
- high-stakes grades;
- batch grading;
- OCR or image-only grading;
- automatic answer mapping;
- auto-approval;
- automatic `FinalGrade` creation;
- unsupervised provider calls;
- more than two real Codex calls;
- mock grading;
- mock fallback after provider failure;
- export of unapproved draft suggestions;
- any provider/model call outside the two explicit grading calls.

If any forbidden action appears possible or occurs, stop the session.

## 4. Founder/observer checklist

Before the session:

- [ ] Confirm `git status --short` is clean.
- [ ] Confirm the expected repository baseline.
- [ ] Run `make health`.
- [ ] Run `make frontend-health`.
- [ ] Confirm the session uses synthetic/demo data only.
- [ ] Confirm the teacher has the quick-start guide.
- [ ] Confirm the teacher understands that manual answer text is required.
- [ ] Confirm the teacher understands draft suggestions are not final grades.
- [ ] Verify Codex auth/model only if real grading will run.
- [ ] Record starting `GradeSuggestion`, `FinalGrade`, and `GradingJob` counts for target regions once regions exist.

During the session:

- [ ] Verify every provider call is explicit.
- [ ] Count real Codex calls and stop at two maximum.
- [ ] Confirm no batch action is used.
- [ ] Confirm no mock grading or mock fallback is used.
- [ ] Confirm evidence preview is complete before each grading call.
- [ ] Confirm the queue item is fresh before each grading call.
- [ ] Stop immediately on any unexpected score, missing evidence, stale queue, provider failure, or hidden call.

After the session:

- [ ] Count `GradeSuggestion`, `FinalGrade`, and `GradingJob` rows for target regions.
- [ ] Confirm `FinalGrade` rows exist only after teacher approval.
- [ ] Confirm export row count equals approved final-grade count.
- [ ] Confirm export excludes draft suggestions.
- [ ] Record the final verdict and required changes.

## 5. Session script

### Introduction

Say:

> Today we are testing a small teacher-controlled marking flow with synthetic data only. This is not production marking. The system may create draft grade suggestions, but you remain the final authority.

### Explain limitations

Tell the teacher:

- The system does not automatically find the answer.
- The system does not perform OCR in this pilot.
- The system does not batch grade.
- The system does not create final marks automatically.
- The teacher must check the evidence, draft score, feedback, and rubric breakdown before approval.

### Walk through Step 1 to Step 13

Use the teacher quick-start guide and walk through:

1. Create or open the assessment.
2. Add the question.
3. Add the model answer.
4. Add the rubric.
5. Upload or attach the student script.
6. Select or create the answer evidence region.
7. Enter teacher-confirmed manual answer text.
8. Confirm evidence readiness.
9. Queue the ready packet.
10. Run one real draft grade.
11. Review score, feedback, rubric breakdown, and evidence.
12. Approve only after review.
13. Export approved final grades.

### Ask the teacher to verbalize confusion points

Ask during the flow:

- What is unclear on this screen?
- Can you tell what is evidence and what is grading?
- Can you find where to enter the manual answer text?
- Can you tell whether the packet is ready?
- Can you tell that the AI result is a draft?
- Can you tell what must be reviewed before approval?
- Can you tell what the export should contain?

### Record timing and friction

Record:

- total session time;
- time to create assessment/question/rubric;
- time to prepare each evidence packet;
- time to review each draft;
- time to approve/export;
- where the teacher hesitated;
- where the observer had to explain the UI.

### Record label understanding

Record whether the teacher understood labels for:

- manual answer text;
- evidence packet preview;
- ready for grading;
- queue;
- draft grade suggestion;
- needs review;
- final grade;
- approved export.

### Confirm draft vs final understanding

Before approval, ask:

> Is this mark final yet, or is it still a draft suggestion?

Pass this point only if the teacher answers that it is still a draft until approved.

## 6. Pass/fail criteria

The session passes only if all conditions are true:

- the teacher can identify the required materials;
- the teacher can find the manual answer text field;
- evidence readiness is understandable;
- draft grading is clearly understood as non-final;
- the teacher reviews before approval;
- export contains only approved rows;
- no batch action occurs;
- no mock grading occurs;
- no hidden provider action occurs;
- no private data appears;
- no more than two real Codex calls occur.

The session is partial if the safety rules hold but the teacher needs observer help for important UI steps.

The session fails if any forbidden action occurs, any private data appears, or the teacher cannot distinguish draft suggestions from final grades.

## 7. Stop conditions

Stop immediately if:

- the teacher cannot understand the workflow;
- manual answer text is missing;
- model answer is missing;
- rubric is missing;
- evidence is not ready;
- the queue item is stale;
- Codex/provider is unavailable;
- score or feedback is obviously wrong;
- unexpected `GradeSuggestion` count appears;
- unexpected `FinalGrade` count appears;
- any private data appears;
- any provider call happens without explicit teacher/observer action;
- batch grading appears;
- a final grade appears before teacher approval;
- export includes unapproved drafts.

If stopped, record the reason and do not continue without founder approval.

## 8. Final observation report template

Use this template after the session.

```text
TA-PILOT-014 observed synthetic pilot report

Teacher role/context:
Observer/founder:
Date/time:
Scenario used:
Data type: synthetic/demo only yes/no

Assessment id:
Question id:
Submission ids:
Answer region ids:

Time taken:
- total session time:
- setup time:
- evidence preparation time:
- grading/review time:
- approval/export time:

Confusion points:
- required materials:
- manual answer text field:
- evidence readiness:
- queue:
- draft vs final grade:
- approval:
- export:

Label understanding:
- manual answer text understood yes/no:
- evidence packet preview understood yes/no:
- ready for grading understood yes/no:
- draft suggestion understood yes/no:
- final grade understood yes/no:
- approved-only export understood yes/no:

Safety counts:
- GradeSuggestion count before:
- GradeSuggestion count after:
- FinalGrade count before:
- FinalGrade count after:
- GradingJob count before:
- GradingJob count after:
- real Codex call count:
- provider/model used:
- mock used yes/no:
- batch used yes/no:
- hidden provider call yes/no:

Scores generated:
- GradeSuggestion id / answer region id / score / needs_review:
- GradeSuggestion id / answer region id / score / needs_review:

Approvals:
- approved yes/no:
- FinalGrade id / source GradeSuggestion id / final score:
- FinalGrade id / source GradeSuggestion id / final score:
- stopped before approval yes/no and reason:

Export result:
- export path:
- row count:
- approved-only rows yes/no:
- drafts excluded yes/no:

Stop conditions encountered:

Final verdict: passed / partial / failed

Changes required before next teacher:
```

## 9. Next step

If this protocol is accepted, the next task is:

`TA-PILOT-014: run real-teacher observed synthetic pilot session`
