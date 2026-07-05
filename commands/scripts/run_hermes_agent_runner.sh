#!/bin/bash
# Hermes Auto Runner — 定时自动开发执行器 (cron 安全版)
set -e

# 注入 PATH 确保 cron 能找到 claude (nvm node path)
NVM_BIN=/home/ly/.nvm/versions/node/v22.16.0/bin
export PATH="/usr/local/bin:/usr/bin:/bin:$NVM_BIN:/home/ly/.local/bin:$PATH"
export HERMES_CLAUDE_BIN=/home/ly/.nvm/versions/node/v22.16.0/bin/claude

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py
cd /home/ly/.hermes/research-assistant/commands || exit 1

# 心跳
$VENV -c "from factor_lab.leader.auto_loop import tick; tick()" 2>>/tmp/hermes_agent_runner.log

# 自动执行
$VENV $CLI leader:auto-run-once 2>>/tmp/hermes_agent_runner.log

echo "[$(date)] auto loop done" >> /tmp/hermes_agent_runner.log
