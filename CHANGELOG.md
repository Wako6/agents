# CHANGELOG

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
