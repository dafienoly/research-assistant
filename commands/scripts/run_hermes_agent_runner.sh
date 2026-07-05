#!/bin/bash
# Hermes Auto Runner — 定时自动开发执行器
set -e
VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py
cd /home/ly/.hermes/research-assistant/commands || exit 1

# 心跳
$VENV -c "from factor_lab.leader.auto_loop import tick; tick()" 2>>/tmp/hermes_agent_runner.log

# 自动执行
$VENV $CLI leader:auto-run-once 2>>/tmp/hermes_agent_runner.log

echo "[$(date)] auto loop done" >> /tmp/hermes_agent_runner.log
