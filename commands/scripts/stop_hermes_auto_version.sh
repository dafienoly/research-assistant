#!/bin/bash
# Hermes Auto Version System — 一键停止
set -e
VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
cd /home/ly/.hermes/research-assistant/commands || exit 1

echo "💾 停止前备份..."
$VENV -c "from factor_lab.leader.roadmap_backup import auto_backup; b=auto_backup(); print(f'✅ 已备份: {b[\"backup_id\"]}')"

echo "🛑 停止 Dashboard..."
pkill -f "leader:dashboard" 2>/dev/null && echo "✅ Dashboard 已停止" || echo "⚠️ Dashboard 未运行"

echo "📋 当前状态:"
$VENV hermes_cli.py leader:roadmap-status 2>&1
