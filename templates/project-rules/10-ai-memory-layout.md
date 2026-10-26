---
paths:
  - "ai_memory/**"
  - "ai_rules/**"
  - "ai_doc/**"
  - "AGENT.md"
  - "STACK_SPEC.md"
---

# Formats des fichiers de mémoire du dépôt (V3)

Chargée uniquement quand un de ces fichiers est lu ou édité. Le registre est celui de `.claude/project-manager.config.json` (`ledger` ou `gitlab-issues`) ; `<WI>` = `WI-YYYYMMDD-BSLUG-###` ou `#NN`.

- `ai_memory/REPO_STATE.md` — `project_purpose`, `run_commands`, `test_commands`, `lint_commands`, `last_toa_run` (ISO 8601), `stack_spec_hash`, éléments actifs (garder le nom existant : `active_issues` en GitLab, `active_work_items` sinon), `blocking_questions` ; GitLab : `gitlab_reachable` ; optionnel `capabilities:`. Pas de `known_pitfalls` ni `latest_decisions` (migrés dans `ai_rules/`).
- Registre `ledger` uniquement : `ai_memory/WI_COUNTER.lock` (une ligne `BSLUG=WI-YYYYMMDD-BSLUG-###` par slug, mise à jour de sa ligne seulement), `ai_memory/WORK_ITEMS.md` (statut, `attempt_count`, propriétaires, liens), `ai_memory/INDEX.md` (`WI-… | titre | statut | rôles | notes` ; `ANALYSIS | <WI> | <chemin> | <titre>`). Ces fichiers n'existent pas dans un projet GitLab.
- Registre `gitlab-issues` : `ai_memory/PENDING_GITLAB.md` = actions à rejouer quand GitLab est injoignable.
- Notes de rôle — `ai_memory/YYYY-MM-DD__ROLE-<rôle>__<WI>.md` : Work item | Role | Status | Scope | Files touched | Evidence | Decisions | Open blockers | Next actions | Recall hints (+ `Proposed Rules` pour developer et solution-architect).
- `ai_rules/*.md` — entrées `### <ID> — <titre>` avec `Scope / Origin / Added / Verified` (+ `Deprecated`, `Autoload: yes|no`, `Paths:`), IDs `CONV-|DEC-|PIT-|SEC-|PERF-###`, `INDEX.md` à jour, dépréciées préfixées `# DEPRECATED`. Rédacteur unique : `rules-curator`.
- `ai_doc/ANALYSIS__<WI>__<slug>.md` — date dans l'en-tête ; rapports de revue `ai_doc/reports/<KIND>_REVIEW_REPORT__<WI>.md`.
- `AGENT.md` (si le projet en a un) — carte de lecture importée par `CLAUDE.md` via `@AGENT.md`, sans duplication des règles.
