# Project Manager V3.3-C — Profils de confidentialité

État : **préparation, non activée**. Ni `pmx` ni le cockpit ne lisent ces profils. Le champ `profile` du prototype n'est qu'un libellé fictif, marqué « non activé ».

## 1. Principes

1. **Un profil restreint, il n'élargit jamais.** Il ne peut pas affaiblir un garde-fou de V3.2.
2. **Refus par défaut :** une exigence non satisfaite empêche le lancement. Il n'y a aucun repli silencieux.
3. **Isolation locale et confidentialité sont deux sujets.** Un agent cloud envoie le code à son fournisseur, quelle que soit l'isolation du poste.
4. **Le classement d'un projet relève d'une décision humaine.** L'outil ne le déduit pas.
5. **Ces profils ne valent pas conformité.** La compatibilité avec un contrat, une politique d'entreprise ou une réglementation relève de votre organisation.

## 2. Profils proposés

| Exigence | `pilote-non-sensible` | `pro-standard` | `pro-confidentiel` | `pro-restreint` |
|---|---|---|---|---|
| Exemple | Projet fictif | Code interne sans donnée client | Code ou données clients | Données réglementées, réseau protégé |
| Fournisseurs de modèle | Abonnements existants | Liste approuvée par l'organisation | Contrat approuvé, nommé | **Aucun agent cloud** |
| Isolation (V3.3-B) | V3.2 actuelle | Option A validée | Option C validée | Hors de ce poste |
| Réseau des agents | Sandbox natif | Fournisseur approuvé seul | Fournisseur approuvé seul | Aucun |
| MCP et connecteurs | Aucun | Aucun | Aucun | Aucun |
| Données réelles dans les tests | Non | Non | Non | Non |
| Prompts et rapports conservés | Oui | Oui, durée à définir | Durée courte, purge documentée | Sans objet |
| Cockpit | Toutes les vues | Fichiers et titres visibles | Titres masqués par défaut | Non utilisé |
| Revue humaine avant intégration | Oui | Oui | Oui, plus revue de sécurité | Sans objet |
| Publication distante | Accord par opération | Accord par opération | Accord par opération | Sans objet |
| État sur ce poste | Disponible avec limites | **Bloqué : V3.3-B absente** | **Bloqué : V3.3-B absente** | **Refusé** |

Aucun profil n'autorise ni ne prépare l'accès à une infrastructure professionnelle protégée.

## 3. Format envisagé

Exemple, non lu par `pmx` :

```json
{
  "schema": "pm-profile/1",
  "profile": "pro-standard",
  "providers_allowed": ["à définir par l'organisation"],
  "isolation_required": "V33B-A",
  "network": "provider-only",
  "mcp": "none",
  "real_data_in_tests": false,
  "retention_days": null,
  "cockpit": { "show_files": true, "show_titles": true },
  "decided_by": "human:<nom>",
  "decided_on": null
}
```

Une valeur `null` ou absente **bloque** : elle ne vaut jamais accord.

## 4. Contrôles prévus à l'activation

| Id | Contrôle | Attendu |
|---|---|---|
| PC-01 | Projet sans profil | Comportement défini et documenté, sans élévation |
| PC-02 | Profil invalide, inconnu ou incomplet | Refus de lancement |
| PC-03 | Isolation exigée non validée | Refus de lancement |
| PC-04 | Fournisseur hors liste | Refus de lancement |
| PC-05 | Changement de profil par un agent | Fichier sensible, arrêt critique |
| PC-06 | Baisse de niveau | Confirmation humaine au terminal, consignée |
| PC-07 | Cockpit `pro-confidentiel` | Champs masqués absents de l'API, pas seulement de l'écran |
| PC-08 | Rétention | Purge prouvée, sans effacer les preuves requises |

## 5. Décisions attendues

1. Qui décide du classement d'un projet professionnel ?
2. Quels fournisseurs votre organisation autorise-t-elle, et pour quelles données ?
3. Quelles durées de conservation s'appliquent ?
