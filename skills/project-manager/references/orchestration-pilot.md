# Orchestration pilote — débat Claude–Codex et deux équipes parallèles (`pmx`, ledger)

> **Pilote, opt-in.** Actif seulement si la configuration contient `orchestration.enabled: true` **et** `work_items.backend: "ledger"`. Sinon : `multi-team.md` (GitLab) ou délégation mono-session, inchangés. Lead session uniquement (cascade guard ; `pmx` refuse de tourner depuis un worktree lié). Implémente les interfaces I1, I2, I3 (variante ledger), I4, I6 (plafonds), I7 de `extension-points.md` — sans nouveau registre.

Outil : `python3 -I ${CLAUDE_SKILL_DIR}/scripts/pmx.py --root <repo> <commande>` — ci-dessous `pmx`.
Codes : 0 ok · 1 échec/refus · **2 décision humaine** · **3 échec critique (équipes arrêtées)** · **10 attente d'un agent externe** · 64 usage.

## Où vit l'état

| Donnée | Emplacement | Écrit par |
|---|---|---|
| Statuts, `attempt_count`, `parent`, `depends_on`, `session`, `worktree`, `files_probably_touched` | `ai_memory/WORK_ITEMS.md` (+ `WI_COUNTER.lock`, `INDEX.md`) — **registre unique** | `pmx` (lead) |
| Exécution technique (tours, PID, branches, commits, verdicts) | `ai_memory/runs/<WI parent>/run.json` + `events.jsonl` (append-only) | `pmx` ; les processus d'équipe n'écrivent que leurs résultats |
| Débat (contrat I1) | `ai_doc/DEBATE__<WI>__<slug>.md` + verbatim `ai_memory/runs/<WI>/debate/` | `pmx` |
| Décisions | `ai_doc/DECISIONS__<WI>.md` (journal) ; règle durable → proposition `DEC-` à `rules-curator` (deux temps) | `pmx` / manager |
| Notes de rôle | `ai_memory/YYYY-MM-DD__ROLE-developer|verifier__<WI>.md` | `pmx` (enregistre le rapport de l'équipe) |
| Revues croisées | `ai_doc/reviews/PEER__<WI>__<n>.md` | `pmx` |

`run.json` ne contient **aucun statut** de work item : la coordination fonctionnelle reste dans le registre.

## Flux (12 étapes) et gates

1. **Demande** → `pmx start --title … --request <fichier>` : réserve le WI parent (protocole ledger), ouvre le run.
2. **Débat** → `pmx debate next --run <WI>` : Claude puis Codex, lecture seule, transmission verbatim, marqueurs Claudex (`<<CONSENSUS>>`, `<<CONTINUE>>`, `<<WAIT_HUMAN>>`), **≤ `max_rounds` (3) tours**. Agent externe (`drop`) → code 10 : lancer un sous-agent **en lecture seule** (`Plan`/`Explore`) avec le prompt indiqué, enregistrer sa réponse verbatim : `pmx debate submit --side claude --file …`, puis `debate next`.
3. **Synthèse** automatique (contrat I1) : positions, accords, désaccords non résolus, questions, décision proposée.
4. **Arbitrage** : consensus sans désaccord ni question → `pmx decide --by consensus` ; sinon **code 2** → présenter les options à l'utilisateur (le manager ne tranche jamais) → `pmx decide --by human:<nom> --text …`.
5. **Plan** : le manager rédige `plan.json` (tâches : `key`, `title`, `team`, `files`, `depends_on`, `test_command`, `acceptance`, `details`) → `pmx plan submit` : valide champs, chemins sensibles, cycles, **collisions de fichiers entre tâches parallélisables**, calcule les vagues.
6. **Parallélisable** = même vague (aucune relation de dépendance) et fichiers disjoints.
7. **Gate « go »** : `pmx plan approve --by <nom>` après accord explicite → crée un WI enfant par tâche (`parent`, `depends_on`).
8. **Worktrees** : `pmx dispatch` crée une branche `pilot/<run>/<tâche>` + un worktree par tâche prête (dépendances `DONE` = intégrées), au plus `max_parallel` (2), une tâche par équipe.
9. **Exécution parallèle** : équipe processus (`codex-cli`, `claude-cli`, `cmd`) détachée ; équipe `drop` (sous-agent Claude) → code 10 : lancer le sous-agent avec le brief (`run_in_background`), il écrit son rapport puis le manager lance `pmx report`. `pmx wait` surveille : périmètre, collisions, fins, interruptions, tentatives.
10. **Collecte** : contrôle de périmètre, commit **local** de la branche d'équipe par `pmx`, note `developer` → `READY_FOR_VERIFICATION`.
11. **Vérification indépendante** : `pmx verify` (checkout détaché propre du commit livré, commandes de test exactes — rôle `verifier`) → `READY_FOR_REVIEW` ; puis **revue croisée** `pmx review run` (l'autre équipe, lecture seule) → triage `review-triage.md`.
12. **Livraison** : `pmx integrate --dry-run`, puis, **après accord humain explicite pour cette opération**, `pmx integrate --approved-by <nom>` : fusion **locale** dans `integration_branch` (jamais protégée), dans un worktree temporaire, tests sur l'arbre fusionné, `update-ref` conditionnel. WI enfants `DONE`, parent `READY_FOR_REVIEW`. Fusion vers `main` / push / MR : **humain**, hors pilote.

À tout moment : `pmx status` (format multi-team : coordination fonctionnelle / orchestration technique), `pmx evidence` (preuve de parallélisme : PID, intervalles, chevauchement), `pmx resume` (reprise), `pmx abort --reason …`.

## Circuit breakers

- Fichier hors périmètre, chemin sensible (secret, `.claude/`, hooks, settings, CI/production), suppression, ou même fichier modifié par deux équipes → **échec critique** : toutes les équipes arrêtées (process group), WI `BLOCKED`, worktrees conservés comme preuve, code 3. Équipe `drop` : fichier `STOP` écrit, le manager arrête le sous-agent.
- Échec ou interruption d'une équipe → tentative suivante si `auto_retry` et `attempts < max_attempts` (3) ; sinon `ESCALATED` (cohérent avec `attempt_count ≥ 3`).
- `verifier` FAIL → WI rouvert (nouvelle tentative) ou `ESCALATED`.
- Intégration : conflit ou tests rouges → branche d'intégration inchangée, arbitrage humain.

## Permissions (pilote)

- **Automatique** (dans les worktrees isolés uniquement) : lecture, écriture des fichiers du périmètre, exécution des tests, `git worktree add`, commits locaux sur `pilot/*` par `pmx`.
- **Toujours humain** : secrets/identifiants, permissions, hooks/garde-fous, branches protégées, suppressions, production, toute opération distante (push, MR, GitLab), toute fusion (y compris locale : `--approved-by`).
- Technique : Codex équipe = sandbox `workspace-write` (worktree seul, pas de réseau) ; Codex débat/revue = `read-only` ; Claude débat/revue = outils `Read,Grep,Glob` ou sous-agent sans outil d'écriture ; `claude-cli` équipe = `--settings` pilote (jamais la config globale). Le sous-agent Claude `drop` n'est **pas** sandboxé OS : consigne + contrôle a posteriori + arrêt.

## Ce que le pilote ne fait pas

Pas de variante `gitlab-issues` · pas de push/MR · pas de fusion vers une branche protégée · pas de lancement de sessions Desktop · pas de pilotage de l'UI Claudex (non interactif impossible) · pas d'écriture dans `ai_rules/`.
