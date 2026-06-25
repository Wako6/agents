---
name: project-memory-clean
description: "Safe compaction and archival of repository memory (ai_memory/) via the memory-cleaner sub-agent. Invoke at the top level of the main conversation when the user asks to clean, compact, archive, trim, prune, purge, or do housekeeping on project memory — French triggers: 'nettoyer la mémoire', 'faire le ménage', 'compacter ai_memory', 'archiver les work items', 'mémoire pleine', 'purge la mémoire', 'nettoyage projet'; English triggers: 'clean memory', 'clean up ai_memory', 'compact memory', 'archive old work items', 'prune memory', 'memory cleanup', 'housekeeping on ai_memory'. Also invoke when the user flags that ai_memory/ has grown large, has many stale DONE entries, or needs maintenance before a new phase. Force mode (irreversible operations) activates when the request contains the word 'force'. MUST NEVER run inside a spawned sub-agent."
---

# Project Memory Clean

Use this skill for repository memory maintenance only. It is not a hook for normal dev work and must not run automatically at the end of features, bug fixes, PRs, or releases — the user decides when to clean.

## Cascade Guard

This skill runs ONLY at the top level of the main Codex conversation.

- If you are a spawned sub-agent, do NOT invoke this skill. `memory-cleaner` itself must be launched by the top-level controller, never by another sub-agent.
- Sub-agents report memory growth or staleness to the caller; they do not delegate cleaning.

## When to Activate

Activate when any of these is true at the top level:

- The user uses a trigger phrase listed in the description (FR or EN).
- The user asks to clean, compact, archive, trim, prune, or purge `ai_memory/`.
- The user asks for project memory maintenance, housekeeping, or archive review.
- The user flags that `ai_memory/` is large, noisy, or full of old DONE entries.
- The request contains `force` in a memory-cleaning context (triggers force mode).

Do not activate when:

- The user is starting or running a dev task, PR, or release (that is `project-manager`).
- The user only asks to read, inspect, or list memory contents (answer directly).
- You are running as a spawned sub-agent.

## Mode Selection

- If the request contains `force`, use force mode.
- Otherwise use normal mode.

## Normal Mode

Delegate to `memory-cleaner`.

Scope:

- `ai_memory/`
- `ai_memory/archive/`
- `ai_memory/WORK_ITEMS.md`
- `ai_memory/REPO_STATE.md`
- `ai_memory/INDEX.md`
- `ai_doc/` and `ai_doc/archive/` — move AI artifacts older than 30 days into `ai_doc/archive/` after confirming the manager has extracted any durable rules to `ai_rules/`

Expected result:

1. Compact `WORK_ITEMS.md` by collapsing DONE items older than 7 days.
2. Clean obsolete decisions and resolved pitfalls from `REPO_STATE.md`.
3. Archive role notes for DONE work items older than 7 days into `ai_memory/archive/`.
4. Archive `ai_doc/` artifacts older than 30 days into `ai_doc/archive/` — only after the manager has confirmed any durable rules were extracted to `ai_rules/`.
5. Update `INDEX.md`.
6. Present archive files older than 30 days for explicit user confirmation before deletion.

## Force Mode

Before delegating, display a clear irreversible-operation warning and wait for explicit confirmation.

Delegate to `memory-cleaner` only after the user confirms.

Expected result:

1. Compact all DONE entries in `WORK_ITEMS.md`, regardless of age.
2. Clean obsolete decisions and resolved pitfalls from `REPO_STATE.md`.
3. Archive all DONE role notes immediately.
4. Archive all `ai_doc/` artifacts tied to closed work items — only after the manager confirms rule extraction to `ai_rules/` is complete.
5. Update `INDEX.md`.
6. Present the full archive inventory for confirmation before any deletion.

## Never Touch

- `AGENT.md`
- `STACK_SPEC.md`
- `ARCHITECTURE.md`
- `WI_COUNTER.lock`
- `ai_rules/` and anything under it — durable knowledge base, only the manager writes here
- any note tied to an active work item

After delegation, report the cleaner summary to the user and wait for a decision on proposed deletions.
