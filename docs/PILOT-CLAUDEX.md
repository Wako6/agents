# Pilote « Claudex + orchestration multi-agents » — candidat `3.0.0-rc1+pilot.claudex.1`

Statut : **candidat, non intégré au V3 officiel**. Rien n'est installé dans `~/.claude` ; le V3 publié (`Wako6/agents`) n'est pas modifié.

## Contenu du candidat (diff vs `3.0.0-rc1`)

| Fichier | Nature |
|---|---|
| `skills/project-manager/scripts/pmx.py` | **nouveau** — orchestrateur (Python stdlib) |
| `skills/project-manager/references/orchestration-pilot.md` | **nouveau** — protocole du manager |
| `adapters/pilot-claudex/` | **nouveau** — configuration, politique d'intégration, permissions pilote |
| `tests/pilot/` | **nouveau** — 13 tests, agents factices |
| `skills/project-manager/SKILL.md` | +1 ligne de chargement, +1 phrase de routage (opt-in) |
| `references/extension-points.md`, `project-config.md`, `work-items.md` | mentions du pilote (I1–I4, I6, I7 ; clé `orchestration` ; champs ledger) |
| `scripts/pm_config.py` | clé `orchestration` reconnue et validée (backend ledger exigé) |
| `tests/run.sh` | section 11 (tests pilote) |
| `VERSION` | `3.0.0-rc1+pilot.claudex.1` |

Sans `orchestration.enabled: true` dans un projet, le comportement est **identique** au V3.

## Utilisation (dépôt pilote uniquement)

1. Copier `adapters/pilot-claudex/project-manager.config.json` et `pmx.integration-policy.json` dans `<repo>/.claude/` ; ajuster `worktree_root` et `verify_commands`.
2. Dans la session lead, demander au manager (« pm, cadre et lance … ») : il suit `orchestration-pilot.md`. À la main :

```bash
PMX="python3 -I <kit>/skills/project-manager/scripts/pmx.py --root <repo>"
$PMX doctor
$PMX start --title "…" --request demande.md          # → WI parent
$PMX debate next --run <WI>                          # code 10 : tour Claude externe → sous-agent Plan, puis debate submit
$PMX decide --run <WI> --by consensus                # ou --by human:<nom> --text "…"
$PMX plan submit --run <WI> --file plan.json         # code 2 : gate « go »
$PMX plan approve --run <WI> --by <nom>
$PMX dispatch --run <WI>                             # code 10 : brief de l'équipe Claude à donner au sous-agent
$PMX wait --run <WI>                                 # surveillance ; code 3 = arrêt critique
$PMX report --run <WI> --task <clé> --status done --file <rapport>
$PMX verify --run <WI> && $PMX review run --run <WI>
$PMX integrate --run <WI> --dry-run
$PMX integrate --run <WI> --approved-by <nom>        # après accord explicite
$PMX status --run <WI> ; $PMX evidence --run <WI> ; $PMX resume --run <WI>
```

3. Tests : `python3 -I -B tests/pilot/test_pmx.py -v` (ou `tests/run.sh`, section 11).

## Limites connues

- **Claudex n'est pas piloté** : son UI exige un TTY ; `pmx` rejoue son protocole (verbatim, marqueurs, lecture seule). Les fonctions propres à Claudex (`/implement`, mémoire `.claudex/`, interventions en cours de tour) ne sont pas utilisées.
- **Équipe Claude `drop` non sandboxée** au niveau OS : consigne + contrôle de périmètre a posteriori (toutes les 3 s pendant `wait`, puis à la collecte) + arrêt. Une écriture hors périmètre peut exister quelques secondes avant détection ; elle n'est jamais commitée. `claude-cli` (avec `--settings` pilote) donnerait un contrôle par outil, mais n'a pas été exercé (CLI non authentifiée sur la machine du pilote).
- **Codex `read-only` peut lire tout fichier du compte** (limite Codex documentée par Claudex) : ne jamais lancer de débat sur un dépôt contenant ou côtoyant des secrets professionnels.
- **Synthèse du débat mécanique** : union des blocs JSON finaux ; un agent qui omet le bloc force l'arbitrage humain (conservateur).
- **Collisions de globs** : détection conservatrice (même répertoire = collision) ; préférer des chemins explicites.
- **Variante `gitlab-issues` non couverte** ; pas de push, pas de MR, pas de fusion vers une branche protégée — par conception.
- `pmx` n'est pas un démon : la surveillance n'a lieu que pendant `wait` / `tick` / `report` / `resume`.
- Deux échecs de `tests/run.sh` (« scripts exécutables », « modes 100755 ») existent **déjà** sur `3.0.0-rc1` (`pm_config.py`, `rules_sync.py` non exécutables en amont) ; non corrigés ici (hors périmètre).

## Retour arrière

| Ce qui a été fait | Comment revenir |
|---|---|
| Candidat (ce dépôt) | rien à défaire ailleurs : dépôt local isolé, sans remote. Supprimer le dossier suffit. |
| Intégration au V3 officiel (si validée plus tard) | revert du commit de la MR ; aucune donnée de projet n'en dépend tant qu'aucun projet n'active `orchestration.enabled`. |
| Activation dans un projet | retirer la clé `orchestration` (ou `enabled: false`) : le manager repasse au workflow V3 ; `WORK_ITEMS.md` reste un ledger V3 valide (champs supplémentaires ignorés). |
| Branches / worktrees d'un run | `git worktree list` puis, **avec accord humain**, `git worktree remove <chemin>` et `git branch -D pilot/<run>/…` (pmx ne supprime jamais rien). |
| Intégration locale | `git update-ref refs/heads/pilot/integration <ancien> <nouveau>` (commande exacte consignée dans `ai_doc/DECISIONS__<WI>.md`). |
