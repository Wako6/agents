# Project Manager V3 — Unified (Claude Code)

Version **3.2.0-rc1** (candidate). Kit d'orchestration multi-agents pour [Claude Code](https://code.claude.com) : un seul skill `project-manager` qui pilote une équipe d'agents spécialisés, tient l'état du projet dans des fichiers du dépôt et soumet chaque opération sensible à votre accord.

Cette branche (`claude`) a la forme exacte d'un dossier `~/.claude/` : elle peut être clonée directement à cet emplacement pour une **première installation**, ou installée de façon non destructive dans une configuration existante.

---

## 1. Présentation

Le Project Manager V3 fusionne deux lignées :
- un PM **multi-équipes** éprouvé sur un projet pilote GitLab (issues et labels comme registre, une session par fonctionnalité, contrôle d'intégration des MR) ;
- le kit **claude-agents v2** (registre local de Work Items, règles natives Claude Code, installateur non destructif).

Vous parlez en français ou en anglais ; le PM choisit le flux, les rôles et les protocoles. Il orchestre, il n'implémente pas.

## 2. Fonctionnalités principales

- **Un seul skill public** `project-manager`, avec routage d'intention : statut et reprise, analyse avant de coder (QUICK / DEEP), implémentation, planification multi-fonctionnalités et multi-équipes, nettoyage de la mémoire, gestion des règles durables.
- **Classification** `simple` / `medium` / `complex`, plan présenté et confirmé avant toute délégation, disjoncteurs (3 tentatives, blocage > 48 h), Definition of Done.
- **Un registre de work items par projet**, au choix : registre local (`ai_memory/WORK_ITEMS.md`, identifiants `WI-AAAAMMJJ-SLUG-###`) **ou** issues GitLab (`#NN`, un seul label d'état). Jamais les deux.
- **Mode multi-équipes** (GitLab) : specs, brief de session, agent `feature-lead`, dépendances débloquées seulement sur intégration vérifiée.
- **Mémoire de dépôt** : `ai_memory/` (état, notes de rôle, reprise de session), `ai_doc/` (analyses, rapports), `ai_rules/` (connaissance durable).
- **Règles natives Claude Code** : règle globale du kit, règles de projet générées depuis `ai_rules/` par `rules_sync.py`.
- **Vérification indépendante** (`verifier`) et revues spécialisées en lecture seule.
- **Garde-fous** : un accord explicite par opération sortante (commit, push, MR/PR, issue), aucun merge par l'IA, aucun accès aux secrets, garde-fous des projets jamais modifiés, sous-agents sans accès aux skills.
- **Orchestration multi-agents (pilote, opt-in)** pour les projets à registre local : débat Claude–Codex borné à 3 tours, décision humaine si désaccord, plan avec détection des collisions, deux équipes parallèles en worktrees isolés, vérification indépendante, revue croisée, intégration **locale** sur accord explicite, arrêt des relances dès qu'une cause d'échec se répète (`scripts/pmx.py`, `docs/PILOT-CLAUDEX.md`). Inactif tant qu'un projet n'active pas `orchestration.enabled`.
- **Profil hybride `host-agents+docker-verification` (pilote, opt-in ; mode recommandé en 3.2.0-rc1, limité aux projets non sensibles)** : Claude Code et Codex tournent sur l'hôte avec leurs authentifications existantes. Leurs **outils** sont confinés au worktree par les sandbox natifs des CLI (`confinement: native`, réglages imposés par `pmx`, arrêt sans repli si le sandbox est indisponible). Vérification et tests d'intégration se font obligatoirement en conteneur isolé (`docs/PILOT-HYBRID.md`). **Ce n'est pas une isolation complète** : le processus de chaque CLI garde les droits de l'utilisateur et ses sessions.
- **Isolation Docker des équipes (pilote, opt-in, expérimental)** : adaptateur `docker`, un conteneur par équipe. Non-root, racine en lecture seule, sans capacité Linux, sans réseau, avec limites CPU, mémoire et processus ; seul son worktree est monté. Les commandes de test de `verify` et `integrate` peuvent aussi tourner en conteneur (`verify_runner`) ; sans cela, elles s'exécutent sur l'hôte, sans isolation. Validé avec des agents factices uniquement (`docs/PILOT-DOCKER.md`).
- **Installateur non destructif** avec manifeste, sauvegardes, conflits, `--dry-run`, `--merge`, `--force`, verrou d'interruption, et **rollback**.

## 3. Architecture

```
.                                   (= ~/.claude après un clone direct)
├── CLAUDE.md                       mémoire utilisateur minimale (chargée dans toutes les sessions)
├── skills/project-manager/         le skill (découvert par Claude Code) : skills/project-manager/SKILL.md
│   ├── SKILL.md
│   ├── references/                 runbook, work-items, backend-ledger, backend-gitlab, multi-team,
│   │                               problem-solver, memory-clean, rules-wiki, review-triage,
│   │                               project-config, extension-points, session-brief, spec-template,
│   │                               orchestration-pilot (opt-in)
│   ├── scripts/                    pm_config.py (configuration de projet), rules_sync.py (règles),
│   │                               pmx.py (orchestrateur pilote, opt-in)
│   └── hooks/review-guard.sh       garde-fou des agents de revue
├── agents/                         12 agents (découverts par Claude Code)
├── rules/00-kit-workflow.md        règle globale (chargée dans toutes les sessions)
├── optional-agents/                4 agents optionnels (Flutter, SPIP) — non chargés par défaut
├── adapters/                       generic/ (registre local) · gitlab-multi-team/ (exemple GitLab) · pilot-claudex/ (orchestration opt-in) · pilot-docker/ (équipes en conteneurs, expérimental) · pilot-hybrid/ (agents sur l'hôte, vérification en conteneur)
├── templates/                      project-rules/, settings.kit.json, CLAUDE.md.template, ai_rules-example/, mcp…
├── install.sh · rollback.sh        installation non destructive et retour arrière
├── tests/run.sh                    suite de tests en bac à sable (+ tests/pilot/ : orchestrateur, agents factices ; validation réelle opt-in)
└── docs/                           audit, matrice V1/V2/V3, arbitrages, installation, migration, rollback, tests, risques, extensions
```

Agents : `explorer` (TOA, mémoire), `code-base-analyst`, `solution-architect`, `developer`, `devops-engineer`, `verifier`, `feature-lead`, `backend-reviewer-analyst`, `frontend-reviewer-analyst`, `django-reviewer`, `rules-curator` (seul rédacteur de `ai_rules/`), `memory-cleaner`.

## 4. Prérequis et compatibilité

- Claude Code récent (utilise : `disallowedTools` et `hooks` dans le frontmatter des agents, `${CLAUDE_SKILL_DIR}`, `.claude/rules/` avec `paths:`).
- `bash`, `git`, `python3` ≥ 3.8 (aucune dépendance), `sha256sum`, `find`, `awk`, `sed`. Testé sous Linux / WSL.
- Précédence documentée par Claude Code : **skills personnels > skills de projet** ; **agents de projet > agents personnels**. Voir § 11.
- Sous WSL, extraire et cloner dans le système de fichiers Linux (pas sous `/mnt/c`) pour conserver les droits d'exécution.

## 5. Première installation (dossier `~/.claude` absent ou vide)

**Uniquement pour une première installation** :
```bash
git clone --branch claude --single-branch \
  https://github.com/Wako6/agents.git ~/.claude
```
- `git` refuse le clone si `~/.claude` existe déjà et n'est pas vide (cas d'une installation de Claude Code déjà utilisée) : passez alors au § 6.
- Après le clone, Claude Code trouve le skill (`~/.claude/skills/project-manager/`), les agents (`~/.claude/agents/`) et la règle globale (`~/.claude/rules/`).
- Le `.gitignore` est une **liste blanche** : vos données personnelles que Claude Code écrira ensuite dans `~/.claude` (identifiants, `settings.json`, transcriptions `projects/`, historique, sauvegardes, plugins, vos propres agents ou skills) ne sont **jamais** suivies par git.
- Mise à jour d'une installation faite ainsi : `git -C ~/.claude pull --ff-only` (ne jamais re-cloner).

## 6. Installation non destructive dans une configuration existante

Ne **jamais** cloner dans un `~/.claude` existant. Clonez le kit ailleurs, puis installez :
```bash
git clone --branch claude --single-branch https://github.com/Wako6/agents.git ~/src/pm-v3
cd ~/src/pm-v3
tests/run.sh                       # facultatif : tests en bac à sable, ne touche pas ~/.claude
./install.sh --with-rules --dry-run
./install.sh --with-rules          # copie skill, agents, règle globale ; jamais settings, hooks, CLAUDE.md
```
- Fichier identique → ignoré ; fichier modifié par vous → **conflit, non touché** (`--merge` dépose `<fichier>.kit-new`, `--force` sauvegarde puis écrase).
- Un `project-manager` déjà présent dans `~/.claude/skills` et différent : **tout le skill** est en conflit (aucun mélange de fichiers).
- Lancé depuis un dépôt qui a son propre `.claude/skills/project-manager`, l'installateur refuse (un skill personnel le masquerait) ; `--allow-shadowing` pour passer outre en connaissance de cause.
- Agents optionnels : `--with-optional`.
- Chaque exécution écrit un manifeste dans `~/.claude/.project-manager-v3-kit/`.

## 7. Utilisation en langage naturel

Ouvrez Claude Code dans un projet et parlez normalement, ou tapez `/project-manager` :
- « où en est-on ? », « reprends », « qu'est-ce qui bloque ? » → reprise et état ;
- « analyse ce problème », « compare deux approches », « pourquoi ça casse ? » → analyse sans code ;
- « ajoute une fonctionnalité… », « corrige ce bug », « prépare une MR » → classification, plan, délégation (plan confirmé avant d'agir) ;
- « cadre et planifie ces trois fonctionnalités », « lance les features », « où en sont les équipes ? » → multi-équipes (registre GitLab) ;
- « nettoie la mémoire », « archive les work items » → nettoyage (jamais automatique) ;
- « note cette règle », « cette convention est obsolète » → `rules-curator`.

Au premier contact avec un projet sans configuration, le PM **demande** quel registre utiliser ; il ne crée jamais un second registre.

## 8. Règles et mémoire

- `ai_memory/` : `REPO_STATE.md` (état opérationnel), notes `AAAA-MM-JJ__ROLE-<rôle>__<WI>.md`, registre local si choisi, `PENDING_GITLAB.md` (actions à rejouer si GitLab est injoignable).
- `ai_doc/` : analyses `ANALYSIS__<WI>__<slug>.md`, rapports de revue.
- `ai_rules/` : connaissance durable (conventions, décisions, pièges, sécurité, performance), écrite uniquement par `rules-curator`, **en deux temps** (proposition, validation humaine, application).
- Règles natives : `rules/00-kit-workflow.md` (globale) ; `templates/project-rules/10-ai-memory-layout.md` (projet, à portée `paths:`) ; `.claude/rules/ai-rules*.md` **générés** depuis les entrées `ai_rules/` marquées `Autoload: yes` :
  ```bash
  python3 -I ~/.claude/skills/project-manager/scripts/rules_sync.py --ai-rules ai_rules --out .claude/rules --check
  python3 -I ~/.claude/skills/project-manager/scripts/rules_sync.py --ai-rules ai_rules --out .claude/rules --write
  ```

## 9. Installation par projet

Recommandée quand un projet doit embarquer son workflow (ou a déjà son propre PM) :
```bash
cd /chemin/du/projet
~/src/pm-v3/install.sh --scope project --with-rules --adapter generic            # registre local (adapters/generic)
~/src/pm-v3/install.sh --scope project --with-rules --adapter gitlab-multi-team  # issues GitLab
```
- Écrit dans `./.claude/` : skill, agents, règles, `project-manager.config.json` et `.profile.md`. Jamais `CLAUDE.md`, `settings*.json`, les hooks ni la politique du projet.
- Refuse si une opération git est en cours ou si des chemins cibles ont des modifications non commitées (`--allow-dirty`).
- Vérifier : `python3 -I .claude/skills/project-manager/scripts/pm_config.py validate --root .`
- Ces fichiers font partie du dépôt : branche, commit et MR selon vos règles.
- Exemple GitLab : `adapters/gitlab-multi-team/` (configuration qui lit `<projet>`, `<intégration>` et les labels dans un tableau « Référentiel » de `CLAUDE.md`, profil de règles locales, exemple de tableau).

## 10. Mise à jour et retour arrière

- Clone direct (§ 5) : `git -C ~/.claude pull --ff-only`.
- Installation par l'installateur (§ 6, § 9) : `git -C ~/src/pm-v3 pull --ff-only` puis `./install.sh … --dry-run`, puis `./install.sh …` (les fichiers que le kit a installés et que vous n'avez pas modifiés sont mis à jour après sauvegarde).
- Retour arrière :
  ```bash
  ./rollback.sh --dest ~/.claude --dry-run
  ./rollback.sh --dest ~/.claude              # dernière exécution ; --dest <projet>/.claude pour un projet
  ./rollback.sh --dest ~/.claude --all        # désinstallation complète (toutes les exécutions, de la plus récente à la plus ancienne)
  ```
  Restaure les sauvegardes, supprime seulement les fichiers créés par le kit et restés identiques, lève le verrou d'une installation interrompue. Détails : `docs/ROLLBACK.md`. Migration depuis un PM existant ou depuis la V2 : `docs/MIGRATION.md`.

## 11. Limites et précautions de sécurité

- **Collision de nom** : un `project-manager` installé dans `~/.claude` masque celui d'un projet (précédence des skills). Pour un projet qui a son propre PM, installez par projet.
- Les tests fournis sont **statiques ou simulés** (bac à sable, faux serveur GitLab) : ils ne remplacent pas une vérification dans une vraie session Claude Code (`docs/INSTALL.md` § Vérification).
- Les garde-fous (règles, hook `review-guard`) sont des **contrôles de convenance** contre la dérive d'un agent coopératif, pas une barrière de sécurité. Les vraies barrières : branches protégées, merge humain, identité à moindre privilège. Une session CLI partagée avec des droits élevés n'est pas une barrière.
- Le kit ne lit jamais de secret et n'écrit jamais `settings.json`, les hooks ni la politique d'un projet ; fusionnez `templates/settings.kit.json` à la main, sans affaiblir des règles plus strictes.
- `CLAUDE.md` à la racine devient votre mémoire utilisateur après un clone direct : il est court et peut être vidé.
- Ne publiez jamais un `~/.claude` complet : seule la liste blanche du `.gitignore` est destinée à être versionnée.
- Liste complète : `docs/RISKS.md`.

## 12. Feuille de route — Claudex et orchestration multi-agents

Le PM fonctionne toujours sans Claudex ni Codex. Depuis 3.1.0-rc1, un **pilote opt-in** (`references/orchestration-pilot.md`, `scripts/pmx.py`, `docs/PILOT-CLAUDEX.md`) couvre une partie de la feuille de route, pour les projets à registre local uniquement. Interfaces : `skills/project-manager/references/extension-points.md` ; plan : `docs/EXTENSION-PLAN.md`.

| # | Élément | État en 3.1.0-rc1 |
|---|---|---|
| 1 | Validation en session réelle sur un projet jetable | **fait pour le pilote** : cycle complet réel sur un projet fictif ; adaptateurs `codex-cli` et `claude-cli` exercés en réel |
| 2 | Reprise d'exécution multi-agents fondée sur les fichiers existants | **pilote** : `pmx resume` (registre + journal d'exécution), interruption = tentative |
| 3 | Ressources et coûts déclaratifs | **partiel** : `max_parallel`, `max_attempts` ; aucun plafond de coût |
| 4 | Revues croisées | **pilote** : revue entre équipes en lecture seule ; la revue adversariale du plugin Codex n'est pas intégrée |
| 5 | Débat Claude–Codex | **pilote** : protocole Claudex rejoué par `pmx`, borné à 3 tours ; l'application Claudex (TTY) n'est pas pilotée |
| 6 | Planification multi-équipes pour le registre local | **pilote** : variante ledger d'I3 (WI parent/enfants, dépendances, collisions) |
| 7 | Worktrees parallèles et intégration conditionnelle | **pilote** : intégration **locale** sur une branche non protégée, sur accord explicite ; pas de preuve CI, pas de push ni de MR, merge vers les branches protégées toujours humain |

Invariants : registre unique, gates, Definition of Done, rédacteur unique de `ai_rules/`, un accord par opération sortante, aucun merge par l'IA.
