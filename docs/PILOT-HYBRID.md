# Pilote — profil hybride `host-agents+docker-verification` (3.2.0-rc1, opt-in)

**Portée.** C'est le mode recommandé du pilote 3.2.0-rc1, **pour les projets non sensibles uniquement**. Le confinement natif enferme les **outils** des agents dans leur worktree, pas le processus de la CLI. Ce processus tourne sous votre compte, détient vos sessions et n'est pas isolé. Ne pas confier à ce mode un dépôt contenant des secrets professionnels.

Les autres modes restent des options explicites :
- `default` : comportement 3.1. Les vérifications s'exécutent sur l'hôte, **non isolées**, et c'est signalé comme tel.
- Équipes Docker et passerelle réseau (`docs/PILOT-DOCKER.md`) : **expérimental**, désactivé par défaut, validé avec des agents et des API simulés uniquement.

Claude Code et Codex CLI s'exécutent **sur l'hôte**, avec les authentifications que l'utilisateur a déjà établies (`claude.ai`, ChatGPT). Il n'y a ni clé API, ni facturation API, ni identifiant transmis à Docker. Chaque équipe travaille dans son worktree, avec les **permissions natives** de sa CLI. **Toute vérification** (`pmx verify`, tests de l'arbre fusionné par `pmx integrate`) s'exécute dans un conteneur isolé : sans réseau, sans HOME, sans identifiant, avec seulement le checkout jetable.

Exemple complet : `adapters/pilot-hybrid/` (`project-manager.config.json`, `settings.hybrid.json`, `pmx.integration-policy.json`).

## Confinement natif des CLI (`orchestration.confinement = "native"`, obligatoire dans ce profil)

Les deux CLI gardent vos sessions (le processus de la CLI n'est pas enfermé). En revanche, **leurs outils** (commandes shell, et outils de fichiers de Claude) sont confinés au worktree par les sandbox natifs des éditeurs, tous deux basés sur bubblewrap sous WSL2. Les réglages sont **générés par `pmx`** pour chaque appel ; `~/.claude` et `~/.codex` ne sont ni lus ni modifiés.

- **Claude Code** (≥ 2.1.257) : `--settings` généré à côté du prompt, hors du worktree. Il reprend la politique de l'équipe et ajoute :
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
- **Environnement** : `WSL_INTEROP` est retiré pour tous les agents.
- **Préflight**, une fois par processus, avant le premier agent du débat, du lancement ou de la revue :
  - `bwrap` et `socat` présents ;
  - Claude ≥ 2.1.257 ;
  - essai du sandbox Codex **sans modèle** (`codex sandbox`) : le worktree doit être lisible et inscriptible, un fichier témoin hors worktree doit être illisible.

  Toute anomalie arrête `pmx` (code 64) : **aucun agent lancé, aucun repli non isolé**. Claude, lui, échoue d'office si son sandbox ne démarre pas (`failIfUnavailable`) : vérifié avec un `bwrap` factice.

### Contrôles réels du confinement (`live_hybrid.py`, scénario C, 2026-10-28)

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

- **Claude Code** : `claude -p --settings .claude/settings.hybrid.json`. Pour une équipe, outils `Read,Grep,Glob,Edit,Write,Bash` et `--permission-mode acceptEdits` ; pour le débat et la revue, `Read,Grep,Glob` en mode `default`.
  - Écriture limitée à `src/**` et `test/**`.
  - Bash limité à `python3 -B -m unittest` et aux commandes `git` en lecture.
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
