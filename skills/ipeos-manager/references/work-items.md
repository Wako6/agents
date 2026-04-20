# Work Items and Repository Memory Formats

> Loaded when opening/closing a work item, reserving an ID, or updating `ai_memory/` ledgers. Orchestration workflow and gates live in `manager-runbook.md`. Rules-wiki operations live in `rules-wiki.md`.

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

### Collision-safe reservation protocol

1. Derive `BSLUG`.
2. Read `ai_memory/WI_COUNTER.lock`.
3. Find the line `BSLUG=WI-YYYYMMDD-BSLUG-###`.
4. If the stored date is today, increment the sequence.
5. Otherwise start at `001`.
6. Upsert the line immediately before any delegation.
7. If `WI_COUNTER.lock` is missing, scan `ai_memory/WORK_ITEMS.md` and `ai_doc/` for the highest existing ID for that branch slug, create the lock file, then continue.

If uniqueness cannot be verified, stop and mark the task `BLOCKED`.

### Reservation entry (in `WORK_ITEMS.md`)

Record at reservation time:

- Work Item ID
- Date/Time
- Short Title
- Status = `OPEN`
- TOA
- Primary Executor
- `attempt_count = 0`

## `ai_memory/WI_COUNTER.lock`

One line per branch slug:

```text
MAIN=WI-20260325-MAIN-004
FIXAUT=WI-20260325-FIXAUT-001
FEATPA=WI-20260324-FEATPA-002
```

Preserve other branches' lines when editing — never rewrite the whole file.

## `ai_memory/WORK_ITEMS.md`

Main ledger. Keep status, attempt count, owners, memory links, pending clarifications, and the linked `ai_doc/ANALYSIS__<WI-ID>__*.md` path (if any) current.

## `ai_memory/INDEX.md`

One searchable line per work item:

```text
WI-YYYYMMDD-BSLUG-### | Short Title | Status | Roles | Note path(s)
```

Also hosts analysis pointers emitted by `ipeos-problem-solver`:

```text
ANALYSIS | <WI-ID or n/a> | ai_doc/ANALYSIS__<WI-ID>__<slug>.md | <short title>
```

## Role Memory Notes

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

Optional (for `developer` and `solution-architect`):

- `Proposed Rules` — durable rules the role wants promoted to `ai_rules/`. Never written directly. Triaged at closure by `rules-curator` (see `rules-wiki.md`).

Archive `DONE` notes older than 7 days to `ai_memory/archive/`.

## `ai_memory/REPO_STATE.md` required fields

Keep `REPO_STATE.md` limited to **live operational state**. Durable rules, decisions, and pitfalls belong in `ai_rules/` — do not duplicate them here.

Maintain:

- `project_purpose`
- `run_commands`
- `test_commands`
- `lint_commands`
- `last_toa_run`
- `stack_spec_hash`
- `active_work_items`
- `blocking_questions`

Removed on purpose (migrated to `ai_rules/`): `known_pitfalls`, `latest_decisions`. On first contact with an existing project that still carries these fields, delegate the migration to `rules-curator` (see `rules-wiki.md`) before deleting them from `REPO_STATE.md`.

## `AGENT.md` (repo root)

Reading map, not a rules dump. Keep run/test/lint/startup/shutdown/env commands accurate, plus pointers to:

- `STACK_SPEC.md`
- `ai_rules/INDEX.md`

Do NOT duplicate durable rules inside `AGENT.md` — link to the relevant `ai_rules/` entries instead.
