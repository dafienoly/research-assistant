#!/bin/bash
# Backward-compatible entry point. The only production post-market writer is
# the declarative scheduler; keeping orchestration here would recreate a second
# set of dependencies, retries and data ownership rules.
set -euo pipefail

ROOT="/home/ly/.hermes/research-assistant"
exec env PYTHONPATH="$ROOT/commands" \
  "$ROOT/.venv_quant/bin/python3" \
  "$ROOT/commands/scripts/run_scheduled_dag.py" postmarket "$@"
