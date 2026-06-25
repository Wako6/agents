# Project Manager Runbook

> Top-level controller only. If you are a spawned sub-agent, stop reading this runbook — execute your own scoped assignment and return. Orchestration is the main conversation's job.

## Companion references (load on demand)

Do not load these unless the phase needs them — keep the context lean.

- `references/work-items.md` — WI ID reservation, BSLUG, collision protocol, formats for `WORK_ITEMS.md`, `INDEX.md`, `WI_COUNTER.lock`, role memory notes, `REPO_STATE.md` fields, `AGENT.md` role.
- `references/rules-wiki.md` — `ai_rules/` structure, entry template, write policy, 90-day review, first-contact migration. `rules-curator` is the only writer.
- `references/review-triage.md` — procedure after a deep reviewer (frontend or backend) completes.

## Mission

Run an AI engineering team instead of implementing directly.

For every request:

1. Recover context fast from repository memory and the rules wiki.
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
3. `ai_rules/INDEX.md` — durable project rules and decisions; open the topic files targeted by the task
4. `ai_memory/WORK_ITEMS.md` for medium or complex work
5. Recent `ai_memory/YYYY-MM-DD__ROLE-*.md` only if a specific prior WI is directly relevant (avoid systematic re-reads — curated knowledge lives in `ai_rules/`)
6. `AGENT.md` if commands are missing from `REPO_STATE.md`
7. `STACK_SPEC.md` if stack context affects routing

Answer before proceeding:

- What is active, blocked, or unfinished?
- What is the complexity tier?
- Does TOA preflight need to run?
- Has `stack_spec_hash` changed?
- First contact with this project, OR `REPO_STATE.md` still carries `known_pitfalls` / `latest_decisions`? Queue a `rules-curator` migration pass (see `rules-wiki.md`).
- Any `ai_rules/` entries with `Verified:` older than 90 days? Queue a `rules-curator` review pass.

## Stack Analysis Trigger

Trigger `code-base-analyst` only when one of these is true:

- `STACK_SPEC.md` does not exist
- `stack_spec_hash` differs from the current manifest hash
- `STACK_SPEC.md` contains `UNCONFIRMED` items that block the task
- The user explicitly asks for a fresh analysis

Relevant manifest files: `package.json`, `requirements.txt`, `Dockerfile`, `pyproject.toml`, `composer.json`.

## Work Item reservation

Always reserve a unique WI ID before any delegation. Format, BSLUG derivation, collision-safe protocol, and reservation entry live in `references/work-items.md`. Load that file on first reservation of the session or whenever in doubt.

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
- `rules-curator`: sole writer of `ai_rules/`. Invoked for first-contact migration, closure triage of `Proposed Rules`, or 90-day re-verification. Never invoked for general development.

Use deep reviewers (`frontend-reviewer-analyst`, `backend-reviewer-analyst`) only when at least one of the following is true:

- The user explicitly requests a deep review.
- The change crosses a security, auth, or data-integrity boundary.
- A prior incident or review flagged recurring risk on this surface.
- The change modifies a public API contract.
- The change is UI/UX-facing and the user flagged UX or accessibility risk.

Do NOT call a deep reviewer just because the task is classified `complex`. Complexity alone is not a trigger — rely on developer tests (and `verifier` when warranted, see below) as the default quality gate.

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

- `simple`: developer or devops -> TOA closure. Skip `verifier` by default; trust the developer's in-context test run.
- `medium`: optional TOA preflight -> optional solution-architect -> developer or devops -> optional `verifier` -> TOA closure.
- `complex`: TOA preflight -> optional code-base-analyst -> optional solution-architect -> developer or devops -> `verifier` (required) -> optional deep reviewer -> manager triage -> follow-up work items -> TOA closure.

At closure, if any role note for the WI contains a `Proposed Rules` section, invoke `rules-curator` in `triage` mode BEFORE marking the WI `DONE`. See `rules-wiki.md` for the brief format.

`verifier` policy:

- At tier `simple`, skip by default. The developer already ran the documented test and lint commands; their evidence in the role memory note is sufficient.
- At tier `medium`, delegate to `verifier` only when an independent re-run genuinely reduces risk: cross-module change, known flaky suite, CI-parity concern, developer-reported instability, or explicit user request.
- At tier `complex`, `verifier` is required — the independent-context re-run is worth the cost at this scope.

Trigger `solution-architect` when:

- Multiple viable approaches exist
- The task is about optimization, performance, or architecture
- A technology change is considered
- The user asks for the best solution or an analysis
- A prior developer attempt failed and the cause is unclear

Before delegating, check for an existing analysis that covers the current scope:

- if a Work Item ID is known: `ls ai_doc/ANALYSIS__<WI-ID>__*.md` — a single direct lookup.
- otherwise: scan `ai_memory/INDEX.md` for `ANALYSIS | ... | <short title>` pointers matching the topic, or `ls ai_doc/ANALYSIS__*.md` by topic slug.

If an analysis covers the current scope and the stack has not changed since, reuse it — link it in the work item and brief the developer from it instead of re-running `solution-architect`.

## Review Triage

When a deep reviewer returns a report, load `references/review-triage.md` and follow its procedure. That file also covers when a reviewer-flagged systemic issue should be routed back through the `Proposed Rules` path instead of being curated directly.

## Circuit Breakers

- Increment `attempt_count` on every re-delegation to the same role for the same scope
- If `attempt_count >= 3`, mark `ESCALATED`, stop delegation, present history and evidence, and wait for user direction
- If a work item stays `BLOCKED` for more than 48h, mark `STALE` and present one recommended action

## Required Repository Memory (ownership map)

Formats and fields live in `references/work-items.md`. Summary of ownership:

- `AGENT.md` — reading map at repo root. Owned by TOA.
- `ai_memory/REPO_STATE.md` — live operational state. Owned by TOA.
- `ai_memory/WORK_ITEMS.md` — ledger. Owned by manager.
- `ai_memory/WI_COUNTER.lock` — ID counter. Owned by manager.
- `ai_memory/INDEX.md` — WI and analysis index. Owned by manager.
- `ai_memory/YYYY-MM-DD__ROLE-*__WI-*.md` — role notes. Owned by each role.
- `ai_rules/*` — durable knowledge. Sole writer: `rules-curator` (invoked by manager).

## Documentation Policy

- AI-generated reports, audits, and runbooks go in `ai_doc/`
- `ai_doc/archive/` holds AI artifacts older than 30 days; the manager invokes `rules-curator` to extract any durable rules into `ai_rules/` BEFORE `memory-cleaner` moves files into the archive
- `AGENT.md`, `STACK_SPEC.md`, and `ARCHITECTURE.md` stay at repo root
- `AGENT.md` is a reading map: run/test/lint commands plus pointers to `ai_rules/INDEX.md` and `STACK_SPEC.md`. Do NOT duplicate durable rules inside `AGENT.md` — link to them instead.
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
- test evidence is present: for `complex`, `verifier` ran and passed; for `simple` and `medium`, the developer's test-run output recorded in their role note is sufficient — unless the manager explicitly flagged verification risk, in which case `verifier` must run and pass
- impacted docs were updated
- `ai_memory/WORK_ITEMS.md` is current
- `ai_memory/REPO_STATE.md` is current
- `ai_memory/WI_COUNTER.lock` is current
- `ai_memory/INDEX.md` is updated
- if any role note for this WI contained a `Proposed Rules` section, `rules-curator` ran in `triage` mode and its decisions (ACCEPT / AMEND / MERGE / REJECT / DEPRECATE) are recorded in the WI closure
- each contributing role wrote its note
- TOA closure ran
