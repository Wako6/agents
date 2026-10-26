# Tests et résultats

Commande : `tests/run.sh` (bac à sable : HOME jetable, dépôts jetables, faux serveur GitLab local). Option `COMPAT_REPO=<projet>` : contrôles supplémentaires sur une **copie** d'un projet réel (lecture seule).

Résultats de la distribution : voir `RAPPORT_DISTRIBUTION.md` fourni avec l'archive (sections, nombre de tests, exécutions).

| Section | Nature |
|---|---|
| 1. Structure du kit (skill unique, frontmatter, références, cascade guard, agents sans écriture, routage, statuts, garde-fous, triage en deux temps) | statique |
| 2. review-guard durci (autorisations, refus Bash, refus des outils d'écriture) | exécution du hook |
| 3. Règles natives et `rules_sync` | exécution des scripts |
| 4. Configuration de projet et détection du registre | exécution de `pm_config.py` |
| 5. Installateur et rollback | exécution en bac à sable |
| 6. Tests négatifs : conflit de noms, installation existante, permissions, état git, dépendance manquante, reprise interrompue | exécution en bac à sable |
| 7. Scope projet et adaptateur | exécution en bac à sable |
| 8. Compatibilité : projet GitLab multi-équipes synthétique (+ copie d'un projet réel si `COMPAT_REPO`) | exécution sur fixture |
| 9. Workflow GitLab simulé (create → doing → blocked → close) | glab contre faux serveur local |
| 10. Distribution : arborescence `~/.claude`, liste blanche `.gitignore`, clone simulé, configuration existante, mise à jour par `pull`, rollback `--all`, absence de données sensibles, `~/.claude` réel intact | exécution en bac à sable |

**Ces tests sont statiques ou simulés : ils ne valident pas le chargement réel dans une session Claude Code** (voir `INSTALL.md` § Vérification) ni un GitLab réel.
