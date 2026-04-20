# Rules Wiki (`ai_rules/`)

> Loaded on first contact, at closure when a role note contains `Proposed Rules`, or when preflight flags entries whose `Verified:` date is older than 90 days. The manager NEVER writes to `ai_rules/` directly — every write goes through the `rules-curator` sub-agent.

## Why it exists

`ai_memory/` is ephemeral (archived after 7 days). `ai_doc/` holds per-WI artifacts that are archived after 30 days. Neither is durable enough to carry project-wide rules across a long project lifetime. `ai_rules/` is the only place where conventions, decisions, pitfalls, security and performance rules survive.

## Structure

```text
ai_rules/
  INDEX.md                — one-line pointer per entry; always loaded by manager and specialist agents
  conventions.md          — code, naming, commit, test conventions
  decisions.md            — architectural decisions (ADR-lite)
  pitfalls.md             — known traps, root causes, mitigations
  security.md             — security rules, auth boundaries, sensitive surfaces
  performance.md          — perf budgets, hotspots, benchmarks
  roles/
    developer.md          — rules the developer agent must read before coding
    devops.md             — rules the devops-engineer must read before infra work
    reviewer.md           — rules reviewers must apply
```

Topic files are lazy — created only when `rules-curator` adds the first entry.

## `INDEX.md` line format

```text
<TOPIC> | <ID> | <short title> | <file>#<id-lower> | Verified: YYYY-MM-DD
```

Example:

```text
CONVENTION | CONV-012 | ORM queries must use select_related on FK chains | conventions.md#conv-012 | Verified: 2026-04-10
PITFALL    | PIT-005  | Celery beat skips tasks on DST rollover          | pitfalls.md#pit-005    | Verified: 2026-03-22
DECISION   | DEC-003  | Switched from Redis to PG advisory locks         | decisions.md#dec-003   | Verified: 2026-02-14
```

Deprecated entries are prefixed `# DEPRECATED` and kept for historical trace.

## Entry template (enforced by `rules-curator`)

```markdown
### <ID> — <short title>

Scope: <where this applies — module, role, stack area>
Origin: <WI-ID, role-note path, ANALYSIS path, or "migrated from REPO_STATE.md">
Added: YYYY-MM-DD
Verified: YYYY-MM-DD

**Rule / Decision / Pitfall:** <one clear sentence>

**Why:** <reason — incident, constraint, tradeoff>

**How to apply:** <concrete guidance for the agent reading this>

**Counter-indications:** <when this does NOT apply, if any>
```

ID prefixes: `CONV-###`, `DEC-###`, `PIT-###`, `SEC-###`, `PERF-###`. `rules-curator` reads INDEX.md to find the next free number.

## Write policy

- **Single writer:** `rules-curator` is the only agent allowed to write in `ai_rules/`. The manager delegates every write.
- **Proposals:** `developer` and `solution-architect` may emit a `Proposed Rules` section in their role memory note. The manager passes those proposals to `rules-curator` at closure.
- **Never-touch:** `memory-cleaner` must not modify or delete `ai_rules/`.
- **Conflict resolution:** `rules-curator` handles contradictions and reports the resolution to the manager. The manager records the decision in the WI closure.

## When the manager invokes `rules-curator`

### 1. First-contact migration

Triggered when `ai_rules/` does not exist, OR `REPO_STATE.md` still carries `known_pitfalls` / `latest_decisions`, OR explorer flagged a migration gap in preflight.

Brief:

- `mode: migrate`
- `work_item: GLOBAL`
- inputs:
  - `repo_state: ai_memory/REPO_STATE.md`
  - `role_notes: <glob of last 30 days under ai_memory/>`
  - `analysis_docs: <glob of ai_doc/ANALYSIS__*.md>`

Expected curator output:

- created `ai_rules/` tree with migrated entries
- INDEX.md with `Verified:` = today
- a migration diff summary for the user
- an instruction to the manager to delete the migrated fields from `REPO_STATE.md` (the manager performs the deletion; the curator does not touch `REPO_STATE.md`).

### 2. Work-item closure with `Proposed Rules`

Triggered when at least one role note tied to the closing WI contains a `Proposed Rules` section.

Brief:

- `mode: triage`
- `work_item: <WI-ID>`
- inputs:
  - `role_notes: <list of role-note paths for this WI>`
  - `analysis_doc: <ai_doc/ANALYSIS__<WI-ID>__*.md if present>`

Expected curator output:

- per-proposal decision: ACCEPT / AMEND / MERGE / REJECT / DEPRECATE with reason
- written entries in the relevant topic files
- updated INDEX.md lines with `Verified:` = today

### 3. 90-day re-verification

Triggered when preflight (explorer) lists entries with `Verified:` older than 90 days and the manager confirms a review pass.

Brief:

- `mode: review`
- `work_item: GLOBAL`
- inputs:
  - `stale_entries: <list of <file>#<id> tuples>`

Expected curator output:

- per-entry decision: STILL VALID (bump `Verified:`) / NEEDS UPDATE (edit + bump) / OBSOLETE (deprecate)
- updated INDEX.md

## Manager checklist around `rules-curator`

Before invoking:

- gather the exact inputs (paths, IDs) — the curator must not hunt for context.
- announce the invocation to the user if the closure gate is open (medium/complex).

After invocation:

- read the curator's role memory note.
- record the accepted rules in the WI closure summary.
- for rejected proposals, surface the rejection reason back to the proposing role's role note if useful.
- only then mark the WI `DONE` (see DoD in `manager-runbook.md`).

## Curator memory note path

`rules-curator` writes to `ai_memory/YYYY-MM-DD__ROLE-rules-curator__<WI-ID or GLOBAL>.md`. The manager reads this note as part of closure.
