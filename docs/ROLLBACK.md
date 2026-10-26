# Procédure de rollback

## Installation terminée
```bash
./rollback.sh --dest <DIR> --dry-run              # DIR = ~/.claude ou <dépôt>/.claude
./rollback.sh --dest <DIR>                        # dernière exécution ayant écrit
./rollback.sh --dest <DIR> --all                  # toutes les exécutions, de la plus récente à la plus ancienne
./rollback.sh --dest <DIR> --manifest <DIR>/.project-manager-v3-kit/manifest-<horodatage>.tsv
```
- Restaure les fichiers sauvegardés (mises à jour, `--force`).
- Supprime les fichiers créés **et** les `.kit-new` seulement s'ils sont identiques à ce qui a été installé ; tout fichier modifié depuis est conservé et signalé (`KEEP`).
- Retire seulement les dossiers devenus vides sur le chemin des fichiers supprimés (jamais `DIR`).
- Ne touche à rien d'autre ; garde les manifestes et sauvegardes dans `.project-manager-v3-kit/` (trace).

## Installation interrompue
Symptôme : `install.sh` refuse avec « installation précédente interrompue » (verrou `install.lock`).
```bash
./rollback.sh --dest <DIR>          # utilise automatiquement le manifeste du verrou, supprime les *.pmv3-tmp, lève le verrou
./install.sh ...                    # relancer ensuite
```

## Dans un dépôt
Les fichiers installés dans un dépôt sont versionnés : avant commit, `rollback.sh` ou `git restore` ; après merge, MR de revert (accords distincts). Les garde-fous du dépôt (hooks, settings, policy, `CLAUDE.md`) ne sont jamais concernés : l'installateur ne les écrit pas.

## Permissions fusionnées à la main
Retirer à la main les entrées ajoutées depuis `templates/settings.kit.json` (le kit ne modifie jamais `settings.json`).
