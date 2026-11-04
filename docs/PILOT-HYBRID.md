# Pilote — profil hybride `host-agents+docker-verification` (3.2.0-rc1, opt-in)

**Portée.** C'est le mode recommandé du pilote 3.2.0-rc1, **pour les projets non sensibles uniquement**. Le confinement natif enferme les **outils** des agents dans leur worktree, pas le processus de la CLI. Ce processus tourne sous votre compte, détient vos sessions et n'est pas isolé. Ne pas confier à ce mode un dépôt contenant des secrets professionnels.

Les autres modes restent des options explicites :
- `default` : comportement 3.1. Les vérifications s'exécutent sur l'hôte, **non isolées**, et c'est signalé comme tel.
- Équipes Docker et passerelle réseau (`docs/PILOT-DOCKER.md`) : **expérimental**, désactivé par défaut, validé avec des agents et des API simulés uniquement.

Claude Code et Codex CLI s'exécutent **sur l'hôte**, avec les authentifications que l'utilisateur a déjà établies (`claude.ai`, ChatGPT). Il n'y a ni clé API, ni facturation API, ni identifiant transmis à Docker. Chaque équipe travaille dans son worktree, avec les **permissions natives** de sa CLI. **Toute vérification** (`pmx verify`, tests de l'arbre fusionné par `pmx integrate`) s'exécute dans un conteneur isolé : sans réseau, sans HOME, sans identifiant, avec seulement le checkout jetable.

Exemple complet : `adapters/pilot-hybrid/` (`project-manager.config.json`, `settings.hybrid.json`, `pmx.integration-policy.json`).

## Confinement natif des CLI (`orchestration.confinement = "native"`, obligatoire dans ce profil)

Les deux CLI gardent vos sessions (le processus de la CLI n'est pas enfermé). En revanche, **leurs outils** (commandes shell, et outils de fichiers de Claude) sont confinés au worktree par les sandbox natifs des éditeurs, tous deux basés sur bubblewrap sous WSL2. Les réglages sont **générés par `pmx`** pour chaque appel ; `~/.claude` et `~/.codex` ne sont ni lus ni modifiés.

- **Claude Code** (≥ 2.1.257) : **une équipe n'a pour l'instant pas d'outil shell, dans ce profil uniquement** (`--tools Read,Grep,Glob,Edit,Write`, et `Bash` en `deny`). Elle écrit par ses outils de fichiers, soumis aux règles, et ne lance aucun test : le verdict vient de `pmx verify`, en conteneur. Voir « Pourquoi pas de Bash » ci-dessous. `--settings` est généré à côté du prompt, hors du worktree. Il reprend la politique de l'équipe et ajoute :
  - `permissions.blockReadsOutsideWorkingDirectories: true` ;
  - `sandbox.enabled: true`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false` ;
  - `filesystem.denyRead` : `~/`, `/mnt`, `/run/WSL`, `/mnt/wsl`, `/var/run/docker.sock`, `/run/docker.sock`, `/tmp` ;
  - `allowRead` et `allowWrite` : **chemin absolu du worktree** (aucune écriture pour une revue) ;
  - `network.allowedDomains: []`.

  Attention : dans un fichier `--settings`, `.` désigne le dossier du fichier de réglages, pas le worktree. Ce piège a été constaté en réel, d'où le chemin absolu. Un bloc `sandbox` fourni par l'utilisateur est refusé : `pmx` le gère seul.
- **Codex CLI** : profil de permissions officiel (bêta) passé uniquement par `-c`, à la place de `--sandbox` :
  - `pmx-ws` pour une équipe : `extends=":workspace"`, `":root"="deny"`, `":minimal"="read"`, `":tmpdir"` et `":slash_tmp"="deny"`, réseau désactivé ;
  - `pmx-ro` pour le débat et la revue : `extends=":read-only"`, avec en plus `":workspace_roots"="read"`.

  Le répertoire d'installation de Codex est le seul chemin du HOME rendu lisible : Codex s'y ré-exécute dans le sandbox. Il ne contient aucun identifiant ; `pmx` refuse un répertoire contenant `auth.json`, ainsi que `~` et `~/.codex`.
- **Environnement des agents : liste d'autorisation** (tous les modes ; `agent_env()`). Ce que reçoit une CLI est visible des commandes de l'agent, sandbox compris. Les CLI ne reçoivent donc que :
  - `HOME`, `USER`, `LOGNAME`, `PATH`, `SHELL`, `TMPDIR`, `LANG`, `LANGUAGE`, `LC_*`, `TERM`, `TZ`, `XDG_*_HOME` ;
  - `CLAUDE_CONFIG_DIR` et `CODEX_HOME`, emplacements de l'authentification existante ;
  - les certificats TLS (`NODE_EXTRA_CA_CERTS`, `SSL_CERT_*`, `CODEX_CA_CERTIFICATE`) ;
  - les proxys `*_PROXY`, **écartés s'ils contiennent des identifiants**.

  Tout nom contenant `TOKEN`, `SECRET`, `PASSW`, `API_KEY`, `CREDENTIAL`, `PRIVATE`, `AWS`, `AZURE`, `GITHUB`, `GITLAB`, `SSH_AUTH`, `OAUTH`, `COOKIE` ou `SESSION` est refusé, même s'il figure dans la liste. Ne sont jamais transmis notamment : la socket de l'agent SSH, le bus DBus, l'interop Windows (`WSL_INTEROP`), les variables de la session Claude Code qui lance `pmx` (`CLAUDE_CODE_*`, `ANTHROPIC_BASE_URL`…). **Conséquence** : une authentification fournie par variable d'environnement (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `OPENAI_API_KEY`…) n'est pas utilisable par les agents ; ce profil s'appuie sur la connexion existante, stockée sous `HOME`.

  Mesuré en réel : avec ces seules variables, les deux CLI fonctionnent avec leurs abonnements, et aucune variable de la session hôte n'atteint leurs outils. **Limite** : Claude Code crée lui-même, pour ses propres outils, une variable `CLAUDE_CODE_MESSAGING_TOKEN`. Ce jeton est propre à la session enfant (empreinte différente de celle de la session hôte, mesurée) ; `pmx` ne peut pas l'empêcher. Les variables qu'exporte la configuration de shell de l'utilisateur peuvent aussi être rechargées par l'outil Bash de Claude. Sur le poste de validation, aucune variable sensible ne l'était (`SSH_AUTH_SOCK` absent, mesuré avec zsh et bash).
- **Préflight**, une fois par processus, avant le premier agent du débat, du lancement ou de la revue :
  - `bwrap` et `socat` présents ;
  - Claude ≥ 2.1.257 ;
  - essai du sandbox Codex **sans modèle** (`codex sandbox`) : le worktree doit être lisible et inscriptible, un fichier témoin hors worktree doit être illisible.

  Toute anomalie arrête `pmx` (code 64) : **aucun agent lancé, aucun repli non isolé**. Claude, lui, échoue d'office si son sandbox ne démarre pas (`failIfUnavailable`) : vérifié avec un `bwrap` factice.

### Pourquoi pas de Bash pour l'équipe Claude (temporaire)

Sous Linux et WSL2, chaque commande sandboxée de Claude Code protège en écriture les chemins sensibles absents (25 entrées : `.claude/settings.json`, `.claude/hooks`, `.mcp.json`, `.gitconfig`, `.bashrc`, `.vscode`…). Pour cela, `bwrap` crée **sur l'hôte, dans le worktree**, un fichier vide en mode 444 à chacun de ces chemins, qui lui sert de point de montage pour `/dev/null`. Claude Code les supprime à la fin de la commande, et ils restent si la session est tuée (comportement [documenté](https://code.claude.com/docs/en/sandboxing), mesuré sur 2.1.311, 2.1.314 et 2.1.317).

Pendant toute la commande, `git status` les voit, et le contrôle de périmètre de `pmx` déclenche l'arrêt critique. Rien ne distingue ces fichiers, par leur seul aspect, d'une écriture de l'agent. `pmx` **n'accorde donc aucune exception** : sans commande sandboxée, ces fichiers n'existent pas, et le garde-fou reste entier.

Conséquence fonctionnelle : l'équipe Claude ne peut pas lancer de tests, de lint ni de build ; un échec n'apparaît qu'à `pmx verify`. L'équipe Codex garde son shell : son sandbox ne crée que des répertoires vides (`.codex`, `.agents`, `.aws`), invisibles pour Git.

Ce retrait ne concerne que `orchestration.mode = "host-agents+docker-verification"` avec `confinement = "native"`. Le mode par défaut, même avec `confinement = "native"`, garde `Bash`.

### Restriction des outils MCP externes pour les agents

Les outils MCP et les connecteurs liés aux comptes tournent **hors du sandbox** des CLI. `--tools` et le réseau du sandbox ne les retirent pas. Dans tous les modes, `pmx` applique à chaque agent de développement, de débat ou de revue, pour cet appel seulement, les restrictions ci-dessous ; les connexions de l'utilisateur ne sont pas modifiées. Les résultats obtenus ne constituent pas une garantie d'isolation complète.

- **Claude Code :** `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`, `--disallowedTools=mcp__*` et `ENABLE_CLAUDEAI_MCP_SERVERS=false`. En confinement natif, `--setting-sources ""` écarte aussi les réglages utilisateur et projet : un hook du dépôt s'exécuterait hors du sandbox.
- **Codex :** pas d'équivalent de `--strict-mcp-config`, et `-c mcp_servers={}` ne retire rien. `pmx` liste les serveurs (`codex mcp list --json`) depuis le dossier de l'agent, désactive chacun par son nom, relit le résultat, et **refuse le lancement** au moindre doute. Il coupe aussi `apps`, `plugins`, `remote_plugin`, `tool_suggest`, `skill_mcp_dependency_install`, `hooks` et la recherche web.

Scénarios de validation réels : `tests/pilot/live_mcp.py`.

Limites acceptées pour un pilote non sensible, qui ne sont pas des garanties démontrées :

1. **Connecteurs Codex :** la désactivation de `apps` n'a pas été mesurée avec un connecteur réellement actif. Elle repose sur la documentation de Codex.
2. **Hooks Codex :** `--disable hooks` n'a pas été testé avec un hook réel.
3. **Projet Codex approuvé :** ce cas n'a pas été testé en réel.
4. **Liste d'outils Codex :** elle vient de ce que l'agent déclare et peut être incomplète. Les preuves mesurées sont l'absence de processus serveur et l'échec de l'appel.
5. **Sous-agents :** l'héritage des restrictions par un sous-agent n'a pas été mesuré.
6. **Réglages administrés :** les réglages gérés par une organisation n'ont pas été testés.
7. **Versions :** les résultats valent pour Claude Code 2.1.317 et Codex 0.162.1. Après une mise à jour d'une CLI, `live_mcp.py` est à relancer.
8. **Claude hors confinement natif :** les réglages utilisateur restent chargés, hooks compris.
9. **Outils Codex conservés :** la génération d'images, qui est distante, et les outils de collaboration restent présents.

Effets à connaître : `pmx` applique aux agents les restrictions MCP décrites ci-dessus, sans politique d'exception pour le moment. Ces restrictions ont été validées sur les surfaces testées et ne constituent pas une garantie d'isolation complète. En profil hybride, les réglages utilisateur et projet de Claude sont ignorés ; un nom de serveur Codex hors `[A-Za-z0-9_-]` ou une liste illisible refuse le lancement.

### Arrêt critique vérifié

`pmx` lance chaque tentative dans son propre scope systemd utilisateur (`systemd-run --user --scope`), sans privilège ni changement de configuration, donc dans son propre cgroup v2. Le nom du scope est tiré au hasard. Un descendant reste dans le cgroup même s'il change de groupe de processus ou de session, et l'identité ne dépend plus d'un PID. Ce suivi est **obligatoire en profil hybride** : sans lui, aucun agent n'est lancé.

Déroulement d'un arrêt :

1. L'état bloquant (`stop.state = IN_PROGRESS`) est écrit **avant tout signal**.
2. SIGTERM va aux seuls membres confirmés : `pidfd`, puis relecture de l'appartenance au cgroup.
3. Après 1 s au plus, `cgroup.kill` envoie SIGKILL à tout le cgroup.
4. Pendant 5 s au plus, `pmx` attend `populated 0` ou la disparition du cgroup.
5. La preuve va dans `ai_memory/runs/<run>/stop-evidence.jsonl`, et le verdict est `STOPPED` ou `UNRESOLVED`.

« Équipes arrêtées » ne s'affiche qu'avec `STOPPED`. Tant que l'état reste `IN_PROGRESS` ou `UNRESOLVED`, `dispatch`, `debate`, `verify`, `review`, `integrate` et `reopen` sont refusés. `tick` reprend et revérifie, y compris après la mort du manager pendant l'arrêt : c'est le seul chemin vers `STOPPED`.

**Verdict technique et acquittement sont distincts.** `stop-ack --by human:<nom>`, au terminal, consigne qui a pris connaissance de l'incident et les cgroups vus actifs. Il ne change pas le verdict, ne prouve rien et ne débloque rien : ni relance, ni intégration.

**Récupération manuelle**, si la preuve reste impossible :

1. Contrôler et arrêter soi-même les processus restants (`status`, `stop-evidence.jsonl`).
2. Conserver le run bloqué, ses worktrees et ses preuves en l'état : `pmx` ne les débloque jamais.
3. Reprendre le travail dans un **nouveau run** (`start`).

**Fin normale d'une tentative.** Avant d'exploiter le résultat et de commiter, `pmx` vérifie le cgroup, arrête les descendants encore actifs, revérifie et enregistre la preuve (`attempt_end`). Sans preuve : aucun commit, arrêt critique, verdict `UNRESOLVED` si elle reste impossible. `pmx` ne supprime jamais un cgroup : systemd le retire une fois vide.

**Débat et revue.** Leurs agents utilisent le même scope et la même fonction d'arrêt. Ils sont enregistrés avant leur lancement : l'arrêt critique les atteint, aucun nouvel agent ne part après un arrêt survenu pendant la commande, et si le manager meurt, la commande `pmx` suivante les arrête et le prouve (`helper_end`). Un agent de débat ou de revue en adaptateur `docker` ou `drop` reste hors de ce suivi.

Hors profil hybride, sans systemd utilisateur, l'équipe se lance sans cgroup : le groupe n'est signalé que si son chef porte encore la même heure de démarrage, et tout arrêt critique reste `UNRESOLVED`, car rien ne prouve l'arrêt des descendants hors groupe. Une fin normale y est signalée « non vérifiée » (`status`, `UNVERIFIED` dans la preuve) sans bloquer le run.

Limites : un processus du même utilisateur qui écrit dans un autre `cgroup.procs` de son sous-arbre délégué pourrait sortir du cgroup. Cette sortie a été observée bloquée pour Codex, dans son sandbox, par une sonde externe au dépôt (`codex_escape.py`), et non par `live_hybrid.py`. Le même comportement n'a pas été mesuré directement pour Claude. Aucune garantie générale de résistance à l'évasion du cgroup n'est revendiquée. Le scope dépend du gestionnaire `systemd --user`. Un descendant qui garde la sortie standard de l'agent retarde la fin de la tentative jusqu'à `team_timeout_s` : il n'est arrêté qu'à ce moment.

#### Évolution : shell Claude sécurisé

La capacité n'est pas retirée de l'architecture : `confined_team_without_shell()` est le seul point de décision, et le bloc `sandbox` reste généré. Rétablir le shell demande d'abord, dans `scope_check`, une **preuve technique** qu'un fichier est un artefact vivant du sandbox, jamais une exception sur son nom, sa taille ou son mode. La piste mesurée est le point de montage `/dev/null` visible dans `mountinfo`. Elle n'est ni implémentée ni validée.

`.mcp.json` reste un chemin sensible dans tous les cas : refusé dans les plans, arrêt critique à l'exécution.

### Contrôles réels du confinement (`live_hybrid.py`, scénario C, 2026-10-28)

*Ce tableau date de la version où l'équipe Claude avait encore Bash. Depuis, elle n'a plus de shell : les lignes portant sur les commandes ne la concernent plus. Re-mesuré sur Claude Code 2.1.314 et 2.1.317 : outils `Read` et `Write` refusés hors worktree et sur `.claude/settings.json` et `.mcp.json` ; aucun artefact ; Codex inchangé.*

Claude Code 2.1.311 et Codex 0.162.1, lancés avec exactement la commande de `pmx`. Les cibles sont factices et ont été supprimées. Une sonde de 16 contrôles est exécutée **par l'agent**, et les écritures sont vérifiées sur l'hôte.

| Contrôle | Claude | Codex |
|---|---|---|
| Lire / écrire le worktree | possible / possible | possible / possible |
| Lire hors worktree (dossier voisin, `/tmp`, `~/.config`) | **bloqué** | **bloqué** |
| Lire sous `/mnt/c` | **bloqué** | **bloqué** |
| Lister `~/.ssh` | **bloqué** | **bloqué** |
| Socket d'interop `/run/WSL`, variable `WSL_INTEROP` | **bloqués** | **bloqués** |
| Exécuter `cmd.exe` | **bloqué** | **bloqué** |
| Socket Docker, `docker version` | **bloqués** | **bloqués** |
| Réseau (TCP) | **bloqué** | **bloqué** |
| Écrire hors worktree, dans `/tmp`, dans `.git` | **bloqué** (vérifié sur l'hôte) | **bloqué** (vérifié sur l'hôte) |
| Outil `Read` hors worktree (3 faux fichiers, dont `/mnt/c`) | **refusé** | — (pas d'outil distinct du shell) |
| Tentative de sortie du sandbox | **refusée** (`dangerouslyDisableSandbox` désactivé) | **refusée** |

## Ce que `pmx` impose dans ce profil

`orchestration.mode = "host-agents+docker-verification"`. Ces exigences sont contrôlées dès la première commande (`start`) ; à défaut, `pmx` refuse de fonctionner (code 64) :

| Exigence | Raison |
|---|---|
| `verify_runner.adapter = "docker"`, configuration valide | le code produit par les agents n'est jamais exécuté sur l'hôte lors des vérifications |
| `require_isolated_verification: true` dans la politique d'intégration | `integrate` refuse toute tâche vérifiée hors conteneur |
| équipes, reviewers et débatteurs sur l'hôte (`codex-cli`, `claude-cli`, `drop`, `cmd`) ; pas de passerelle | profil sans clé API : rien de conteneurisé côté agents |
| `claude-cli` avec réglages explicites (`settings`) qui refusent `Bash(docker:*)` | aucun accès Docker pour les agents |
| `confinement: "native"` et préflight conforme | outils des agents confinés au worktree (voir ci-dessus) |

Sont aussi refusés dans **tous** les modes :
- tout drapeau ou réglage de contournement des permissions natives : `--dangerously-*`, `bypassPermissions`, `danger-full-access`, `--yolo` ;
- un `defaultMode` Claude hors de `default`, `acceptEdits`, `plan` ou `dontAsk`.

La vérification n'a **jamais de repli sur l'hôte**. Docker absent, image absente, conteneur interrompu, OOM ou délai dépassé donnent `INCONCLUSIVE` ; la tâche passe en `BLOCKED` et l'intégration est bloquée. L'intégration locale reste sous **confirmation humaine au terminal** (C3).

## Permissions natives appliquées par `pmx`

- **Claude Code** : `claude -p --settings .claude/settings.hybrid.json`. Pour une équipe, outils `Read,Grep,Glob,Edit,Write` (sans `Bash`) et `--permission-mode acceptEdits` ; pour le débat et la revue, `Read,Grep,Glob` en mode `default`.
  - Écriture limitée à `src/**` et `test/**`.
  - Aucun shell en confinement natif : les règles `Bash(...)` de `settings.hybrid.json` ne servent qu'hors de ce mode.
  - Refusés : `docker`, `podman`, `sudo`, `ssh`, `curl`, `wget`, `nc`, installations de paquets, `git push` et `git remote`, ainsi que la lecture de `~/.ssh`, `~/.claude`, `~/.codex`, `~/.config`, `~/.docker`, `~/.aws`, etc.
  - Modification de `.git`, `.claude`, des hooks et de `.gitattributes` refusée.
- **Codex CLI** : `codex exec --sandbox workspace-write` pour une équipe, `read-only` pour le débat et la revue. `pmx` ajoute **toujours** les réglages suivants, en ligne de commande, sans lire ni modifier `~/.codex/config.toml` :
  - `sandbox_workspace_write.network_access=false` ;
  - `sandbox_workspace_write.exclude_slash_tmp=true` ;
  - `sandbox_workspace_write.exclude_tmpdir_env_var=true`.

  Raison : la configuration de l'utilisateur sur ce poste activait le réseau dans ce mode, et `/tmp` et `$TMPDIR` sont inscriptibles par défaut. Sans ces réglages, Codex écrivait dans `/tmp`, accédait au réseau et **interrogeait le démon Docker** (mesuré, voir ci-dessous).
- **`pmx`** :
  - contrôle de périmètre pendant et après le travail : hors périmètre, chemins sensibles, liens symboliques, fichiers spéciaux, suppressions ⇒ arrêt critique de **toutes** les équipes (groupe de processus) ;
  - contrôle du **pointeur `.git`** de chaque worktree avant toute commande Git ;
  - Git durci : sans hook, sans configuration globale, sans transport ;
  - commit des seuls fichiers autorisés, par `pmx`.

## Permissions effectives mesurées sur l'hôte

Mesures faites avec `tests/pilot/live_hybrid.py`, scénario P, le 2026-10-28, avec Claude Code 2.1.311 et Codex CLI 0.162.1, sur WSL2. Chaque CLI est lancée avec exactement la commande que construit `pmx`. Les cibles sont fictives ; « observé » désigne l'état réel de l'hôte, vérifié par le test, et non ce que l'agent a déclaré.

| Action | Claude (équipe) | Codex (équipe, sandbox durci) | Codex (sandbox par défaut avec la configuration utilisateur, avant durcissement) |
|---|---|---|---|
| Écrire dans son worktree | possible | possible | possible |
| Écrire hors worktree (hors `/tmp`) | **empêché** (permissions) | **empêché** (« Read-only file system ») | non mesuré (cible dans `/tmp` lors de cette mesure) |
| Écrire dans `/tmp` | **empêché** | **empêché** | **possible** |
| Lire un fichier hors worktree (`/tmp`) | **possible** | **possible** | possible |
| Lire un fichier sous `~/.config` | **empêché** (règle `deny`) | **possible** | possible |
| Interroger Docker (`docker version`) | **empêché** (règle `deny`) | **empêché** (« permission denied » sur `docker.sock`) | **possible** (version du démon obtenue) |
| Réseau (`https://example.com`) | **empêché** (règle `deny`) | **empêché** (échec de résolution DNS) | **possible** (HTTP 200) |
| Modifier le pointeur `.git` du worktree | **empêché** | **empêché** (« Read-only file system ») | empêché |

## Accès qui ne peuvent pas être empêchés techniquement

**Avec le confinement natif, les points 1 à 3 ci-dessous ne valent plus pour les outils des agents** : lectures limitées au worktree, Docker et Windows bloqués, comme mesuré ci-dessus. Ils restent vrais pour le **processus de la CLI** lui-même, qui tourne sous votre compte et détient vos sessions, et pour les outils non couverts par le sandbox (serveurs MCP, hooks, WebFetch : non activés par `pmx`). Mesures **sans** confinement natif, pour mémoire :

1. **Lecture des fichiers de l'utilisateur par Codex.** Le sandbox de Codex restreint l'écriture et le réseau, pas la lecture. Codex peut lire tout fichier lisible par l'utilisateur, **y compris `~/.ssh`, `~/.claude` et `~/.codex/auth.json`**. Mesuré sur un faux fichier sous `~/.config`. Aucun réglage de `pmx` ne l'empêche. Ce que lit l'agent peut se retrouver dans sa sortie (rapport, revue), donc dans `ai_memory/`, ainsi que chez le fournisseur du modèle.
2. **Lecture hors worktree par Claude** pour les chemins non refusés explicitement : mesuré sur un faux fichier dans `/tmp`. Les règles `deny` ne couvrent que les répertoires listés ; tout chemin non listé reste lisible par l'outil `Read`.
3. **Les deux CLI tournent sous l'utilisateur, membre du groupe `docker`.** Elles sont empêchées d'utiliser Docker : Claude par ses règles, Codex par son sandbox durci. Mais une faille de l'une ou l'autre de ces barrières donnerait un accès équivalent à root. La seule protection technique complète serait de retirer l'utilisateur du groupe `docker`, ce qui n'est pas fait ici.
4. **Les CLI joignent leurs fournisseurs** (Anthropic, OpenAI) avec les sessions de l'utilisateur : c'est inhérent au profil. Le contenu du projet fictif, les briefs et les sorties sont envoyés aux modèles.
5. **Ce que fait la CLI elle-même** (télémétrie, mises à jour, fichiers de session dans `~/.claude` et `~/.codex`) relève de la CLI et de la configuration de l'utilisateur, non de `pmx`. Les sessions de Codex sont lancées avec `--ephemeral`.
6. **Les permissions de Claude sont des règles applicatives, pas un sandbox du système.** Elles ont tenu dans tous les essais, mais une commande Bash autorisée (`python3 -B -m unittest`) exécute du code du dépôt : du code écrit par l'agent peut donc s'exécuter sur l'hôte à travers les tests que l'agent lance lui-même pendant son travail. Mesures en place : le contrôle de périmètre détecte et arrête les écritures hors périmètre, et la vérification officielle tourne en conteneur.
7. **Codex lancé par `pmx` n'est jamais en `danger-full-access`.** Un utilisateur qui lance Codex à la main, hors de `pmx`, avec sa propre configuration, n'est pas couvert.

## Utilisation

1. Copier `adapters/pilot-hybrid/*` dans `<repo>/.claude/` d'un dépôt pilote (`settings.hybrid.json` à côté de la configuration).
2. Disposer d'une image de vérification **locale**, épinglée par digest, contenant l'outillage de test. L'exemple utilise `python:3.13-alpine` (digest `8bcfa47b…`) et adapte `verify_commands`.
3. Lancer `pmx doctor`, qui doit indiquer `✔ profil : host-agents+docker-verification`, puis suivre le flux habituel (`references/orchestration-pilot.md`). Le manager s'arrête à `integrate --dry-run` ; l'intégration réelle est lancée par l'humain, dans son terminal.
4. Validation réelle (opt-in, consomme l'usage des abonnements) : `PMX_LIVE=1 python3 -I -B tests/pilot/live_hybrid.py <dossier-neuf>`.

## Retour arrière

Retirer `orchestration.mode` (ou mettre `default`) et `verify_runner` : on revient au comportement de 3.1, avec des vérifications sur l'hôte, **non isolées**. Les réglages durcis de Codex restent appliqués par `pmx`.
