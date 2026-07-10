#!/bin/bash
# =====================================================
# DataHub 最终全量管线 — 等待当前进程后执行所有剩余任务
# =====================================================
set -e
DIR="/home/ly/.hermes/research-assistant/commands"
VENV="/home/ly/.hermes/research-assistant/.venv_quant/bin/python3"
LOG="/home/ly/.hermes/research-assistant/data/audit/datahub_final_pipeline.log"
MAIN_PID=10642

mkdir -p "$(dirname "$LOG")"
cd "$DIR"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# 0. 等待主进程结束
log "等待主进程 (pid=$MAIN_PID) 完成..."
while kill -0 "$MAIN_PID" 2>/dev/null; do sleep 15; done
log "主进程已结束"

# 1. 财务指标逐股全量
log "=== (1/5) 财务指标 fina_indicator ==="
$VENV hermes_cli.py data:pull-fina --start 20200101 2>&1 | tee -a "$LOG"
log "财务指标 完成"

# 2. 复权因子
log "=== (2/5) 复权因子 adj_factor ==="
$VENV hermes_cli.py data:pull-remaining 2>&1 | tee -a "$LOG"
log "复权因子+涨跌停+停复牌 完成"

# 3. 概念/行业 mx-data
log "=== (3/5) 概念/行业 mx-data ==="
$VENV hermes_cli.py data:pull-concept-industry 2>&1 | tee -a "$LOG"
log "概念/行业 完成"

# 4. DataHub 聚合重建
log "=== (4/5) 聚合重建 + 新鲜度检查 ==="
$VENV hermes_cli.py data:hub-rebuild fundamentals 2>&1 | tee -a "$LOG"
$VENV hermes_cli.py data:hub-rebuild sentiment 2>&1 | tee -a "$LOG"
$VENV hermes_cli.py data:freshness-check 2>&1 | tee -a "$LOG"
log "聚合重建+检查 完成"

# 5. 全系统刷盘
log "=== (5/5) os.sync() 强制落盘 ==="
$VENV -c "import os; os.sync(); print('✅ os.sync() 完成')" 2>&1 | tee -a "$LOG"

log ""
log "=== 🎉 DataHub 全量管线全部完成 ==="
echo ""
echo "======================================"
echo "📋 DataHub 最终状态"
echo "======================================"
$VENV -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
BASE = Path('data/normalized/market')
daily = len([f for f in BASE.glob('*.csv') if not f.name.startswith('valuation_')])
val = len(list(BASE.glob('valuation_*.csv')))
ff = len(list(Path('data/normalized/fund_flow').glob('*.csv')))
fina = len(list(Path('data/normalized/fundamentals').glob('*.csv')))
limits = len(list(Path('data/normalized/limits').glob('*.csv')))
north = sum(1 for _ in open('data/north_flow_timeseries.csv')) - 1 if Path('data/north_flow_timeseries.csv').exists() else 0
margin = sum(1 for _ in open('data/margin_timeseries.csv')) - 1 if Path('data/margin_timeseries.csv').exists() else 0
print(f'  📊 日线:     {daily} 只')
print(f'  📈 估值:     {val} 只')
print(f'  💰 资金流:   {ff} 只')
print(f'  📑 财务:     {fina} 只')
print(f'  📊 复权+涨跌: {limits} 只')
print(f'  🏦 北向:     {north} 行')
print(f'  📊 两融:     {margin} 行')
" 2>&1 | tee -a "$LOG"
echo "======================================"
