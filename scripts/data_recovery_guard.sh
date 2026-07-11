#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${HERMES_BACKUP_ROOT:-/mnt/d/HermesBackups}"
LATEST_FILE="$BACKUP_ROOT/LATEST-research-assistant-data.txt"
THRESHOLD_PCT="${HERMES_RECOVERY_THRESHOLD_PCT:-90}"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

mkdir -p "${HERMES_LOCK_DIR:-$HOME/.hermes/locks}"
exec 8>"${HERMES_LOCK_DIR:-$HOME/.hermes/locks}/datahub-global.lock"
flock -n 8 || { echo "DataHub writer, backup, or recovery is active; recovery deferred" >&2; exit 75; }
export HERMES_DATA_LOCK_HELD=1

[[ -f "$LATEST_FILE" ]] || { echo "no finalized D-drive backup pointer; recovery skipped"; exit 0; }
backup="$(head -n 1 "$LATEST_FILE")"
[[ -d "$backup" ]] || { echo "latest backup directory is missing" >&2; exit 2; }
grep -qx 'status=FINAL_COMPLETE' "$backup/metadata/manifest.env" || {
  echo "latest backup is not finalized" >&2
  exit 3
}

count_csv() {
  [[ -d "$1" ]] || { echo 0; return 0; }
  find "$1" -maxdepth 1 -type f -name '*.csv' 2>/dev/null | wc -l
}

current_market="$(count_csv "$ROOT/data/normalized/market")"
backup_market="$(count_csv "$backup/data/normalized/market")"
current_hub="$(count_csv "/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")"
backup_hub="$(count_csv "$backup/shared-data-hub/market/daily_kline")"

catastrophic=0
if ((backup_market >= 100 && current_market * 100 < backup_market * THRESHOLD_PCT)); then
  catastrophic=1
fi
if ((backup_hub >= 100 && current_hub * 100 < backup_hub * THRESHOLD_PCT)); then
  catastrophic=1
fi

if ((!FORCE && !catastrophic)); then
  echo "data coverage is above recovery threshold; no restore required"
  exit 0
fi

pgrep -f 'data:full-init|data:pull-|data:incremental-update|datahub_reference_fetch|datahub_market_series_fetch|datahub_suspension_fetch' >/dev/null && {
  echo "data writer is active; recovery deferred" >&2
  exit 75
}

echo "catastrophic data loss detected; verifying and restoring D-drive backup first"
"$ROOT/scripts/restore_data_from_d.sh" --backup "$backup" --apply

echo "backup restore complete; starting incremental pull"
cd "$ROOT"
PYTHONPATH=commands .venv_quant/bin/python3 commands/hermes_cli.py data:incremental-update
echo "restore-then-incremental recovery complete"
