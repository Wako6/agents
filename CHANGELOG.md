# CHANGELOG

## 3.1.0-rc1 — orchestration multi-agents pilote (opt-in) — 2026-10-26

Inactif par défaut : sans `orchestration.enabled: true` (backend `ledger`) dans la configuration d'un projet, le comportement est celui de 3.0.0-rc1.

### Nouveau
- `scripts/pmx.py` (Python stdlib) et `references/orchestration-pilot.md` : demande → débat Claude–Codex (protocole Claudex rejoué, lecture seule, ≤ 3 tours) → décision (humaine si désaccord) → plan (collisions de fichiers, cycles, chemins sensibles) → gate « go » → deux équipes parallèles en worktrees `pilot/*` → collecte avec contrôle de périmètre → `verifier` indépendant → revue croisée → intégration **locale** lancée par l'humain dans son terminal (nom déclaré + phrase de confirmation saisie) et politique écrite.
- Adaptateurs d'agents : `codex-cli`, `claude-cli` (`--settings` pilote, jamais la configuration globale), `drop` (sous-agent de la session lead), `cmd` (tests).
- Registre unique conservé : statuts dans `WORK_ITEMS.md` (champs ledger `parent`, `depends_on`, `session`, `worktree`, `files_probably_touched`, `blocker`, `integrated`) ; exécution technique dans `ai_memory/runs/<WI>/` (journal append-only).
- Disjoncteurs : fichier hors périmètre, chemin sensible, suppression ou collision entre équipes → arrêt de toutes les équipes ; cause d'échec répétée → `ESCALATED` immédiat avec `ai_doc/ESCALATION__<WI>.md` ; plafond de 3 tentatives ; réouverture uniquement sur décision humaine (`pmx reopen --by human:<nom>`).
- `adapters/pilot-claudex/` : configuration, politique d'intégration (`local-only`), permissions pilote.
- `pm_config.py` reconnaît et valide la clé `orchestration` (backend `ledger` exigé).
- Tests : section 11 de `tests/run.sh` (29 tests, agents factices) ; `tests/pilot/live_claude_cli.py` (validation réelle, opt-in).

### Validé en réel (projets fictifs)
Cycle complet avec Codex CLI 0.162 et Claude Code 2.1 : débat clos par consensus, deux équipes simultanées (chevauchements mesurés de 49,5 s Codex ‖ sous-agent Claude, et 26,1 s `codex exec` ‖ `claude -p`), vérification, revues croisées, intégration locale ; refus de permissions de `claude -p` (secret, push, réseau, `.claude/`, écriture hors worktree, commit) ; arrêt d'un `claude -p` en cours sur dépassement de périmètre ; arrêt des relances sur erreur répétée.

### Corrigé
- `pm_config.py` et `rules_sync.py` en mode `100755` (oubli de `6e382fa` ; commit distinct, sans changement de contenu).

### Corrections issues de la revue de la PR (avant fusion)
- **C1 — intégrité des checkouts de vérification et d'intégration** : après les tests, `pmx` contrôle HEAD, fichiers modifiés ou ajoutés, références git et checkout principal, puis la suppression du checkout. Tout écart donne le verdict `INCONCLUSIVE` (jamais PASS) et passe le WI en `BLOCKED`, sans relance automatique. Le checkout est conservé et la preuve écrite dans `ai_memory/runs/<run>/integrity/`. À l'intégration, le candidat est figé avant les tests.
- **C2 — commandes de test** : seules les commandes de confiance écrites par l'humain dans la configuration (`verify_commands`, nouvelle clé `allowed_test_commands`) s'exécutent, toujours sans shell et sans métacaractères. Un plan rédigé par une IA ne peut que les citer mot pour mot. Le contrôle est refait à chaque exécution.
- **C3 — autorisation d'intégration** : `--approved-by` n'est plus qu'un nom déclaré. L'intégration réelle exige une phrase de confirmation saisie sur le terminal de contrôle. Elle est refusée sans terminal ou si des variables d'une CLI d'agent sont présentes. C'est un garde-fou contre une intégration déclenchée par un agent, pas une authentification.

### Limites
Voir `docs/PILOT-CLAUDEX.md` : Claudex (application TTY) non piloté ; confirmation d'intégration ≠ authentification ; les tests exécutent du code produit par les agents ; aucun sandbox OS côté Claude (refus par règles + détection et arrêt) ; Codex en lecture seule peut lire tout le compte ; pas de variante `gitlab-issues`, pas de push, MR ni fusion vers une branche protégée ; coûts non plafonnés.

## 3.0.0-rc1 — distribution GitHub (branche `claude`) — 2026-10-26

Même contenu fonctionnel que le candidat 3.0.0-rc1 ; adaptations de distribution :
- arborescence = racine de `~/.claude` : agents optionnels déplacés de `agents/optional/` vers `optional-agents/` (Claude Code découvre `agents/` récursivement) ; règle globale à plat dans `rules/` ; règle de projet déplacée vers `templates/project-rules/` ; installateur adapté ;
- `.gitignore` en liste blanche (données personnelles de `~/.claude` jamais suivies) ; `CLAUDE.md` utilisateur minimal ;
- installateur : détection du clone direct (« rien à installer ») ;
- adaptateur du projet pilote remplacé par l'exemple anonymisé `adapters/gitlab-multi-team/` ; références au projet pilote anonymisées ;
- README GitHub ; tests de distribution (clone simulé, liste blanche, configuration existante, mise à jour par `pull`, absence de données sensibles).

## 3.0.0-rc1 — 2026-10-26 (candidat, non installé)

Fusion V1 (PM du projet pilote) + V2 (claude-agents-v2). Détail : `docs/MATRIX-V1-V2-V3.md`.

### Conservé de V1
Mode multi-équipes (specs, brief de session, feature-lead), registre GitLab (labels d'état uniques), contrôle S7, mode GitLab injoignable, accord par opération, preuve liée à HEAD (via configuration), verifier et reviewers sans écriture, triage des règles en deux temps.

### Repris de V2
Routage d'intention, protocoles d'analyse (QUICK/DEEP) et de nettoyage mémoire, registre local Work Items, règles natives et `rules_sync.py`, cascade guard technique, agents code-base-analyst / devops / backend & frontend reviewers / memory-cleaner / optionnels, installateur et rollback, extensions détectées.

### Nouveau
Configuration de projet `pm-v3/1` + `pm_config.py` (détection, refus d'un second registre, référentiel sans copie) ; adaptateurs `generic` et `gitlab-multi-team` ; protocole et agent memory-cleaner conscients du backend ; interfaces I2, I5, I6, I7.

### Corrigé / durci (défauts V2)
Résidu A2 et test inopérant ; `review-guard` (env, HTTP en écriture, wget, find -delete, git branch -D) ; reviewers avec Write ; installateur : skill hybride, masquage d'un PM de projet, interruption non détectée, chemins protégés, dépendances, droits, état git ; rollback : suppression de dossiers vides limitée ; règle globale neutre vis-à-vis du backend ; snippet de permissions sans règles de stack ; django-reviewer sans demande de jetons.
