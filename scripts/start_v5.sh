#!/usr/bin/bash
# Hermes V5 一键启动脚本
# 同时启动后端 API (FastAPI) + 前端开发服务器 (Vite)
# 用法: bash start_v5.sh [--build] [--prod]

set -e

HERMES_HOME="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERMES_HOME"

# ─── 颜色 ──────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  Hermes V5 Quant Research Control Tower  ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"

# ─── 参数 ──────────────────────────────────────
BUILD=false
PROD=false
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    --prod)  PROD=true ;;
  esac
done

# ─── 检查前端依赖 ──────────────────────────────
if [ ! -d "commands/frontend/node_modules" ]; then
  echo -e "${YELLOW}⏳ 安装前端依赖...${NC}"
  cd commands/frontend && npm install --silent && cd "$HERMES_HOME"
  echo -e "${GREEN}✅ 前端依赖安装完成${NC}"
fi

# ─── 生产模式: 构建前端 ────────────────────────
if [ "$PROD" = true ] || [ "$BUILD" = true ]; then
  echo -e "${YELLOW}⏳ 构建前端生产包...${NC}"
  cd commands/frontend && npm run build && cd "$HERMES_HOME"
  echo -e "${GREEN}✅ 前端构建完成 (dist/)${NC}"
fi

# ─── 检查 data/ 目录 ──────────────────────────
if [ ! -f "data/universes.json" ]; then
  echo -e "${YELLOW}⚠️  data/universes.json 不存在${NC}"
  echo -e "   运行: python3 commands/hermes_cli.py universe:build"
fi

# ─── 启动后端 API ──────────────────────────────
echo -e "${GREEN}🚀 启动后端 API (127.0.0.1:8766)${NC}"

cd "$HERMES_HOME"
.venv_quant/bin/python3 -c "
import sys; sys.path.insert(0, 'commands')
from factor_lab.api_server.main import serve
serve()
" &
BACKEND_PID=$!

sleep 2

# ─── 验证后端启动 ──────────────────────────────
if kill -0 $BACKEND_PID 2>/dev/null; then
  echo -e "${GREEN}✅ 后端 API 启动成功 (PID=$BACKEND_PID)${NC}"
else
  echo -e "${RED}❌ 后端 API 启动失败${NC}"
  exit 1
fi

# ─── 启动前端开发服务器 ────────────────────────
if [ "$PROD" != true ]; then
  echo -e "${GREEN}🚀 启动前端开发服务器 (localhost:5173)${NC}"
  cd commands/frontend
  npm run dev &
  FRONTEND_PID=$!
  cd "$HERMES_HOME"
  echo -e "${GREEN}✅ 前端开发服务器启动 (PID=$FRONTEND_PID)${NC}"
fi

# ─── 输出访问地址 ──────────────────────────────
echo ""
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  Hermes V5 已启动${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
if [ "$PROD" = true ]; then
  echo -e "  访问:  ${GREEN}http://127.0.0.1:8766${NC}          (生产模式)"
else
  echo -e "  前端:   ${GREEN}http://localhost:5173${NC}          (开发模式)"
  echo -e "  后端:   ${GREEN}http://127.0.0.1:8766${NC}          (API)"
fi
echo -e "  API文档: ${GREEN}http://127.0.0.1:8766/docs${NC}"
echo -e "  关闭:    ${YELLOW}bash $(basename "$0") stop${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"

# ─── PID 记录 ──────────────────────────────────
echo "BACKEND_PID=$BACKEND_PID" > /tmp/hermes_v5.pid
[ -n "$FRONTEND_PID" ] && echo "FRONTEND_PID=$FRONTEND_PID" >> /tmp/hermes_v5.pid

# ─── 等待信号 ──────────────────────────────────
trap "echo ''; echo -e '${YELLOW}正在关闭...${NC}'; \
  kill $BACKEND_PID 2>/dev/null; \
  [ -n '$FRONTEND_PID' ] && kill $FRONTEND_PID 2>/dev/null; \
  echo -e '${GREEN}✅ Hermes V5 已关闭${NC}'; exit 0" SIGINT SIGTERM

wait
