# Référence Projet

## Structure du dépôt
- `README.md`: installation + étapes d'intégration.
- `setup.py`: métadonnées package Python + dépendances.
- `runtests.py`: script de lancement des tests.
- `ibootstrap/`: package Django principal.

## Modules Python (`ibootstrap/`)

### Bootstrap applicatif et configuration
- `ibootstrap/__init__.py`
- Rôle: version package + déclaration app config.
- API publique: `get_version()`.

- `ibootstrap/apps.py`
- Rôle: configuration au démarrage de l'app.
- Comportement de `ready()`:
  - garantit la présence du finder SASS dans `STATICFILES_FINDERS`
  - applique des valeurs par défaut pour crispy, thumbnails, TinyMCE.

- `ibootstrap/context_processors.py`
- Rôle: variables globales injectées dans les templates.
- API publique:
  - `default_form_helper()`
  - `get_app_version()`
  - `generate_uid_from_version(version)`
  - `template_var(context)`.

### Modèles/admin/formulaires
- `ibootstrap/models.py`
- Modèles:
  - `SiteConfig`: configuration par site (logo, favicon, SEO).
  - `PersonalisedField`: persistance des colonnes choisies par utilisateur et content type.
- Signaux:
  - suppression des fichiers media sur suppression/remplacement de `SiteConfig`
  - création automatique de `SiteConfig` lors de la création d'un `Site`.

- `ibootstrap/admin.py`
- Rôle:
  - ajout de `SiteConfig` inline dans l'admin Django `Site`
  - enregistrement de l'admin `PersonalisedField`.

- `ibootstrap/forms.py`
- Formulaires:
  - `SiteConfigForm`: validation du type MIME favicon.
  - `CurrentSiteForm`: formulaire de configuration du site courant.
  - `SiteConfigFormset`: inline formset de configuration site.

### Framework de vues génériques
- `ibootstrap/generic/mixins.py`
- Mixins:
  - `ContextMixin`: variables de contexte communes.
  - `FormMixin`: branchement helper + messages succès/erreur.
  - `ModelFormMixin`, `TemplateResponseFormMixin`.

- `ibootstrap/generic/views.py`
- Classes génériques:
  - `TemplateView`, `ListView`, `FormView`, `CreateView`, `UpdateView`, `DeleteView`, `DetailView`.
- `ListView` ajoute:
  - tri piloté par la requête (`order_by`)
  - recherche dynamique via paramètres `search_*`
  - personnalisation persistée des colonnes (`PersonalisedField`)
  - intégration export CSV/XLS.

- `ibootstrap/generic/modal.py`
- Équivalents modaux des classes génériques.
- Ajout de la logique de rafraîchissement modal/page (`refresh_page`, `refresh_modal`, `refresh_new_page`).

- `ibootstrap/generic/export.py`
- `XLSListMixin`, `XLSStreamingListMixin`: sérialisation des données liste/queryset vers XLSX/CSV.

- `ibootstrap/generic/excel.py`
- Implémentations de réponses HTTP:
  - `ExcelResponse` (mémoire)
  - `StreamingExcelResponse` (streaming)
- Constantes limites Excel: `ROW_LIMIT`, `COL_LIMIT`.

### Utilitaires/services
- `ibootstrap/views.py`
- UI configuration du site courant (`CurrentSiteView`) + endpoint de sauvegarde des colonnes (`set_selected_fields`).

- `ibootstrap/emails.py`
- Service `EmailNotification`:
  - rendu sujet/corps via templates
  - emails texte + html
  - pièces jointes et fichiers joints
  - insertion optionnelle du logo du site.

- `ibootstrap/storage.py`
- `serve_private_file()` pour servir des fichiers privés avec callback d'autorisation optionnel.

- `ibootstrap/utils.py`
- Helpers `render_csv()` et `db_field_to_type()`.

- `ibootstrap/widgets.py`
- Widgets:
  - `SelectDateTimeWidget`
  - `SelectTimeWidget`
  - `SplitDateSelectTimeWidget`
  - `TextEditorWidget`
  - `DragAndDropImageWidget`.

- `ibootstrap/templatetags/ibootstrap_tags.py`
- Filtres/tags:
  - comparaison racine URL, helper paramètres GET, helper tri
  - rendu label/search/value de champs
  - `{% ibs_pipeline %}` pour injection dynamique.

### Permissions/rules/management
- `ibootstrap/rules.py`: enregistrement de permissions fallback rules.
- `ibootstrap/init_perms.py`: helper d'affectation de permissions Django à des groupes.
- `ibootstrap/management/commands/init_perms.py`: commande de scan des apps et exécution des hooks d'init permissions.

### Routage
- `ibootstrap/urls.py`
- Route: `set-fields/<ref>/` pour personnalisation colonnes.

## Templates
- Layouts de base:
  - `ibootstrap/templates/base.html`
  - `ibootstrap/templates/site_base.html`
  - `ibootstrap/templates/base-modal.html`
  - `ibootstrap/templates/body.html`
  - `ibootstrap/templates/body-modal.html`
- Pages génériques:
  - `list.html`, `list-modal.html`, `form.html`, `form-modal.html`, `delete.html`, `delete-modal.html`, `form-modal-success.html`
- Includes:
  - table de liste, sélecteur de colonnes, sélecteur langue, navbar, messages, fragments formset.
- Templates de tags:
  - `ibootstrap/templates/ibootstrap/tags/*.html`.

## Assets statiques
- JS principal: `ibootstrap/static/js/*.js`
- Scripts d'intégration `ibs-*`:
  - `ibootstrap/static/js/ibs-lib.js`: helper `docReady(...)`
  - `ibootstrap/static/js/ibs-modal.js`: moteur de chargement modal (AJAX + exécution scripts injectés)
  - `ibootstrap/static/js/ibs-init-modal.js`: binding des liens/formulaires modaux (`.in-modal`, `.form-in-modal`)
  - `ibootstrap/static/js/ibs-widget-selected-fields.js`: widget de sélection/réordonnancement des colonnes
- SCSS: `ibootstrap/static/scss/*.scss`
- Vendor bundles:
  - Bootstrap (`ibootstrap/static/vendor/bootstrap/**`)
  - Font Awesome (`ibootstrap/static/vendor/font-awesome/**`)
- Drapeaux de langue: `ibootstrap/static/flags/*.png`.

## Build frontend vendor
- `ibootstrap/package.json`: dépendances npm (`bootstrap`, `fontawesome`).
- `ibootstrap/gulpfile.js`: copie des assets vendor vers `static/vendor/`.

## i18n
- Répertoires locale présents pour: `de`, `en`, `es`, `fr`, `ht`.

## Tests
- `ibootstrap/tests/test_views.py`: comportements vues génériques.
- `ibootstrap/tests/test_storage.py`: service fichiers privés.
- `ibootstrap/tests/test_emails.py`: comportements notifications email.
