#!/bin/bash
# Hermes Agent Runner — 定时自动执行入口 (绝对路径版)
set -e
VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
HERMES=/home/ly/.hermes/research-assistant/commands/hermes_cli.py

cd /home/ly/.hermes/research-assistant/commands || exit 1

# 心跳
$VENV -c "from factor_lab.leader.auto_loop import tick; tick()" 2>>/tmp/hermes_agent_runner.log

# 执行 (dry-run 安全模式)
$VENV $HERMES leader:agent-runner --once --backend dry-run 2>>/tmp/hermes_agent_runner.log

# Leader 循环
$VENV $HERMES leader:loop-once 2>>/tmp/hermes_agent_runner.log

echo "[$(date)] auto loop done" >> /tmp/hermes_agent_runner.log
