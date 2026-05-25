# DEVELOPMENT PROTOCOL

## Builder Model
Hermes is the single builder/controller for this project.

Hermes owns planning, coding, testing, review, documentation, backlog updates, and reporting. Hermes may use available tools internally, including coding assistants or LLM tools if available, but no separate implementation worker is assumed and no work is considered complete until Hermes verifies it with commands/tests.

Human owns product direction, scope approval, sensitive policy decisions, deployment constraints, credential decisions, ambiguous grading behavior, and final acceptance.

## Locked Stack
All implementation must follow `TECH_STACK_DECISION.md`:
- Next.js App Router, TypeScript, Tailwind CSS
- FastAPI, Python, Pydantic, SQLAlchemy 2.x, Alembic
- PostgreSQL
- Redis + RQ
- local filesystem behind storage adapter
- custom Brain Adapter only for LLM calls
- PyMuPDF, Pillow, OpenCV
- openpyxl
- Docker Compose and Makefile
- pytest backend tests

## Synchronization Rules
1. No coding starts before constitution, architecture, specs, protocol, week map, backlog, tech stack decision, and Hermes-only scaffold plan exist.
2. Every implementation task must reference a TASK-ID.
3. Hermes must update `BACKLOG.md` after every task status change.
4. Hermes must not mark work done unless required commands/tests pass, or exact failures are reported.
5. If implementation conflicts with `PROJECT_CONSTITUTION.md`, `ARCHITECTURE.md`, or locked stack, Hermes must stop and ask Human.
6. Production code starts only after `DAY_1_SCAFFOLD_PLAN.md` is updated for Hermes-only implementation.

## Hermes Role
Hermes = planner + coder + tester + reviewer.

For every task Hermes must:
1. restate the active TASK-ID internally before editing;
2. inspect relevant docs/files before changing code;
3. make only scoped changes;
4. run required commands/tests;
5. fix failures when within scope;
6. update `BACKLOG.md`;
7. report files changed, commands run, test results, remaining issues.

## Task ID Format
`TA-W1-###` for week 1 tasks. Example: `TA-W1-001`.

Future format: `TA-W{week}-{number}` unless replaced by issue tracker IDs.

## Branch Naming
Use: `task/TA-W1-001-short-title`

Examples:
- `task/TA-W1-003-project-scaffold`
- `task/TA-W1-006-brain-adapter-contracts`

## Commit Rules
Commit messages must include the task ID.

Format:
```text
<type>(<scope>): <summary> [TA-W1-###]
```

Allowed types: `docs`, `test`, `feat`, `fix`, `refactor`, `chore`.

## File Ownership Rules
Hermes owns all project files unless a future Human decision introduces another worker. File locks still apply to prevent accidental architectural drift.

Locked files require deliberate review before editing:
- `PROJECT_CONSTITUTION.md`
- `ARCHITECTURE.md`
- `TECH_STACK_DECISION.md`
- `BRAIN_ADAPTER_SPEC.md`
- `GRADING_ENGINE_SPEC.md`
- `DEVELOPMENT_PROTOCOL.md`
- `WEEK_1_EXECUTION_MAP.md`
- `DAY_1_SCAFFOLD_PLAN.md`
- `BACKLOG.md`

For locked files, Hermes may edit only when the active task explicitly requires it, and must report the reason.

## When to Stop and Ask Human
Stop when:
- final grade behavior is ambiguous
- privacy/data retention requirement is unclear
- provider/model/API key choice is needed
- uploaded student data handling policy is involved
- architecture boundary must be changed
- acceptance criteria cannot be met
- cost/security tradeoff appears
- a new dependency outside locked stack is desired
- a real LLM provider integration is being considered

## Test-Before-Done Rule
A task is not done until required tests pass and evidence is recorded in the final task report. For docs-only tasks, acceptance means documents contain required sections and are internally consistent. For implementation tasks, commands must be run, not assumed.

## Required Task Report Format
After every task, Hermes reports:

```markdown
## Task Report: TASK-ID

Files changed:
- path: summary

Commands run:
- command: result

Test results:
- test/check: pass/fail and evidence

Backlog update:
- status change or note

Remaining issues:
- issue or `None`
```

## Daily Checkpoint Format
```markdown
# Daily Checkpoint - YYYY-MM-DD

## Completed
- TASK-ID: result and files changed

## In Progress
- TASK-ID: current blocker/next action

## Decisions Needed
- question, options, recommendation

## Risks
- risk, impact, mitigation

## Tests / Verification
- command or review performed, result

## Next Day Plan
- ordered tasks
```
