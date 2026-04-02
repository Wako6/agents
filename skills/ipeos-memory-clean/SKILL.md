---
name: ipeos-memory-clean
description: Compact and archive IPEOS project memory without damaging active continuity. Use when Codex must clean `ai_memory/`, delegate maintenance to `memory-cleaner`, compact old DONE entries, archive old role notes, update `INDEX.md`, or prepare a user-confirmed archive deletion pass. Supports normal mode and force mode.
---

# IPEOS Memory Clean

Use this skill for repository memory maintenance, not for feature work.

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

Expected result:

1. Compact `WORK_ITEMS.md` by collapsing DONE items older than 7 days.
2. Clean obsolete decisions and resolved pitfalls from `REPO_STATE.md`.
3. Archive role notes for DONE work items older than 7 days into `ai_memory/archive/`.
4. Update `INDEX.md`.
5. Present archive files older than 30 days for explicit user confirmation before deletion.

## Force Mode

Before delegating, display a clear irreversible-operation warning and wait for explicit confirmation.

Delegate to `memory-cleaner` only after the user confirms.

Expected result:

1. Compact all DONE entries in `WORK_ITEMS.md`, regardless of age.
2. Clean obsolete decisions and resolved pitfalls from `REPO_STATE.md`.
3. Archive all DONE role notes immediately.
4. Update `INDEX.md`.
5. Present the full archive inventory for confirmation before any deletion.

## Never Touch

- `AGENT.md`
- `STACK_SPEC.md`
- `ARCHITECTURE.md`
- `WI_COUNTER.lock`
- any note tied to an active work item

After delegation, report the cleaner summary to the user and wait for a decision on proposed deletions.
