# Custom Controlled V0 Demo Checklist

Use this checklist for a founder-supervised Custom Controlled V0 demo. Do not use it as authorization for a public teacher pilot.

## Pre-demo lock

- [ ] Repository root: `/home/newton/teacher-assistant`
- [ ] `git status --short` is clean
- [ ] `make health` passes
- [ ] `make frontend-health` passes
- [ ] Synthetic/demo data only
- [ ] No private files unless exact files are founder-approved
- [ ] No mock grading
- [ ] No batch grading
- [ ] No auto-approval or auto-finalization
- [ ] Provider/model call count is explicitly approved before any real grading call

## Assessment setup

- [ ] Create/select one clean assessment
- [ ] Create question/grading unit
- [ ] Question label visible
- [ ] Max marks visible
- [ ] Question text visible
- [ ] Model answer / solution text present
- [ ] Active rubric present
- [ ] Rubric criteria visible

## Evidence setup per packet

For each target packet:

- [ ] Synthetic script page uploaded
- [ ] Manual answer region/crop created
- [ ] Crop contains complete answer
- [ ] Full answer confirmed only after crop inspection
- [ ] Continuation state resolved
- [ ] Student crop/segment visible in evidence preview
- [ ] `evidence_status = complete`
- [ ] `ready_for_grading = true`
- [ ] blockers empty

## Evidence prep

- [ ] Run evidence prep
- [ ] ready count equals target packet count
- [ ] blocked count is `0`
- [ ] No partial/blank target packet

## Queue scaffold

- [ ] Build queue scaffold
- [ ] queued count equals target packet count
- [ ] refused count is `0`
- [ ] Every target queue item is `fresh`
- [ ] Provider remains disabled until explicit single-packet grading action

## Real grading gate

Before each approved single-packet real Codex call:

- [ ] Packet still `ready_for_grading = true`
- [ ] Model answer present
- [ ] Active rubric present
- [ ] `evidence_status = complete`
- [ ] blockers empty
- [ ] continuation resolved
- [ ] queue item fresh
- [ ] no existing GradeSuggestion for this answer region
- [ ] real-call counter is below the approved limit

After each call:

- [ ] exactly one GradeSuggestion created for the intended answer region
- [ ] GradeSuggestion has score and max score
- [ ] `needs_review = true`
- [ ] confidence captured if returned
- [ ] feedback/rationale captured if returned
- [ ] rubric breakdown captured if returned
- [ ] no FinalGrade created yet

Stop on first provider failure. Do not retry or use mock fallback without founder approval.

## Teacher review and approval

For each draft GradeSuggestion:

- [ ] Teacher/founder opens review view
- [ ] Draft score/max marks visible
- [ ] confidence visible if available
- [ ] feedback/rationale visible
- [ ] rubric breakdown visible
- [ ] linked evidence/crop visible
- [ ] `needs_review = true` visible
- [ ] Not final yet before approval
- [ ] Teacher edits score/comment if needed
- [ ] Teacher explicitly approves
- [ ] FinalGrade created after approval only
- [ ] FinalGrade source GradeSuggestion id is traceable
- [ ] FinalGrade teacher id is traceable
- [ ] Audit/timestamp available where supported

## Export verification

Only after approval:

- [ ] Export XLSX downloaded/generated
- [ ] XLSX opens/parses successfully
- [ ] Row count equals approved FinalGrade count
- [ ] Draft/unapproved GradeSuggestions excluded
- [ ] Final score is exported, not only AI suggestion score
- [ ] Teacher-edited score preserved
- [ ] `approval_status = approved`
- [ ] source GradeSuggestion id included
- [ ] answer_region_id included
- [ ] unsafe internals such as password hashes/raw provider JSON excluded

## Known good five-packet demo evidence

TA-DEMO-006 passed with:

- [ ] Assessment id `13007`
- [ ] Answer regions `8111`–`8115`
- [ ] GradeSuggestions `4587`–`4591`
- [ ] FinalGrades `2992`–`2996`
- [ ] XLSX row count `5`
- [ ] model `gpt-5.5`
- [ ] mock used: no
- [ ] batch grading: no
- [ ] git clean

## Final demo verdict

- Founder-supervised demo ready: yes / no
- External teacher pilot ready: no unless remaining blockers are separately closed
- Remaining blockers noted:
  - [ ] non-synthetic data policy
  - [ ] auth/session hardening
  - [ ] operational support/runbook hardening
  - [ ] larger failure-path testing
