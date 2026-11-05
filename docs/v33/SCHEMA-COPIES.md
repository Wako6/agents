# V3.3-A2 — Schéma des copies minimisées (`pm-cockpit-copy/1`)

Le serveur du cockpit lit uniquement ces copies, jamais un run. L'extracteur manuel `cockpit/extract.py` les produit, en lecture seule sur ses sources, et le serveur ne l'utilise pas. La règle exécutable est `SCHEMA` dans `cockpit/adapter.py` : tout champ absent de ce schéma fait refuser le fichier entier.

## Types

| Type | Règle |
|---|---|
| Pseudonyme | Préfixe et 10 caractères hexadécimaux : `P` projet, `R` run, `T` tâche, `E` équipe, `W` work item, `C` commit, `H` humain, `A` acteur |
| Horodatage | ISO 8601 strict |
| Mot | `[A-Za-z0-9_.-]{1,40}`, sans texte libre |
| Entier, booléen | Types stricts |

Les pseudonymes reposent sur une clé aléatoire tirée à chaque extraction, jamais écrite. Ils sont propres à chaque run : deux copies ne se recoupent pas.

## Champs

| Bloc | Champs |
|---|---|
| Racine | `schema`, `captured`, `sources`, `events_malformed` |
| `project` | `id` |
| `run` | `id`, `created`, `updated`, `base` |
| `debate` | `status`, `turns` (nombre), `needs_human` |
| `decision` | `by`, `ts` |
| `plan` | `status`, `approved_by`, `approved`, `waves` |
| `teams[]` | `id`, `adapter` |
| `tasks[]` | `id`, `wi`, `status`, `team`, `depends_on`, `files` (nombre), `budget_base`, `commit`, `attempts[]`, `verify`, `review` |
| `attempts[]` | `n`, `adapter`, `started`, `ended`, `result`, `settled`, `tracked` (booléen) |
| `verify` | `verdict`, `commit`, `runner`, `tests`, `failed`, `integrity_problems` (nombre), `ts` |
| `review` | `verdict`, `by`, `commit`, `uncovered` (nombre), `ts` |
| `helpers[]` | `kind`, `ended`, `tracked` |
| `stop_evidence[]` (non produit à ce stade) | `kind`, `state`, `ts`, `task`, `attempt`, `problems` (nombre), `attempts[]` : `task`, `attempt`, `before`, `populated_after`, `killed`, `term` et `errors` (nombres) |
| `stop` | `state`, `reason_kind` (catégorie), `ack_by`, `ack_ts`, `problems` (nombre), `started`, `ended` |
| `integration` | `commit`, `by`, `ts`, `merged` (nombre) |
| `events[]` | `seq`, `ts`, `kind`, `task`, `attempt`, `verdict`, `result` |

## Exclu de toute copie

Titres, décisions, propositions, motifs, chemins, branches, worktrees, fichiers de tâche, commandes, sorties de test, prompts, rapports, journaux, `os_user`, `tty`, `pid`, `unit`, nom de cgroup, identités, noms d'équipe et de tâche.

Les sorties de test sont lues par l'extracteur seulement pour en tirer deux nombres, et ne sont pas conservées.

## Sources

| Source | État |
|---|---|
| `run.json`, `events.jsonl` | Autorisées |
| `WORK_ITEMS.md` | Autorisée avec `--with-work-items`, pour les seuls statuts des work items du run |
| `stop-evidence.jsonl` | **Jamais lue** : extraction préparée, testée sur données synthétiques, reliée à aucune option |

Sans `--with-work-items`, le statut des tâches s'affiche « Inconnu », et la copie le signale.

## `stop-evidence.jsonl` : préparé, non branché

**Utilité :** prouver l'arrêt des cgroups, pour chaque fin de tentative ou arrêt critique. La preuve ne change jamais le verdict d'arrêt du run.

| Champ gardé | Forme |
|---|---|
| `kind`, `state` | Mot |
| `ts` | Horodatage |
| `task` | Pseudonyme |
| `attempt` | Entier |
| `attempts[].before`, `populated_after`, `killed` | Booléen |
| `attempts[].term`, `errors`, `problems` | **Nombre d'éléments seulement** |

**Jamais conservés :** `reason`, texte de `problems` et d'`errors`, `cgroup`, `unit`, `dir`, `pid`, `pid_start`, `alive_seen`.

## `WORK_ITEMS.md`

**Utilité :** afficher le statut réel des tâches.

| Champ gardé | Forme |
|---|---|
| Identifiant du work item | Lu pour relier le statut à la tâche, jamais conservé |
| `status` | Valeur connue, sinon le marqueur `UNRECOGNIZED` ; absent si le work item n'y figure pas |

**Stratégie :** analyse ligne à ligne de l'en-tête `### <id>` et de la ligne `- status:`. Le titre et tous les autres champs (`blocker`, `session`, `links`, `worktree`, `restore_state`…) sont ignorés sans être conservés.
