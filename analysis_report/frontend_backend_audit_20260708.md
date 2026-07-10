# 投研系统前后端架构审计报告

**时间**: 2026-07-08 23:10 CST  
**范围**: commands/factor_lab/api_server (后端) + commands/frontend (前端)

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                 前端 (React 18 + Vite)                    │
│  localhost:5173 (dev) / localhost:8766 (prod static)    │
│  10 个页面: Dashboard/Data/Console/Roadmap/Reports/     │
│            Risk/Paper/Feedback/Ops/History              │
└──────────────┬──────────────────────────────────────────┘
               │ HTTP / JSON
┌──────────────▼──────────────────────────────────────────┐
│             后端 FastAPI (uvicorn)                        │
│             127.0.0.1:8766                               │
│  10 个路由模块: status/roadmap/console/backup/data/     │
│               reports/risk/paper/feedback/ops            │
└──────────────┬──────────────────────────────────────────┘
               │ import
┌──────────────▼──────────────────────────────────────────┐
│         commands/ 因子引擎 + 策略 + 数据 + 风控           │
│         200+ Python 模块                                 │
└─────────────────────────────────────────────────────────┘
```

---

## 二、后端 (FastAPI API Server)

### 路由模块审计

| 路由 | 前缀 | 行数 | 主要功能 | 状态 |
|------|------|------|---------|------|
| `main.py` | — | 57 | 入口: CORS, 路由注册, SPA fallback, 静态文件 | ✅ |
| `routes_status.py` | `/api` | 50+ | 系统健康检查 | ✅ |
| `routes_roadmap.py` | `/api` | ~130 | 路线图状态查询 | ✅ |
| `routes_console.py` | `/api` | ~200 | Agent Console (SSE流式推送) | ✅ |
| `routes_backup.py` | `/api` | ~35 | 路线图备份管理 | ✅ |
| `routes_data.py` | `/api` | ~200 | 数据源注册表、健康、采集 | ✅ |
| `routes_reports.py` | `/api` | 631 | 报告中心: 发现/查看/管理 | ✅ |
| `routes_risk.py` | `/api` | ~160 | 风控仪表盘、安全边界 | ✅ |
| `routes_paper.py` | `/api` | ~120 | Paper Trading 状态/操作 | ✅ |
| `routes_feedback.py` | `/api` | ~170 | 用户反馈提交/查询 | ✅ |
| `routes_ops.py` | `/api` | ~110 | 运维操作 | ✅ |

### 后端暴露的 API 端点（按功能域）

| 功能域 | 关键端点 | 数据来源 |
|--------|---------|---------|
| **系统状态** | `GET /api/health` | 运行时 + 数据源 |
| **路线图** | `GET /api/roadmap` | leader/roadmap* |
| **Agent Console** | `GET /api/console/list` / `POST /api/console/create` / `SSE /api/console/{id}/stream` | agent_console/ |
| **数据中心** | `GET /api/data/health` / `GET /api/data/coverage` | data_health, data_source |
| **报告中心** | `GET /api/reports/list` / `GET /api/reports/view` | /mnt/d/HermesReports/ |
| **风控** | `GET /api/risk/status` / `GET /api/risk/log` | kill_switch, risk_sentinel |
| **Paper Trading** | `GET /api/paper/status` / `POST /api/paper/action` | paper/standing_paper_trading |
| **反馈** | `POST /api/feedback/submit` / `GET /api/feedback/list` | decision/ |
| **运维** | `GET /api/ops/backup-list` / `POST /api/ops/backup` | leader/roadmap_backup |

### 后端基础架构

| 组件 | 状态 |
|------|------|
| FastAPI (uvicorn) | ✅ |
| CORS 全开放 | ⚠️ `allow_origins=["*"]` — 生产环境需限制 |
| SPA fallback (404→index.html) | ✅ |
| 静态文件服务 (dist) | ✅ |
| 静态文件构建状态 | ✅ dist 已构建 (2026-07-08) |
| 认证/鉴权 | ❌ 无任何认证中间件 |
| 速率限制 | ❌ 无 |
| 日志 | ❌ 无统一请求日志 |
| API 文档 (Swagger) | ✅ FastAPI 自动生成 `/docs` |

---

## 三、前端 (React + Vite)

### 技术栈

| 组件 | 版本/类型 |
|------|----------|
| React | 18.x |
| Vite | 最新版 |
| Ant Design | 5.x |
| React Router | 6.x (HashRouter) |
| 请求 | fetch (原生, 无 axios) |
| 构建输出 | dist/ (静态 HTML + JS bundle) |

### 页面功能审计

| 页面 | 路由 | 主要功能 | 对应后端API | 状态 |
|------|------|---------|------------|------|
| **总览 Dashboard** | `/` | 系统健康、版本状态 | `/api/health` | ✅ |
| **数据状态** | `/data` | 数据源列表、覆盖、新鲜度 | `/api/data/*` | ✅ |
| **Agent Console** | `/console` | 创建/查看 Agent session, SSE 实时流 | `/api/console/*` | ✅ |
| **路线图** | `/roadmap` | 查看/编辑 V3-V9 版本 | `/api/roadmap` | ✅ |
| **报告中心** | `/reports` | 回测/策略/版本报告列表+查看 | `/api/reports/*` | ✅ |
| **风险仪表盘** | `/risk` | Kill Switch、安全边界、异常 | `/api/risk/*` | ✅ |
| **纸面交易** | `/paper` | Paper Trading 状态 | `/api/paper/*` | ✅ |
| **反馈** | `/feedback` | 提交/查看反馈 | `/api/feedback/*` | ✅ |
| **运维中心** | `/ops` | 备份/恢复 | `/api/ops/*` | ✅ |
| **Session 历史** | `/history` | 历史 session | agent_console/ | ✅ |

### 前端代码组织

```
src/
├── App.jsx          — 路由 + 侧边栏布局 (React Router + Ant Design)
├── main.jsx         — Vite 入口
├── App.css          — 全局样式
├── index.css        — Ant Design 主题覆盖
├── assets/          — 静态资源
├── hooks/           — 自定义 hooks
└── pages/           — 10 个页面组件
    ├── Dashboard.jsx
    ├── DataStatus.jsx
    ├── AgentConsole.jsx
    ├── Roadmap.jsx
    ├── Reports.jsx
    ├── RiskDashboard.jsx
    ├── PaperDashboard.jsx
    ├── Feedback.jsx
    ├── OpsCenter.jsx
    └── SessionHistory.jsx
```

---

## 四、前后端交互模式

### 通信协议

```
前端 ←→ 后端: JSON over HTTP (非 GraphQL, 非 WebSocket 除 SSE)
SSE 仅在 Agent Console 页面使用: /api/console/{id}/stream
```

### 数据流

```
页面加载
  → fetch(`/api/{resource}`)
  → 后端调用 commands/ 下的模块
  → 返回 JSON
  → 前端渲染
```

### 缺失的自动化集成

| 能力 | 当前状态 | 缺口 |
|------|---------|------|
| V4.0 data:bootstrap 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.2 data:pipeline 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.3 benchmark:list 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.4 factor:validate-v4 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.5 semiconductor_factors 后端集成 | ❌ | 有模块但无 API 端点 |
| V4.7 portfolio:recommend 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.8 shadow:v4-run 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.9 live-readiness:v4 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |
| V4.10 semiconductor_events 后端集成 | ❌ | 有模块但无 API 端点 |
| V4.11 intraday:monitor 后端集成 | ❌ | 有 CLI 命令但无对应 API 端点 |

---

## 五、关键发现与风险

### P1: 后端缺少认证和鉴权

**问题**: FastAPI 无任何认证中间件，CORS `allow_origins=["*"]`，所有端点可被局域网其他进程访问。

**影响**: 本地开发无风险，但如果后续通过 Nginx 暴露或 Windows 侧映射则可能被未授权访问。

**建议**: 添加 Token 检查中间件（或依赖 Hermes Gateway 代理）

### P1: V4 新功能未对接前端

**问题**: V4.0-V4.11 的 CLI 命令在 hermes_cli.py 中已注册，但 API server 的 10 个路由模块中没有任何 V4 新增的端点。前端也无法访问 V4 功能。

**影响**: V4 功能只能通过 CLI `python3 hermes_cli.py` 使用，无法通过 Web UI 访问。

**建议**: 新建 `routes_v4.py` 路由模块，注册 V4 关键功能端点

### P2: 前端无状态管理

**问题**: 前端使用原生 fetch 无全局状态管理（Redux/Zustand/React Query），每个页面独立请求数据。

**影响**: 数据一致性无保障，重复请求无缓存，SSE 连接管理在页面级别。

**建议**: 引入 React Query 或 SWR 管理服务端状态

### P2: 无前端测试

**问题**: 10 个页面组件、5 个 hooks 无任何单元测试或 E2E 测试（`test_*.py` 全部是后端 Python 测试）。

**影响**: 前端重构或新增功能可能引入回归。

**建议**: 至少添加 Smoke Test（页面加载不 crash）

### P3: 构建输出 2 周未更新

**问题**: `dist/index.html` 2026-07-08 16:54 构建，但部分页面变更可能在之后。

**建议**: 建立 CI 构建流程或 `npm run build` 纳入版本推进

### P3: 无前端错误边界

**问题**: 无 `ErrorBoundary` 组件，API 失败时可能出现白屏或未处理异常。

**建议**: 添加全局 ErrorBoundary + 错误提示组件

---

## 六、综合评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 后端架构合理性 | ⭐⭐⭐⭐ | FastAPI 路由拆分清晰，模块化好 |
| 后端代码质量 | ⭐⭐⭐⭐ | 类型提示、docstring、异常处理普遍覆盖 |
| 后端 API 覆盖率 | ⭐⭐⭐ | V4 新功能未暴露到 API，仅 CLI 可用 |
| 后端安全 | ⭐⭐ | 无认证、CORS 全开放 |
| 前端架构合理性 | ⭐⭐⭐⭐ | React Router + Ant Design，页面拆分合理 |
| 前端代码质量 | ⭐⭐⭐ | 原生 fetch 无封装，无状态管理 |
| 前后端集成度 | ⭐⭐⭐ | 基础功能集成完成，V4 新功能待补 |
| 前端测试 | ⭐ | 无任何前端测试 |
| SSR/SSE 支持 | ⭐⭐⭐ | Agent Console SSE 实现正确 |
| 部署就绪度 | ⭐⭐⭐ | 需补充 Nginx 反向代理配置 |

**总体评级**: 基础架构合理，后端 CLI 功能充实，前端覆盖主要页面。主要缺口在：① V4 新功能未集成到 API/前端，② 无认证鉴权，③ 无前端测试。
