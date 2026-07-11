#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${HERMES_BACKUP_ROOT:-/mnt/d/HermesBackups}"
LATEST_FILE="$BACKUP_ROOT/LATEST-research-assistant-data.txt"
APPLY=0
EXACT=0
BACKUP=""

while (($#)); do
  case "$1" in
    --apply) APPLY=1 ;;
    --exact) EXACT=1 ;;
    --backup) shift; BACKUP="${1:-}" ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ -z "$BACKUP" && -f "$LATEST_FILE" ]]; then
  BACKUP="$(head -n 1 "$LATEST_FILE")"
fi
[[ -d "$BACKUP" ]] || { echo "backup directory not found" >&2; exit 2; }
grep -qx 'status=FINAL_COMPLETE' "$BACKUP/metadata/manifest.env" || {
  echo "backup is not finalized" >&2
  exit 3
}

if [[ "${HERMES_DATA_LOCK_HELD:-0}" != "1" ]]; then
  mkdir -p "${HERMES_LOCK_DIR:-$HOME/.hermes/locks}"
  exec 8>"${HERMES_LOCK_DIR:-$HOME/.hermes/locks}/datahub-global.lock"
  flock -n 8 || { echo "DataHub writer, backup, or recovery is active; restore deferred" >&2; exit 75; }
fi

(
  cd "$BACKUP"
  sha256sum -c metadata/SHA256SUMS --quiet
)

args=(-a --partial --safe-links)
((EXACT)) && args+=(--delete-delay)

if ((!APPLY)); then
  echo "verified backup: $BACKUP"
  echo "dry run only; use --apply to restore, optionally --exact to remove extra files"
  rsync "${args[@]}" --dry-run "$BACKUP/data/" "$ROOT/data/"
  exit 0
fi

pgrep -f 'data:full-init|data:pull-|data:incremental-update|datahub_reference_fetch|datahub_market_series_fetch|datahub_suspension_fetch' >/dev/null && {
  echo "data writer is active; stop it before restore" >&2
  exit 4
}

rsync "${args[@]}" "$BACKUP/data/" "$ROOT/data/"
rsync "${args[@]}" "$BACKUP/commands-data/" "$ROOT/commands/data/"
if [[ -d "$BACKUP/shared-data-hub" ]]; then
  rsync "${args[@]}" "$BACKUP/shared-data-hub/" "/mnt/c/Users/ly/.codex/data/a-share-data-hub/"
else
  echo "legacy snapshot has no shared hub; project data restored and hub must be re-mirrored" >&2
fi
echo "restore complete: $BACKUP"
