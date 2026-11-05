# Project Manager V3.3-B — Modèle de menace et critères d'isolation

État : **conception seule, non lancée**. Poste visé : Windows 11 et WSL2, un seul utilisateur humain.

## 1. Point de départ mesuré

La V3.2 superpose le sandbox natif des CLI, les restrictions MCP, les cgroups et Docker pour les vérifications. Les agents restent des processus de **votre utilisateur Linux**. La V3.2 n'est donc pas une frontière forte, et reste destinée aux projets pilotes non sensibles.

Limites déjà documentées : connecteur Codex actif non mesuré, hooks Codex, projet approuvé, sous-agents, réglages administrés.

## 2. Biens à protéger

| Bien | Exemple | Gravité d'une fuite |
|---|---|---|
| Identifiants | `~/.ssh`, jetons Git, connexions Claude et Codex | Critique |
| Code et données professionnels | Dépôts clients, fichiers Windows | Critique |
| Connecteurs des comptes | Stockage distant, boutique, services tiers | Critique |
| Poste hôte | Fichiers Windows, interop, socket Docker | Élevée |
| Intégrité des dépôts | Branches, hooks, historique | Élevée |
| Preuves d'exécution | Journaux, verdicts, `stop-evidence.jsonl` | Moyenne |

## 3. Attaquants et scénarios

| Attaquant | Scénario | Protection actuelle | Écart |
|---|---|---|---|
| Injection de prompt dans un dépôt ou une dépendance | L'agent lit puis exfiltre | Lectures limitées au worktree, réseau du sandbox fermé | Le canal du fournisseur de modèle reste ouvert |
| Dépôt hostile | Hook, `.mcp.json`, `.codex/` | Réglages écartés, chemins sensibles | Mesuré pour Claude ; partiel pour Codex |
| Agent compromis | Sortie du sandbox | Sandbox natif | Même utilisateur, même noyau |
| Dépendance malveillante | Exécution pendant les tests | Docker sans réseau ni secrets | Le développement Codex a un shell sur l'hôte |
| Serveur MCP | Exécution hors sandbox | Désactivé | Dépend d'options de CLI |
| Faille du noyau ou de bubblewrap | Évasion | Aucune | Noyau WSL2 partagé |
| Erreur de manipulation | Mauvais projet, mauvaise branche | Validations humaines | Facteur humain |
| Autre compte local Windows | Accès au cockpit ou au relais WSL | Jeton | Non mesuré |

**Hors périmètre :** poste Windows déjà compromis, attaque matérielle, fournisseur de modèle lui-même. Tout code envoyé à un agent cloud sort du poste : **aucune isolation locale n'y change rien**, et c'est le sujet de V3.3-C.

## 4. Options

| Option | Frontière | Avantages | Limites | Avis |
|---|---|---|---|---|
| **A. Distribution WSL dédiée** et utilisateur séparé | Système de fichiers, utilisateur | Sans `/mnt`, sans interop, sans vos clés ; simple | **Noyau et VM partagés** avec vos autres distributions ; deuxième connexion aux CLI | **Recommandée en première étape** |
| **B. Agents en conteneur** | Espaces de noms | Adaptateur `docker` existant, passerelle réseau | Authentification par abonnement difficile en conteneur ; noyau partagé | Si l'authentification est résolue |
| **C. VM Hyper-V dédiée** | Hyperviseur | Frontière la plus forte | Édition de Windows à vérifier ; lourd à maintenir | Pour les projets confidentiels |
| **D. Poste ou machine distante** | Machine | Séparation réelle | Coût, hors « poste local » | Pour le niveau restreint |

**Recommandation :** A, avec un proxy de sortie sur liste d'autorisation, en gardant les sandbox natifs. C ensuite si un projet confidentiel le justifie. Une option n'est retenue qu'après mesure de ses critères.

## 5. Critères de validation

Chaque critère se mesure par un test reproductible, avec un agent factice puis une CLI réelle. **Un seul échec interdit de déclarer l'isolation validée pour ce niveau.**

| Id | Critère | Mesure | Attendu |
|---|---|---|---|
| IS-01 | Clés et jetons de l'utilisateur | Lire `~/.ssh` et les jetons de l'utilisateur principal | Refusé ou absent |
| IS-02 | Fichiers Windows | Lister `/mnt/c` | Absent |
| IS-03 | Interop | Exécuter `cmd.exe`, socket `/run/WSL` | Échec |
| IS-04 | Autres distributions | Accès à `/mnt/wsl`, `\\wsl$` | Absent |
| IS-05 | Docker | Socket et commande `docker` | Absents |
| IS-06 | Réseau sortant | Hôte non autorisé, adresse IP directe, DNS | Refusé et journalisé |
| IS-07 | Réseau local | Passerelle, autres machines, services de l'hôte, `127.0.0.1` Windows | Refusé |
| IS-08 | Séparation entre équipes | Lecture et écriture dans le worktree voisin | Refusé |
| IS-09 | Dépôt hostile | Hook, `.mcp.json`, `.codex/`, `.envrc`, script de test | Non exécuté hors contrôle |
| IS-10 | MCP et connecteurs | Sonde locale et témoin, pour Claude et Codex, sous-agents compris | Aucun serveur, témoin détecté |
| IS-11 | Connecteur Codex actif | Avec un connecteur de test dédié | Indisponible |
| IS-12 | Persistance | Fichier de démarrage, tâche planifiée, service utilisateur | Absent après redémarrage |
| IS-13 | Arrêt | Agent qui ignore SIGTERM, descendant hors groupe | Arrêt prouvé, sinon `UNRESOLVED` |
| IS-14 | Ressources | Bombe de processus, mémoire, disque | Limité, hôte stable |
| IS-15 | Évasion volontaire | Sortie du cgroup, montage, `ptrace`, `setuid` | Échec |
| IS-16 | Fuite de secrets factices | Variables et fichiers témoins, dans journaux et rapports | Absents |
| IS-17 | Authentification | Connexion distincte et révocable | Les jetons de l'agent n'ouvrent pas ceux de l'utilisateur |
| IS-18 | Non-régression | Suites V3, orchestrateur, Docker, hybride, arrêt, MCP | Conformes |
| IS-19 | Limite assumée | Noyau partagé | **Documentée**, pas masquée |

**Risque résiduel à accepter explicitement :** un agent lit toujours sa propre connexion dans son environnement, et il peut transmettre ce qu'il lit au fournisseur du modèle.

## 6. Plan d'évolution

| Étape | Contenu | Sortie |
|---|---|---|
| B0 | Vos réponses (voir ci-dessous), mesures en lecture seule | Option choisie |
| B1 | Banc de critères avec agents factices, **écrit avant toute mise en œuvre** | Critères qui échouent sur la V3.2, ce qui montre l'écart |
| B2 | Distribution dédiée, créée et supprimable | IS-01 à IS-05 |
| B3 | Proxy de sortie | IS-06, IS-07 |
| B4 | `pmx` lance les agents dans cet environnement, derrière une option | IS-08 à IS-16 |
| B5 | CLI réelles sur projets fictifs | IS-17 à IS-19 |
| B6 | Revue, rapport, décision | GO, GO sous conditions ou STOP |

## 7. Décisions attendues avant B0

1. Quelle édition de Windows 11 ? Elle décide si l'option C est possible.
2. Acceptez-vous une deuxième connexion Claude et Codex, dans un environnement séparé ?
3. Créer une distribution WSL est une modification du poste : l'acceptez-vous ?
4. Votre poste ou votre employeur imposent-ils des règles sur la virtualisation ?
