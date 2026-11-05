# V3.3-A2 — Rapport de sécurité de l'adaptateur

Ce rapport décrit des contrôles mesurés sur les surfaces testées. Il ne constitue pas une garantie d'absence de fuite, et le cockpit n'est pas prêt pour des projets sensibles.

## Barrières

| Étape | Contrôle |
|---|---|
| Extraction | Lit `run.json` et `events.jsonl` et, sur option, les statuts du registre, sans lien symbolique ; liste d'autorisation ; pseudonymes sans collision entre copies ; aucun texte libre |
| Écriture de la copie | Hors du dépôt, du run et de son projet ; tout ou rien ; dossier en 700, fichiers en 600 ; même validation que le lecteur |
| Dossier lu | Hors du dépôt, sans lien sur le chemin, sans allure de projet ou de run réel |
| Fichier lu | Nom strict, `O_NOFOLLOW`, fichier ordinaire, 2 Mio au plus |
| Contenu | Recherche de données sensibles, JSON strict, schéma fermé, relations vérifiées |
| Sortie de l'API | Liste d'autorisation et masquage déjà en place |
| Serveur | Boucle locale, `GET` et `HEAD`, session, `Host` et `Origin`, CSP inchangée |

**Refus sans repli :** un fichier non conforme n'apporte aucune donnée, et son motif est un code, jamais son contenu. Un dossier disparu vide l'affichage au lieu de laisser un ancien état présenté comme actuel.

**Aucun état inventé :** sans `--with-work-items`, la copie ne contient pas de statut de tâche, et elle ne contient jamais d'observation de processus. L'écran affiche donc « Inconnu », et ces points sont marqués `Non mesuré`.

## Limites

- **Horodatages conservés :** ils sont nécessaires à la chronologie, et peuvent suffire à recouper un run avec d'autres informations.
- **Structure conservée :** le nombre de tâches, de fichiers et d'événements reste visible.
- **Pseudonymes :** ils ne sont pas recoupables sans la clé, mais une structure très particulière pourrait rester reconnaissable.
- **Détection à motifs :** elle n'est pas exhaustive. Le schéma fermé reste la barrière principale, et n'accepte aucun texte libre.
- **Sorties de test :** l'extracteur les lit en mémoire pour en tirer deux nombres.
- **Extracteur :** c'est un outil manuel qui lit de vrais runs. Son lancement relève d'une décision humaine, projet par projet.
- **Processus du même utilisateur :** il peut lire les copies et obtenir le jeton affiché au lancement.
- **Sondes :** le test d'exécution repose sur le journal d'audit de Python, et ne voit pas un code natif. L'analyse du code ne voit pas un appel dynamique. Aucune des deux n'est une garantie.
- **`stop-evidence.jsonl` :** testé sur données synthétiques seulement ; un vrai fichier peut contenir une forme non prévue.
