# Protocol — memory housekeeping (ex skill `project-memory-clean`, made backend-aware)

> Executed by the manager in the lead session **only when the user asks** (« nettoie la mémoire », « compacte ai_memory », « archive les work items », « mémoire pleine », « faire le ménage »). Never automatically at the end of a task. Never inside a subagent.

## Mode

- request contains `force` → force mode;
- otherwise → normal mode.

## Before delegating (manager)

1. Build the list of **closed** work items from the configured backend — the cleaner never queries a forge itself:
   - ledger: `DONE` entries of `ai_memory/WORK_ITEMS.md`;
   - GitLab: closed issues (`glab issue list -R <project> --closed`, read-only) cross-checked with `REPO_STATE.md`; GitLab unreachable → only items already recorded as closed in local memory; when in doubt, treat as active.
2. Confirm with `rules-curator` (or the latest closure records) that durable rules were extracted from `ai_doc/` artifacts before any of them is archived.
3. Multi-team projects: run from the lead session only; never touch a feature worktree.

## Normal mode — brief to `memory-cleaner` (Agent tool)

Scope: `ai_memory/`, `ai_memory/archive/`, `ai_doc/`, `ai_doc/archive/`; ledger files only in a ledger project. Inputs: the closed-items list, the rule-extraction confirmation, the backend.
Expected:
1. ledger only: compact `WORK_ITEMS.md` (closed items older than 7 days → one line);
2. `REPO_STATE.md`: remove answered blocking questions only; `known_pitfalls` / `latest_decisions` are **flagged** for `rules-curator` migration, never deleted;
3. move role notes of closed items older than 7 days to `ai_memory/archive/`;
4. `ai_doc/` artifacts older than 30 days tied to closed items → `ai_doc/archive/`, only with the rule-extraction confirmation;
5. update `ai_memory/INDEX.md` paths (ledger) — GitLab projects keep no INDEX unless they already had one;
6. **list** archive files older than 30 days and ask the user before any deletion.

## Force mode

Show an explicit irreversible-operation warning and wait for confirmation; then the same brief with `force mode`: all closed items regardless of age; full archive inventory presented before any deletion.

## Never touch

`AGENT.md`, `STACK_SPEC.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `WI_COUNTER.lock`, `ai_rules/**`, specs, the proof file (`ai_memory/verification.json` or configured), `ai_memory/PENDING_GITLAB.md` entries not yet replayed, any note of an active item, anything under `.claude/`.

Report the cleaner's summary and wait for the user's decision on proposed deletions.
