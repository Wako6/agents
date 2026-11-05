# V3.3-A2 — Rapport de reconnexion SSE

## Comportement

| Situation | Serveur | Navigateur |
|---|---|---|
| Connexion | `hello` avec instance et séquence | « Resynchronisation », puis « En direct » après l'instantané |
| Mise à jour | `update` numéroté | Nouvel instantané |
| Doublon ou ancienne séquence | — | Ignoré |
| Séquence manquante | — | Perte de continuité signalée, instantané complet |
| Silence | `ping` à chaque battement | Sans message pendant 3 battements : « Hors ligne », reconnexion |
| Coupure | — | « Hors ligne », bandeau avec l'heure des dernières données |
| Reprise avec `Last-Event-ID` connu | Rejoue les mises à jour | « En direct » seulement une fois à jour |
| Reprise sans preuve | `resync: true` | Perte signalée, instantané complet |
| Mémoire dépassée (256 mises à jour) | `lost` | Perte signalée, instantané complet |
| Serveur redémarré | Nouvelle instance | Perte signalée, ou « Session perdue » si le jeton a changé |
| Instantané indisponible | — | « Instantané indisponible », jamais « En direct » |

L'avis de perte reste affiché 5 minutes.

## Mesures

| Niveau | Résultat |
|---|---|
| Automate du navigateur (`ui/live.js`), avec Node | 10 tests |
| Serveur réel, flux SSE réel | Rejeu, perte, séquence, `ping` (`test_adapter.py`) |
| Navigateur réel à travers un relais TCP coupé volontairement | 18/18 (Firefox local sous Linux, banc hors dépôt) |

Mesures en navigateur réel : coupure réelle, flux muet sans coupure, reconnexion immédiate, mise à jour manquée, fichier devenu non conforme, session invalide. « En direct » ne réapparaît jamais une fois la coupure constatée.

## Limites

- **Firefox Windows : observations visuelles seulement.** Affichage des copies minimisées, statuts des tâches, simulation de coupure et retour visuel à « En direct » observés. Non vérifiés : reconnexion après une véritable interruption réseau, rejeu effectif des événements manqués, accès depuis un autre compte Windows.
- **Rejeu en navigateur non observé :** dans les essais, Firefox a repris sans demander les mises à jour manquées, par le chemin prudent (perte signalée, instantané complet). Le rejeu est testé côté serveur et dans l'automate.
- **Délai de constat :** « En direct » peut rester affiché jusqu'à 3 battements (30 s par défaut) sur un flux devenu muet.
- **Événements intermédiaires :** après une perte, seul l'état complet est garanti à jour, dans la limite de la source.
- **Copies figées :** « En direct » décrit le flux entre le serveur et le navigateur, pas l'activité d'un run. Une copie ne change que si une nouvelle extraction la remplace, et le bandeau d'ancienneté le rappelle.
