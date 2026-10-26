# F<n> — <titre court>

Issue: #NN (renseigné par le PM après création)
Statut: proposée | validée | livrée
Dépend de: [F…] (MR intégrée dans la branche d'intégration avant lancement) ou aucune
Tier: simple | medium | complex (complex obligatoire dès que ≥ 2 features tournent en parallèle)
Revue spécialisée: aucune | django-reviewer

## Objectif
Une phrase : ce que l'utilisateur final obtient.

## Périmètre
- …

## Hors périmètre (explicite)
- …

## Décisions arrêtées
- [DÉCIDÉ] …
- [PROPOSÉ] … (à trancher par l'utilisateur avant « go »)

## Critères d'acceptation (vérifiables)
1. Étant donné … quand … alors …
2. …

## Tests attendus
- unitaires : …
- intégration / vue : …
- commande : la commande de test du projet (`REPO_STATE.md` → `test_commands`), ex. `python manage.py test <app>`

## Fichiers probablement touchés
(exemple Django ci-dessous — remplacer par les chemins réels du projet)
`catalog/models.py`, `catalog/views.py`, `catalog/tests.py`, `catalog/migrations/`
(sert à détecter les collisions entre features parallèles)

## Points de vigilance
- …

## Message de commit recommandé
`feat(<app>): <résumé>` (#NN)
