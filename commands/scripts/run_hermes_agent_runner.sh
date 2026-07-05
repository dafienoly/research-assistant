#!/bin/bash
# Hermes Agent Runner — 定时自动执行入口
cd /home/ly/.hermes/research-assistant/commands || exit 1
../.venv_quant/bin/python3 hermes_cli.py leader:agent-runner --once --backend claude 2>>/tmp/hermes_agent_runner.log
../.venv_quant/bin/python3 hermes_cli.py leader:loop-once 2>>/tmp/hermes_agent_runner.log
