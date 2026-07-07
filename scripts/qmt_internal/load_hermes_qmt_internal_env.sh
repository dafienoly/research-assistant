#!/usr/bin/env bash
# Source this file before running Hermes QMT internal HTTP commands:
#   source scripts/qmt_internal/load_hermes_qmt_internal_env.sh

set -euo pipefail

CONFIG_PATH="${QMT_INTERNAL_CONFIG_PATH:-/mnt/d/HermesQMTBridge/qmt_http_executor_config.json}"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "QMT internal config not found: $CONFIG_PATH" >&2
  return 1 2>/dev/null || exit 1
fi

read -r port token live_enabled < <(
  python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8-sig") as f:
    cfg = json.load(f)

print(
    cfg.get("PORT", 18765),
    cfg.get("TOKEN", ""),
    "1" if cfg.get("LIVE_TRADING_ENABLED") else "0",
)
PY
)

if [ -z "$token" ]; then
  echo "TOKEN is empty in $CONFIG_PATH" >&2
  return 1 2>/dev/null || exit 1
fi

export QMT_BRIDGE_MODE=internal_http
export QMT_INTERNAL_HTTP_BASE_URL="http://127.0.0.1:${port}"
export QMT_INTERNAL_HTTP_TOKEN="$token"

# Hermes live gate stays closed unless explicitly enabled by the caller.
export QMT_LIVE_TRADING_ENABLED="${QMT_LIVE_TRADING_ENABLED:-0}"

echo "Loaded QMT internal HTTP env from $CONFIG_PATH"
echo "QMT_INTERNAL_HTTP_BASE_URL=$QMT_INTERNAL_HTTP_BASE_URL"
echo "QMT_LIVE_TRADING_ENABLED=$QMT_LIVE_TRADING_ENABLED"
echo "QMT executor local LIVE_TRADING_ENABLED=$live_enabled"
