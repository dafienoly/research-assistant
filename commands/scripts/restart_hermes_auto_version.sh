#!/bin/bash
# Hermes Auto Version System — 一键重启
set -e
cd /home/ly/.hermes/research-assistant/commands || exit 1

echo "⏹️  停止..."
bash scripts/stop_hermes_auto_version.sh

echo "🧹 检查锁状态..."
/home/ly/.hermes/research-assistant/.venv_quant/bin/python3 -c "from factor_lab.leader.workloop import release_lock; release_lock('completed')"
echo "✅ 锁已释放"

echo "⏳ 等待 3 秒..."
sleep 3

echo "▶️  启动..."
bash scripts/start_hermes_auto_version.sh

echo "🧪 验证..."
/home/ly/.hermes/research-assistant/.venv_quant/bin/python3 hermes_cli.py leader:automation-status 2>&1 | grep -E "cron|tick|lock"
/home/ly/.hermes/research-assistant/.venv_quant/bin/python3 hermes_cli.py leader:roadmap-status 2>&1
echo "✅ 重启完成"
