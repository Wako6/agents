# Journal des arbitrages

## A. Arbitrages tranchés par les règles de fusion (pas de choix arbitraire)

| # | Divergence | Décision V3 | Règle appliquée |
|---|---|---|---|
| R1 | Registre : issues GitLab (V1) vs ledger local (V2) | un backend par projet, choisi par configuration ; jamais deux | 1, 6, « pas de second système » |
| R2 | 3 skills publics (V2) | 1 skill public ; problem-solver et memory-clean en protocoles internes | 3, 4 |
| R3 | Accord global (V2) vs accord par opération (V1) | accord par opération, partout | 10 |
| R4 | Reviewers et verifier avec Write (V2) vs inline (V1) | inline, sans Write | 10 |
| R5 | Triage des règles en un temps (V2) vs deux temps (V1) | deux temps, + champs natifs V2 | 1, 2, 10 |
| R6 | `django-reviewer` (V1) vs `django-reviewer-analyst` (V2) | un agent `django-reviewer` (nom V1, contenu fusionné) | 1, 5 |
| R7 | Règle globale imposant les IDs `WI-…` (V2) | règle globale neutre vis-à-vis du backend | 9 |
| R8 | explorer V2 réécrit/crée `CLAUDE.md` | création seulement si absent ; jamais de réécriture d'une ligne lue par une machine | 1, 10 |
| R9 | `review-guard` V2 permissif (`env`, HTTP en écriture, `wget`, `find -delete`, `git branch -D`) | durci | 10 |
| R10 | Paramètres du PoC dans le skill (V1) | adaptateur `adapters/gitlab-multi-team` (configuration + profil), valeurs référencées depuis `CLAUDE.md` § Référentiel | universalité, « pas de copie » |
| R11 | Installateur V2 : hybride de skill, masquage, interruption | corrigés (unité de skill, refus de masquage, verrou) | 10, contrainte « aucun remplacement automatique » |
| R12 | Runtime du django-reviewer : jetons de test demandés (V2) | jamais de jeton/secret ; GET local ou de test seulement | contraintes « aucun accès aux secrets » |

## B. Décisions humaines requises (options documentées, rien n'est tranché)

### H1 — Portée d'installation et collision de nom `project-manager` (bloquant pour toute installation)
Fait documenté : skills **personnel > projet** ; agents **projet > personnel**.
- **(a) recommandé** — installer la V3 **par projet** (`--scope project`) dans chaque dépôt qui l'adopte ; rien dans `~/.claude`. Dans le projet pilote, le remplacement du PM du dépôt passe par une branche `chore/*`, un commit et une MR (accords distincts), puisque ce sont des fichiers versionnés.
- (b) installer la V3 dans `~/.claude` pour les autres projets **sans** l'utiliser dans le projet pilote tant que le PM du projet pilote n'est pas remplacé — l'installateur refuse par défaut ce masquage depuis un dépôt qui a son propre `project-manager` (`--allow-shadowing` requis), mais le masquage s'appliquerait quand même dans le projet pilote ouvert plus tard : **déconseillé**.
- (c) renommer l'un des deux skills — contraire à « un seul skill public » ; non recommandé.

### H2 — Remplacement du PM du projet pilote (après H1)
Trois options :
- remplacement **complet** dans le dépôt : skill V3, adaptateur, agents V3 à la place des agents homonymes du projet pilote ;
- remplacement du **skill + adaptateur** seulement, en conservant les 7 agents du projet pilote, qui priment de toute façon dans ce projet. Plus prudent, mais les deux jeux d'agents divergent ;
- **différer**.

Dans tous les cas, l'opération passe par un lot dédié : commit et MR sur accords distincts, puis S7.

### H3 — Largeur de l'auto-activation
- V2 : activation sur toute demande de développement.
- V1 : déclencheurs explicites.
- La V3 reprend la largeur V2, plus le garde-fou de session-feature et l'intention « question seule → réponse directe ».
- **Option** : une description plus étroite, proche de la V1, si l'utilisateur préfère n'invoquer le PM qu'explicitement. La description d'un skill est statique : elle ne peut pas varier selon le projet.

### H4 — Accès direct aux anciens protocoles
- Choix V3 : protocoles internes, aucune commande slash.
- **Option** : réintroduire `project-problem-solver` et `project-memory-clean` comme skills invocables par Claude seulement (`user-invocable: false`, champ documenté). On garderait un seul skill visible dans le menu `/`, au prix de trois skills installés.

### H5 — Permissions
- Fusion manuelle de `templates/settings.kit.json` : oui ou non, et à quel niveau.
- Pour le projet pilote, le PoC a déjà des règles plus strictes et ne doit **pas** être affaibli.
- Ses règles `Write(path)` sont inopérantes (constat documenté) : à corriger côté PoC, par un lot séparé, sur décision humaine.

### H6 — Règles natives générées
Entrées de `ai_rules/` à passer en `Autoload: yes`, avec leurs `Paths`, projet par projet. Défaut : aucune, donc aucun effet.

### H7 — Agents optionnels et MCP
- Flutter et SPIP : `--with-optional` ou non.
- `frontend-reviewer-analyst` : configurer chrome-devtools, ou ne pas l'utiliser.

### H8 — Reviewers en lecture seule stricte
- La V3 limite le runtime des reviewers aux requêtes GET et HEAD. C'est plus strict que la V2.
- Conséquence : les écritures d'API ne sont vérifiées que par les tests du projet.
- À accepter, ou à assouplir explicitement : par exemple, un environnement de test dédié et une liste blanche d'hôtes.

### H9 — Source unique du Référentiel du projet pilote
- Aujourd'hui, l'adaptateur lit le Référentiel dans `CLAUDE.md`.
- Au lot L7.4 (`.claude/workflow.toml`), la configuration devra désigner ce fichier à la place, pour éviter une quatrième copie.
- À planifier avec L7.4.
