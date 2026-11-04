# Project Manager V3.3 — Phase A : architecture du cockpit

État : **proposition à valider**, sur une branche de développement locale. La V3.2 reste la version stable. Rien ici ne modifie `pmx`, le kit installé, les connexions ou les runs existants.

## 1. Objectif et limites de la phase A

Le cockpit montre l'état des équipes, des tâches, du pipeline, des décisions et de la sécurité d'un ou plusieurs projets. Il ne pilote rien.

| Dans la phase A | Hors de la phase A |
|---|---|
| Conception, modèle de données, API en lecture seule | Lecture de vrais runs par le cockpit |
| Prototype sur données fictives | Toute commande d'écriture vers `pmx` |
| Modèle de menace et critères de V3.3-B | Mise en œuvre de l'isolation |
| Profils de V3.3-C, inactifs | Activation des profils |

Le prototype est dans `cockpit/`. Le dépôt ne l'installe pas dans `~/.claude`.

## 2. Audit de `pmx` (kit V3.2, 3002 lignes)

### Commandes

| Effet | Commandes |
|---|---|
| Lecture seule | `status`, `evidence`, `debate show` |
| Écrivent dans le dépôt, sans lancer d'agent | `doctor` (fichier témoin temporaire), `start`, `decide`, `plan`, `reopen`, `stop-ack`, `tick` |
| Lancent des agents ou des conteneurs | `debate next`, `dispatch`, `wait`, `resume`, `verify`, `review run`, `integrate` |
| Arrêtent | `abort` |
| Interne | `_team` |

**Conséquence : le cockpit ne doit appeler aucune commande `pmx`.** `doctor` et `tick` écrivent, et `tick` peut déclencher un arrêt critique. Il lit des fichiers.

### États

| Domaine | Valeurs |
|---|---|
| Work item | `OPEN`, `IN_PROGRESS`, `READY_FOR_VERIFICATION`, `READY_FOR_REVIEW`, `BLOCKED`, `ESCALATED`, `STALE`, `DONE` |
| Tentative (`result`) | `done`, `failed`, `aborted`, `interrupted`, absent si en cours |
| Fin de tentative (`settled`) | `vérifiée`, `descendants arrêtés`, `non résolue`, `non vérifiée (pas de cgroup)` |
| Vérification | `PASS`, `FAIL`, `INCONCLUSIVE` |
| Revue | `APPROVE`, `CHANGES_REQUESTED`, `UNPARSEABLE`, plus `uncovered` |
| Arrêt critique | `IN_PROGRESS`, `STOPPED`, `UNRESOLVED`, plus `ack` (administratif) |
| Débat | `running`, `consensus`, `no_consensus`, `awaiting_human` |
| Plan | `proposed`, `approved` |

### Événements (`events.jsonl`)

| Famille | Événements |
|---|---|
| Cycle | `run_started`, `decision_recorded`, `plan_submitted`, `plan_approved`, `task_reopened` |
| Débat | `debate_turn_requested`, `debate_turn`, `debate_turn_failed`, `debate_closed` |
| Équipes | `team_started`, `team_process_begin`, `team_process_end`, `team_reported`, `team_finished`, `retry_decision` |
| Vérification, revue | `verified`, `verify_refused`, `review_requested`, `reviewed` |
| Intégration | `integration_dry_run`, `integration_failed`, `integration_refused`, `integration_conflict`, `integration_integrity_failed`, `integration_not_confirmed`, `integrated` |
| Arrêt | `critical_stop_begin`, `critical_abort`, `critical_stop_acknowledged` |
| Passerelle | `gateway_started`, `gateway_stopped`, `gateway_team_attached` |

### Sources et sensibilité

| Source | Usage prévu | Traitement |
|---|---|---|
| `ai_memory/runs/<run>/run.json` | État principal | Liste d'autorisation. Exclus : `os_user`, `tty`, `brief`, `report`, `pid` brut |
| `events.jsonl`, `stop-evidence.jsonl` | Chronologie, preuves | Champs autorisés seulement. Ligne finale incomplète ignorée et signalée |
| `ai_memory/WORK_ITEMS.md` | Statut des work items | Analyse défensive du format Markdown |
| `.claude/project-manager.config.json` | Mode, équipes | Champs autorisés |
| `/proc`, `cgroup.events`, `cgroup.procs` | Observation datée | Compteur seulement, jamais de ligne de commande à l'écran |
| Journaux, prompts, rapports, `*.claude-settings.json` | **Non lus** | Peuvent contenir du code client ou des secrets |

## 3. Architecture

```text
 Windows 11                          │  WSL2 (mode réseau mesuré : NAT)
                                     │
 ┌────────────────┐  HTTP loopback   │  ┌───────────────────────────────────────────┐
 │  Navigateur    │  GET, HEAD seuls │  │  Serveur du cockpit  127.0.0.1:8765        │
 │  (cockpit)     │◄─── cookie ─────►│  │  ┌──────────┐ ┌───────────┐ ┌───────────┐ │
 │  CSP stricte   │     de session   │  │  │ Contrôles│►│ Projection│►│ Masquage  │ │
 └────────────────┘  SSE : mises     │  │  │ Host,    │ │ par liste │ │ (2e       │ │
                     à jour          │  │  │ session  │ │ d'autor.  │ │ barrière) │ │
                                     │  │  └──────────┘ └─────▲─────┘ └───────────┘ │
                                     │  │          ┌──────────┴─────────┐           │
                                     │  │          │ Source de données  │           │
                                     │  │          ├────────────────────┤           │
                                     │  │          │ Prototype : fixture│           │
                                     │  │          │ Plus tard : fichiers (lecture) │
                                     │  │          └──────────▲─────────┘           │
                                     │  └─────────────────────┼─────────────────────┘
                                     │                 lecture│seule, aucun appel
                                     │  ┌─────────────────────┴─────────────────────┐
                                     │  │ pmx et les agents : écrivent run.json et   │
                                     │  │ events.jsonl, sans connaître le cockpit    │
                                     │  └───────────────────────────────────────────┘
```

**Flux, à sens unique :** `pmx` écrit ses fichiers ; le serveur les lit ; il projette ; le navigateur affiche. Aucun chemin ne va du navigateur vers `pmx`.

**Protections du serveur :**
- écoute sur une adresse de boucle locale, refus de démarrer sinon ;
- `GET` et `HEAD` seulement, toute autre méthode rend 405 ;
- jeton de session aléatoire, échangé contre un cookie `HttpOnly`, `SameSite=Strict` ;
- contrôle de `Host` et d'`Origin`, contre le rebinding DNS ;
- aucun chemin construit depuis une requête : table fixe de fichiers ;
- CSP sans ressource externe, aucun CORS ;
- nombre de flux limité, adresses non journalisées.

### Choix techniques

| Sujet | Recommandation | Alternatives écartées |
|---|---|---|
| Serveur | Python, bibliothèque standard : cohérent avec `pmx`, aucune dépendance | FastAPI, Node : dépendances à auditer |
| Interface | HTML et JavaScript sans framework, sans compilation | React : chaîne de build disproportionnée |
| Direct | Server-Sent Events, instantané au moindre doute | WebSocket : bidirectionnel, donc une voie d'écriture inutile |
| Données | Lecture de fichiers, avec garde de schéma | `pmx status` : texte pour humains ; `tick` : écrit |
| Emplacement | Serveur dans WSL, navigateur Windows | Service Windows : franchit la frontière sans raison |
| Installation | Opt-in, séparée du kit | Dans `~/.claude` : élargit la surface du kit |

## 4. Modèle de données (`pm-cockpit/1`)

```text
Snapshot { schema, source, read_only, instance, seq, generated, projects[] }
Project  { id, name, backend, mode, profile, profile_active, source, runs[] }
Run      { id, title, parent_wi, created, updated, observed_at, source, source_note, base,
           pipeline[], teams[], tasks[], decisions[], security, events[] }
Phase    { key, label, state, detail }
Team     { name, adapter, role, task, cgroup, processes, observed_at }
Task     { key, wi, title, team, status, files[], depends_on[], budget, commit, blocker,
           attempts[], verify, review }
Attempt  { n, adapter, branch, worktree, started, ended, result, liveness, observed_at, settled, cgroup }
Verify   { verdict, commit, runner, tests, failed, ts }
Review   { verdict, by, commit, uncovered[], findings, ts }
Decision { ts, kind, by, text }
Security { stop { state, reason, ack_by }, items[] { label, value, proof, note } }
Event    { seq, ts, kind, task, severity, text }
```

**Règles du modèle :**
1. **Liste d'autorisation :** tout champ non prévu est retiré, avant tout masquage.
2. **Un état inconnu reste inconnu :** une valeur non reconnue devient `{value: "UNKNOWN", raw}`. Elle n'est jamais convertie en succès.
3. **Toute observation est datée :** `observed_at` accompagne chaque constat sur un processus.
4. **Niveau de preuve explicite :** `OBSERVED`, `DECLARED` ou `NOT_MEASURED`.
5. **Aucun verdict global « sécurisé ».**
6. **Verdict technique et acquittement restent deux champs distincts.**

**Dérivation du pipeline :** demande → débat → décision → plan → équipes → vérification Docker → revue → intégration à blanc → intégration. Chaque étape vient de champs précis de `run.json` ; sans preuve, elle reste `pending` ou `UNKNOWN`.

## 5. API en lecture seule

| Route | Rôle |
|---|---|
| `GET /auth?t=<jeton>&v=<vue>` | Échange le jeton contre le cookie, puis redirige |
| `GET /`, `/app.js`, `/app.css` | Interface, table fixe |
| `GET /api/v1/snapshot` | État complet, projeté et masqué |
| `GET /api/v1/stream` | Flux SSE : `hello`, `update`, battements |

Réponses d'erreur : 401 sans session, 403 pour `Host` ou `Origin` refusés, 404 hors table, 405 pour toute écriture, 503 si trop de flux.

**Favicon, avertissement connu et accepté :** Firefox tente automatiquement de charger `/favicon.ico`, et la CSP actuelle refuse cette ressource avant tout envoi au serveur.

- Ce refus est attendu.
- Aucun chargement de favicon n'est autorisé : ni `img-src`, ni route `/favicon.ico`, ni déclaration dans le HTML.
- Le cockpit reste fonctionnel, et l'onglet garde l'icône par défaut du navigateur.
- L'avertissement dans la console est connu et accepté.
- Aucun assouplissement de la CSP n'est prévu pour ce motif. Une icône `data:` est elle aussi refusée par `default-src 'none'`.

**Masquage, seconde barrière :** jetons, clés, `motcle=valeur`, chemins personnels, e-mails, adresses privées. Ce filtre ne remplace pas la liste d'autorisation : aucun filtre à motifs n'est exhaustif.

## 6. Direct, reprise et états inconnus

| Situation | Comportement |
|---|---|
| Fonctionnement normal | `update` déclenche un nouvel instantané ; le numéro de séquence est croissant |
| Flux coupé | Indicateur « Hors ligne », bandeau avec l'heure des dernières données, reconnexion du navigateur |
| Reconnexion | `hello` compare instance et séquence ; au moindre écart, nouvel instantané |
| Serveur redémarré | Nouvelle instance, donc nouvel instantané |
| Aucune observation récente | Bandeau : « cet état peut être dépassé » (seuil de 300 s, à régler) |
| `run.json` illisible ou en cours d'écriture | Dernière version valide marquée `PARTIAL`, ou `UNREADABLE` |
| Ligne finale de journal incomplète | Ignorée et signalée |
| Schéma inconnu | Valeurs `UNKNOWN`, sans plantage |
| Manager mort pendant un arrêt | `stop.state = IN_PROGRESS` affiché « Arrêt interrompu » |
| Agent de débat ou de revue orphelin | Observation du cgroup (source réelle, à valider) |

Le cockpit est **sans état** : il peut s'arrêter à tout moment sans effet sur un run, et il n'a rien à reprendre.

## 7. Vues

Captures du prototype dans `maquettes/`, données fictives.

| Vue | Question traitée | Capture |
|---|---|---|
| Projets | Où en sont mes projets ? | `projets.png` |
| Équipes | Qui travaille, avec combien de processus observés ? | `equipes.png` |
| Tâches | Quel état, quelle tentative, quelle preuve ? | `taches.png`, `etats-inconnus.png`, `telephone.png` |
| Pipeline | À quelle étape est ce run ? | `pipeline.png` |
| Décisions | Qui a décidé quoi ? | `decisions-arret.png` |
| Sécurité | Qu'est-ce qui est prouvé, et qu'est-ce qui ne l'est pas ? | `securite-non-resolu.png` |

Les états passent par un libellé et une couleur, jamais la couleur seule. L'interface suit le thème clair ou sombre du système.

## 8. Lancer le prototype

```bash
python3 -I -B cockpit/server.py --port 8765
```

Ouvrir l'adresse affichée. Les données fictives évoluent toutes les 4 s, puis le scénario recommence. « Simuler une coupure » ne coupe que le flux de ce navigateur.

## 9. Plan de tests

| Domaine | Test | État |
|---|---|---|
| Boucle locale | Refus de `0.0.0.0`, `::` et d'une adresse publique | Automatisé |
| Lecture seule | `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, `TRACE` rendent 405 | Automatisé |
| Session | Jeton faux, absence de cookie, redirection ouverte | Automatisé |
| Rebinding | `Host` et `Origin` étrangers | Automatisé |
| Fichiers | Traversée de chemins, encodages | Automatisé |
| Fuites | Champs non autorisés, masquage | Automatisé |
| États inconnus | Valeurs futures, absence de donnée | Automatisé |
| Direct | Séquence croissante, resynchronisation, limite de flux | Automatisé |
| Isolation du code | Aucun import de `pmx` ou `subprocess`, aucune écriture | Automatisé (analyse du code) |
| Interface | Aucune ressource externe, aucune insertion HTML | Automatisé (analyse du code) |
| Rendu | Titre hostile en texte, largeur téléphone | Contrôlé sur captures |
| Accès depuis Firefox Windows | Ouverture de la page par l'adresse locale | Constaté (observation visuelle) |
| Thème clair | Affichage sur Firefox Windows | Constaté (observation visuelle) |
| Thème sombre | Affichage sur Firefox Windows | Constaté (observation visuelle) |
| Simulation de coupure | Bandeau et statut hors ligne | Constaté (observation visuelle) |
| **Rétablissement du flux après coupure** | Le flux reprend, et les données se mettent à jour | **Non vérifié** |
| **Reconnexion automatique** | Après une véritable interruption réseau | **Non vérifié** |
| **Accès depuis un autre compte Windows** | Via le relais WSL : le port répond-il, le jeton bloque-t-il ? | **Non vérifié** |
| **Lecture de copies de vrais runs** | `run.json` tronqué, écriture concurrente, grands journaux | **Non vérifié, non implémenté** |
| Avertissement CSP du favicon | Refus attendu de `/favicon.ico` en console | Connu, accepté et documenté ; CSP figée par test automatisé |

## 10. Analyse des risques

| Risque | Niveau | Mesure | Reste |
|---|---|---|---|
| Fuite d'un secret à l'écran | Élevé | Liste d'autorisation, journaux et prompts non lus, masquage | Un secret dans un titre autorisé peut échapper au filtre |
| Autre site interrogeant le serveur | Moyen | `Host`, `Origin`, `SameSite=Strict`, pas de CORS | Faille éventuelle du navigateur |
| Autre processus local | Moyen | Jeton de session | Un processus du même utilisateur peut lire la mémoire ou la sortie du serveur |
| Exposition par le relais WSL2 vers Windows | Moyen | Jeton, écoute en boucle locale | **Non mesuré** |
| Fausse impression de sécurité | Élevé | Niveau de preuve, aucun verdict global, données datées | Lecture humaine |
| État périmé pris pour réel | Moyen | Observations datées, bandeaux | Seuil à régler |
| Injection par contenu d'agent | Moyen | `textContent` seul, CSP | Couvert sur le prototype seulement |
| Glissement vers une commande d'écriture | Élevé | Aucune route d'écriture, test bloquant | Décision à reprendre si le besoin vient |
| Couplage au format interne de `pmx` | Moyen | Garde de schéma, `UNKNOWN` | À réévaluer avec un export stable |
| Déni de service local | Faible | Limite de flux, plafonds de taille | Non testé sous charge |

## 11. Étapes suivantes, à décider

1. Vous testez le prototype depuis votre navigateur Windows.
2. Adaptateur en lecture seule sur de vrais runs, d'abord sur des copies. Il exigera sa propre liste d'autorisation et ses tests.
3. V3.3-B, selon `ISOLATION-V33B.md`.
4. V3.3-C, selon `PROFILS-V33C.md`.

Aucune de ces étapes n'est lancée.
