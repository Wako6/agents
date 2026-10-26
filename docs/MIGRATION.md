# Migration vers le Project Manager V3

## Depuis le PM installé dans le projet pilote (V1)

Préalable : décisions H1 et H2 (`ARBITRATION-LOG.md`). Rien ne se fait automatiquement.

1. **Lot dédié** dans le dépôt : branche `chore/pm-v3` depuis `origin/<intégration>` (après les lots en cours du projet).
2. **Préflight** : arbre propre, preuve PASS, mode shadow, aucun worktree d'équipe actif sur une feature en cours (sinon reporter).
3. **Installation** (humain ou agent selon la politique du dépôt — les fichiers `.claude/skills` et `.claude/agents` ne sont pas protégés par les hooks, mais ce sont des fichiers de workflow) :
   `install.sh --scope project --adapter gitlab-multi-team --with-rules --dry-run` → relire le plan ; puis selon H2 :
   - skill + adaptateur seulement : `--merge`, puis remplacer à la main le dossier `.claude/skills/project-manager/` par la version V3 (le dossier existant est une **unité en conflit** : l'installateur n'y écrit rien sans `--merge/--force`) ;
   - remplacement complet : `--force` (sauvegardes dans `.claude/.project-manager-v3-kit/`).
4. **Contrôles** : `pm_config.py validate --root .` (doit lire le projet, la branche d'intégration et les labels d'état depuis `CLAUDE.md`) ; `git diff --stat` limité à `.claude/skills/project-manager/`, `.claude/agents/`, `.claude/rules/`, `.claude/project-manager.*` ; hooks, `settings.json`, `policy.json`, `CLAUDE.md` inchangés ; harnais des hooks inchangé ; Django.
5. Ce qui **ne change pas** pour l'équipe : issues/labels, `#NN`, notes `__#NN.md`, `REPO_STATE.md` (`active_issues`), `PENDING_GITLAB.md`, specs, brief de session, S7, accords, verify-gate.
6. Ce qui **change** : routage d'intention, protocoles d'analyse et de nettoyage disponibles, `rules-curator` avec champs natifs, reviewers bornés par hook, `django-reviewer` enrichi.
7. Commit, preuve sur HEAD, push, MR draft, merge humain, S7 : accords distincts.

## Depuis la V2 (`claude-agents-v2`) ou le kit v1 générique

- Fichiers de projet : `ai_memory/` (ledger `WORK_ITEMS.md`, `WI_COUNTER.lock`, `INDEX.md`), `ai_rules/`, `ai_doc/`, `AGENT.md`, `STACK_SPEC.md` lus tels quels ; la détection classe le projet en `ledger` (compatible). Écrire `adapters/generic/project-manager.config.json` dans le projet pour figer le choix.
- `/project-problem-solver`, `/project-memory-clean` : remplacés par les intentions du PM (« analyse… », « nettoie la mémoire »).
- `django-reviewer-analyst` → `django-reviewer`.
- Reviewers et verifier : rapports et notes rendus inline, enregistrés par le PM (mêmes chemins qu'en V2, suffixés `__<WI>`).
- Installation V2 dans `~/.claude` : ses fichiers n'ont pas de manifeste V3 → conflits ; procédure : `rollback.sh` de la V2 (avec son manifeste), puis installation V3 ; ou `--merge` pour comparer.
- Notes au format défectueux `**ROLE-**` : laissées telles quelles, lisibles.

## Coexistence

Un même poste peut avoir des projets `ledger` et des projets `gitlab-issues` : le choix est par projet. Ne jamais installer la V3 dans `~/.claude` tant qu'un projet utilisé garde un `project-manager` différent dans son dépôt (H1).
