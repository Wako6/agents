# Rapport d'audit comparatif — Project Manager V1 (projet pilote) / V2 (claude-agents-v2) → V3 Unified

Date : 2026-10-26. Méthode : lecture intégrale des fichiers réels (aucune fonctionnalité supposée), exécution des tests de la V2 en bac à sable, vérification des mécanismes Claude Code dans la documentation officielle (code.claude.com, pages skills, sub-agents, memory, permissions, worktrees, consultées le 2026-10-26 par un agent de lecture ; citations à reconfirmer mot à mot avant usage contractuel).

## Sources auditées

| Nom | Emplacement | Contenu réel |
|---|---|---|
| **V1** — PM installé | projet pilote : `.claude/skills/project-manager/` (SKILL.md, references/runbook.md, session-brief.md, spec-template.md), `.claude/agents/` (7 agents), `CLAUDE.md`, `.claude/settings.json`, hooks `verify-gate`/`protect-files`, `ai_rules/` (5 entrées) | PM multi-équipes : registre = issues GitLab + labels d'état, sessions-feature en worktree, feature-lead, preuve de test liée à HEAD, contrôle S7 d'intégration, mode local GitLab |
| **V2** — kit candidat | `claude-agents-v2.zip` (57 fichiers, sha256 b516d0ae…) | PM générique converti de Codex : registre local Work Items (`WORK_ITEMS.md`, `WI_COUNTER.lock`), 3 skills, 11 agents + 4 optionnels, règles natives, `rules_sync.py`, `review-guard`, installateur/rollback, 51 tests |
| (référence) kit v1 générique | `claude-agents.zip` (24 fichiers) | ancêtre de la V2 ; remplacé par elle ; pris en compte pour la migration seulement |

## Inventaire par domaine

### Skills
- V1 : un skill `project-manager` (session lead uniquement, déclencheurs explicites), 3 références.
- V2 : `project-manager` (routage d'intention, auto-activation large), `project-problem-solver` (QUICK/DEEP), `project-memory-clean` (normal/force), 5 références, script `rules_sync.py`, hook `review-guard.sh`.
- Constat : V1 n'a ni protocole d'analyse ni protocole de nettoyage ; V2 n'a ni mode multi-équipes ni contrôle d'intégration.

### Agents
| Agent | V1 | V2 | Écart principal |
|---|---|---|---|
| explorer | FR, GitLab, `REPO_STATE` session lead only, `gitlab_reachable` | EN, ledger, crée `CLAUDE.md`/`@AGENT.md` | registre ; V2 modifierait `CLAUDE.md` |
| solution-architect | FR, `ANALYSIS__#NN` | FR, `ANALYSIS__<WI>` | quasi identiques |
| developer | FR, jamais commit/push, jamais `git stash` | EN, ledger | V1 plus strict |
| verifier | **sans Write**, note inline, `record-verification.sh` d'abord | **Write**, écrit sa note | V1 plus strict |
| rules-curator | **triage en deux temps** (propose → validation humaine → apply) | triage en un temps ; champs `Autoload`/`Paths`, contrôle de contradictions | V1 plus strict, V2 plus riche |
| django-reviewer / django-reviewer-analyst | inline, sans Write | Write + review-guard ; runtime via curl, demande « test credentials or tokens » | V1 plus strict ; V2 plus complet au runtime |
| feature-lead | oui (multi-équipes) | absent (« à définir ») | V1 seul |
| code-base-analyst, devops-engineer, backend/frontend-reviewer-analyst, memory-cleaner, 4 optionnels | absents | présents | V2 seul |
| Cascade guard | textuel | textuel + `disallowedTools: Agent, Skill` | V2 plus fort |

### Règles natives et `ai_rules/`
- V1 : `ai_rules/` (rédacteur unique `rules-curator`), aucune règle native `.claude/rules/`.
- V2 : `ai_rules/` + règles natives (globale inconditionnelle, projet à portée `paths:`, générées `ai-rules*.md` via `rules_sync.py --check/--write`).
- Contrôle : `rules_sync.py --check` sur `ai_rules/` du projet pilote → 5 entrées, 0 problème, 0 exportable (aucune entrée `Autoload`) : compatible sans effet.
- La règle globale V2 impose `WI-YYYYMMDD-BSLUG-###` : **contradiction** avec V1 (`#NN`) ; règles utilisateur et projet sont chargées sans priorité (doc) → à rendre neutre.

### Work Items, états, identifiants, réservation
- V1 : issues GitLab, `#NN`, un seul label d'état (`todo`/`doing`/`tests`/`review`/`blocked`), dépendances `Depends on`, déblocage sur verdict S7 **INTÉGRÉE** uniquement, fermeture par le PM. Décision durable `ai_rules` DEC-001 : « GitLab issues/labels are the task registry ».
- V2 : `WI-YYYYMMDD-BSLUG-###`, `WI_COUNTER.lock` (protocole anti-collision), `WORK_ITEMS.md`, `INDEX.md`, 8 statuts.
- Incompatibilité structurelle : deux registres. Les fusionner en un seul système imposerait un changement fonctionnel à l'un des deux → résolu par un **backend unique par projet** (voir arbitrages).

### Mémoire et reprise
- Communs : `ai_memory/REPO_STATE.md`, notes de rôle, `ai_doc/`, archivage 7 j / 30 j, migration `known_pitfalls`/`latest_decisions`.
- V1 : `active_issues`, `gitlab_reachable`, `PENDING_GITLAB.md` (mode local), REPO_STATE écrit en session lead seulement.
- V2 : `active_work_items`, `capabilities:`, `AGENT.md` + `CLAUDE.md @AGENT.md`.

### Git et GitLab
- V1 : branche depuis `origin/<intégration>`, MR draft vers `<intégration>`, **un accord par opération**, preuve PASS liée à HEAD (relancée après chaque commit), formes littérales (verify-gate), jamais `git stash`, jamais `cd` dans un worktree d'équipe, contrôle S7.
- V2 : « pas de commit/push/MR/merge sans accord » (formulation globale), forge optionnelle.

### Permissions, hooks, garde-fous
- V1 : `settings.json` (deny `git push --force`, `rm -rf`, `glab mr merge`, `Edit/Write(.claude/hooks/**)`…), hooks `verify-gate` (shadow) et `protect-files`, `policy.json`. **Constat confirmé par la documentation** : les règles `Write(path)` ne correspondent jamais (seules `Edit(path)`/`Read(path)` comptent) ; `protect-files` compense. Signalé, non modifié (hors périmètre).
- V2 : `review-guard` (PreToolUse) ; snippet `settings.kit.json`.
- **Défauts V2 trouvés** : `review-guard` autorise `env` (affiche l'environnement, donc d'éventuels secrets), `curl`/`http` avec toute méthode (écritures distantes), `wget` (écrit des fichiers), `find -delete`, `git branch -D` ; la V2 autorise aux reviewers l'outil Write (plus faible que V1).

### Erreurs et blocages
- Communs : `BLOCKED` = blocage + hypothèse + action ; `attempt_count ≥ 3` → escalade ; > 48 h → action.
- V1 : `blocked` remplace l'état et la note donne l'état à restaurer ; `GATE-DENY` → réécriture, jamais de contournement.

### Tests et livraison
- V1 : DoD avec preuve PASS sur HEAD poussé, MR draft, merge humain, S7, fermeture par le PM ; aucun test automatisé du PM lui-même (les hooks ont leur harnais).
- V2 : DoD ledger ; 51 tests (structure, YAML, review-guard, rules_sync, installateur).
- **Défauts V2 trouvés** : résidu A2 (`WI-YYYYMMDD-###` sans BSLUG) dans `verifier.md` et `memory-cleaner.md`, non détecté car le motif de test `###\b` ne correspond jamais ; test `grep -q` sur l'installateur sensible à SIGPIPE.

### Installation et retour arrière
- V1 : aucun installateur (fichiers versionnés dans le dépôt).
- V2 : installateur non destructif (manifeste, sauvegarde, conflits, `--merge`, `--force`, `--dry-run`, scope user/project) + `rollback.sh`.
- **Défauts V2 trouvés** : (1) écrit les fichiers NEW dans un dossier de skill existant étranger → **skill hybride** (ex. ancien `SKILL.md` du projet pilote + nouvelles références) ; (2) une installation interrompue n'est pas détectée (le manifeste « latest » reste l'ancien) ; (3) `rollback.sh` supprime tous les dossiers vides sous `skills/`, `agents/`, `rules/` (y compris des dossiers vides de l'utilisateur) ; (4) aucune vérification des dépendances, des droits ni de l'état git ; (5) installation `--scope user` d'un `project-manager` personnel **masque** celui d'un projet (doc : skills personnel > projet ; agents : projet > personnel).

## Conclusion d'audit

V1 et V2 sont deux lignées distinctes (multi-équipes GitLab vs mono-session ledger) partageant rôles et mémoire. La fusion sans régression exige : un registre unique choisi par projet, les garde-fous les plus stricts de chaque côté, l'isolement des spécificités du PoC dans un adaptateur, et un installateur qui ne peut ni masquer ni hybrider le PM existant. C'est l'architecture de la V3 (voir `MATRIX-V1-V2-V3.md`, `ARBITRATION-LOG.md`).
