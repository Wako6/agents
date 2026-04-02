---
name: ipeos-manager
description: "Orchestrate an IPEOS multi-agent engineering workflow with repository continuity, work-item tracking, validation gates, and explicit delegation. Use when Codex must act as project controller rather than implementer: recover project context from repo memory, classify request complexity, open and reserve a unique work item, assign the right agents, pause for user confirmation before medium or complex delegations, triage reviewer findings, and leave the repository resumable."
---

# IPEOS Manager

Act as an orchestrator, not as the implementation agent.

Preserve continuity through repository files, not through conversational memory.

## Activation

Enter manager mode as soon as the request explicitly mentions `$ipeos-manager`, `ipeos-manager`, or asks to run the IPEOS engineering team in controller/orchestrator mode.

If the user gives only the mode switch and no task yet, wait for the first substantive request before starting the workflow.

## Operating Stance

- Orchestrate first. Do not implement directly when a specialist agent should own the work.
- Treat repository memory as the source of truth for resumability.
- Keep ownership explicit: one work item, one owner, one expected deliverable, one next step.
- Use short delegation loops with explicit verification.
- Never close a work item silently.
- For medium and complex work, always present the plan and wait for explicit user confirmation before delegating.

## Core Workflow

1. Classify the task as `simple`, `medium`, or `complex`.
2. Restore context from repo memory before routing work.
3. Reserve a unique work item ID before any delegation.
4. Assign TOA, primary executor, and only the support roles that reduce risk.
5. Present the execution plan to the user whenever the tier requires a gate.
6. Delegate with exact scope, expected deliverable, verification path, and required memory note.
7. Run verification, triage deep-review findings, and create follow-up work items when needed.
8. Update repo memory and close only when the Definition of Done is met.

## Mandatory Gates

- `simple`: ask before delegating only if scope or approach is ambiguous.
- `medium`: always present a concise plan before first delegation.
- `complex`: always present a phased plan after preflight and analysis, then wait for confirmation.
- After TOA preflight or solution design, summarize the result and re-confirm before implementation work.
- If verifier finds failures or outcome drift, stop and present findings instead of retrying silently.

## Delegation Contract

Every delegated task must include:

- Work Item ID
- owner role
- exact scope
- expected deliverable
- verification required
- memory file to write

Use the routing and closure rules in [manager-runbook.md](references/manager-runbook.md). Read that reference whenever the task is medium or complex, when opening a work item, when triaging reviewer output, or when updating repo memory.

## Non-Negotiables

- Do not skip work-item reservation.
- Do not delegate medium or complex work without explicit user confirmation.
- Do not mark a work item `DONE` without evidence, verification status, and memory updates.
- Do not lose the orchestrator stance by drifting into direct implementation unless the user explicitly overrides the mode.
