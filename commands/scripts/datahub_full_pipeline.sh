#!/bin/bash
# =====================================================
# DataHub 全量管线 — 等待主进程完成后顺序执行所有剩余任务
# =====================================================
set -e
DIR="/home/ly/.hermes/research-assistant/commands"
VENV="/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
LOG="/home/ly/.hermes/research-assistant/data/audit/datahub_full_pipeline.log"
MAIN_PID=19276

mkdir -p "$(dirname "$LOG")"
cd "$DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# 0. 等待主进程结束
log "等待主进程 (pid=$MAIN_PID) 完成..."
while kill -0 "$MAIN_PID" 2>/dev/null; do
  sleep 10
done
log "主进程已结束，开始执行剩余管线"

# 1. 北向资金 + 两融 回填
log "=== (1/4) 北向资金 + 两融回填 ==="
$VENV hermes_cli.py data:backfill-timeseries 2>&1 | tee -a "$LOG"
log "北向+两融 完成"

# 2. 概念板块 + 行业 + ETF持仓
log "=== (2/4) 概念/行业/ETF持仓 ==="
$VENV hermes_cli.py data:weekly-refresh 2>&1 | tee -a "$LOG"
log "概念/行业/ETF 完成"

# 3. 财务指标全量（逐股，最慢）
log "=== (3/4) 财务指标全量拉取 ==="
$VENV hermes_cli.py data:pull-fina --start 20200101 2>&1 | tee -a "$LOG"
log "财务指标 完成"

# 4. DataHub 聚合重建 + 新鲜度检查
log "=== (4/4) DataHub 聚合重建 ==="
$VENV hermes_cli.py data:hub-rebuild fundamentals 2>&1 | tee -a "$LOG"
$VENV hermes_cli.py data:hub-rebuild sentiment 2>&1 | tee -a "$LOG"
$VENV hermes_cli.py data:freshness-check 2>&1 | tee -a "$LOG"
log "聚合重建+新鲜度检查 完成"

log "${LOG}"
log "=== 🎉 DataHub 全量管线全部完成 ==="
echo ""
echo "=============================="
echo "📋 DataHub 全量管线结果摘要"
echo "=============================="
tail -30 "$LOG" | grep -E '✅|完成|status|ok|error' | tail -15
echo "=============================="
