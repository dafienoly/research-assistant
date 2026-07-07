#!/bin/bash
# Hermes Auto Version Loop — 独立包装脚本，由 hermes-daemon.sh 启动
# 每 180 秒执行一次 auto_run_once，记录日志到 $HOME/.hermes/hermes-auto-loop.log
set -e

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py
WORKDIR=/home/ly/.hermes/research-assistant/commands
LOGFILE=$HOME/.hermes/hermes-auto-loop.log
PIDFILE=$HOME/.hermes/hermes-auto-loop.pid

cd "$WORKDIR"

echo "[$(date)] === Auto Version Loop started (pid $$) ===" >> "$LOGFILE"
echo $$ > "$PIDFILE"

# 每 3 分钟循环
while true; do
  echo "[$(date)] === tick ===" >> "$LOGFILE"

  # 心跳记录
  $VENV -c "from factor_lab.leader.auto_loop import tick; tick()" >> "$LOGFILE" 2>&1

  # 自动版本推进
  $VENV $CLI leader:auto-run-once >> "$LOGFILE" 2>&1

  echo "[$(date)] === tick done ===" >> "$LOGFILE"
  sleep 180
done
