# Rules Wiki (`ai_rules/`) — V3

> Loaded on first contact, at closure when a role note contains `Proposed Rules`, or when preflight flags entries whose `Verified:` date is older than 90 days. The manager NEVER writes to `ai_rules/` directly — every write goes through the `rules-curator` subagent.

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

Optional fields (Claude Code native rules):

- `Autoload: yes|no` (default `no`) — `yes` exports the entry to `.claude/rules/` so it is injected automatically. Reserve it for rules an agent must obey *while editing code* (conventions, security patterns), not for history or rationale.
- `Paths: <glob>[, <glob>]` — with `Autoload: yes`, scopes the injection to sessions that read/edit matching files (e.g. `src/**/views.py`). Without `Paths`, the rule loads in every session of the project: keep those rare.

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

Triage is done **in two steps** (from the multi-team PM of the pilot project — no rule enters `ai_rules/` without human validation):

1. Brief `step: propose` — `mode: triage`, `work_item: <WI>`, inputs `role_notes` (paths), `analysis_doc` (if any). The curator writes **nothing**; for each proposal it returns: decision (ACCEPT / AMEND / MERGE / REJECT / DEPRECATE), justification, exact entry text (provisional ID), target file, planned INDEX line, risks.
2. The manager presents these proposals to the user, who validates, edits or refuses each one.
3. Brief `step: apply` — lists **only** the validated decisions with their final text. The curator writes exactly those, without adding or reinterpreting; any divergence with the brief → BLOCKED.

`step` missing in a triage brief → the curator returns BLOCKED.

Expected output of `apply`: written entries, INDEX.md lines with `Verified:` = today, curator note.

### 3. 90-day re-verification

Triggered when preflight (explorer) lists entries with `Verified:` older than 90 days and the manager confirms a review pass — or for an entry explicitly designated by the manager after a validated human decision (the brief quotes the decision).

Brief:

- `mode: review`
- `work_item: GLOBAL`
- inputs:
  - `stale_entries: <list of <file>#<id> tuples>`

Expected curator output:

- per-entry decision: STILL VALID (bump `Verified:`) / NEEDS UPDATE (edit + bump) / OBSOLETE (deprecate)
- updated INDEX.md

## Native rules sync (`.claude/rules/`) — manager's job, after every curator pass

`ai_rules/` stays the single source of truth. `.claude/rules/ai-rules.md` (unconditional) and `.claude/rules/ai-rules-<hash>.md` (with `paths:` frontmatter) are **generated**:

```
python3 -I ${CLAUDE_SKILL_DIR}/scripts/rules_sync.py --ai-rules ai_rules --out .claude/rules --check   # validate only
python3 -I ${CLAUDE_SKILL_DIR}/scripts/rules_sync.py --ai-rules ai_rules --out .claude/rules --write   # regenerate
```

The script refuses to write when it finds: duplicate IDs, duplicate titles, entries missing from INDEX.md (or the reverse), a deprecated entry still `Autoload: yes`, an exported entry without a `**Rule:**` line. Fix in `ai_rules/` (via `rules-curator`), never in the generated files. Hand-written rules in `.claude/rules/` (other names) are never touched by the script.

Three levels, no duplication:

| Level | File(s) | Content | Who writes |
|---|---|---|---|
| global | `~/.claude/rules/00-kit-workflow.md` (or the project copy when installed per project) | backend-neutral workflow invariants of this kit | kit installer |
| project | `.claude/rules/10-ai-memory-layout.md` (path-scoped), `.claude/rules/ai-rules*.md` (generated) | memory formats; project rules flagged `Autoload` | installer / `rules_sync.py` |
| knowledge | `ai_rules/*.md` | every rule with Scope, Why, How, Counter-indications, history | `rules-curator` only |

`CLAUDE.md` holds none of these rules: it is a short reading map (`@AGENT.md`, pointers).

### Semantic contradictions (not detectable by script)

In `review` mode, and whenever triage touches a topic that already has entries, `rules-curator` checks each pair of entries with overlapping `Scope`:

1. Do they prescribe incompatible actions for the same situation? → keep the more recent unless the older documents a hard constraint; `DEPRECATE` the other explicitly.
2. Is one a special case of the other? → `MERGE` (attach the case as a counter-indication).
3. Same intent, different wording? → `MERGE`, keep one ID.
4. Does a project rule contradict the global kit rule (`00-kit-workflow.md`)? → report to the manager, who asks the user. Claude Code loads user and project rules side by side without precedence (documentation): a contradiction is never left in place. A project rule that is **stricter** than the kit rule is not a contradiction.

The curator records every resolution in its memory note.

## Manager checklist around `rules-curator`

Before invoking:

- gather the exact inputs (paths, IDs) — the curator must not hunt for context.
- announce the invocation to the user if the closure gate is open (medium/complex).

After invocation:

- triage: present the `propose` result to the user and wait; then brief `apply` with the validated decisions only.
- read the curator's role memory note.
- record the accepted rules in the WI closure summary.
- for rejected proposals, surface the rejection reason back to the proposing role's role note if useful.
- only then mark the WI `DONE` (see DoD in `manager-runbook.md`).

## Curator memory note path

`rules-curator` writes to `ai_memory/YYYY-MM-DD__ROLE-rules-curator__<WI or GLOBAL>.md` (`<WI>` = `WI-…` or `#NN` per backend). The manager reads this note as part of closure.
