# Work Items — common model (V3)

> One project = **one registry**. The backend is chosen by the project configuration (`project-config.md`) and never mixed. This file defines what is common; the backend files define IDs, commands and storage.

## Backends

| Backend | Registry | Identifier `<WI>` | Reference |
|---|---|---|---|
| `ledger` (default for a new project) | `ai_memory/WORK_ITEMS.md`, `ai_memory/WI_COUNTER.lock`, `ai_memory/INDEX.md` | `WI-YYYYMMDD-BSLUG-###` | `backend-ledger.md` |
| `gitlab-issues` | GitLab issues + **one** state label per issue | `#NN` (issue number) | `backend-gitlab.md` |

Rules:
- Never create `WORK_ITEMS.md` / `WI_COUNTER.lock` in a `gitlab-issues` project, nor use issues as a second registry in a `ledger` project (an MR/PR may still reference a ledger WI).
- Backend unknown (no configuration) → detection in `project-config.md`; ambiguous → ask the user, do not guess.
- Backend unreachable → its offline mode; never simulate its state.

## Status model and mapping

| Common status | Ledger value | GitLab label / state | Condition |
|---|---|---|---|
| open | `OPEN` | `todo` | created/reserved; dependencies integrated |
| in progress | `IN_PROGRESS` | `doing` | owner assigned; (multi-team) branch + worktree + opening note |
| ready for verification | `READY_FOR_VERIFICATION` | `tests` | developer evidence; proof PASS on the current tree if a proof command is configured |
| ready for review | `READY_FOR_REVIEW` | `review` | draft MR/PR open towards the integration branch (if any) |
| blocked | `BLOCKED` | `blocked` (**replaces** the state label) | note: exact blocker, hypothesis, recommended action, **state to restore** |
| escalated | `ESCALATED` | `blocked` + escalation note | `attempt_count ≥ 3`, or decision only the user can take |
| stale | `STALE` | `blocked` > 48 h, flagged in the status report | blocked for more than 48 h |
| done | `DONE` | issue **closed by the manager** after verified integration | Definition of Done met |

GitLab: exactly one state label at a time; every change removes the previous one.

## Dependencies

- Ledger: `depends_on: [WI-…]` in the entry (pilot `orchestration-pilot.md`: also `parent`, `session`, `worktree`, `files_probably_touched`, `blocker`, `integrated`); a dependent WI is delegated only when every dependency is `DONE` (or, if the plan says so explicitly, `READY_FOR_REVIEW`).
- GitLab: `Depends on: #NN (must be integrated into <integration>)` in the description; the dependent issue is created `blocked`; it becomes `todo` only on an **INTÉGRÉE** verdict (`backend-gitlab.md` § integration check). `review` is never enough.

## Role memory notes (both backends)

Path: `ai_memory/YYYY-MM-DD__ROLE-<role>__<WI>.md` — `<WI>` is `WI-YYYYMMDD-BSLUG-###` (ledger) or `#NN` (GitLab), or `GLOBAL` for migration/review passes.

Required fields: Work item | Role | Status | Scope | Files touched | Evidence | Decisions | Open blockers | Next actions | Recall hints. Optional for `developer` and `solution-architect`: `Proposed Rules`.

Roles without write tools (`verifier`, reviewers) return their note inline; the caller records it under the same path.

Legacy compatibility: notes written with the old defective pattern `**ROLE-x**` stay readable; new notes use `__ROLE-x__`. No automatic renaming.

## `ai_memory/REPO_STATE.md` (both backends)

Live operational state only. Fields: `project_purpose`, `run_commands`, `test_commands`, `lint_commands`, `last_toa_run` (ISO 8601), `stack_spec_hash`, active items, `blocking_questions`; optional `capabilities:` (`extension-points.md`).
- Active items field: **keep the name the project already uses** — `active_issues` (number, label, branch, worktree) in existing GitLab projects, `active_work_items` otherwise.
- GitLab backend adds `gitlab_reachable` (true/false + timestamp).
- No `known_pitfalls` / `latest_decisions` (migrated to `ai_rules/` by `rules-curator`).
- Multi-team: written from the lead session only.

## Analyses and specs

- `ai_doc/ANALYSIS__<WI>__<slug>.md` (date in the header, not the name) — or `ai_doc/ANALYSIS__<slug>.md` without a WI.
- Multi-team specs: `docs/specs/F<n>-<slug>.md` (`spec-template.md`), linked to the WI.
