# Adaptateur d'exemple — GitLab multi-équipes

| Fichier | Destination dans le dépôt du projet |
|---|---|
| `project-manager.config.json` | `.claude/project-manager.config.json` |
| `project-manager.profile.md` | `.claude/project-manager.profile.md` (à adapter) |
| `referentiel.example.md` | à intégrer dans `CLAUDE.md` (tableau « Référentiel ») si le projet n'en a pas |

Installation : `install.sh --scope project --adapter gitlab-multi-team` (dépose la configuration et le profil ; jamais `CLAUDE.md`).
Vérification (lecture seule) : `python3 -I .claude/skills/project-manager/scripts/pm_config.py validate --root .`
Les fichiers déposés dans un dépôt sont des modifications du dépôt : branche, commit et MR selon les règles du projet.
