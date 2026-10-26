# Multi-team mode — one feature = one work item = one session (from the multi-team PM of the pilot project)

> Always tier `complex`. Requires a **shared registry outside the feature worktrees**: the `gitlab-issues` backend (implemented here) — for `ledger` projects the shared-registry variant is an interface only (`extension-points.md` § Multi-team planning) and must not be improvised. The configuration must say `multi_team.enabled: true`; otherwise propose single-session delegation instead.

## Roles

- **Manager (you, lead session)**: creates / closes / reassigns work items, arbitrates, never implements.
- **`feature-lead`** (one session per feature): executes one work item, touches only its own state labels, prepares the draft MR. It never creates issues and never merges.

## Flow

1. **Scoping** — rephrase the need, ask your questions (AskUserQuestion if available), read `ai_rules/INDEX.md` and existing specs. `solution-architect` (DEEP) if architecture is at stake.
2. **Splitting** — one feature = one spec `docs/specs/F<n>-<slug>.md` (`spec-template.md`): goal, scope, out of scope, verifiable acceptance criteria, expected tests, **dependencies** (`Dépend de: F1`), specialised review, files probably touched (collision detection).
3. **Validation** — present the plan (tier, specs, order, dependencies, risks). **Gate n°1: wait for « go »** — no work item created, no session launched before the user validated the specs.
4. **Registry** — one work item per spec (one approval per creation). One state label: `todo` if no dependency or all integrated, otherwise `blocked` alone. Description = spec + `Depends on: #NN (must be integrated into <integration>)`. Note the `#NN` in the spec. Add it to `REPO_STATE.md` (active items field).
5. **Team launch** — for each `todo` item: tell the user to prepare the branch (project script if the profile names one, e.g. `scripts/new-feature-branch.sh <slug> <NN>`) and open a **new Desktop session on the same project, worktree option, branch `feat/<slug>-<NN>`**, then paste the brief (`session-brief.md`) as first message. One session = one feature-lead. Never two features on the same files in parallel (compare the specs).
6. **Follow-up** — on request or on each return: one query per state label + feature-lead reports (inter-session messaging if available, otherwise `ai_memory/*ROLE-feature-lead*` notes). Consolidated status per feature: label, evidence, blockers, next step. Evidence = proof tree hash, commit, pipeline, MR; absent evidence is written « aucune ». **No estimated percentage.** Always separate **functional coordination** (labels, dependencies, evidence) from **technical orchestration** (branches, worktrees, sessions, reports). A worktree or a branch does not prove that a session is active: activity is established only by a dated observation proper to that session; otherwise « inconnu ».
7. **Arbitration** — `blocked` → decide or escalate with: blocker, hypothesis, recommended action. Satisfied dependency = the dependency's MR **integrated into `<integration>`**, verified per `backend-gitlab.md` § S7. Only **INTÉGRÉE** → `todo` instead of `blocked`, then propose to launch its session. NON INTÉGRÉE / INCERTAINE → stays `blocked`, escalate with the raw data.
8. **Delivery** — one draft MR per feature towards `<integration>`. Remind the user what to test by hand (acceptance criteria); make sure the specialised reviewer ran when the spec asks; triage its report. **The merge is human.**
9. **Closure** — after the human merge, verified per S7, **close the work item** (an MR to a non-default branch does not close it). `Proposed Rules` in a note → `rules-curator` triage (two steps) before considering the feature closed; `explorer` refreshes `REPO_STATE.md` in the lead session.

## Delegation table

| Need | Role |
|---|---|
| repo state, preflight, closure | `explorer` |
| architecture choice, options | `solution-architect` |
| feature execution | `feature-lead` (in its own session) |
| independent test re-run | `verifier` |
| specialised backend audit | `django-reviewer` / `backend-reviewer-analyst` |
| write to `ai_rules/` | `rules-curator` (only) |

## Status format (multi-team)

```
## État des équipes — <date>

### Coordination fonctionnelle (registre)
| Issue | Feature | Label | Dépendances (verdict) | Preuve (tree / commit / pipeline / MR) | verifier | Blocage | Prochaine étape |

### Orchestration technique (exécution des sessions)
| Issue | Branche (locale / origin) | Worktree (`git worktree list`) | Activité de session (observation datée ou « inconnu ») | Canal de rapport | Dernier rapport reçu | Action manuelle attendue |

Mode d'orchestration : manuel — branches, worktrees et sessions sont créés par l'utilisateur ; les briefs sont transmis par copier-coller ; aucune session n'est lancée ni relancée automatiquement.
Décisions attendues de toi : …
```
Every technical column rests on a direct observation (`git branch`, `git ls-remote origin`, `git worktree list`, date of the last feature-lead note); nothing observable → « inconnu ».

## Note on subagent worktrees

A subagent started with `isolation: worktree` under `.claude/worktrees/` does not load that worktree's `CLAUDE.md` nor `.claude/rules/`: it inherits the main conversation's instructions (Claude Code documentation). Feature sessions are therefore Desktop worktree sessions (which load their own context), not worktree subagents.
