# Risques résiduels

| # | Risque | Nature | Effet possible | Atténuation | Décision liée |
|---|---|---|---|---|---|
| K1 | Aucune validation en session Claude Code réelle : chargement du skill, des règles, routage en langage naturel, délégation, reprise | limite de test | comportement réel différent des contrôles statiques | vérification manuelle `INSTALL.md` § 6 sur un projet jetable avant tout projet réel | — |
| K2 | Collision `project-manager` personnel/projet | précédence documentée | le skill personnel masque celui du projet | installation par projet ; refus par défaut de l'installateur | H1 |
| K3 | Auto-activation large (description) | conception | le PM s'invite sur des demandes simples | intention « question seule » ; garde-fou session-feature ; option description étroite | H3 |
| K4 | Garde-fou session-feature fondé sur des indices (brief, worktree lié) | heuristique | PM lancé dans une session-feature ouverte autrement | consigne textuelle conservée ; feature-lead sans accès au skill (`disallowedTools: Skill`) | — |
| K5 | `review-guard` filtre par motifs (liste blanche de préfixes + motifs interdits) | contrôle de convenance | contournement par une forme non prévue | reviewers sans outil d'écriture ; hooks du projet (verify-gate) toujours actifs ; barrières réelles = GitLab, merge humain | H8 |
| K6 | Configuration : lecture d'un référentiel Markdown | format | une modification du tableau casse la résolution | erreur explicite, jamais de valeur par défaut ; migrer vers `.claude/workflow.toml` avec L7.4 | H9 |
| K7 | Agents homonymes du projet pilote prioritaires sur ceux de la V3 tant que le dépôt n'est pas migré | précédence documentée | deux jeux d'agents divergents | migration complète ou maintien explicite | H2 |
| K8 | Mode multi-équipes en backend `ledger` | non implémenté | indisponible pour les projets ledger | interface I3 ; le PM propose la délégation mono-session | — |
| K9 | Protocole de nettoyage GitLab : liste des items clos lue en ligne | dépendance réseau | GitLab injoignable → nettoyage limité | items inconnus traités comme actifs | — |
| K10 | Règles `Write(path)` inopérantes dans le `settings.json` du projet pilote | constat documenté (hors kit) | protection par settings illusoire pour Write | `protect-files` compense ; correction par un lot PoC séparé | H5 |
| K11 | L'absence d'identifiants n'est pas une barrière ; session glab Owner partagée | contexte | un agent pourrait techniquement écrire sur GitLab | accords par opération, hooks, branches protégées, merge humain ; identité agent à moindre privilège (futur) | — |
| K12 | Tests de l'installateur sous Linux/WSL uniquement | portabilité | `sed -i`, `sha256sum` différents sous macOS | documenté ; tests à rejouer sur la plateforme cible | — |
| K13 | Simulation GitLab : faux serveur et glab 1.53 | limite de test | autre version de glab → requêtes différentes | contrôle de transitions, pas de contrat d'API complet | — |
| K14 | Descriptions longues des agents V2 repris | budget de contexte | listes d'agents tronquées | raccourcissement possible sans changement de comportement | — |
