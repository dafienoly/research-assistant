#!/bin/bash
# Hermes One-click Local Ops — 一键运维入口
# Usage: bash hermes_ops.sh <command> [service]
#   Commands:
#     health       — 所有服务健康状态
#     start <svc>  — 启动服务 (dashboard|auto-loop|mcp)
#     stop <svc>   — 停止服务
#     restart <svc> — 重启服务
#     backup       — 一键备份
#     diag         — 全面诊断
#     ports        — 端口扫描
#     all          — 启动所有核心服务

set -e

VENV=/home/ly/.hermes/research-assistant/.venv_quant/bin/python3
CLI=/home/ly/.hermes/research-assistant/commands/hermes_cli.py
cd /home/ly/.hermes/research-assistant/commands || exit 1

show_usage() {
  echo "用法: bash hermes_ops.sh <command> [service]"
  echo ""
  echo "命令:"
  echo "  health              查看所有服务健康状态"
  echo "  start <service>     启动服务: dashboard | auto-loop | mcp"
  echo "  stop <service>      停止服务"
  echo "  restart <service>   重启服务"
  echo "  backup              一键备份 (状态+配置+日志)"
  echo "  diag                全面诊断报告"
  echo "  ports               端口占用扫描"
  echo "  all                 启动全部核心服务 (dashboard+auto-loop)"
  exit 0
}

CMD=${1:-help}
SERVICE=${2:-}

case "$CMD" in
  health)
    echo "🔍 服务健康状态检查..."
    echo "────────────────────────────────────────"
    $VENV $CLI leader:ops-health
    ;;

  start)
    if [ -z "$SERVICE" ]; then
      echo "❌ 请指定服务: dashboard | auto-loop | mcp"
      echo "用法: bash hermes_ops.sh start dashboard"
      exit 1
    fi
    echo "🚀 启动 $SERVICE ..."
    $VENV $CLI leader:ops-start "$SERVICE"
    ;;

  stop)
    if [ -z "$SERVICE" ]; then
      echo "❌ 请指定服务: dashboard | auto-loop | mcp"
      echo "用法: bash hermes_ops.sh stop dashboard"
      exit 1
    fi
    echo "🛑 停止 $SERVICE ..."
    $VENV $CLI leader:ops-stop "$SERVICE"
    ;;

  restart)
    if [ -z "$SERVICE" ]; then
      echo "❌ 请指定服务: dashboard | auto-loop | mcp"
      echo "用法: bash hermes_ops.sh restart dashboard"
      exit 1
    fi
    echo "🔄 重启 $SERVICE ..."
    $VENV $CLI leader:ops-restart "$SERVICE"
    ;;

  backup)
    echo "💾 一键备份..."
    echo "────────────────────────────────────────"
    $VENV $CLI leader:ops-backup
    ;;

  diag)
    echo "🩺 全面诊断..."
    echo "────────────────────────────────────────"
    $VENV $CLI leader:ops-diagnostics
    ;;

  ports)
    echo "🔌 端口扫描..."
    echo "────────────────────────────────────────"
    $VENV $CLI leader:ops-ports
    ;;

  all)
    echo "🚀 启动全部核心服务..."
    echo "────────────────────────────────────────"
    echo ""
    echo ">>> 1/3: Dashboard (port 8766)"
    $VENV $CLI leader:ops-start dashboard
    sleep 2
    echo ""
    echo ">>> 2/3: Auto Version Loop"
    $VENV $CLI leader:ops-start auto-loop
    echo ""
    echo ">>> 3/3: 验证启动状态"
    $VENV $CLI leader:ops-health | $VENV -c "
import sys, json
d = json.load(sys.stdin)
svc = d.get('services', {})
for sid, s in svc.items():
    icon = '✅' if s.get('running') else '❌'
    print(f'  {icon} {s.get(\"name_zh\", sid)} ({sid})')
ok = all(s.get('running') for s in svc.values())
print(f'\\n{\"✅ 所有服务已就绪\" if ok else \"⚠️ 部分服务未运行\"}')" 2>/dev/null || true
    echo ""
    echo "📊 Dashboard: http://127.0.0.1:8766"
    ;;

  help|*)
    show_usage
    ;;
esac
