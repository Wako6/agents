# Pilote — isolation Docker des équipes (`3.2.0-rc1`, opt-in)

L'adaptateur `docker` de `pmx` lance chaque équipe dans **son propre conteneur**, avec seulement son worktree monté. Il ne crée aucune nouvelle porte d'entrée : on l'active en déclarant `"adapter": "docker"` pour une équipe, dans la configuration d'un projet pilote.

- Sans ce réglage, rien ne change par rapport à 3.1.0-rc1.
- Les adaptateurs `codex-cli`, `claude-cli`, `drop` et `cmd` restent disponibles, et un même run peut mélanger équipes Docker et équipes processus.

**Statut : expérimental, désactivé par défaut. Validé avec des agents factices uniquement.** Le mode recommandé en 3.2.0-rc1 est le profil hybride `host-agents+docker-verification` (`docs/PILOT-HYBRID.md`) : agents sur l'hôte, vérification en conteneur avec `verify_runner`, décrit plus bas. Claude et Codex n'ont pas été lancés dans un conteneur ; voir « Limites ».

## Ce que fait l'adaptateur

Le cycle d'un conteneur se déroule en cinq étapes, toutes pilotées par `pmx`, qui reste seul responsable du cycle de vie :

1. **`docker create`** : le conteneur reçoit un nom unique (`pmx-<empreinte du dépôt>-<run>-<tâche>-a<n>`) et des labels (`pmx.pilot=1`, `pmx.root=<dépôt>`).
2. **Contrôle avant démarrage** : `docker inspect` lit la configuration réelle, telle que le démon l'a créée. Tout écart à la politique (voir ci-dessous) empêche le démarrage et supprime le conteneur.
3. **`docker start --attach`** : la sortie standard devient le rapport de l'équipe.
4. **Arrêt** : le conteneur est arrêté en cas de dépassement du délai, d'échec critique (`abort`) ou de reprise après coupure (conteneur orphelin).
5. **Preuve, puis suppression** : `container-<nom>.json` est écrit dans `ai_memory/runs/<run>/tasks/<tâche>/` (configuration, montages, utilisateur, variables, code de sortie, `OOMKilled`), puis le conteneur est supprimé.

`pmx` n'agit (`kill`, `rm`) que sur un conteneur dont les labels désignent **ce** dépôt. Il ne fait jamais de `prune`, ni d'action sur un conteneur qu'il n'a pas créé.

### Politique appliquée et revérifiée sur le conteneur créé

| Protection | Réglage |
|---|---|
| Utilisateur non-root | `--user <uid>:<gid>` de l'hôte (refus de root) |
| Racine en lecture seule | `--read-only` |
| Aucune capacité Linux | `--cap-drop ALL`, aucun `--cap-add` |
| Pas d'élévation | `--security-opt no-new-privileges`, seccomp par défaut du démon |
| Réseau | `--network none` (seule valeur acceptée) |
| Limites | `--cpus`, `--memory` = `--memory-swap` (pas de swap), `--pids-limit`, `--ulimit nofile` |
| Espace temporaire | `--tmpfs /tmp:noexec,nosuid,nodev,size=…` |
| Espaces de noms | pid et ipc privés ; pas de `--privileged`, pas de périphérique, pas de `userns=host` |
| Montages | exactement : le worktree de la tâche → `/work` (lecture seule pour une revue) ; son fichier `.git` → `/work/.git` en **lecture seule** ; le brief → `/pmx/brief.md` en lecture seule ; optionnellement le programme de l'agent → `/agent` en lecture seule |
| Variables | `HOME=/tmp`, `PMX_BRIEF`, `PMX_WORK`, `PMX_MODE` seulement (aucune variable de l'hôte) |
| Image | `--pull never` : jamais téléchargée par `pmx` |

Ne sont jamais montés : la socket Docker, le HOME de l'hôte, les clés SSH, les identifiants, le dépôt principal, les worktrees des autres équipes.

Le fichier `.git` d'un worktree pointe vers le dépôt. S'il était modifiable, une équipe pourrait rediriger les commandes `git` que `pmx` lance ensuite sur l'hôte : il est donc monté en lecture seule.

### Vérification isolée (`verify_runner`)

Les commandes de test de confiance (`verify_commands`, `allowed_test_commands`, C2) exécutent le code livré par les équipes. Avec `verify_runner.adapter = "docker"`, elles tournent **dans un conteneur**, pour `pmx verify` comme pour les tests de `pmx integrate` sur l'arbre fusionné.

- **Une commande = un conteneur.** On y retrouve les protections des équipes : non-root, racine en lecture seule, `cap-drop ALL`, `no-new-privileges`, réseau `none`, limites, `/tmp` limité.
- **Montages** : le checkout jetable (`/work`) et son fichier `.git` en lecture seule. Le dépôt Git lui-même n'est pas monté : les tests ne peuvent toucher ni HEAD, ni les références, ni la configuration.
- **Configuration fermée** : image et limites seulement. `argv` est interdit, car les commandes viennent exclusivement des listes approuvées. Aucun montage, réseau ou privilège ne peut être ajouté.
- **C1 reste actif** sur le checkout après les tests (HEAD, fichiers suivis et non suivis, références, checkout principal, nettoyage).
- **Preuves** : sorties dans la note du verifier et dans `run.json` ; `container-*.json` dans `ai_memory/runs/<run>/verify/<tâche>/` et `.../integrate/`.
- **Non concluant ⇒ bloqué.** Dans les cas suivants, le verdict est `INCONCLUSIVE`, la tâche passe en `BLOCKED` et aucune relance automatique n'a lieu ; l'intégration est donc impossible :
  - conteneur non créé (image absente, démon indisponible) ;
  - politique non respectée ;
  - délai dépassé ;
  - OOM ;
  - conteneur tué par un signal (code 137 ou 143) ;
  - preuve introuvable.
- **Jamais de repli sur l'hôte.**
- **Exiger l'isolation** : `"require_isolated_verification": true` dans la politique d'intégration. `integrate` refuse alors si l'exécuteur n'est pas `docker`, ou si une tâche a été vérifiée sur l'hôte.
- **Mode hôte (3.1, par défaut)** : il reste disponible pour la compatibilité, mais **il n'est pas sécurisé**. Le code des équipes s'exécute avec les droits de l'utilisateur. La note du verifier, `doctor`, `integrate` et `DECISIONS__<WI>.md` l'indiquent explicitement : « host — NOT isolated ».

### Git exécuté par `pmx` sur les contenus des équipes

Aucune commande Git n'est considérée comme sûre par principe :
- `worktree add` peut déclencher `post-checkout` et les filtres `smudge` ;
- `status` et `add` peuvent déclencher les filtres `clean` et `fsmonitor` ;
- `commit` peut déclencher `pre-commit`, `commit-msg`, `post-commit` et `reference-transaction` ;
- `merge` peut déclencher `pre-merge-commit` et `post-merge` ;
- `diff` peut déclencher un diff externe et `textconv`.

Toutes les commandes Git de `pmx` passent donc par une invocation durcie :
- `core.hooksPath=/dev/null` : aucun hook, y compris des hooks versionnés de type husky ;
- `core.fsmonitor=false` et `protocol.allow=never` : aucun transport réseau ;
- configuration globale et système ignorées (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`) : ni les pilotes de filtre ou de diff de l'utilisateur (git-lfs par exemple), ni ses alias ne s'appliquent ;
- `--no-ext-diff --no-textconv` pour le diff fourni au reviewer.

Le test `v12` le démontre. Le dépôt y a des hooks versionnés (`core.hooksPath=.githooks`), un `.gitattributes` qui active un filtre et un `textconv` définis dans la configuration globale, et le cycle complet est déroulé. Aucun hook, filtre ou `textconv` n'est exécuté par `pmx`. Un `git commit` ordinaire, lancé en témoin, déclenche bien le hook.

`.gitattributes`, `.gitmodules`, `.git` imbriqué et les répertoires de hooks sont des chemins sensibles : une équipe ne peut pas les modifier (refus du plan ou arrêt critique).

### Passerelle réseau des équipes (`orchestration.gateway`, opt-in, services simulés uniquement)

Par défaut, une équipe Docker n'a **aucun réseau**. Une équipe déclarée `"network": "gateway", "gateway_routes": [...]` reçoit :
- un réseau Docker **interne** dédié à sa tentative : pas de route sortante, seuls l'équipe et la passerelle y sont ;
- l'alias `pmx-gateway` et un **jeton temporaire**, passé au conteneur par l'environnement du client `docker` (jamais dans `argv`, les journaux ou `run.json`) ;
- les variables des CLI officielles :
  - `ANTHROPIC_BASE_URL=http://pmx-gateway:8080/anthropic` et `ANTHROPIC_AUTH_TOKEN` ;
  - `OPENAI_BASE_URL=http://pmx-gateway:8080/openai/v1` et `OPENAI_API_KEY` ;
  - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.

La passerelle (`scripts/pmx_gateway.py`, Python standard), un conteneur par run :
- **Relais inverse à routes fixes**. `CONNECT` et URI absolues refusés : une équipe ne choisit jamais sa destination.
- **Jeton lié** à l'équipe, à ses routes, au **sous-réseau** de sa tentative et à une échéance. Un jeton volé ne sert pas depuis un autre réseau. Le fichier des jetons ne contient que des empreintes SHA-256. Le jeton est révoqué et le réseau supprimé dès la fin du conteneur.
- **Clé amont injectée** par la passerelle seule. Le fichier des clés n'est monté que dans la passerelle, et l'équipe ne le voit jamais.
- **Destinations vérifiées après résolution, puis connexion à l'adresse vérifiée.** Toujours refusés : loopback, lien local et métadonnées cloud, `*.docker.internal`, ports de l'API Docker (2375–2377), adresses non routables. Les réseaux privés sont refusés, sauf pour un amont explicitement marqué `allow_private` (services simulés).
- **Redirections ni suivies ni relayées** (502).
- **Limites et quotas** : taille des requêtes (413), requêtes en flux refusées (411), taille des réponses (troncature journalisée), délais client et amont (504). Quotas **par équipe** en requêtes, octets et jetons LLM estimés (429). Requêtes simultanées limitées.
- **Journal JSON par décision**. Jamais d'en-tête, de corps, de requête (query), de jeton ni de clé : seulement une empreinte courte du jeton.
- **Pas de port publié.** Elle est attachée uniquement au réseau amont configuré et aux réseaux internes des équipes. Elle n'est joignable ni depuis l'hôte ni depuis un autre réseau Docker (testé). Même durcissement que les équipes : non-root, racine en lecture seule, aucune capacité, limites. Configuration réelle contrôlée avant démarrage.
- **Durée de vie** : démarrée au premier `dispatch` qui en a besoin, arrêtée (preuve gardée) quand plus aucune équipe `gateway` n'est en cours.

**La vérification isolée garde toujours le réseau `none`** (`verify_runner` refuse `gateway`). Exemple de configuration : `adapters/pilot-docker/gateway.example.json`.

### Contrôles ajoutés pour tous les adaptateurs

Le contrôle de périmètre (`scope_check`) refuse désormais aussi :
- les **liens symboliques** : les tests et outils de l'hôte les suivraient ;
- les **fichiers spéciaux** (FIFO, socket, périphérique), que `git status` ne montre pas.

Les deux déclenchent l'arrêt critique, comme une écriture hors périmètre.

## Configuration (par équipe, explicite)

```json
"team-a": {
  "adapter": "docker",
  "docker": {
    "image": "<image locale>:<tag>",
    "argv": ["<programme>", "{prompt_file}"],
    "cpus": 1.0, "memory": "512m", "pids": 128, "tmpfs_size": "64m", "nofile": 1024,
    "network": "none",
    "agent_dir": "<répertoire du programme, monté en lecture seule sur /agent (optionnel)>"
  }
}
```

- `{prompt_file}` devient `/pmx/brief.md`, `{cwd}` devient `/work` et `{mode}` devient `write` ou `read`.
- Toute autre clé est refusée : pas de montage, d'argument `docker` libre, de privilège ni de réseau supplémentaires.
- `agent_dir` est refusé s'il est égal au HOME, au dépôt, aux worktrees ou à un répertoire système (`/`, `/etc`, `/var`, `/run`), ou s'il les contient. Il est aussi refusé s'il contient un chemin d'identifiants (`.ssh`, `.claude`, `.codex`, `.docker`…) ou une socket.
- La validation a lieu au `dispatch`, avant toute création de worktree (code 64). `pmx doctor` l'affiche aussi.

Exemple complet : `adapters/pilot-docker/project-manager.config.json`.

## Utilisation

1. Disposer d'une image **locale** contenant le programme de l'agent, et d'une image **locale** contenant l'outillage de test du projet (`verify_runner`) (pour les tests : `alpine:3.22` et `tests/pilot/docker-agent/agent.sh`).
2. Copier `adapters/pilot-docker/project-manager.config.json` et `pmx.integration-policy.json` dans `<repo>/.claude/`, puis remplacer l'image, `argv` et les commandes de test.
3. Lancer `pmx doctor`, puis suivre le flux habituel (`references/orchestration-pilot.md`) : `dispatch`, `wait`, `verify`, `review` et `integrate` sont inchangés.
4. Tests :
   - `python3 -I -B tests/pilot/test_docker.py -v` (ignoré sans Docker) ;
   - mesure : `python3 -I -B tests/pilot/docker_measure.py <dossier-neuf>`.

## Limites (non couvertes ou non démontrées)

- **Passerelle validée seulement avec des services amont simulés**, sur un réseau amont Docker interne. Les points suivants ne sont **pas testés** :
  - aucun appel aux API réelles ;
  - pas de TLS vers l'amont (code HTTPS écrit, avec vérification de certificat, mais non exercé) ;
  - pas de passage par le proxy de l'hôte, ni d'inspection TLS d'entreprise ;
  - pas de vrai Claude Code ni de vrai Codex.

  Comptage des jetons LLM : estimation par lecture de `input_tokens`/`output_tokens` dans les réponses. Quotas en mémoire, perdus si la passerelle redémarre en cours de run. Le jeton est visible par `docker inspect` (comme toute variable d'environnement) pour qui a accès au démon. Le flux d'un amont qui envoie des en-têtes puis se bloque est borné par `upstream_timeout_s` entre deux lectures, pas sur la durée totale.

- **Pas d'agent réel dans un conteneur.** Claude et Codex n'y ont pas été lancés. Avec `--network none`, ils ne peuvent pas joindre leur API ; il faudrait un proxy sortant restreint et un moyen de fournir une clé sans exposer les identifiants de l'utilisateur. Ce n'est pas fait.
- **Même UID que l'hôte pour toutes les équipes.**
  - La séparation entre équipes repose sur les montages et les espaces de noms, pas sur des utilisateurs distincts.
  - Pas de `userns-remap` : cela demanderait de modifier la configuration du démon.
  - Une évasion du conteneur donnerait les droits de l'utilisateur hôte. Or cet utilisateur appartient au groupe `docker`, ce qui équivaut à root sur l'hôte.
- **Noyau partagé.** L'isolation est celle des conteneurs : espaces de noms, cgroups, seccomp par défaut. Il n'y a ni AppArmor ni SELinux sous WSL2, ni frontière de machine virtuelle entre les équipes.
- **Disque non plafonné dans le worktree.** Une équipe peut remplir le disque par `/work` ; seul `/tmp` est limité. Le délai `team_timeout_s` borne seulement la durée.
- **Mode hôte toujours disponible.** Sans `verify_runner` docker, la vérification et l'intégration exécutent le code des équipes sur l'hôte (comportement 3.1, signalé comme non isolé). Seule `require_isolated_verification` dans la politique rend l'isolation obligatoire.
- **Opérations Git de `pmx` sur l'hôte.** `status`, `add`, `commit`, `worktree add` et `merge` lisent toujours les contenus des équipes, sans hook, filtre ni configuration globale. Une faille de Git lui-même (analyse d'objets ou de chemins malveillants) n'est pas couverte.
- **Image de test.** Elle doit contenir l'outillage du projet (Node, Python…). Les tests du pilote utilisent `alpine:3.22` et des scripts `sh`.
- **Informations visibles depuis le conteneur.** `/proc/self/mountinfo` révèle les chemins hôte des montages (noms de dossiers, pas leur contenu). `/etc/hosts`, `/etc/hostname` et `/etc/resolv.conf` sont fournis par Docker, en lecture seule.
- **Mesures CPU et mémoire grossières.** Elles reposent sur un échantillonnage de `docker stats` (environ 1 à 2 s par appel). Un pic légèrement supérieur à 100 % pour une limite d'un CPU est un artefact de mesure.
- **Docker Desktop sous WSL2** : c'est la seule plateforme testée.

## Retour arrière

| Ce qui a été fait | Comment revenir |
|---|---|
| Équipe passée en `docker` | remettre son adaptateur précédent (`codex-cli`, `claude-cli`, `drop` ou `cmd`) |
| Version du kit | revenir à `3.1.0-rc1` (revert, ou `rollback.sh --dest <DIR>`). Aucune donnée de projet ne dépend de l'adaptateur. |
| Conteneurs | supprimés par `pmx` après chaque tentative. Un conteneur restant (coupure pendant la finalisation) se liste avec `docker ps -a --filter label=pmx.pilot=1` et se supprime **à la main**, après vérification de son label `pmx.root`. |
| Preuves | `ai_memory/runs/<run>/tasks/<tâche>/container-*.json`, à conserver ou à supprimer à la main |
