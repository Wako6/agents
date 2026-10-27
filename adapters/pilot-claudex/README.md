# Adaptateur pilote — Claudex / orchestration multi-agents (`pmx`)

Pilote opt-in : débat Claude–Codex borné (protocole Claudex), deux équipes parallèles en worktrees, vérification indépendante, revue croisée, intégration **locale** contrôlée. Référence : `skills/project-manager/references/orchestration-pilot.md`.

À n'installer que dans un dépôt pilote :
- `project-manager.config.json` → `<repo>/.claude/project-manager.config.json` (adapter `worktree_root`, `verify_commands` et, si besoin, `allowed_test_commands` : seules commandes de test que pmx exécutera, sans shell)
- `pmx.integration-policy.json` → `<repo>/.claude/pmx.integration-policy.json`
- `settings.pilot.json` : à passer à l'adaptateur `claude-cli` (`"settings": ".claude/settings.pilot.json"`) ; jamais dans la configuration globale.

Adaptateurs : `codex-cli` (Codex CLI ≥ 0.162), `claude-cli` (`claude -p`, compte connecté), `drop` (sous-agent de la session lead, échange par fichiers), `cmd` (commande arbitraire, utilisée par les tests).
