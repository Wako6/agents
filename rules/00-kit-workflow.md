# Workflow multi-agents (règle globale — Project Manager V3 Unified)

Invariants valables dans tout dépôt piloté par `/project-manager`. Courts et peu nombreux : le détail vit dans le skill. Une règle de projet peut être **plus stricte**, jamais plus permissive.

- **Orchestration** : la session principale (session lead) orchestre ; un sous-agent exécute sa mission bornée et rend un seul rapport. Il n'invoque jamais `/project-manager` et ne lance pas d'orchestration. Une session de feature-lead n'exécute pas le PM.
- **Registre unique** : chaque projet a UN registre de work items, fixé par `.claude/project-manager.config.json` — registre local (`ai_memory/WORK_ITEMS.md`, identifiants `WI-YYYYMMDD-BSLUG-###`) **ou** issues GitLab (identifiants `#NN`, un seul label d'état). Jamais les deux ; en cas de doute, demander.
- **Mémoire du dépôt** : `ai_memory/` = état opérationnel et notes de rôle `ai_memory/YYYY-MM-DD__ROLE-<rôle>__<WI>.md` ; `ai_doc/` = analyses et rapports ; `ai_rules/` = connaissance durable, rédacteur unique `rules-curator`, sur brief du manager et après validation humaine.
- **Validation humaine** : plan confirmé avant toute délégation `medium`/`complex` ; **un accord explicite par opération sortante** (`git commit`, `git push`, création de MR/PR ou d'issue, toute écriture distante), qui ne vaut jamais pour l'opération suivante ; **aucun merge par l'IA**.
- **Preuves, pas déclarations** : un work item n'est terminé qu'avec une preuve d'exécution consignée (sortie de commande, test ; preuve du projet si une commande de preuve est configurée).
- **Garde-fous et secrets** : ne jamais modifier les hooks, réglages, politiques ou fichiers de preuve du projet ; ne jamais lire de jeton, secret, clé ni valeur de variable CI/CD.
- **Langue** : français avec l'utilisateur ; anglais dans `ai_memory/`, `ai_rules/`, `ai_doc/`.
- **Règles natives** : `.claude/rules/ai-rules*.md` sont **générés** depuis `ai_rules/` par `rules_sync.py` ; on modifie `ai_rules/` (via `rules-curator`), jamais ces fichiers.
