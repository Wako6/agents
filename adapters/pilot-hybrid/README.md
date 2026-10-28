# Adaptateur pilote — mode hybride `host-agents+docker-verification` (opt-in, 3.2.0-rc1)

Claude Code et Codex CLI s'exécutent **sur l'hôte**, avec leurs authentifications existantes : aucune clé API, aucun identifiant transmis à Docker. Chacun travaille dans son worktree, avec ses permissions natives :
- `claude -p --settings settings.hybrid.json`, sans mode bypass ;
- Codex `--sandbox workspace-write` pour les équipes, `read-only` pour le débat et la revue.

**Toute vérification se fait en conteneur** : `pmx verify` et les tests de `pmx integrate` tournent sans réseau, sans HOME, sans identifiant, sur le checkout jetable seul.

`pmx` refuse de fonctionner dans ce mode si l'une de ces conditions n'est pas remplie :
- `verify_runner` docker ;
- `require_isolated_verification: true` dans la politique ;
- équipes, débat et reviewers sur l'hôte (pas d'équipe docker, pas de passerelle) ;
- réglages `claude-cli` explicites qui refusent `Bash(docker:*)`.

Quel que soit le mode, tout drapeau ou réglage de contournement des permissions natives est refusé.

À copier dans `<repo>/.claude/` d'un dépôt **pilote** :
- `project-manager.config.json` ;
- `settings.hybrid.json` ;
- `pmx.integration-policy.json`.

Puis adapter `verify_commands`, l'image de vérification (locale, épinglée par digest) et `worktree_root`. Limites et accès non empêchables : `docs/PILOT-HYBRID.md`.
