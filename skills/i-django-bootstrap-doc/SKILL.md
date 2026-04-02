---
name: i-django-bootstrap-doc
description: Documentation de developpement pour le module Django i-django-bootstrap. Use quand Codex doit comprendre rapidement l architecture, les vues generiques, les modales, les exports CSV/XLS, les template tags, les widgets, l integration frontend, les services email ou stockage prive, ou avant d implementer une fonctionnalite basee sur ce module.
---

# i-django-bootstrap Doc

## Overview

Utiliser ce skill comme point d entree documentaire avant de coder avec `i-django-bootstrap`.
S appuyer d abord sur l index IA, puis ouvrir uniquement les references pertinentes pour limiter le contexte.

## Workflow

1. Lire `references/AI_INDEX.md` pour obtenir la carte rapide du module et les chemins de code importants.
2. Choisir ensuite la reference adaptee au besoin:
   - `references/DEVELOPER_GUIDE_BACKEND.md` pour l integration Django, les vues generiques, les contrats de recherche/tri, les exports, les pipelines, l email et le stockage prive.
   - `references/DEVELOPER_GUIDE_FRONTEND.md` pour `docReady(...)`, le cycle modal, `ibs.modal.loaded`, les classes `.in-modal` et `.form-in-modal`, et les widgets JS `ibs-*`.
   - `references/PROJECT_REFERENCE.md` pour la cartographie du depot, des modules Python, des templates, des assets statiques et des tests.
   - `references/TEST_MATRIX.md` pour la couverture existante et les zones a tester en priorite.
3. Verifier ensuite le code reel dans le depot consommateur si une question depend d une implementation locale ou d un override projet.

## Important Rules

- Commencer par `references/AI_INDEX.md` avant d ouvrir des references plus longues.
- Ne pas supposer un comportement frontend hors `docReady(...)` ou hors evenement `ibs.modal.loaded` tant que la documentation ne le confirme pas.
- Pour les listes, prendre en compte les contrats `search_*`, `order_by`, `csv_download`, `csv_all_fields` et `can_select_fields`.
- Pour les modales, verifier la semantique `refresh_page`, `refresh_modal` et `refresh_new_page`.
- Pour les integrations sensibles, verifier la doc puis le code source correspondant avant de modifier une API publique du module.

## Source Canonique

Le depot amont a utiliser pour resynchroniser la documentation est:

`ssh://git@git.ipeos.com:10022/ipeos/i-django-bootstrap.git`

Le dossier `references/` de ce skill contient une copie des fichiers `docs/*.md` du projet au moment de la creation ou de la mise a jour du skill.
