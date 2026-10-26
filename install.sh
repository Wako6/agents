#!/usr/bin/env bash
# Project Manager V3 — Unified : installateur non destructif
#
#   ./install.sh [--scope user|project] [--dest DIR] [--dry-run] [--force | --merge]
#                [--with-optional] [--with-rules] [--adapter NAME]
#                [--allow-shadowing] [--allow-dirty]
#
#   --scope user        (défaut) → DIR = ~/.claude
#   --scope project     → DIR = <dépôt courant>/.claude (ou --dest)
#   --dry-run           affiche le plan et les contrôles, n'écrit rien
#   --force             conflit → sauvegarde puis écrase   |  --merge  conflit → dépose <fichier>.kit-new
#   --with-optional     agents optionnels (Flutter, SPIP) depuis optional-agents/
#   --with-rules        règle globale rules/*.md (user) ; + templates/project-rules/*.md (project)
#   --adapter NAME      (scope project seulement) installe adapters/NAME/project-manager.{config.json,profile.md}
#   --allow-shadowing   (scope user) accepte qu'un project-manager personnel masque celui d'un projet
#   --allow-dirty       (scope project) accepte des modifications non commitées sur les chemins écrits
#
# Garanties : aucun rm -rf ; aucun fichier utilisateur supprimé ; fichier identique → ignoré ; fichier que
# NOUS avons installé et non modifié → mis à jour après sauvegarde ; fichier inconnu ou modifié → CONFLIT,
# non touché (sauf --force/--merge) ; settings*.json, hooks/ du projet, policy.json, test-command, CLAUDE.md :
# jamais écrits (refus explicite) ; manifeste écrit AVANT chaque écriture, copie atomique (tmp + mv),
# verrou d'installation : une installation interrompue est détectée et doit être annulée (rollback.sh).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCOPE=user; DEST=""; DRY=0; FORCE=0; MERGE=0; OPTIONAL=0; RULES=0; ADAPTER=""; SHADOW=0; DIRTY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --scope) SCOPE="$2"; shift 2;;
    --dest) DEST="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    --force) FORCE=1; shift;;
    --merge) MERGE=1; shift;;
    --with-optional) OPTIONAL=1; shift;;
    --with-rules) RULES=1; shift;;
    --adapter) ADAPTER="$2"; shift 2;;
    --allow-shadowing) SHADOW=1; shift;;
    --allow-dirty) DIRTY=1; shift;;
    -h|--help) sed -n '2,26p' "$0"; exit 0;;
    *) echo "option inconnue: $1" >&2; exit 64;;
  esac
done
die() { echo "ERREUR : $*" >&2; exit "${2:-1}"; }
[ "$FORCE" = 1 ] && [ "$MERGE" = 1 ] && die "--force et --merge sont exclusifs" 64

# ---- 0. dépendances
for c in sha256sum python3 find awk sed mktemp cp mv; do command -v "$c" >/dev/null 2>&1 || die "dépendance manquante : $c" 69; done

# ---- 1. destination
case "$SCOPE" in
  user) DEST="${DEST:-$HOME/.claude}";;
  project) if [ -z "$DEST" ]; then TOP="$(git rev-parse --show-toplevel 2>/dev/null)" || die "--scope project : pas de dépôt git courant (ou --dest)" 64; DEST="$TOP/.claude"; fi;;
  *) die "--scope user|project" 64;;
esac
[ -n "$ADAPTER" ] && [ "$SCOPE" != project ] && die "--adapter n'a de sens qu'en --scope project" 64
[ -n "$ADAPTER" ] && [ ! -d "$HERE/adapters/$ADAPTER" ] && die "adaptateur inconnu : $ADAPTER ($(ls "$HERE/adapters" | tr '\n' ' '))" 64
# clone direct : le kit est déjà à l'emplacement cible (ex. dépôt cloné dans ~/.claude) → rien à copier
if [ -d "$DEST" ] && [ "$(cd "$DEST" && pwd -P)" = "$(cd "$HERE" && pwd -P)" ]; then
  echo "Le kit est déjà à cet emplacement ($DEST, clone direct) : rien à installer. Mise à jour : git -C \"$DEST\" pull --ff-only (README § 10)."
  exit 0
fi
STATE="$DEST/.project-manager-v3-kit"
LOCK="$STATE/install.lock"

# ---- 2. installation interrompue ?
if [ -f "$LOCK" ]; then
  die "installation précédente interrompue (verrou $LOCK, manifeste $(cat "$LOCK")). Annule-la d'abord : $HERE/rollback.sh --dest \"$DEST\" --manifest \"$(cat "$LOCK")\"" 75
fi

# ---- 3. droits d'écriture (premier ancêtre existant)
probe="$DEST"; while [ ! -e "$probe" ]; do probe="$(dirname "$probe")"; done
[ -d "$probe" ] && [ -w "$probe" ] || die "droits insuffisants : $probe n'est pas un dossier accessible en écriture" 77

# ---- 4. masquage d'un project-manager de projet (skills : personnel > projet)
if [ "$SCOPE" = user ]; then
  CWDTOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$CWDTOP" ] && [ -f "$CWDTOP/.claude/skills/project-manager/SKILL.md" ] && [ "$SHADOW" = 0 ]; then
    die "le dépôt courant ($CWDTOP) a son propre skill project-manager ; un skill personnel du même nom le MASQUERAIT (doc Claude Code : personnel > projet). Installe en --scope project dans ce dépôt, ou relance avec --allow-shadowing en connaissance de cause." 65
  fi
fi

# ---- 5. état git du dépôt cible (scope project)
if [ "$SCOPE" = project ]; then
  REPO="$(git -C "$(dirname "$DEST")" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$REPO" ]; then
    GD="$(git -C "$REPO" rev-parse --git-dir)"; case "$GD" in /*) ;; *) GD="$REPO/$GD";; esac
    for m in MERGE_HEAD REBASE_HEAD CHERRY_PICK_HEAD rebase-merge rebase-apply; do
      [ -e "$GD/$m" ] && die "état git inattendu dans $REPO : opération en cours ($m)" 73
    done
  fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
BACKUP="$STATE/backup-$STAMP"
MANIFEST="$STATE/manifest-$STAMP.tsv"
LATEST="$STATE/manifest-latest.tsv"
sha() { sha256sum "$1" | cut -d' ' -f1; }
log() { printf '%s\n' "$*"; }

# ---- 6. staging (copie transformée du kit)
STAGING="$(mktemp -d)"; : > "$STAGING/.kit-staging"
cleanup_staging() { [ -n "${STAGING:-}" ] && [ -f "$STAGING/.kit-staging" ] && find "$STAGING" -depth -delete; }
trap cleanup_staging EXIT
stage() {
  local f rel
  find "$HERE/skills/project-manager" -type f | while read -r f; do rel="skills/project-manager/${f#"$HERE/skills/project-manager/"}"; mkdir -p "$STAGING/$(dirname "$rel")"; cp -p "$f" "$STAGING/$rel"; done
  mkdir -p "$STAGING/agents"
  for f in "$HERE"/agents/*.md; do cp -p "$f" "$STAGING/agents/"; done
  if [ "$OPTIONAL" = 1 ]; then for f in "$HERE"/optional-agents/*.md; do cp -p "$f" "$STAGING/agents/"; done; fi
  if [ "$RULES" = 1 ]; then
    mkdir -p "$STAGING/rules"
    for f in "$HERE"/rules/*.md; do [ -e "$f" ] && cp -p "$f" "$STAGING/rules/"; done
    if [ "$SCOPE" = project ]; then for f in "$HERE"/templates/project-rules/*.md; do [ -e "$f" ] && cp -p "$f" "$STAGING/rules/"; done; fi
  fi
  if [ -n "$ADAPTER" ]; then
    for f in project-manager.config.json project-manager.profile.md; do [ -e "$HERE/adapters/$ADAPTER/$f" ] && cp -p "$HERE/adapters/$ADAPTER/$f" "$STAGING/$f"; done
  fi
  if [ "$SCOPE" = project ]; then
    sed -i 's#"\$HOME/\.claude/skills/project-manager/hooks/#"${CLAUDE_PROJECT_DIR}/.claude/skills/project-manager/hooks/#g' "$STAGING"/agents/*.md
  fi
  true
}
stage
plan() { find "$STAGING" -type f ! -name .kit-staging | while read -r f; do printf '%s\t%s\n' "$f" "${f#"$STAGING/"}"; done | sort -t$'\t' -k2; }

# ---- 7. chemins interdits (garde-fous du projet ou de l'utilisateur)
is_protected() {
  case "$1" in
    settings.json|settings.local.json|policy.json|test-command|CLAUDE.md|hooks/*|*/policy.json|.mcp.json) return 0;;
  esac
  return 1
}
while IFS=$'\t' read -r _ rel; do is_protected "$rel" && die "le plan viserait un chemin protégé : $rel (refus)" 70; done < <(plan)

recorded_sha() { [ -f "$LATEST" ] && awk -F'\t' -v p="$1" '$2==p {print $3}' "$LATEST" | tail -1 || true; }

declare -i n_new=0 n_same=0 n_upd=0 n_conf=0 n_merge=0
rows=()
while IFS=$'\t' read -r src rel; do
  dst="$DEST/$rel"; ssha="$(sha "$src")"
  if [ ! -e "$dst" ]; then action=NEW
  elif [ "$(sha "$dst")" = "$ssha" ]; then action=SAME
  elif [ -n "$(recorded_sha "$rel")" ] && [ "$(recorded_sha "$rel")" = "$(sha "$dst")" ]; then action=UPDATE
  elif [ "$FORCE" = 1 ]; then action=FORCE
  elif [ "$MERGE" = 1 ]; then action=MERGE
  else action=CONFLICT; fi
  rows+=("$action	$rel	$src	$ssha")
  case $action in NEW) n_new+=1;; SAME) n_same+=1;; UPDATE|FORCE) n_upd+=1;; CONFLICT) n_conf+=1;; MERGE) n_merge+=1;; esac
done < <(plan)

# ---- 7b. le skill est une unité : un project-manager étranger présent → tout le skill en conflit (jamais d'hybride)
SKILL_DST="$DEST/skills/project-manager/SKILL.md"
if [ -e "$SKILL_DST" ]; then
  ours="$(sha "$STAGING/skills/project-manager/SKILL.md")"; theirs="$(sha "$SKILL_DST")"
  if [ "$theirs" != "$ours" ] && [ "$(recorded_sha skills/project-manager/SKILL.md)" != "$theirs" ] && [ "$FORCE" = 0 ]; then
    new_rows=(); n_new=0; n_upd=0; n_conf=0; n_merge=0; n_same=0
    for r in "${rows[@]}"; do
      IFS=$'\t' read -r a rel src ssha <<<"$r"
      case "$rel" in skills/project-manager/*) [ "$a" = SAME ] || a=$([ "$MERGE" = 1 ] && echo MERGE || echo CONFLICT);; esac
      new_rows+=("$a	$rel	$src	$ssha")
      case $a in NEW) n_new+=1;; SAME) n_same+=1;; UPDATE|FORCE) n_upd+=1;; CONFLICT) n_conf+=1;; MERGE) n_merge+=1;; esac
    done
    rows=("${new_rows[@]}")
    log "⚠ un skill project-manager étranger existe déjà dans $DEST/skills/project-manager : le skill V3 est traité comme une unité ($([ "$MERGE" = 1 ] && echo 'fichiers .kit-new déposés' || echo 'aucun fichier écrit dans ce dossier'))."
  fi
fi

# ---- 8. git : chemins modifiés non commités (scope project)
if [ "$SCOPE" = project ] && [ -n "${REPO:-}" ] && [ "$DIRTY" = 0 ]; then
  dirty=""
  for r in "${rows[@]}"; do IFS=$'\t' read -r a rel _ _ <<<"$r"; case $a in SAME|CONFLICT) continue;; esac
    p="$DEST/$rel"; [ "$a" = MERGE ] && p="$p.kit-new"
    [ -n "$(git -C "$REPO" status --porcelain -- "$p" 2>/dev/null)" ] && dirty="$dirty $rel"
  done
  [ -n "$dirty" ] && die "état git inattendu : modifications non commitées sur :$dirty (--allow-dirty pour passer outre)" 73
fi

log "Project Manager V3 — destination : $DEST   (scope=$SCOPE, dry-run=$DRY, force=$FORCE, merge=$MERGE, adapter=${ADAPTER:-aucun})"
log "Plan : $n_new à créer, $n_same identiques (ignorés), $n_upd à mettre à jour, $n_conf conflit(s), $n_merge à fusionner"
for r in "${rows[@]}"; do IFS=$'\t' read -r a rel _ _ <<<"$r"; [ "$a" = SAME ] || log "  $a	$rel"; done
[ "$DRY" = 1 ] && { log "(dry-run : rien n'a été écrit)"; exit 0; }
# exécution sans écriture (tout identique ou en conflit) : aucun nouveau manifeste, le précédent reste la référence du rollback
if [ $((n_new + n_upd + n_merge)) -eq 0 ]; then log "Aucune écriture nécessaire ; manifeste précédent conservé."; exit 0; fi

mkdir -p "$STATE"
: > "$MANIFEST"
printf '%s\n' "$MANIFEST" > "$LOCK"
written=0
put() {  # copie atomique : tmp puis mv ; PMV3_TEST_ABORT_AFTER=N simule une interruption (tests uniquement)
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"; cp "$src" "$dst.pmv3-tmp"; mv "$dst.pmv3-tmp" "$dst"
  written=$((written+1))
  if [ -n "${PMV3_TEST_ABORT_AFTER:-}" ] && [ "$written" -ge "$PMV3_TEST_ABORT_AFTER" ]; then echo "(interruption simulée)" >&2; exit 99; fi
}
for r in "${rows[@]}"; do
  IFS=$'\t' read -r a rel src ssha <<<"$r"; dst="$DEST/$rel"
  case $a in
    SAME) printf 'SAME\t%s\t%s\t\n' "$rel" "$ssha" >> "$MANIFEST";;
    NEW) printf 'NEW\t%s\t%s\t\n' "$rel" "$ssha" >> "$MANIFEST"; put "$src" "$dst";;
    UPDATE|FORCE) mkdir -p "$BACKUP/$(dirname "$rel")"; cp -p "$dst" "$BACKUP/$rel"
                  printf '%s\t%s\t%s\t%s\n' "$a" "$rel" "$ssha" "$BACKUP/$rel" >> "$MANIFEST"; put "$src" "$dst";;
    MERGE) printf 'MERGE\t%s\t%s\t%s\n' "$rel" "$ssha" "$dst.kit-new" >> "$MANIFEST"; put "$src" "$dst.kit-new";;
    CONFLICT) printf 'CONFLICT\t%s\t%s\t\n' "$rel" "$ssha" >> "$MANIFEST";;
  esac
done
cp "$MANIFEST" "$LATEST"
rm -f "$LOCK"
[ -d "$BACKUP" ] && rmdir "$BACKUP" 2>/dev/null || true

log
log "Manifeste : $MANIFEST"
[ -d "$BACKUP" ] && log "Sauvegardes : $BACKUP"
[ "$n_conf" -gt 0 ] && log "⚠ $n_conf conflit(s) non touché(s) : --merge (dépose .kit-new) ou --force (sauvegarde puis écrase)."
[ "$n_merge" -gt 0 ] && log "ℹ fichiers .kit-new déposés : compare-les (diff) puis décide à la main."
log "Retour arrière : $HERE/rollback.sh --dest \"$DEST\" --manifest \"$MANIFEST\""
log "Jamais installés (à faire à la main, voir templates/ et docs/INSTALL.md) : settings/permissions, hooks de projet, .mcp.json, CLAUDE.md."
