#!/bin/bash
# Hermes Auto Version System — 一键启动
set -e
VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py
cd /home/ly/.hermes/research-assistant/commands || exit 1

echo "🔍 检查 cron 状态..."
$VENV $CLI leader:automation-status 2>&1 | grep -E "cron" || echo "⚠️ cron 可能未运行"

echo "🔍 检查版本一致性..."
$VENV $CLI leader:roadmap-status 2>&1

echo "💾 备份当前状态..."
$VENV -c "from factor_lab.leader.roadmap_backup import auto_backup; b=auto_backup(); print(f'✅ 已备份: {b[\"backup_id\"]}')"

echo "🚀 启动 Dashboard..."
nohup $VENV $CLI leader:dashboard --host 127.0.0.1 --port 8766 > /tmp/hermes_dashboard.log 2>&1 &
echo "✅ Dashboard: http://127.0.0.1:8766"
echo "✅ Console: http://127.0.0.1:8766/console"
echo "✅ 版本推进由 cron 自动运行 (每 3 分钟)"
