# i-django-bootstrap: Index IA Rapide

## Objectif

Application de base Django qui fournit:

- Des templates de base Bootstrap
- Des vues génériques enrichies (messages, mode modal, export CSV/XLS, colonnes sélectionnables)
- Une configuration de site (`SiteConfig`) et son intégration admin
- Un service email (`EmailNotification`)
- Un helper de service de fichiers privés
- Des template tags pour affichage liste/recherche/tri et injection de pipelines

## Réponses rapides (pour agents)

- Installation/configuration: `README.md`
- Configuration d'app Django: `ibootstrap/apps.py`
- Modèles: `ibootstrap/models.py`
- Vues génériques (standard): `ibootstrap/generic/views.py`
- Vues génériques (modal): `ibootstrap/generic/modal.py`
- Comportements formulaire/contexte: `ibootstrap/generic/mixins.py`
- Chaîne export CSV/XLS: `ibootstrap/generic/export.py`, `ibootstrap/generic/excel.py`
- Template tags: `ibootstrap/templatetags/ibootstrap_tags.py`
- Intégration JavaScript (`docReady`, modal, widgets): `ibootstrap/static/js/ibs-lib.js`, `ibootstrap/static/js/ibs-modal.js`, `ibootstrap/static/js/ibs-init-modal.js`, `ibootstrap/static/js/ibs-widget-selected-fields.js`
- Widgets (date/heure/tinymce/fichier): `ibootstrap/widgets.py`
- UI de configuration du site courant: `ibootstrap/views.py`, `ibootstrap/forms.py`, `ibootstrap/templates/ibootstrap/current_site.html`
- Service email: `ibootstrap/emails.py`
- Stockage privé/service de fichier: `ibootstrap/storage.py`
- Commande d'initialisation des permissions: `ibootstrap/management/commands/init_perms.py`
- Tests: `ibootstrap/tests/test_views.py`, `ibootstrap/tests/test_storage.py`, `ibootstrap/tests/test_emails.py`

## Dépendances runtime

- Django `<5.3`
- crispy-forms + crispy-bootstrap5
- easy-thumbnails
- django-tinymce
- django-sekizai
- django-compressor
- django-sass-processor
- rules
- django-autocomplete-light
- openpyxl

Voir `setup.py` pour la liste exacte.

## Flux global

1. Démarrage app: `ibootstrap/apps.py` applique des défauts (crispy, thumbnails, TinyMCE, finder SASS).
2. Context processor: `ibootstrap/context_processors.py` injecte `CURRENT_SITE`, `DEFAULT_FORM_HELPER`, `IBS_VERSION`.
3. Vues:

- flux standard via `ibootstrap/generic/views.py` + `ibootstrap/generic/mixins.py`
- flux modal via `ibootstrap/generic/modal.py`

4. Flux listing:

- sélection de champs + recherche + tri + enrichissement du contexte
- export CSV/XLS optionnel (`XLSStreamingListMixin`)

5. Les templates consomment le contexte et les tags (`ibootstrap_tags`).

## Points d'extension principaux

- Sous-classer `ibootstrap.generic.views.ListView` pour les pages de liste.
- Activer les colonnes personnalisables avec `can_select_fields = True`.
- Activer l'export CSV avec `csv_button = True`.
- Utiliser les variantes de `ibootstrap.generic.modal` quand l'UI doit rester en modal.
- Ajouter des pipelines spécifiques dans `<votre_app>/pipelines.py` pour `{% ibs_pipeline %}`.

## Clés de configuration (settings)

- `IBS_PIPELINE_DEBUG`: affiche des marqueurs debug pipeline dans les templates (si `DEBUG=True`).
- `IBS_APP_VERSION`: force la version/fingerprint des assets.
- `ACCOUNT_DELETE`: exposé dans le contexte template.
- `PRIVATE_MEDIA_ROOT`, `PRIVATE_MEDIA_URL`: chemins du stockage privé.
- `DEFAULT_HTTP_PROTOCOL`: protocole des URLs absolues dans les emails.

## Carte de documentation

- Référence complète du projet: `docs/PROJECT_REFERENCE.md`
- Guide backend: `docs/DEVELOPER_GUIDE_BACKEND.md`
- Guide frontend: `docs/DEVELOPER_GUIDE_FRONTEND.md`
- Matrice de couverture tests: `docs/TEST_MATRIX.md`
