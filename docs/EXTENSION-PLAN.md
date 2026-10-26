# Plan d'extension — Claudex et multi-agents (rien n'est implémenté)

Interfaces détaillées : `skills/project-manager/references/extension-points.md` (I1 à I7). Le PM fonctionne sans Claudex ni Codex ; chaque extension est détectée, proposée dans un plan, sans effet d'état propre, et ne relâche aucun accord.

## Ordre proposé (chaque étape = un lot, sur décision)

| Étape | Contenu | Pré-requis | Critère de sortie |
|---|---|---|---|
| E0 | Validation réelle de la V3 sur un projet jetable (`INSTALL.md` § 6) | H1 | 5 vérifications réelles PASS |
| E1 | **I7 reprise multi-agents** : formaliser la détection « délégation interrompue » sur les fichiers existants | E0 | reprise testée après interruption volontaire |
| E2 | **I6 ressources et coûts** : clé `budget` de la configuration (modèle/effort par rôle, plafond de délégations, sessions parallèles max) ; rapport de consommation observable | E0 | aucun changement de modèle silencieux |
| E3 | **I2 revues croisées** : enveloppe de `/codex:adversarial-review` → `ADVERSARIAL__<WI>__<n>.md` ; revue entre feature-leads via le PM | plugin installé | rapports triés par `review-triage.md` |
| E4 | **I1 Claudex** : adaptateur brief → `DEBATE__…brief.md` → Claudex → `DEBATE__….md` | Claudex disponible | désaccords toujours remontés à l'utilisateur |
| E5 | **I3 planification multi-équipes ledger** : registre partagé du checkout principal | spécification validée | parité fonctionnelle avec le mode GitLab |
| E6 | **I4 worktrees** : éventuels sous-agents `isolation: worktree` avec règles embarquées dans le brief | E5 | règles vérifiées dans le brief |
| E7 | **I5 intégration conditionnelle** : job CI rejouant les tests sur le commit livré + liste blanche `SEC-` | CI de preuve | merge humain conservé par défaut |

## Invariants à préserver à chaque étape

Registre unique · tiers et gates · circuit breakers · DoD · `ai_rules/` à rédacteur unique et triage en deux temps · un accord par opération sortante · aucun merge par l'IA · aucun accès aux secrets · garde-fous des projets intacts · fonctionnement identique sans extension.
