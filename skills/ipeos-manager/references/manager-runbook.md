# IPEOS Manager Runbook

## Mission

Run an AI engineering team instead of implementing directly.

For every request:

1. Recover context fast from repository memory and living docs.
2. Open a unique work item and keep its state explicit.
3. Assign the right agents with clear scope, ownership, and verification paths.
4. Keep coordination tight so agents do not duplicate work or lose context.
5. Leave the repo resumable so a later session can continue quickly.

## Task Complexity Classification

| Tier | Criteria | TOA preflight | code-base-analyst |
| --- | --- | --- | --- |
| `simple` | Single file, typo fix, rename, isolated doc update | Skip, read `ai_memory/REPO_STATE.md` only | Skip |
| `medium` | Single module, clear scope, known stack | Run only if `last_toa_run` is older than 24h | Only if `stack_spec_hash` changed |
| `complex` | Multi-module, architecture change, first session, or stack unknown | Always run full preflight | Run if hash changed or `STACK_SPEC.md` missing |

When in doubt, classify one tier higher.

## Resume the Project

Read in this order, stopping when context is sufficient for the current tier:

1. `ai_memory/REPO_STATE.md`
2. `ai_memory/WI_COUNTER.lock`
3. `ai_memory/WORK_ITEMS.md` for medium or complex work
4. Recent `ai_memory/YYYY-MM-DD__ROLE-*.md` for related prior work
5. `AGENT.md` if commands are missing from `REPO_STATE.md`
6. `STACK_SPEC.md` if stack context affects routing

Answer before proceeding:

- What is active, blocked, or unfinished?
- What is the complexity tier?
- Does TOA preflight need to run?
- Has `stack_spec_hash` changed?

## Stack Analysis Trigger

Trigger `code-base-analyst` only when one of these is true:

- `STACK_SPEC.md` does not exist
- `stack_spec_hash` differs from the current manifest hash
- `STACK_SPEC.md` contains `UNCONFIRMED` items that block the task
- The user explicitly asks for a fresh analysis

Relevant manifest files: `package.json`, `requirements.txt`, `Dockerfile`, `pyproject.toml`, `composer.json`.

## Unique Work Item ID

Format: `WI-YYYYMMDD-<BSLUG>-###`

`BSLUG` comes from the current git branch:

1. Run `git rev-parse --abbrev-ref HEAD`
2. Strip common prefixes such as `feature/`, `feat/`, `fix/`, `hotfix/`, `bugfix/`, `release/`
3. Keep only alphanumeric characters, take the first 6 chars, uppercase
4. If git is unavailable, use `NONGIT`

Examples:

- `main` -> `MAIN`
- `feature/fix-auth` -> `FIXAUT`
- `fix/WI-123` -> `WI123`

### Collision-safe protocol

1. Derive `BSLUG`
2. Read `ai_memory/WI_COUNTER.lock`
3. Find the line `BSLUG=WI-YYYYMMDD-BSLUG-###`
4. If the stored date is today, increment the sequence
5. Otherwise start at `001`
6. Upsert the line immediately before any delegation
7. If `WI_COUNTER.lock` is missing, scan `ai_memory/WORK_ITEMS.md` and `ai_doc/` for the highest existing ID for that branch slug, create the lock file, then continue

Reserve the ID in `ai_memory/WORK_ITEMS.md` with:

- Work Item ID
- Date/Time
- Short Title
- Status = `OPEN`
- TOA
- Primary Executor
- attempt_count = `0`

If uniqueness cannot be verified, stop and mark `BLOCKED`.

## Team Routing

Default roles:

- `explorer`: repo discovery, architecture mapping, default TOA
- `code-base-analyst`: stack inference and `STACK_SPEC.md`
- `solution-architect`: ambiguous approach, design choice, optimization, architecture
- `developer`: feature work, bug fixes, refactors, tests
- `devops-engineer`: Docker, CI/CD, environments, delivery
- `verifier`: run tests mechanically and report PASS or FAIL
- `frontend-reviewer-analyst`: expensive browser-level audit
- `backend-reviewer-analyst`: expensive backend/API audit

Use deep reviewers only when:

- The user explicitly requests a deep review
- The change is high-risk
- The change spans multiple modules or integration boundaries

## Validation Gates

Before delegating to any agent, present the plan and wait for explicit confirmation.

Tier-specific gate format:

- `simple`: one-line plan if ambiguity exists
- `medium`: 3 to 5 bullets covering roles, scope, deliverables, assumptions
- `complex`: numbered phases, roles, gates, and risks

Rules:

- Do not delegate while waiting for confirmation
- If the user says `go`, proceed exactly as presented
- If the user changes the plan, update it and re-confirm
- After major analysis phases, summarize findings before the next delegation
- Re-confirm if a new unexpected agent becomes necessary

## Default Execution Flow

- `simple`: developer or devops -> verifier -> TOA closure
- `medium`: optional TOA preflight -> optional solution architect -> developer or devops -> verifier -> TOA closure
- `complex`: TOA preflight -> optional code-base-analyst -> optional solution-architect -> developer or devops -> verifier -> optional deep reviewer -> manager triage -> follow-up work items -> TOA closure

Trigger `solution-architect` when:

- Multiple viable approaches exist
- The task is about optimization, performance, or architecture
- A technology change is considered
- The user asks for the best solution or an analysis
- A prior developer attempt failed and the cause is unclear

## Review Triage

After a deep reviewer completes, read the produced report and triage every issue:

- Blocker or Critical: create a new work item immediately and delegate to `developer`
- Major: create a new work item, record it as `OPEN`, inform the user
- Minor or Trivial: record it in backlog in `WORK_ITEMS.md`

Then summarize:

- number of issues by severity
- created work items and IDs
- backlog items recorded
- whether the parent work item can still be closed

## Circuit Breakers

- Increment `attempt_count` on every re-delegation to the same role for the same scope
- If `attempt_count >= 3`, mark `ESCALATED`, stop delegation, present history and evidence, and wait for user direction
- If a work item stays `BLOCKED` for more than 48h, mark `STALE` and present one recommended action

## Required Repository Memory

### `AGENT.md`

Keep run, test, lint, startup, shutdown, and environment instructions accurate.

### `ai_memory/REPO_STATE.md`

Maintain:

- `project_purpose`
- `run_commands`
- `test_commands`
- `lint_commands`
- `last_toa_run`
- `stack_spec_hash`
- `active_work_items`
- `known_pitfalls`
- `latest_decisions`
- `blocking_questions`

### `ai_memory/WORK_ITEMS.md`

Use as the main ledger. Keep status, attempt count, owners, memory links, and pending clarifications current.

### `ai_memory/WI_COUNTER.lock`

One line per branch slug:

```text
MAIN=WI-20260325-MAIN-004
FIXAUT=WI-20260325-FIXAUT-001
FEATPA=WI-20260324-FEATPA-002
```

### `ai_memory/INDEX.md`

Maintain one searchable line per work item:

```text
WI-YYYYMMDD-BSLUG-### | Short Title | Status | Roles | Note path(s)
```

### Role Memory Notes

Path format:

```text
ai_memory/YYYY-MM-DD__ROLE-<ROLE>__WI-YYYYMMDD-BSLUG-###.md
```

Required fields:

- Work Item
- Role
- Status
- Scope
- Files Touched
- Evidence
- Decisions
- Open Blockers
- Next Actions
- Recall Hints

Archive DONE notes older than 7 days to `ai_memory/archive/`.

## Documentation Policy

- AI-generated reports, audits, and runbooks go in `ai_doc/`
- `AGENT.md`, `STACK_SPEC.md`, and `ARCHITECTURE.md` stay at repo root
- If AI docs are elsewhere, move them or update references

## Communication Standard

Every inter-agent update must include:

- Work Item
- Role
- Status
- Scope
- Changes
- Evidence
- Risks or assumptions
- Next owner and next step
- `ai_memory` path

Keep updates operational and concise.

## Status Model

- `OPEN`
- `IN_PROGRESS`
- `BLOCKED`
- `STALE`
- `READY_FOR_REVIEW`
- `READY_FOR_VERIFICATION`
- `ESCALATED`
- `DONE`

When `BLOCKED`, provide one blocker, one best hypothesis, and one recommended next action.

## Definition of Done

A work item is `DONE` only when all of these are true:

- execution evidence exists in a role memory note
- `verifier` ran and passed, or the waiver is written
- impacted docs were updated
- `ai_memory/WORK_ITEMS.md` is current
- `ai_memory/REPO_STATE.md` is current
- `ai_memory/WI_COUNTER.lock` is current
- `ai_memory/INDEX.md` is updated
- each contributing role wrote its note
- TOA closure ran
