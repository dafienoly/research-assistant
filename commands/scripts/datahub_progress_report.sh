#!/bin/bash
# DataHub 进度报告脚本（cron 每10分钟执行）
DIR="/home/ly/.hermes/research-assistant/commands"
cd "$DIR" || exit 1

MAIN_PID=10642
PIPE_PID=998

running=""
ps -p $MAIN_PID --no-headers >/dev/null 2>&1 && running="主进程$MAIN_PID" || running=""
ps -p $PIPE_PID --no-headers >/dev/null 2>&1 && running="$running 管线$PIPE_PID" || running="$running (无活跃进程)"
[ -z "$running" ] && running="已结束"

daily=$(find /home/ly/.hermes/research-assistant/data/normalized/market -maxdepth 1 -name '*.csv' ! -name 'valuation_*' 2>/dev/null | wc -l)
val=$(find /home/ly/.hermes/research-assistant/data/normalized/market -maxdepth 1 -name 'valuation_*.csv' 2>/dev/null | wc -l)
ff=$(find /home/ly/.hermes/research-assistant/data/normalized/fund_flow -name '*.csv' 2>/dev/null | wc -l)
fina=$(find /home/ly/.hermes/research-assistant/data/normalized/fundamentals -name '*.csv' 2>/dev/null | wc -l)
lim=$(find /home/ly/.hermes/research-assistant/data/normalized/limits -name '*.csv' 2>/dev/null | wc -l)

# 样本行数
rows=$(wc -l < /home/ly/.hermes/research-assistant/data/normalized/market/000001.SZ.csv 2>/dev/null || echo 0)

echo "📊 DataHub 进度 $(date '+%H:%M')"
echo "进程: $running"
echo "日线: ${daily}只 ${rows}行"
echo "估值: ${val}只"
echo "资金流: ${ff}只 ✅"
echo "财务: ${fina}只"
echo "复权/涨跌: ${lim}只"
