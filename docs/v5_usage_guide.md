# Hermes V5 前后端构建与使用指引

## 一、快速启动

```bash
# 1. 启动后端 API 服务器
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 -c "from factor_lab.api_server.main import serve; serve()"

# 2. 启动前端开发服务器（新终端）
cd /home/ly/.hermes/research-assistant/commands/frontend
npm run dev
```

- 后端 API: `http://127.0.0.1:8766`
- 前端开发: `http://localhost:5173`（Vite proxy 自动转发 `/api` → `8766`）
- 前端生产: `http://127.0.0.1:8766`（FastAPI 直接托管 `dist/`）

---

## 二、生产构建

```bash
cd /home/ly/.hermes/research-assistant/commands/frontend
npm run build      # 构建前端 → dist/
```

构建产物：`dist/index.html` + `dist/assets/index-*.js`（~2.8MB gzip ~884KB）

重启后端后，访问 `http://127.0.0.1:8766` 即可看到最新界面。

---

## 三、环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HERMES_UI_TOKEN` | 空（不启用） | 设置后前端需 `Authorization: Bearer ***` |
| `HERMES_ALLOWED_ORIGINS` | `http://127.0.0.1:5173,http://127.0.0.1:8766` | CORS 白名单 |
| `HERMES_REPORTS_BASE` | `/mnt/d/HermesReports` | 报告存放目录 |

示例（带认证启动）：
```bash
HERMES_UI_TOKEN="my-secret-token" \
HERMES_ALLOWED_ORIGINS="http://127.0.0.1:5173,http://127.0.0.1:8766" \
cd /home/ly/.hermes/research-assistant/commands && \
../.venv_quant/bin/python3 -c "from factor_lab.api_server.main import serve; serve()"
```

---

## 四、后端 API 路由一览

### 系统（旧路由，保持兼容）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（无认证） |
| GET | `/api/status` | 系统状态 |
| GET | `/api/version` | 版本信息 |

### 数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/data/sources` | 数据源能力列表 |
| GET | `/api/data/health` | 数据健康状态 |
| GET | `/api/data/coverage` | 数据覆盖报表 |
| GET | `/api/data/freshness` | 数据新鲜度 |
| GET | `/api/data/manifests` | Manifest 列表 |
| GET | `/api/data/manifests/{id}` | Manifest 详情 |

### 股票池

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/universe` | 所有股票池列表 |
| GET | `/api/universe/{id}` | 指定股票池详情（U0-U4/ETF） |
| GET | `/api/universe/{id}/audit` | 股票池审计 |
| POST | `/api/universe/build` | 重建股票池 |

### 基准

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/benchmarks` | 所有基准列表 |
| GET | `/api/benchmarks/{id}` | 基准详情 |
| POST | `/api/benchmarks/build` | 重建基准 |

### 因子

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/factors` | 因子排行榜 |
| GET | `/api/factors/{id}` | 因子详情 |
| POST | `/api/factors/validate` | 运行因子验证 |
| GET | `/api/factors/{id}/risk-attribution` | 风险暴露归因 |
| GET | `/api/factors/{id}/ic` | IC 时序 |
| GET | `/api/factors/{id}/layers` | 分层收益 |

### 回测

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backtests/run` | 运行回测 |
| GET | `/api/backtests` | 回测历史列表 |
| GET | `/api/backtests/{run_id}` | 回测结果详情 |

### 组合推荐

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/portfolio/recommendation/latest` | 最新组合推荐 |
| POST | `/api/portfolio/recommendation/run` | 运行组合推荐 |
| GET | `/api/portfolio/risk` | 组合风险 |
| GET | `/api/portfolio/approval-history` | 审批记录 |

### QMT

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/qmt/health` | QMT 连接状态 |
| GET | `/api/qmt/account` | 账户资产 |
| GET | `/api/qmt/positions` | 真实持仓 |
| GET | `/api/qmt/orders` | 当日委托 |
| GET | `/api/qmt/trades` | 当日成交 |

### Paper / Shadow

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/paper/status` | Paper 状态 |
| POST | `/api/paper/v4-run` | 运行 Paper |
| GET | `/api/paper/dashboard` | Paper 看板 |
| GET | `/api/shadow/status` | Shadow 状态 |
| POST | `/api/shadow/v4-run` | 运行 Shadow |

### Live Gate

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/live-readiness/latest` | 最新 Readiness |
| POST | `/api/live-readiness/run` | 运行检查 |
| GET | `/api/live-readiness/history` | 历史记录 |

### 主题

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/theme/semiconductor/status` | 半导体主题状态 |
| GET | `/api/theme/semiconductor/subsectors` | 细分方向数据 |

### 任务 / 审计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 任务列表 |
| POST | `/api/jobs/run` | 创建任务 |
| GET | `/api/jobs/{run_id}` | 任务详情 |
| GET | `/api/jobs/{run_id}/stream` | SSE 实时日志 |
| GET | `/api/audit/events` | 审计事件列表 |
| GET | `/api/audit/run/{run_id}` | 指定审计详情 |

### 事件 / 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | 事件列表 |
| GET | `/api/events/{id}` | 事件详情 |
| GET | `/api/settings` | 系统设置 |
| POST | `/api/settings/update` | 更新设置 |

---

## 五、前端页面一览

| 页面 | 路由 | TypeScript | 行数 | 后端依赖 |
|------|------|-----------|------|---------|
| 首页驾驶舱 | `/` | ✅ Dashboard.tsx | 661 | `/api/health`, `/api/data/health`, `/api/jobs` |
| 数据中心 | `/data` | ✅ DataStatus.tsx | 607 | `/api/data/*` |
| 股票池 | `/stocks` | ✅ StockPool.tsx | 450 | `/api/universe/*` |
| 半导体主题 | `/semi` | ✅ SemiTheme.tsx | 602 | `/api/theme/semiconductor/*` |
| 因子实验室 | `/factors` | ✅ FactorLab.tsx | 945 | `/api/factors/*` |
| 回测实验室 | `/backtest` | ✅ BacktestLab.tsx | 947 | `/api/backtests/*` |
| 组合推荐 | `/portfolio` | ✅ Portfolio.tsx | 890 | `/api/portfolio/*` |
| QMT 实盘 | `/qmt` | ✅ QMTSpot.tsx | 544 | `/api/qmt/*` |
| Paper/Shadow | `/paper` | ✅ PaperDashboard.tsx | 550 | `/api/paper/*`, `/api/shadow/*` |
| Live Gate | `/livegate` | ✅ LiveGate.tsx | 855 | `/api/live-readiness/*` |
| 报告审计 | `/reports` | ✅ Reports.tsx | 388 | `/api/reports/*` |
| 事件研报 | `/events` | ✅ Events.tsx | 730 | `/api/events/*` |
| 任务中心 | `/tasks` | ✅ TaskCenter.tsx | 571 | `/api/jobs/*` |
| 设置 | `/settings` | ✅ Settings.tsx | 735 | `/api/settings*` |
| Agent Console | `/console` | ✅ AgentConsole.tsx | 213 | `/api/console/*` (AgentOps 抽屉) |
| 路线图 | `/roadmap` | ✅ Roadmap.tsx | 334 | (AgentOps 抽屉) |
| 运维中心 | `/ops` | ✅ OpsCenter.tsx | 624 | (AgentOps 抽屉) |

---

## 六、前端技术栈

```
React 18          UI 框架
TypeScript        类型安全
Vite 8.x          构建工具
Ant Design 5      组件库
React Router 6    路由
TanStack Query    服务端状态管理 (自动轮询/缓存/错误处理)
ECharts           图表 (通过 echarts-for-react)
```

### 项目结构

```
commands/frontend/src/
  app/
    App.tsx             入口 + ErrorBoundary + QueryClientProvider
    routes.tsx          路由表（20条）
    layout/
      MainLayout.tsx    主布局（侧边栏+顶栏+内容区）
      Sidebar.tsx       投研主导航（12项）
      TopStatusBar.tsx  顶部状态条
      AgentOpsDrawer.tsx 系统与自动化抽屉
  api/
    client.ts           统一 API 客户端（Auth/超时/错误处理）
    endpoints.ts        所有后端接口的类型化函数（40+）
    schemas.ts          TypeScript 类型定义（50+ 接口）
  hooks/                15 个 TanStack Query hooks
  components/common/    8 个公共组件
  pages/                20 个页面
```

---

## 七、常见问题

### Q: 开发时需要同时开两个终端吗？
是的。一个跑后端 API，一个跑前端 Vite。Vite 自动代理 `/api` 到后端。

### Q: 生产环境怎么部署？
```bash
cd commands/frontend && npm run build
# 然后只需启动后端，它自动托管 dist/
cd commands && python3 -c "from factor_lab.api_server.main import serve; serve()"
```

### Q: 前端页面空白 / spinner 卡死？
检查后端是否在 8766 端口运行。前端所有数据来自 `fetch('/api/...')`，后端不启动时请求失败会显示 ErrorState（非白屏）。

### Q: 如何添加认证？
```bash
export HERMES_UI_TOKEN="your-token"
```
前端需要在 `api/client.ts` 中从 localStorage 读取 token 并添加到 `Authorization` header。

### Q: 如何修改 CORS？
```bash
export HERMES_ALLOWED_ORIGINS="http://localhost:5173,http://localhost:8766,http://192.168.1.100:8766"
```
