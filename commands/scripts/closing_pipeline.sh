#!/bin/bash
# Hermes 收盘管线 — 无 agent 后台静默执行
# 由 cron job 以 no_agent=True 模式调用, agent 繁忙时也可运行

set -e
DIR="/home/ly/.hermes/research-assistant/commands"
VENV="/home/ly/.hermes/research-assistant/.venv_quant/bin/activate"
LOG="/home/ly/.hermes/research-assistant/data/audit/closing_pipeline.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 收盘管线开始 ===" >> "$LOG"

cd "$DIR"
source "$VENV"

# 1. 因子挖掘
echo "[$(date '+%H:%M:%S')] factor:mine 10 ..." >> "$LOG"
python3 hermes_cli.py factor:mine 10 >> "$LOG" 2>&1 || echo "  factor:mine 非致命错误" >> "$LOG"

# 2. 基本面时序重建
echo "[$(date '+%H:%M:%S')] data:hub-rebuild fundamentals ..." >> "$LOG"
python3 hermes_cli.py data:hub-rebuild fundamentals >> "$LOG" 2>&1 || echo "  fundamentals 非致命错误" >> "$LOG"

# 3. 情感时序重建
echo "[$(date '+%H:%M:%S')] data:hub-rebuild sentiment ..." >> "$LOG"
python3 hermes_cli.py data:hub-rebuild sentiment >> "$LOG" 2>&1 || echo "  sentiment 非致命错误" >> "$LOG"

# 4. 新鲜度检查
echo "[$(date '+%H:%M:%S')] data:freshness-check ..." >> "$LOG"
python3 hermes_cli.py data:freshness-check >> "$LOG" 2>&1 || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 收盘管线完成 ===" >> "$LOG"

# 输出结果摘要
echo "=== 收盘管线摘要 ==="
tail -20 "$LOG" | grep -E '✅|⚠️|write|新增|完成'
