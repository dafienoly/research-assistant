#!/bin/sh
# Explicit release-only source audit. This is the only supported automation.
set -eu

VERSION=${1:-}
if [ -z "$VERSION" ]; then
    echo "用法: $0 <major-version> [base-ref]" >&2
    exit 2
fi
BASE_REF=${2:-origin/main}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHON=${HERMES_AUDIT_PYTHON:-$ROOT/.venv_quant/bin/python}

exec "$PYTHON" "$ROOT/commands/hermes_cli.py" audit:code \
    --major-version "$VERSION" \
    --profile security \
    --scope compare \
    --base "$BASE_REF"
