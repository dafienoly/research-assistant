#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${HERMES_BACKUP_ROOT:-/mnt/d/HermesBackups}"
STAMP="${1:-$(date +%Y%m%d_%H%M%S)}"
DEST="$BACKUP_ROOT/research-assistant-data_$STAMP"
LATEST_FILE="$BACKUP_ROOT/LATEST-research-assistant-data.txt"

mkdir -p "$BACKUP_ROOT"
exec 9>"$BACKUP_ROOT/.research-assistant-data.lock"
flock -n 9 || { echo "another Hermes data backup is running" >&2; exit 75; }
pgrep -f 'data:full-init|data:pull-|data:incremental-update' >/dev/null && {
  echo "data writer is active; backup deferred to keep the recovery point consistent" >&2
  exit 75
}

mkdir -p "$DEST/data" "$DEST/commands-data" "$DEST/shared-data-hub" "$DEST/metadata"

previous=""
if [[ -f "$LATEST_FILE" ]]; then
  previous="$(head -n 1 "$LATEST_FILE")"
  [[ -d "$previous" ]] || previous=""
fi

sync_tree() {
  local source="$1" target="$2" previous_tree="$3"
  local args=(-a --partial --safe-links)
  if [[ -n "$previous" && -d "$previous/$previous_tree" ]]; then
    args+=(--link-dest="$previous/$previous_tree")
  fi
  rsync "${args[@]}" "$source/" "$target/"
}

sync_tree "$ROOT/data" "$DEST/data" data
sync_tree "$ROOT/commands/data" "$DEST/commands-data" commands-data
sync_tree "/mnt/c/Users/ly/.codex/data/a-share-data-hub" "$DEST/shared-data-hub" shared-data-hub

(
  cd "$DEST"
  find data commands-data shared-data-hub -type f -print0 |
    sort -z |
    xargs -0 sha256sum > metadata/SHA256SUMS
)

{
  echo "status=FINAL_COMPLETE"
  echo "created_at=$(date --iso-8601=seconds)"
  echo "source_root=$ROOT"
  echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
  echo "live_trading_enabled=${QMT_LIVE_TRADING_ENABLED:-0}"
} > "$DEST/metadata/manifest.env"

printf '%s\n' "$DEST" > "$LATEST_FILE"

echo "$DEST"
