# Installation — Project Manager V3 Unified

> Le `README.md` à la racine donne les procédures pas à pas. Ce document détaille les options et les contrôles.

## Prérequis
- Claude Code récent (champs utilisés : `disallowedTools`, `hooks` dans le frontmatter des agents, `${CLAUDE_SKILL_DIR}`, règles `.claude/rules/` avec `paths:`).
- `bash`, `git`, `python3` (≥ 3.8, aucune dépendance), `sha256sum`, `find`, `awk`, `sed` (Linux, WSL ; macOS : voir les limites dans `RISKS.md`).

## Trois façons d'installer

| Situation | Méthode |
|---|---|
| `~/.claude` n'existe pas, ou est vide | clone direct de la branche `claude` dans `~/.claude` (README § 5) |
| `~/.claude` existe déjà (réglages, agents, skills…) | clone dans un dossier séparé, puis `install.sh --scope user` (non destructif) (README § 6) |
| un projet seulement | `install.sh --scope project` depuis le dépôt du projet (README § 9) |

## Options de `install.sh`
```
--scope user|project   destination ~/.claude (défaut) ou <dépôt>/.claude
--dest DIR             destination explicite
--dry-run              plan et contrôles, aucune écriture
--merge | --force      conflit → dépose <fichier>.kit-new | sauvegarde puis écrase
--with-optional        agents optionnels (optional-agents/)
--with-rules           règle globale (rules/) ; en scope projet + templates/project-rules/
--adapter NAME         scope projet : adapters/NAME/project-manager.{config.json,profile.md}
--allow-shadowing      scope user : accepter qu'un project-manager personnel masque celui d'un projet
--allow-dirty          scope projet : accepter des modifications non commitées sur les chemins écrits
```

## Contrôles effectués avant toute écriture
Dépendances · droits d'écriture · installation précédente interrompue (verrou) · opération git en cours · chemins cibles modifiés non commités · chemins protégés (jamais `settings*.json`, `hooks/` du projet, `policy.json`, `test-command`, `CLAUDE.md`, `.mcp.json`) · masquage d'un `project-manager` de projet par un skill personnel · skill étranger présent (le skill est traité comme une unité : aucun fichier n'est mélangé) · clone direct (kit déjà à l'emplacement cible → rien à faire).

## Configuration d'un projet
- Projet neuf : `adapters/generic/project-manager.config.json` → `.claude/project-manager.config.json` (registre local `ledger`).
- Projet GitLab multi-équipes : `adapters/gitlab-multi-team/` (configuration, profil, exemple de tableau Référentiel).
- Vérifier : `python3 -I .claude/skills/project-manager/scripts/pm_config.py validate --root .` (ou le chemin du skill dans `~/.claude`).

## Compléments manuels (jamais automatisés)
- Permissions : `templates/settings.kit.json` (générique). Ne jamais affaiblir des règles plus strictes déjà présentes.
- `CLAUDE.md` d'un projet : `templates/CLAUDE.md.template` s'il n'existe pas.
- Règles natives générées après décision `Autoload` : `rules_sync.py --check` puis `--write` (le PM le fait à la clôture).
- chrome-devtools (frontend-reviewer) : `templates/mcp.chrome-devtools.json`.

## Vérification dans une vraie session (non couverte par les tests automatiques)
1. `/agents` : les 12 rôles du kit sont visibles (les agents d'un projet priment sur ceux de l'utilisateur).
2. `/project-manager` : le skill lit la configuration puis le runbook ; un projet sans configuration déclenche une question, jamais la création d'un registre.
3. `/memory` : la règle `00-kit-workflow` est chargée.
4. Demander à un reviewer de modifier un fichier → refus (pas d'outil Write ; hook `REVIEW-GUARD`).
5. Un work item `simple` sans Codex/Claudex va jusqu'au bout sans les mentionner.
