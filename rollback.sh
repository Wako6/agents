#!/usr/bin/env bash
# Project Manager V3 — retour arrière d'une installation :
#   ./rollback.sh --dest DIR [--manifest FICHIER | --all] [--dry-run]
# --all : annule toutes les exécutions enregistrées, de la plus récente à la plus ancienne (désinstallation complète)
# - restaure les fichiers sauvegardés (UPDATE/FORCE)
# - supprime les fichiers NEW et les .kit-new (MERGE) UNIQUEMENT s'ils sont identiques à ce qui a été installé
#   (un fichier modifié depuis est laissé en place et signalé)
# - supprime les restes de copie atomique (*.pmv3-tmp) d'une installation interrompue
# - ne retire que les dossiers devenus vides sur le chemin des fichiers supprimés (jamais DIR lui-même)
# - lève le verrou d'installation si le manifeste annulé est celui de l'installation interrompue
set -euo pipefail
DEST=""; MANIFEST=""; DRY=0; ALL=0
while [ $# -gt 0 ]; do case "$1" in
  --dest) DEST="$2"; shift 2;; --manifest) MANIFEST="$2"; shift 2;; --dry-run) DRY=1; shift;; --all) ALL=1; shift;;
  -h|--help) sed -n '2,10p' "$0"; exit 0;;
  *) echo "option inconnue: $1" >&2; exit 64;; esac; done
[ -n "$DEST" ] || { echo "--dest requis" >&2; exit 64; }
STATE="$DEST/.project-manager-v3-kit"
if [ "$ALL" = 1 ]; then
  [ -z "$MANIFEST" ] || { echo "--all et --manifest sont exclusifs" >&2; exit 64; }
  rc=0
  for m in $(ls -1 "$STATE"/manifest-2*.tsv 2>/dev/null | sort -r); do
    echo "== annulation de $(basename "$m")"
    a=(--dest "$DEST" --manifest "$m"); [ "$DRY" = 1 ] && a+=(--dry-run)
    "$0" "${a[@]}" || rc=$?
  done
  exit $rc
fi
LOCK="$STATE/install.lock"
if [ -z "$MANIFEST" ]; then
  if [ -f "$LOCK" ]; then MANIFEST="$(cat "$LOCK")"; else MANIFEST="$STATE/manifest-latest.tsv"; fi
fi
[ -f "$MANIFEST" ] || { echo "manifeste introuvable : $MANIFEST" >&2; exit 66; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
restored=0 removed=0 kept=0
gone=()
rmfile() { echo "remove   ${1#"$DEST/"}"; if [ "$DRY" = 0 ]; then rm -f "$1"; gone+=("$1"); fi; removed=$((removed+1)); }
while IFS=$'\t' read -r action rel ssha backup; do
  dst="$DEST/$rel"
  [ -f "$dst.pmv3-tmp" ] && rmfile "$dst.pmv3-tmp"
  case "$action" in
    NEW)
      if [ -f "$dst" ] && [ "$(sha "$dst")" = "$ssha" ]; then rmfile "$dst"
      elif [ -f "$dst" ]; then echo "KEEP     $rel (modifié depuis l'installation)"; kept=$((kept+1)); fi;;
    UPDATE|FORCE)
      if [ -f "$backup" ]; then echo "restore  $rel"; [ "$DRY" = 1 ] || cp -p "$backup" "$dst"; restored=$((restored+1))
      else echo "KEEP     $rel (sauvegarde absente : $backup)"; kept=$((kept+1)); fi;;
    MERGE)
      if [ -f "$backup" ] && [ "$(sha "$backup")" = "$ssha" ]; then rmfile "$backup"
      elif [ -f "$backup" ]; then echo "KEEP     ${backup#"$DEST/"} (modifié)"; kept=$((kept+1)); fi;;
    SAME|CONFLICT) ;;
  esac
done < "$MANIFEST"
# dossiers devenus vides, uniquement sur le chemin des fichiers supprimés, jamais DEST
for f in "${gone[@]:-}"; do
  [ -n "$f" ] || continue
  d="$(dirname "$f")"
  while [ "$d" != "$DEST" ] && [ "${d#"$DEST/"}" != "$d" ] && rmdir "$d" 2>/dev/null; do d="$(dirname "$d")"; done
done
if [ "$DRY" = 0 ] && [ -f "$LOCK" ] && [ "$(cat "$LOCK")" = "$MANIFEST" ]; then rm -f "$LOCK"; echo "verrou d'installation levé"; fi
echo "restaurés=$restored supprimés=$removed conservés=$kept $([ "$DRY" = 1 ] && echo '(dry-run)')"
