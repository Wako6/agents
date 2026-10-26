# Profil projet — exemple « GitLab multi-équipes avec preuve de test »

> Exemple anonymisé, issu du projet pilote du Project Manager V3. À copier dans `<dépôt>/.claude/project-manager.profile.md` et à adapter. Un profil **ajoute** des règles locales ; il n'en retire aucune du skill.

## Sources uniques
- `<projet>`, `<intégration>`, labels d'état : `CLAUDE.md` § Référentiel (lu par le PM via la configuration ; un hook du projet peut le lire aussi). Toute autre copie technique de ces valeurs (ex. politique d'un hook) se modifie dans le même commit, par un humain.
- Registre : issues GitLab (une décision `ai_rules/` du projet devrait l'acter). Pas de `WORK_ITEMS.md` ni `WI_COUNTER.lock`.
- Branche de production : jamais base, jamais cible.

## Preuve de test (si le projet a un hook de preuve)
- Commande : celle de `proof.command` (ex. `record-verification.sh`, sans argument, exécutée avec l'environnement du worktree activé).
- `tests` et `review` exigent la preuve PASS sur l'arbre courant ; si la preuve est liée à `HEAD`, la relancer **après chaque commit**, avant toute demande de push.
- Un hook de garde est un contrôle de convenance, pas une barrière de sécurité. Barrières réelles : branches protégées, merge humain, identité à moindre privilège. Une session CLI partagée avec des droits élevés n'est pas une barrière.
- Mode du hook (ex. `legacy` / `shadow` / `enforce`) : modifié par un humain seul.

## Forme des opérations sortantes (si le hook l'exige)
`git push`, création/mise à jour de MR, écritures API, labels `tests`/`review` : commande simple et littérale, depuis la racine du worktree ; sans `cd … &&`, `timeout`, `env`, variable, `-C`, `bash -c`, `eval`, alias ni script (exception éventuelle : `cd "$(git rev-parse --show-toplevel)" && …`). Un refus du hook → réécrire en forme directe ; si elle est refusée → `blocked`, jamais de contournement.

## Environnement d'exécution
Un environnement (ex. `.venv`) par worktree, à sa racine, jamais partagé ; toute commande qui l'utilise l'active dans le même appel. Le feature-lead le crée après validation de son plan.

## Fichiers protégés (humain seul)
Hooks du projet, `.claude/settings*.json`, commande de test, fichier de preuve, `.gitignore`. Exécuter les scripts Python des hooks avec `-B`.

## Interdits locaux
`git stash` (pile partagée entre worktrees) ; remotes autres que `origin` ; `git push --force` ; merge par l'IA ; `git reset --hard` ; `rm -rf` ; lecture des variables CI/CD, jetons, clés.

## Multi-équipes
- Session lead = checkout principal ; une session par feature, option worktree, branche `feat/<slug>-<NN>` créée depuis `origin/<intégration>` (script du projet s'il existe).
- `ai_memory/REPO_STATE.md` écrit depuis la session lead uniquement (champ `active_issues`).
- Une feature ne touche que les fichiers de sa spec, plus ses notes `ai_memory/YYYY-MM-DD__ROLE-*__#NN.md`, ses documents `ai_doc/*#NN*` et la ligne `Statut:` de sa spec.
- La session lead n'entre jamais (`cd`) dans un worktree d'équipe : chemins absolus ou `git -C <worktree>` en lecture.

## GitLab injoignable
Mode local, actions à rejouer dans `ai_memory/PENDING_GITLAB.md`.
