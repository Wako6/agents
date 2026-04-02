# Matrice de Tests

## Tests automatisés existants

### `ibootstrap/tests/test_views.py`
Couvre:
- présence du `ContextMixin` dans les vues template/detail
- récupération des champs et activation recherche dans la list view
- tri et filtrage de queryset
- sélection des templates
- getters de configuration modal
- getters permissions/url/titres
- logique champs sélectionnables et champs sélectionnés
- options export CSV et génération des en-têtes
- complétude du contexte list view
- déclenchement réponse CSV via paramètre GET
- suppression en succès et gestion `ProtectedError`

### `ibootstrap/tests/test_storage.py`
Couvre:
- configuration stockage privé par défaut/personnalisée
- service fichier avec réponse standard
- réponse non modifiée (`If-Modified-Since`)
- cas bord non trouvé / fichier absent
- callback permission en refus/acceptation
- mode téléchargement forcé (`attachment=True`)

### `ibootstrap/tests/test_emails.py`
Couvre:
- modes d'initialisation de `EmailNotification`
- génération d'URL absolue
- `send_mail` avec commit true/false
- comportement `send_notification`

## Tests additionnels recommandés
- template tags:
  - branches `search_field` selon type de champ modèle
  - ordre et mode debug de `ibs_pipeline`
- formulaires:
  - cas limites validation MIME favicon
- widgets:
  - parsing invalide/partiel de date-heure dans `value_from_datadict`
- modèles:
  - nettoyage filesystem sur remplacement de fichiers `SiteConfig.save()`
- exports:
  - réponse streaming sur dataset > `ROW_LIMIT`
