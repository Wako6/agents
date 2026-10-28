# Adaptateur pilote — isolation Docker des équipes (`pmx`, opt-in)

Variante de `pilot-claudex` dont les deux équipes tournent chacune dans un conteneur dédié :
- utilisateur non-root ;
- racine en lecture seule ;
- `cap-drop ALL` et `no-new-privileges` ;
- réseau `none` ;
- limites CPU, mémoire et processus ;
- seul le worktree de l'équipe monté.

Référence : `docs/PILOT-DOCKER.md`.

À n'installer que dans un dépôt pilote :
- `project-manager.config.json` → `<repo>/.claude/project-manager.config.json`. Remplacer l'image (**locale**, jamais téléchargée par pmx), `argv`, `worktree_root`, `verify_commands` et `allowed_test_commands`.
- `pmx.integration-policy.json` → `<repo>/.claude/pmx.integration-policy.json`.

Prérequis : Docker joignable par l'utilisateur qui lance `pmx` (session lead). Aucun conteneur n'a accès à Docker.

Statut : validé avec des agents factices uniquement. Un agent réel (Claude, Codex) dans un conteneur sans réseau ne peut pas joindre son API : voir les limites.
