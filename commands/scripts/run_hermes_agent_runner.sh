#!/bin/bash
# Hermes Agent Runner — 定时自动执行入口
# 适用于 WSL crontab 或 Windows schtasks 调用 WSL

set -e
cd /home/ly/.hermes/research-assistant/commands || exit 1

# 记录心跳
../.venv_quant/bin/python3 -c "
from factor_lab.leader.auto_loop import tick
tick()
print(f'❤️  tick: {__import__(\"json\").loads(open(\"/home/ly/.hermes/research-assistant/agent_tasks/auto_loop_state.json\").read())[\"tick_count\"]}')
" 2>>/tmp/hermes_agent_runner.log

# 执行 agent-runner (dry-run 安全模式, 不消耗额度)
../.venv_quant/bin/python3 hermes_cli.py leader:agent-runner --once --backend dry-run 2>>/tmp/hermes_agent_runner.log

# Leader 循环
../.venv_quant/bin/python3 hermes_cli.py leader:loop-once 2>>/tmp/hermes_agent_runner.log

echo "[$(date)] auto loop done" >> /tmp/hermes_agent_runner.log
