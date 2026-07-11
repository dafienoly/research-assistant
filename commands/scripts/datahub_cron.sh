#!/bin/bash
# =====================================================
# DataHub 定时维护脚本 — 由 cronjob no_agent=True 调用
#
# 用法:
#   bash datahub_cron.sh daily-incremental [date]   # 每日增量更新（收盘后）
#   bash datahub_cron.sh weekly-maintenance          # 每周维护（周日）
#   bash datahub_cron.sh freshness-check             # 数据新鲜度检查
#   bash datahub_cron.sh full-init                   # 首次全量初始化
#   bash datahub_cron.sh all                         # 每日全流程（增量+重建+检查）
# =====================================================
set -euo pipefail
DIR="/home/ly/.hermes/research-assistant/commands"
VENV="/home/ly/.hermes/research-assistant/.venv_quant/bin/activate"
LOG="/home/ly/.hermes/research-assistant/data/audit/datahub_cron.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TS] $*"; }

mkdir -p "$(dirname "$LOG")"
cd "$DIR"
source "$VENV"

CMD="${1:-help}"
DATE="${2:-}"

# 静默模式：无数据时不报错（收盘后数据可能还未推送到Tushare）
NO_DATA_OK=1

case "$CMD" in
  daily-incremental)
    log "=== DataHub 每日增量更新开始 ==="
    DATE_ARG=""
    [ -n "$DATE" ] && DATE_ARG="--date $DATE"
    # shellcheck disable=SC2086
    python3 hermes_cli.py data:incremental-update $DATE_ARG 2>&1 | tee -a "$LOG"
    PYTHONPATH=. python3 scripts/datahub_reference_fetch.py 2>&1 | tee -a "$LOG"
    PYTHONPATH=. python3 scripts/datahub_market_series_fetch.py 2>&1 | tee -a "$LOG"
    log "=== DataHub 每日增量更新完成 ==="
    ;;

  weekly-maintenance)
    log "=== DataHub 每周维护开始 ==="
    python3 hermes_cli.py data:weekly-refresh 2>&1 | tee -a "$LOG"
    log "=== DataHub 每周维护完成 ==="
    ;;

  freshness-check)
    log "=== DataHub 新鲜度检查开始 ==="
    python3 hermes_cli.py data:audit 2>&1 | tee -a "$LOG"
    python3 hermes_cli.py data:gap-plan 2>&1 | tee -a "$LOG"
    log "=== DataHub 新鲜度检查完成 ==="
    ;;

  full-init)
    log "=== DataHub 首次全量初始化开始 ==="
    echo "⚠️ 预计运行 1-2 小时，请确保网络稳定"
    python3 hermes_cli.py data:full-init-by-date 2>&1 | tee -a "$LOG"
    log "=== DataHub 首次全量初始化完成 ==="
    ;;

  all)
    log "=== DataHub 每日全流程开始 ==="
    DATE_ARG=""
    [ -n "$DATE" ] && DATE_ARG="--date $DATE"
    # shellcheck disable=SC2086
    python3 hermes_cli.py data:incremental-update $DATE_ARG 2>&1 | tee -a "$LOG"
    PYTHONPATH=. python3 scripts/datahub_reference_fetch.py 2>&1 | tee -a "$LOG"
    PYTHONPATH=. python3 scripts/datahub_market_series_fetch.py 2>&1 | tee -a "$LOG"
    # DataHub 聚合重建
    python3 hermes_cli.py data:hub-rebuild fundamentals 2>&1 | tee -a "$LOG"
    python3 hermes_cli.py data:hub-rebuild sentiment 2>&1 | tee -a "$LOG"
    # 新鲜度检查
    python3 hermes_cli.py data:audit 2>&1 | tee -a "$LOG"
    python3 hermes_cli.py data:gap-plan 2>&1 | tee -a "$LOG"
    log "=== DataHub 每日全流程完成 ==="
    ;;

  help|*)
    echo "用法: bash datahub_cron.sh <command> [date]"
    echo ""
    echo "命令:"
    echo "  daily-incremental [date]   每日增量更新（收盘后调用的核心增量管线）"
    echo "  weekly-maintenance         每周维护（概念/行业/ETF持仓/财务增量）"
    echo "  freshness-check            数据新鲜度检查 + 缺口报告"
    echo "  full-init                  首次全量填充 normalized/ 目录"
    echo "  all [date]                 每日全流程（增量+重建+检查）"
    echo ""
    echo "date 格式: YYYYMMDD，默认当天"
    ;;
esac
