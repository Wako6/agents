# Extension points — interfaces only (V3)

> **Pilot status (3.1.0-rc1):** I1, I2 (peer review), I3 (ledger variant), I4, I6 (`max_parallel`, `max_attempts`) and I7 have an opt-in pilot implementation, `scripts/pmx.py`, described in `orchestration-pilot.md`. Without `orchestration.enabled: true` the statement below still holds.
>
> **Nothing here is implemented.** The manager runs identically when no extension is present. Detection is cheap, silent, at most once per session, and recorded in `REPO_STATE.md` → `capabilities:`. An extension is only *proposed* in a plan (human gate); it never changes state by itself: it produces a file in `ai_doc/`; only the manager updates the registry, decides and delegates. No extension may weaken an approval rule.

## Detection

| Capability | Detection | Absent |
|---|---|---|
| Codex adversarial review (plugin) | the `/codex:adversarial-review` command exists in the session (commands list; never shell out to `codex`) | skip silently |
| Claudex debate | executable `claudex` on PATH **or** `.claude/claudex.json` | skip silently |
| Forge CLI | `command -v glab` / `command -v gh` | ledger: user opens MRs/PRs by hand; GitLab backend: offline mode |
| Inter-session messaging | messaging tool available in the session | feature-lead reports via notes |

`REPO_STATE.md`:
```
capabilities:
  codex_review: yes|no   (checked: YYYY-MM-DD)
  claudex: yes|no        (checked: YYYY-MM-DD)
  forge_cli: glab|gh|none
  messaging: yes|no
```

## I1 — Claudex / Claude–Codex debate

- When: DEEP analysis stage, as an independent second analysis, if the user agreed in the plan.
- Input: `ai_doc/DEBATE__<WI>__<slug>.brief.md` — problem, constraints, pointers (`STACK_SPEC.md`, `ai_rules/INDEX.md`, topics), expected sections.
- Output: `ai_doc/DEBATE__<WI>__<slug>.md` — *Positions (Claude / Codex)*, *Points d'accord*, *Désaccords non résolus*, *Questions pour l'utilisateur*, *Décision proposée*.
- Rule: unresolved disagreements go to the user; the manager never picks a side; a durable decision becomes a `DEC-` proposal to `rules-curator` (two-step).

## I2 — Cross reviews

- Codex adversarial review: input = analysis path or diff vs integration branch; output `ai_doc/reviews/ADVERSARIAL__<WI>__<n>.md`, written by the manager from the command result; triaged with `review-triage.md`.
- Peer review between feature-leads (multi-team): a feature-lead may request a read-only review of another feature's MR through the manager; output `ai_doc/reviews/PEER__<WI>__<n>.md`; never write access to another worktree.

## I3 — Multi-team planning (generalisation)

- Implemented today for `gitlab-issues` (`multi-team.md`).
- `ledger` variant (pilot: `orchestration-pilot.md`, fields below written by `pmx` in the lead session): shared registry = `WORK_ITEMS.md` of the **main checkout**, written by the lead only; entries gain `depends_on`, `parent`, `session`, `worktree`, `files_probably_touched`; feature sessions report through notes, never edit the ledger. Must be specified and validated before use.

## I4 — Parallel worktrees

- Feature sessions = Desktop worktree sessions (they load their own `CLAUDE.md` / `.claude/rules/`).
- Subagents with `isolation: worktree` do **not** load the worktree's `CLAUDE.md` / rules (documentation) → their brief must carry the rules explicitly; not used for feature-leads today.
- `tools: Agent(type, …)` restrictions apply to a main-thread agent only (documentation); a delegating subagent cannot be restricted that way → any future delegating role relies on `permissions.deny: Agent(<type>)` and on its brief.

## I5 — Conditional GitLab integration

- The forge is optional: `forge_cli: none` → the workflow runs on the local registry; MRs by hand.
- Automatic integration of "non-sensitive" changes: **out of scope** until (1) a CI job replays the test commands on the delivered commit and publishes the proof, and (2) a path allow-list exists as an `ai_rules/` `SEC-` entry validated by the user. Human merge stays the default.

## I6 — Resources and costs

- Declarative only, in the project configuration (future key `budget`): per-role `model` / `effort` overrides, max parallel sessions, per-work-item delegation cap (in addition to `attempt_count`), optional token/cost ceilings reported in the status.
- The manager would report consumption it can observe; it never enforces silently and never changes a model without telling the user.

## I7 — Multi-agent execution resume

- Contract on **existing** files only (no new memory system): the registry (state + `attempt_count`), role notes (`Next actions`, `Open blockers`), `REPO_STATE.md` (`blocking_questions`, active items), `PENDING_GITLAB.md` (offline queue).
- Resume algorithm = runbook *Resume the project*; an interrupted delegation is detected as "work item in progress without a closing note from the delegated role" → the manager re-briefs (counts as an attempt) or asks the user.

## Invariants (all extensions)

Registry, tiers, gates, circuit breakers, Definition of Done, `ai_rules/` single writer, one approval per outgoing operation, no AI merge, no secret access, guardrails untouched.
