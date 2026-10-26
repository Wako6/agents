# Pilote « Claudex + orchestration multi-agents » — `3.1.0-rc1`

Statut : **pilote opt-in** (release candidate). Inactif tant qu'un projet ne déclare pas `orchestration.enabled: true` avec le backend `ledger` ; sinon le PM se comporte exactement comme en 3.0.0-rc1.

## Contenu (diff vs `3.0.0-rc1`)

| Fichier | Nature |
|---|---|
| `skills/project-manager/scripts/pmx.py` | **nouveau** — orchestrateur (Python stdlib) |
| `skills/project-manager/references/orchestration-pilot.md` | **nouveau** — protocole du manager |
| `adapters/pilot-claudex/` | **nouveau** — configuration, politique d'intégration, permissions pilote |
| `tests/pilot/` | **nouveau** — `test_pmx.py` (21 tests, agents factices, sans usage), `fake_agent.py`, `fixtures/` (rapports réels de Codex rejoués), `live_claude_cli.py` (validation réelle opt-in) |
| `skills/project-manager/SKILL.md` | +1 ligne de chargement, +1 phrase de routage (opt-in) |
| `references/extension-points.md`, `project-config.md`, `work-items.md` | mentions du pilote (I1–I4, I6, I7 ; clé `orchestration` ; champs ledger) |
| `scripts/pm_config.py` | clé `orchestration` reconnue et validée (backend ledger exigé) |
| `tests/run.sh` | section 11 (tests pilote) |
| `scripts/pm_config.py`, `scripts/rules_sync.py` | mode `100755` (commit distinct ; oubli de l'amont `6e382fa`) |
| `VERSION` | `3.1.0-rc1` |

Sans `orchestration.enabled: true` dans un projet, le comportement est **identique** au V3.

## Utilisation (dépôt pilote uniquement)

1. Copier `adapters/pilot-claudex/project-manager.config.json` et `pmx.integration-policy.json` dans `<repo>/.claude/` ; ajuster `worktree_root` et `verify_commands`. (`install.sh --adapter pilot-claudex` ne copie que `project-manager.config.json` : la politique d'intégration se copie à la main, et sans elle `pmx` refuse toute intégration.)
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

3. Tests : `python3 -I -B tests/pilot/test_pmx.py -v` (ou `tests/run.sh`, section 11) — agents factices, sans usage.
4. Validation réelle de `claude -p` (opt-in, consomme de l'usage ; CLI connectée par l'humain au préalable) :
   `PMX_LIVE=1 python3 -I -B tests/pilot/live_claude_cli.py <dossier-neuf>` → `RESULTS.md` / `RESULTS.json`.

## Relances

Chaque échec reçoit une signature normalisée (type, code de sortie, fichiers produits, identifiants, prose sans bruit). Une cause qui se répète → `ESCALATED` immédiat + `ai_doc/ESCALATION__<WI>.md` ; une cause nouvelle → relance, plafond 3 conservé. Seul `pmx reopen --by human:<nom>` rouvre une escalade.

## Limites connues

- **Claudex n'est pas piloté** : son UI exige un TTY ; `pmx` rejoue son protocole (verbatim, marqueurs, lecture seule). Les fonctions propres à Claudex (`/implement`, mémoire `.claudex/`, interventions en cours de tour) ne sont pas utilisées.
- **Équipe Claude `drop` non sandboxée** au niveau OS : consigne + contrôle de périmètre a posteriori (pendant `wait`, puis à la collecte) + arrêt. Préférer **`claude-cli`** (validé en réel avec `tests/pilot/live_claude_cli.py` : scénarios permissions, brief, fichiers, codes de sortie, parallélisme avec Codex, arrêt sur dépassement) : refus par outil via `--settings` (secrets, `.claude/`, push, réseau, écriture hors worktree, commit), en plus du contrôle de périmètre.
- **`claude-cli` n'est pas un sandbox OS** non plus : les refus viennent des règles de permission de Claude Code ; une commande `Bash` autorisée (ex. `node --test`) peut écrire des effets de bord hors périmètre — ils sont détectés et arrêtés par `pmx`, pas empêchés.
- **Rapprochement des causes rédigées par un agent** : heuristique (recouvrement de mots ≥ 0,5 à identifiants, code et fichiers identiques). Deux explications très différentes d'une même cause comptent comme deux causes : au pire une tentative de plus, jamais au-delà du plafond de 3.
- **Codex `read-only` peut lire tout fichier du compte** (limite Codex documentée par Claudex) : ne jamais lancer de débat sur un dépôt contenant ou côtoyant des secrets professionnels.
- **Synthèse du débat mécanique** : union des blocs JSON finaux ; un agent qui omet le bloc force l'arbitrage humain (conservateur).
- **Collisions de globs** : détection conservatrice (même répertoire = collision) ; préférer des chemins explicites.
- **Variante `gitlab-issues` non couverte** ; pas de push, pas de MR, pas de fusion vers une branche protégée — par conception.
- `pmx` n'est pas un démon : la surveillance n'a lieu que pendant `wait` / `tick` / `report` / `resume`.
- Le pilote n'a été exercé que sur des projets **fictifs** (Node, sans dépendance) ; aucun projet réel ni GitLab.
- Coûts non mesurés ni plafonnés par `pmx` (I6).

## Retour arrière

| Ce qui a été fait | Comment revenir |
|---|---|
| Version du kit | revenir à `3.0.0-rc1` (revert de la fusion, ou `rollback.sh --dest <DIR>` d'une installation) ; aucune donnée de projet n'en dépend tant qu'aucun projet n'active `orchestration.enabled`. |
| Activation dans un projet | retirer la clé `orchestration` (ou `enabled: false`) : le manager repasse au workflow V3 ; `WORK_ITEMS.md` reste un ledger V3 valide (champs supplémentaires ignorés). |
| Branches / worktrees d'un run | `git worktree list` puis, **avec accord humain**, `git worktree remove <chemin>` et `git branch -D pilot/<run>/…` (pmx ne supprime jamais rien). |
| Intégration locale | `git update-ref refs/heads/pilot/integration <ancien> <nouveau>` (commande exacte consignée dans `ai_doc/DECISIONS__<WI>.md`). |
