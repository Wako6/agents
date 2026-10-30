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
5. **Plan** : le manager rédige `plan.json` (tâches : `key`, `title`, `team`, `files`, `depends_on`, `test_command`, `acceptance`, `details`) → `pmx plan submit` : valide champs, chemins sensibles, cycles, **collisions de fichiers entre tâches parallélisables**, calcule les vagues. `test_command` doit être **mot pour mot** une commande de confiance déclarée par l'humain dans la configuration (`verify_commands` ou `allowed_test_commands`) ; un plan ne peut pas en introduire. Commandes exécutées **sans shell** : `;`, `&`, `|`, `$`, backquote, redirections, parenthèses, accolades, `\` et retours à la ligne sont refusés (une commande par entrée). Le contrôle est refait à chaque `verify` / `integrate` (l'état du run n'est pas une source de confiance).
6. **Parallélisable** = même vague (aucune relation de dépendance) et fichiers disjoints.
7. **Gate « go »** : `pmx plan approve --by <nom>` après accord explicite → crée un WI enfant par tâche (`parent`, `depends_on`).
8. **Worktrees** : `pmx dispatch` crée une branche `pilot/<run>/<tâche>` + un worktree par tâche prête (dépendances `DONE` = intégrées), au plus `max_parallel` (2), une tâche par équipe.
9. **Exécution parallèle** : équipe processus (`codex-cli`, `claude-cli`, `cmd`) détachée ; équipe `drop` (sous-agent Claude) → code 10 : lancer le sous-agent avec le brief (`run_in_background`), il écrit son rapport puis le manager lance `pmx report`. `pmx wait` surveille : périmètre, collisions, fins, interruptions, tentatives.
10. **Collecte** : contrôle de périmètre, commit **local** de la branche d'équipe par `pmx`, note `developer` → `READY_FOR_VERIFICATION`.
11. **Vérification indépendante** : `pmx verify` (checkout détaché propre du commit livré, commandes de test de confiance — rôle `verifier`) → `READY_FOR_REVIEW` ; puis **revue croisée** `pmx review run` (l'autre équipe, lecture seule) → triage `review-triage.md`. Avec `verify_runner` docker, chaque commande tourne dans un conteneur isolé (sans réseau, sans HOME, sans secret, checkout seul). Une vérification impossible ou interrompue est `INCONCLUSIVE` et bloque, sans jamais se replier sur l'hôte. Sans `verify_runner`, les tests s'exécutent sur l'hôte : ce n'est **pas** isolé, et le manager doit le dire à l'utilisateur. Après les tests, `pmx` contrôle l'intégrité : HEAD du checkout inchangé, aucun fichier modifié ou ajouté (hors `.gitignore`), références git et checkout principal inchangés, checkout supprimé. Tout écart → verdict **`INCONCLUSIVE`** (jamais PASS), WI `BLOCKED`, checkout **conservé** et preuve écrite dans `ai_memory/runs/<run>/integrity/`, code 2, aucune relance automatique : présenter les écarts à l'utilisateur ; seul `pmx reopen --by human:<nom>` relance.
12. **Livraison** : le manager lance `pmx integrate --dry-run` et présente le résultat. L'intégration réelle est lancée **par l'humain, dans son propre terminal** : `pmx integrate --approved-by <nom>`, puis saisie de la phrase `integrer <commit>` affichée. Le manager ne la lance pas : depuis l'outil Bash d'un agent (pas de terminal, variables `CLAUDECODE` / `CODEX_SANDBOX`…), `pmx` refuse avec le code 2. Effet : fusion **locale** dans `integration_branch` (jamais protégée), dans un worktree temporaire, candidat figé avant les tests, tests et contrôle d'intégrité sur l'arbre fusionné, `update-ref` conditionnel. WI enfants `DONE`, parent `READY_FOR_REVIEW`. Fusion vers `main` / push / MR : **humain**, hors pilote.

À tout moment : `pmx status` (format multi-team : coordination fonctionnelle / orchestration technique), `pmx evidence` (preuve de parallélisme : PID, intervalles, chevauchement), `pmx resume` (reprise), `pmx abort --reason …`.

## Circuit breakers

- Fichier hors périmètre, chemin sensible (secret, `.claude/`, hooks, settings, CI/production), lien symbolique, fichier spécial (FIFO, socket, périphérique), suppression, ou même fichier modifié par deux équipes → **échec critique** : toutes les équipes arrêtées (process group), WI `BLOCKED`, worktrees conservés comme preuve, code 3. Équipe `drop` : fichier `STOP` écrit, le manager arrête le sous-agent.
- Échec d'une équipe ou `verifier` FAIL → **signature de cause** normalisée (type : `exit-N`, `reported-blocked`, `no-changes`, `interrupted`, `timeout`, `verifier-fail` ; texte sans horodatages, SHA, PID, durées, chemin du worktree de la tentative).
- **Même cause qu'un échec antérieur → `ESCALATED` immédiatement**, sans attendre le plafond. Même cause = même type, même code de sortie, mêmes fichiers produits, mêmes identifiants (tests, chemins, valeurs), et une prose identique ou proche (recouvrement ≥ 0,5, score consigné). Une différence objective n'est jamais masquée.
- Cause nouvelle → nouvelle tentative si `auto_retry`, dans la limite de `max_attempts` (3).
- Toute escalade écrit `ai_doc/ESCALATION__<WI>.md` : tentatives, signatures, codes, fichiers, extraits de rapport, journaux. Seul `pmx reopen --by human:<nom> --reason …` rouvre le WI ; `dispatch`, `wait`, `tick` et `resume` ne le relancent jamais.
- Intégration : conflit, tests rouges, écart d'intégrité ou confirmation absente → branche d'intégration inchangée, arbitrage humain (checkout conservé en cas d'écart d'intégrité).

## Permissions (pilote)

- **Automatique** (dans les worktrees isolés uniquement) : lecture, écriture des fichiers du périmètre, exécution des tests, `git worktree add`, commits locaux sur `pilot/*` par `pmx`.
- **Toujours humain** : secrets/identifiants, permissions, hooks/garde-fous, branches protégées, suppressions, production, toute opération distante (push, MR, GitLab), toute fusion (y compris locale : confirmation saisie au terminal de l'humain ; `--approved-by` n'est qu'un nom déclaré, pas une preuve), toute nouvelle commande de test (`allowed_test_commands`).
- **Profil hybride recommandé** (`orchestration.mode = "host-agents+docker-verification"`, exemple `adapters/pilot-hybrid/`).
  - Claude Code et Codex tournent sur l'hôte avec leurs authentifications existantes ; leurs outils sont confinés au worktree par leurs sandbox natifs (`confinement: native`, réglages imposés par `pmx`, préflight avant tout agent).
  - Toute vérification se fait en conteneur, et `pmx` refuse de fonctionner si ce n'est pas garanti. Les accès que les CLI gardent sur l'hôte sont listés dans `docs/PILOT-HYBRID.md` : les présenter à l'utilisateur.
  - Ne jamais ajouter de drapeau de contournement : `pmx` le refuse.
- Adaptateur `docker` (opt-in, **expérimental**) :
  - un conteneur par équipe, sans réseau, non-root, racine en lecture seule, `cap-drop ALL`, `no-new-privileges`, limites CPU, mémoire et processus ;
  - seul le worktree de l'équipe est monté (son `.git` en lecture seule) ;
  - configuration revérifiée sur le conteneur créé, avant démarrage ;
  - `pmx` crée, arrête et supprime le conteneur, et garde la preuve `container-*.json`. Le manager n'appelle jamais `docker` lui-même. Voir `docs/PILOT-DOCKER.md`.
  - Réseau : `none` par défaut. Avec `orchestration.gateway` (opt-in), une équipe `network: gateway` ne joint que la passerelle `pmx_gateway` (routes fixes, jeton lié au réseau de la tentative, clé amont injectée, quotas, journal sans secret). Ne jamais configurer de clé personnelle (`~/.claude`, `~/.codex`) : clés **dédiées** fournies par l'humain.
- Technique : Codex équipe = sandbox `workspace-write` (worktree seul, pas de réseau) ; Codex débat/revue = `read-only` ; Claude débat/revue = outils `Read,Grep,Glob` ou sous-agent sans outil d'écriture ; `claude-cli` équipe = `--settings` pilote (jamais la config globale). Le sous-agent Claude `drop` n'est **pas** sandboxé OS : consigne + contrôle a posteriori + arrêt.

## Ce que le pilote ne fait pas

Pas de variante `gitlab-issues` · pas de push/MR · pas de fusion vers une branche protégée · pas de lancement de sessions Desktop · pas de pilotage de l'UI Claudex (non interactif impossible) · pas d'écriture dans `ai_rules/`.
