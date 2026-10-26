#!/usr/bin/env bash
# review-guard (V3) — garde-fou des agents de revue (PreToolUse, déclaré dans le frontmatter des reviewers).
# Les reviewers n'ont pas d'outil d'écriture (rapport rendu inline, enregistré par l'appelant) ; ce hook
# borne en plus leur Bash à l'observation. Durci par rapport à la V2 : plus de `env` (affichage de l'environnement),
# HTTP en lecture seule (GET/HEAD, sans corps ni fichier de sortie), `wget` seulement vers la sortie standard,
# pas de `find -delete/-exec`, pas de `git branch -d/-D/-m`.
#
# Entrée : JSON Claude Code sur stdin. Sortie : exit 0 = ok ; exit 2 = bloqué (motif sur stderr).
set -uo pipefail
INPUT="$(cat)"
TOOL="$(printf '%s' "$INPUT" | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))' 2>/dev/null || true)"
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    echo "REVIEW-GUARD: un reviewer n'écrit aucun fichier ; rends ton rapport et ta note dans ta réponse, l'appelant les enregistre." >&2
    exit 2;;
  Bash) ;;
  *) exit 0;;
esac
CMD="$(printf '%s' "$INPUT" | python3 -I -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null || true)"
N="$(printf '%s' "$CMD" | tr '\n\t' '  ' | tr -s ' ')"
deny() { echo "REVIEW-GUARD: $1 : $N" >&2; exit 2; }

# 1. jamais d'écriture, d'enchaînement ni de substitution
if printf '%s' "$N" | grep -Eq '(>|\btee\b|\bsed -i\b|\brm\b|\bmv\b|\bcp\b|\bchmod\b|\bchown\b|\btouch\b|\bln\b|&&|;|\|\||`|\$\()'; then
  deny "écriture, enchaînement ou substitution refusés pour un reviewer"
fi
# 2. liste blanche d'observation (préfixe)
if ! printf '%s' "$N" | grep -Eq '^ *(curl|wget|http|jq|python3? -m json\.tool|cat|head|tail|less|wc|ls|find|rg|grep|git (status|log|diff|show|ls-files|blame|rev-parse|branch)|docker compose (ps|logs)|docker (ps|logs)|python3? manage\.py (check|showmigrations|test)|pytest|npm (test|run lint)|npx (eslint|tsc)|ruff|flake8|pylint|mypy|echo|printf|date|pwd|which|sleep|timeout [0-9]+ (curl|python3? manage\.py test|pytest))\b'; then
  deny "commande hors liste d'observation"
fi
# 3. restrictions fines des commandes autorisées
if printf '%s' "$N" | grep -Eq '\b(curl|http)\b'; then
  printf '%s' "$N" | grep -Eqi '(-X|--request) *(POST|PUT|PATCH|DELETE)|\b(POST|PUT|PATCH|DELETE)\b|(^| )(-d|--data[a-z-]*|-F|--form|-T|--upload-file|-o|--output|-O|--remote-name)( |=|$)' \
    && deny "HTTP limité à la lecture (GET/HEAD, sans corps ni fichier de sortie)"
fi
if printf '%s' "$N" | grep -Eq '^ *wget\b'; then
  printf '%s' "$N" | grep -Eq '(-O *-|-qO-|-qO *-)' || deny "wget seulement vers la sortie standard (-O -)"
  printf '%s' "$N" | grep -Eq -- '--post-(data|file)|--method' && deny "wget limité à la lecture"
fi
printf '%s' "$N" | grep -Eq '^ *find\b.*(-delete|-exec|-execdir|-ok|-fprint)' && deny "find limité à la lecture"
printf '%s' "$N" | grep -Eq '^ *git branch\b.*(-d|-D|-m|-M|-c|-C|--delete|--move|--copy|--set-upstream)' && deny "git branch limité à la lecture"
exit 0
