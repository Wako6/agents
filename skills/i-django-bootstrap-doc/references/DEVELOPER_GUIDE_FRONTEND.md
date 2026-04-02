# Guide Développeur Frontend

## JavaScript `ibs-*` (intégration frontend)

Les fichiers `ibootstrap/static/js/ibs-*.js` font partie de l'API d'intégration de la librairie. Ils pilotent le cycle de vie DOM principal + modal.

## Règle d'or: toujours encapsuler vos initialisations JS dans `docReady(...)`

Convention recommandée pour ce projet:
- Toute initialisation de comportement JS doit être déclenchée depuis `docReady(...)`.
- Avec le mode modal, les scripts injectés sont rechargés via `ibsLoadScript(...)`.
- Le contenu encapsulé dans `docReady(...)` est donc exécuté de manière fiable, à la fois:
  - sur les pages classiques (DOM principal)
  - dans le contenu modal injecté dynamiquement.

Pattern recommandé:
```javascript
docReady(function () {
  // binder événements, initialiser composants, etc.
});
```

## 1) `docReady(...)` (`ibs-lib.js`) : point d'entrée incontournable
- Fonction globale: `docReady(callback[, context])`
- Contrat:
  - exécute `callback` quand le DOM est prêt (`DOMContentLoaded` / `load`)
  - si le DOM est déjà prêt, exécute de manière asynchrone immédiate
  - garantit l'ordre des callbacks enregistrés

## 2) Cycle modal (`ibs-modal.js`)
- Fonctions utilitaires clés:
  - `ibsLoadScript(oldScript)`: recharge/active les balises `<script>` injectées
  - `setInnerHTML(modal, html)`: insère le HTML dans `.modal-content` et exécute les scripts dans le bon ordre (`src` puis inline)
  - `loadModal(modal, url, callback)`: charge une URL dans la modal, gère loader/erreur/show/update
  - `loadBackUrl(backUrl)`: gère la navigation retour dans la modal
- Variables d'état utilisées:
  - `modalBackUrlList`, `modalRefreshPage`, `modalRefreshNewPage`, `modalSuccessUrl`
- Événements custom émis:
  - `ibs.modal.load`: début de chargement modal
  - `ibs.modal.loaded`: fin de chargement modal (contenu injecté + scripts exécutés)

Point d'extension recommandé: brancher vos ré-initialisations de composants dynamiques sur `ibs.modal.loaded`.

Exemple:
```javascript
document.getElementById('body-modal').addEventListener('ibs.modal.loaded', function () {
  // réinitialiser plugins/comportements dans le contenu modal injecté
});
```

## 3) Initialisation des actions modal (`ibs-init-modal.js`)
- `.in-modal`: ouvre lien/bouton dans `#body-modal` via `loadModal(...)`
- `form.form-in-modal`: intercepte le submit, envoie `GET/POST` via XHR, puis réinjecte le HTML via `setInnerHTML(...)`

En pratique: tout lien/formulaire destiné au flux modal doit respecter ces classes.

## 4) Widget colonnes sélectionnables (`ibs-widget-selected-fields.js`)
- Gère l'UI de transfert/réordonnancement entre:
  - `#available_c`
  - `#selected_c`
- Boutons supportés:
  - ajout/retrait, montée/descente, top/bottom, validation (`.ibs-btn-submit` sélectionne toutes les options)
- Événement custom émis:
  - `ibs.selectfield.loaded`

## 5) Initialisation globale (`main.js`)
- `loadInlineFormset()`: ajout dynamique d'items de formset inline
- `password_mask()`: bouton afficher/masquer sur champs password
- `initMain`: appelé via `docReady(initMain)`

## Règle pratique d'intégration
1. Initialisation page globale: via `docReady(...)`.
2. Initialisation contenu modal injecté: via listener `ibs.modal.loaded`.
3. Pour les liens/formulaires modaux: classes `.in-modal` et `.form-in-modal`.
