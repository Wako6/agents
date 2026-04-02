# Guide Développeur Backend

## Checklist d'intégration
1. Ajouter les dépendances et `ibootstrap` dans `INSTALLED_APPS`.
2. Ajouter le context processor: `ibootstrap.context_processors.template_var`.
3. Vérifier les static finders incluant SASS et compressor.
4. Configurer le backend d'authentification `rules` si permissions objet utilisées.
5. Lancer les migrations.

Référence: `README.md`.

## Politique de typage du dépôt
- Les fonctions/méthodes du package applicatif sont annotées.
- Les hooks Django fortement dynamiques (forms/views) restent pragmatiques.
- Les retours HTTP sont typés explicitement (`HttpResponse`, `HttpResponseRedirect`, `FileResponse`, etc.).
- Les méthodes métier utilisent des types concrets quand le contrat est stable (`str`, `bool`, `list[str]`, unions explicites).

## Patterns de vues génériques

### Pages standard
Utiliser les classes de `ibootstrap.generic.views`.

Exemple:
```python
from ibootstrap.generic.views import ListView

class UserListView(ListView):
    model = User
    fields = ["username", "first_name", "last_name"]
    csv_button = True
    can_select_fields = True
```

### Pages modal
Utiliser les classes de `ibootstrap.generic.modal`.

Exemple:
```python
from ibootstrap.generic.modal import CreateView

class UserCreateModal(CreateView):
    model = User
    fields = ["username", "email"]
```

## Contrats recherche + tri
- Les paramètres de recherche utilisent le préfixe `search_`.
- Le tri utilise le paramètre GET `order_by`.
- La personnalisation des colonnes est persistée dans `PersonalisedField`, clé `(content_type, user)`.

## Contrats export CSV/XLS
- `ListView.csv_button = True` active l'action de téléchargement.
- Le paramètre `csv_download` déclenche la réponse fichier.
- `csv_all_fields` peut inclure les champs sélectionnables non actifs.
- Sur gros volumes, la réponse bascule en streaming et peut forcer CSV au-delà de la limite de lignes Excel.

## Référence template tags
- `is_same_url_root(path, url)`
- `get_parameters(context, exclude_params)`
- `order_by(context, label, value, **kwargs)`
- `label_field(...)`
- `search_field(...)`
- `value_field(...)`
- `ibs_pipeline(context, pipeline_name, **kwargs)`

## Pipelines (`ibs_pipeline`)
Pour injecter des fragments applicatifs:
1. Créer `<app>/pipelines.py`.
2. Définir une fonction portant le nom du pipeline appelé dans le template.
3. Le paramètre optionnel `ibspipeline_index` permet de contrôler l'ordre d'affichage.

Exemple:
```python
def my_sidebar_pipeline(request, ibspipeline_index=10, **kwargs):
    return render(request, "myapp/pipelines/sidebar.html", kwargs)
```

## Service email
Classe: `ibootstrap.emails.EmailNotification`

Capacités:
- envoi sujet/corps direct
- rendu via templates sujet/texte/html
- pièces jointes
- inclusion optionnelle logo du site.

## Service fichiers privés
Fonction: `ibootstrap.storage.serve_private_file(request, field_file, check_permission_func=None, attachment=False)`

Bonnes pratiques:
- conserver le stockage hors document root public
- fournir un callback d'autorisation explicite pour les documents sensibles
- utiliser `attachment=True` pour forcer le téléchargement.

## Focus de tests recommandé pour les projets consommateurs
- combinaisons filtre + tri de listes
- sémantique de rafraîchissement modal (`refresh_page`/`refresh_modal`)
- export CSV pour querysets volumineux
- flux sauvegarde/réinitialisation des colonnes personnalisées
- fallback de rendu templates email.
