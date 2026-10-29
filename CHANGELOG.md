# CHANGELOG

## 3.2.0-rc1 — isolation Docker des équipes (opt-in) — 2026-10-28

Inactif par défaut : une équipe n'est conteneurisée que si la configuration du projet déclare `"adapter": "docker"` pour elle. Sans ce réglage, le comportement est celui de 3.1.0-rc1.

### Nouveau
- Adaptateur `docker` dans `scripts/pmx.py` : un conteneur dédié par tentative.
  - Protections : utilisateur non-root, racine en lecture seule, `cap-drop ALL`, `no-new-privileges`, réseau `none`, limites CPU, mémoire (sans swap) et processus, `/tmp` en tmpfs limité et `noexec`, espaces de noms pid et ipc privés.
  - Montages : le worktree de la tâche seul, son fichier `.git` en lecture seule, le brief et le programme de l'agent en lecture seule.
  - Jamais montés : la socket Docker, le HOME de l'hôte, les identifiants. Aucune variable de l'hôte n'est transmise. L'image n'est jamais téléchargée (`--pull never`).
  - La configuration réelle du conteneur (`docker inspect`) est contrôlée **avant** son démarrage.
  - Cycle de vie entièrement géré par pmx : arrêt sur dépassement du délai, échec critique ou reprise. Preuve `container-*.json` (configuration, montages, sortie, `OOMKilled`), puis suppression. Seuls les conteneurs créés pour ce dépôt sont touchés (labels).
  - Configuration explicite par équipe (`docker`, clés fermées) ; refus de toute clé de montage, de privilège, d'argument libre ou de réseau. Validation au `dispatch` et dans `doctor`.
- `adapters/pilot-docker/` : configuration d'exemple. `docs/PILOT-DOCKER.md` : utilisation, protections, limites, retour arrière.
- Tests :
  - `tests/pilot/test_hybrid.py` : 15 tests ; `tests/pilot/test_docker.py` : 26 tests, conteneurs réels, agent factice `docker-agent/agent.sh`. Ils couvrent la séparation entre deux équipes, les limites, les arrêts, la reprise et le cycle complet jusqu'à l'intégration. Ils sont ignorés sans Docker.
  - `tests/pilot/docker_measure.py` : mesure du parallélisme et des ressources.

- **Vérification isolée** (`orchestration.verify_runner`, adaptateur `docker`) : les commandes de test de confiance de `verify` et d'`integrate` s'exécutent chacune dans un conteneur, avec les protections des équipes, sur le checkout jetable seul.
  - C1 reste actif.
  - Est `INCONCLUSIVE`, donc bloquant, une vérification impossible (image absente, démon indisponible), interrompue (signal), en OOM ou hors délai. Jamais de repli sur l'hôte.
  - La politique d'intégration peut l'exiger : `require_isolated_verification`.
  - Le mode hôte (3.1, par défaut) reste disponible, explicitement signalé comme non isolé.

- **Passerelle réseau des équipes** (`scripts/pmx_gateway.py`, `orchestration.gateway`, opt-in ; équipes docker `network: gateway`). Validée avec des services amont simulés uniquement.
  - Relais à routes fixes ; jeton par tentative lié au réseau interne de l'équipe ; clé amont injectée, jamais visible de l'équipe.
  - Refus des réseaux privés, du loopback, des métadonnées cloud, de `*.docker.internal` et de l'API Docker (après résolution), ainsi que des redirections, de CONNECT et des URI absolues.
  - Quotas par équipe, limites de taille et de délai, journal sans secret. Aucun port publié.
  - Le réseau `none` reste le défaut, et la vérification isolée ne peut pas recevoir de réseau.
- Correction : le processus d'équipe attend que `dispatch` ait enregistré sa tentative (verrou). Avant, une lecture trop précoce de `run.json` pouvait faire échouer la tentative ; c'était latent en 3.1, et exposé par la création des réseaux.

- **Profil hybride `host-agents+docker-verification`** (`orchestration.mode`, exemple `adapters/pilot-hybrid/`, `docs/PILOT-HYBRID.md`). Claude Code et Codex restent sur l'hôte, avec leurs authentifications existantes (aucune clé API) et leurs permissions natives ; la vérification et les tests d'intégration se font obligatoirement en conteneur. `pmx` refuse de fonctionner si `verify_runner` n'est pas docker, si la politique n'exige pas l'isolation, si un agent est conteneurisé ou si les réglages `claude-cli` n'interdisent pas `docker`. Mode recommandé, **limité aux projets non sensibles** : le confinement natif enferme les outils des agents, pas le processus des CLI. Le mode tout-Docker avec passerelle reste expérimental et désactivé par défaut ; le mode `default` (vérifications sur l'hôte, non isolées) reste disponible.
- **Environnement minimal des agents** (revue de la PR #2, tous les modes) : `agent_env()` applique une **liste d'autorisation** (identité et chemins, langue, emplacement de l'authentification existante, certificats TLS, proxys sans identifiants). Tout nom de type `TOKEN`, `SECRET`, `PASSW`, `API_KEY`, `CREDENTIAL`, `AWS`, `AZURE`, `GITHUB`, `GITLAB`, `SSH_AUTH`, `OAUTH`, `SESSION`… est refusé. Avant ce correctif, les agents héritaient de presque tout l'environnement de l'hôte : socket de l'agent SSH, bus DBus, variables et jeton de la session Claude Code qui lance `pmx`.
- **Confinement natif des CLI** (`orchestration.confinement = "native"`, obligatoire en profil hybride). `pmx` impose les sandbox officiels des deux éditeurs (bubblewrap) :
  - Claude : réglages générés par appel (sandbox, `failIfUnavailable`, aucune commande hors sandbox, lectures limitées au chemin absolu du worktree, réseau vide, `blockReadsOutsideWorkingDirectories`) ;
  - Codex : profil de permissions bêta `pmx-ws` / `pmx-ro` passé par `-c` (racine refusée, chemins minimaux, worktree, ni `/tmp` ni réseau) ;
  - `WSL_INTEROP` retiré ;
  - préflight avant tout agent : `bwrap`, `socat`, Claude ≥ 2.1.257, essai sans modèle du sandbox Codex ; arrêt sans repli.

  Validé en réel : 14 accès sensibles bloqués pour chaque CLI (hors worktree, `/mnt/c`, interop, `cmd.exe`, Docker, réseau, écritures), outil Read de Claude refusé, contournement refusé.
- Adaptateur `codex-cli` : le sandbox natif est **durci explicitement** en ligne de commande, sans lire ni modifier `~/.codex` : `sandbox_workspace_write.network_access=false`, `exclude_slash_tmp=true`, `exclude_tmpdir_env_var=true`. Mesuré en réel : avec la configuration de l'utilisateur, Codex en `workspace-write` écrivait dans `/tmp`, avait le réseau et interrogeait le démon Docker ; après durcissement, ces trois accès sont refusés.
- Contrôle du pointeur `.git` des worktrees **avant toute commande Git** : redirigé vers un faux dépôt ⇒ arrêt critique.
- Tout drapeau ou réglage de contournement des permissions natives est refusé, dans tous les modes : `--dangerously-*`, `bypassPermissions`, `danger-full-access`, `--yolo`.

### Durci (tous adaptateurs)
- Git exécuté par pmx : aucun hook (`core.hooksPath=/dev/null`), aucun fsmonitor, aucun transport (`protocol.allow=never`), configuration globale et système ignorées (pas de filtre, diff externe ou `textconv` de l'utilisateur) ; diff du reviewer sans diff externe ni `textconv`.
- Chemins sensibles : `.gitattributes`, `.gitmodules`, `.git` imbriqué.
- Contrôle de périmètre : un lien symbolique, ou un fichier spécial (FIFO, socket, périphérique, invisible pour `git status`), dans le worktree d'une équipe déclenche l'échec critique.
- Cause d'échec `oom-killed` reconnue (limite mémoire d'un conteneur).

### Limites
Voir `docs/PILOT-DOCKER.md` :
- aucun agent réel dans un conteneur, et un réseau `none` empêche l'accès aux API ;
- même UID que l'hôte, et l'utilisateur hôte appartient au groupe `docker` ;
- noyau partagé, sans AppArmor ni SELinux sous WSL2 ;
- disque du worktree non plafonné ;
- vérification isolée seulement si `verify_runner` docker est configuré (le mode hôte, par défaut, n'est pas isolé) ;
- opérations Git de pmx toujours exécutées sur l'hôte (durcies).

## 3.1.0-rc1 — orchestration multi-agents pilote (opt-in) — 2026-10-26

Inactif par défaut : sans `orchestration.enabled: true` (backend `ledger`) dans la configuration d'un projet, le comportement est celui de 3.0.0-rc1.

### Nouveau
- `scripts/pmx.py` (Python stdlib) et `references/orchestration-pilot.md` : demande → débat Claude–Codex (protocole Claudex rejoué, lecture seule, ≤ 3 tours) → décision (humaine si désaccord) → plan (collisions de fichiers, cycles, chemins sensibles) → gate « go » → deux équipes parallèles en worktrees `pilot/*` → collecte avec contrôle de périmètre → `verifier` indépendant → revue croisée → intégration **locale** lancée par l'humain dans son terminal (nom déclaré + phrase de confirmation saisie) et politique écrite.
- Adaptateurs d'agents : `codex-cli`, `claude-cli` (`--settings` pilote, jamais la configuration globale), `drop` (sous-agent de la session lead), `cmd` (tests).
- Registre unique conservé : statuts dans `WORK_ITEMS.md` (champs ledger `parent`, `depends_on`, `session`, `worktree`, `files_probably_touched`, `blocker`, `integrated`) ; exécution technique dans `ai_memory/runs/<WI>/` (journal append-only).
- Disjoncteurs : fichier hors périmètre, chemin sensible, suppression ou collision entre équipes → arrêt de toutes les équipes ; cause d'échec répétée → `ESCALATED` immédiat avec `ai_doc/ESCALATION__<WI>.md` ; plafond de 3 tentatives ; réouverture uniquement sur décision humaine (`pmx reopen --by human:<nom>`).
- `adapters/pilot-claudex/` : configuration, politique d'intégration (`local-only`), permissions pilote.
- `pm_config.py` reconnaît et valide la clé `orchestration` (backend `ledger` exigé).
- Tests : section 11 de `tests/run.sh` (31 tests, agents factices) ; `tests/pilot/live_claude_cli.py` (validation réelle, opt-in).

### Validé en réel (projets fictifs)
Cycle complet avec Codex CLI 0.162 et Claude Code 2.1 : débat clos par consensus, deux équipes simultanées (chevauchements mesurés de 49,5 s Codex ‖ sous-agent Claude, et 26,1 s `codex exec` ‖ `claude -p`), vérification, revues croisées, intégration locale ; refus de permissions de `claude -p` (secret, push, réseau, `.claude/`, écriture hors worktree, commit) ; arrêt d'un `claude -p` en cours sur dépassement de périmètre ; arrêt des relances sur erreur répétée.

### Corrigé
- `pm_config.py` et `rules_sync.py` en mode `100755` (oubli de `6e382fa` ; commit distinct, sans changement de contenu).

### Corrections issues de la revue de la PR (avant fusion)
- **C1 — intégrité des checkouts de vérification et d'intégration** : après les tests, `pmx` contrôle HEAD, fichiers modifiés ou ajoutés, références git et checkout principal, puis la suppression du checkout. Tout écart donne le verdict `INCONCLUSIVE` (jamais PASS) et passe le WI en `BLOCKED`, sans relance automatique. Le checkout est conservé et la preuve écrite dans `ai_memory/runs/<run>/integrity/`. À l'intégration, le candidat est figé avant les tests.
- **C2 — commandes de test** : seules les commandes de confiance écrites par l'humain dans la configuration (`verify_commands`, nouvelle clé `allowed_test_commands`) s'exécutent, toujours sans shell et sans métacaractères. Un plan rédigé par une IA ne peut que les citer mot pour mot. Le contrôle est refait à chaque exécution.
- **C3 — autorisation d'intégration** : `--approved-by` n'est plus qu'un nom déclaré. L'intégration réelle exige une phrase de confirmation saisie sur le terminal de contrôle. Elle est refusée sans terminal ou si des variables d'une CLI d'agent sont présentes. C'est un garde-fou contre une intégration déclenchée par un agent, pas une authentification.

### Limites
Voir `docs/PILOT-CLAUDEX.md` : Claudex (application TTY) non piloté ; confirmation d'intégration ≠ authentification ; les tests exécutent du code produit par les agents ; aucun sandbox OS côté Claude (refus par règles + détection et arrêt) ; Codex en lecture seule peut lire tout le compte ; pas de variante `gitlab-issues`, pas de push, MR ni fusion vers une branche protégée ; coûts non plafonnés.

## 3.0.0-rc1 — distribution GitHub (branche `claude`) — 2026-10-26

Même contenu fonctionnel que le candidat 3.0.0-rc1 ; adaptations de distribution :
- arborescence = racine de `~/.claude` : agents optionnels déplacés de `agents/optional/` vers `optional-agents/` (Claude Code découvre `agents/` récursivement) ; règle globale à plat dans `rules/` ; règle de projet déplacée vers `templates/project-rules/` ; installateur adapté ;
- `.gitignore` en liste blanche (données personnelles de `~/.claude` jamais suivies) ; `CLAUDE.md` utilisateur minimal ;
- installateur : détection du clone direct (« rien à installer ») ;
- adaptateur du projet pilote remplacé par l'exemple anonymisé `adapters/gitlab-multi-team/` ; références au projet pilote anonymisées ;
- README GitHub ; tests de distribution (clone simulé, liste blanche, configuration existante, mise à jour par `pull`, absence de données sensibles).

## 3.0.0-rc1 — 2026-10-26 (candidat, non installé)

Fusion V1 (PM du projet pilote) + V2 (claude-agents-v2). Détail : `docs/MATRIX-V1-V2-V3.md`.

### Conservé de V1
Mode multi-équipes (specs, brief de session, feature-lead), registre GitLab (labels d'état uniques), contrôle S7, mode GitLab injoignable, accord par opération, preuve liée à HEAD (via configuration), verifier et reviewers sans écriture, triage des règles en deux temps.

### Repris de V2
Routage d'intention, protocoles d'analyse (QUICK/DEEP) et de nettoyage mémoire, registre local Work Items, règles natives et `rules_sync.py`, cascade guard technique, agents code-base-analyst / devops / backend & frontend reviewers / memory-cleaner / optionnels, installateur et rollback, extensions détectées.

### Nouveau
Configuration de projet `pm-v3/1` + `pm_config.py` (détection, refus d'un second registre, référentiel sans copie) ; adaptateurs `generic` et `gitlab-multi-team` ; protocole et agent memory-cleaner conscients du backend ; interfaces I2, I5, I6, I7.

### Corrigé / durci (défauts V2)
Résidu A2 et test inopérant ; `review-guard` (env, HTTP en écriture, wget, find -delete, git branch -D) ; reviewers avec Write ; installateur : skill hybride, masquage d'un PM de projet, interruption non détectée, chemins protégés, dépendances, droits, état git ; rollback : suppression de dossiers vides limitée ; règle globale neutre vis-à-vis du backend ; snippet de permissions sans règles de stack ; django-reviewer sans demande de jetons.
