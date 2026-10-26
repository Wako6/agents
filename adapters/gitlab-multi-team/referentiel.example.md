## Référentiel (exemple à placer dans le CLAUDE.md du projet)

| Clé | Valeur | Usage |
|---|---|---|
| `<projet>` | `groupe/projet` | toute commande `glab` porte `-R <projet>` |
| `<intégration>` | `develop` | base de toute branche `feat/*` et `chore/*`, cible de toute MR ; la branche de production n'est jamais base ni cible |
| labels d'état | `todo` · `doing` · `tests` · `review` · `blocked` | un seul label d'état par issue ; `blocked` remplace l'état courant |
