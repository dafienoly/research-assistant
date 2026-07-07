#!/bin/bash
# Hermes Dashboard Server — 由 hermes-daemon.sh 管理
set -e

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
LOGFILE=$HOME/.hermes/hermes-dashboard.log
PIDFILE=$HOME/.hermes/hermes-dashboard.pid

cd /home/ly/.hermes/research-assistant/commands

echo "[$(date)] === Dashboard server starting on :8766 ===" >> "$LOGFILE"
echo $$ > "$PIDFILE"

exec $VENV -c "from factor_lab.api_server.main import serve; serve(host='127.0.0.1', port=8766)" >> "$LOGFILE" 2>&1
