# Hermes V5 Roadmap：现代化投研前后端控制塔重构方案

## 基于 React + Vite + TypeScript + Ant Design + FastAPI 的量化投研可视化系统

---

# 一、V5 总定位

Hermes V5 的目标是把当前前后端系统从“任务/报告/运维页面集合”升级为：

```text
A 股低频量化投研控制塔
Hermes Quant Research Control Tower
```

V5 不推倒重写，不迁移 Next.js，不更换后端框架。
V5 的重点是：

1. 固化前后端 API 契约；
2. 把 V4 核心量化能力接入 Web UI；
3. 把自动版本推进系统从主界面移走；
4. 建立现代化投研驾驶舱；
5. 支持数据健康、股票池、半导体主题、因子、回测、组合、QMT、Paper/Shadow、Live Gate、报告审计的完整可视化；
6. 建立任务中心、审计链路、Run ID、Manifest、Artifact；
7. 让用户不再主要依赖 CLI 和零散 Markdown 报告。

V5 的核心不是“做一个漂亮网页”，而是让 Hermes 变成一个：

```text
可查看
可追溯
可解释
可审计
可风控
可对账
可长期迭代
```

的现代化量化控制台。

---

# 二、当前架构现状

当前系统已有基础架构：

## 前端

```text
React 18
Vite
Ant Design 5
React Router 6
HashRouter
原生 fetch
10 个页面：
Dashboard / Data / Console / Roadmap / Reports / Risk / Paper / Feedback / Ops / History
```

## 后端

```text
FastAPI
uvicorn
127.0.0.1:8766
SPA fallback
静态文件服务
SSE Agent Console
10 个路由模块：
status / roadmap / console / backup / data / reports / risk / paper / feedback / ops
```

## 当前优点

1. React + Vite 架构轻量，适合本地投研控制台；
2. Ant Design 适合表格、表单、后台布局；
3. FastAPI 与 Hermes Python 量化系统天然兼容；
4. SSE 已经跑通，可复用到任务日志和实时状态；
5. 报告中心、数据状态、风控、Paper、Agent Console 已有基础页面。

## 当前主要问题

1. 主导航被 Agent Console、Roadmap、Ops、History 等自动版本推进系统污染；
2. V4 新功能多数只有 CLI，没有 API 和前端页面；
3. 前端无统一 API client；
4. 前端无 React Query / SWR 服务端状态管理；
5. 前端无 TypeScript；
6. 前端无统一 Loading / Empty / Error / NotReady 状态；
7. 前端无错误边界；
8. 后端无认证；
9. CORS 全开放；
10. 后端无统一响应格式；
11. 后端无统一任务模型；
12. 后端无统一 Run ID / Manifest / Artifact / AuditEvent API；
13. 无前端测试；
14. 无清晰的投研主界面信息架构。

---

# 三、最终技术选型

## 3.1 前端技术栈

V5 采用：

```text
React 18
Vite
TypeScript
Ant Design 5
React Router 6
TanStack Query
ECharts
Zustand
Vitest
React Testing Library
Playwright，后续
```

## 3.2 后端技术栈

V5 采用：

```text
FastAPI
Pydantic
uvicorn
DuckDB
Parquet
SQLite metadata
JSONL audit log
SSE
Command Runner
Job Service
Audit Service
Manifest Service
Artifact Service
```

## 3.3 暂不采用

当前不采用：

```text
Next.js
Node / NestJS 后端
Django
Streamlit 主系统
Dash 主系统
Electron
Tauri
Vue / Nuxt
SvelteKit
```

原因：

1. Hermes 是本地 / 内网量化控制台，不需要 SSR / SEO；
2. 核心量化能力在 Python，FastAPI 最合适；
3. React + Vite 已有基础，迁移成本最低；
4. Ant Design 很适合数据后台和投研控制台；
5. V5 的核心问题是信息架构、API 契约、状态管理、安全、测试，而不是框架选错。

---

# 四、V5 架构原则

## 4.1 不推倒重写

保留现有：

```text
React + Vite
Ant Design
FastAPI
SSE
静态部署模式
```

但进行工程化升级：

```text
JavaScript → TypeScript
裸 fetch → API Client + TanStack Query
页面堆叠 → 业务域模块
粗糙后台 → 投研控制塔
CLI-only → API + Job Service
无审计 → Run ID + Manifest + Artifact + Audit Trail
```

## 4.2 投研主系统优先

主界面只放投研用户每天真正需要看的内容：

```text
首页
数据中心
股票池
半导体主题
因子实验室
回测实验室
组合推荐
QMT 实盘
Paper / Shadow
Live Gate
报告审计
```

自动版本推进系统移入：

```text
系统与自动化
```

小入口中。

## 4.3 AgentOps 降级为高级入口

以下页面不再出现在主导航：

```text
Agent Console
Roadmap
Ops Center
Session History
Feedback
Backup
```

统一放入：

```text
系统与自动化 / AgentOps
```

入口形式：

```text
右上角齿轮
或侧边栏底部小按钮
或折叠菜单
```

默认不展开，避免污染投研主界面。

## 4.4 所有判断必须有证据

任何页面上的成功、失败、推荐、READY、NOT_READY，都必须能追溯：

```text
run_id
manifest_id
data_source
fetch_time
sample_range
universe
benchmark
gate_result
audit_log
artifact_path
```

## 4.5 默认只读，不自动交易

V5 第一阶段允许：

```text
查看数据
触发研究任务
触发回测
查看 QMT 状态
查看持仓
查看 Paper / Shadow
查看 Live Gate
提交人工反馈
```

禁止：

```text
自动下单
自动撤单
绕过审批
绕过 Gate
无审计交易
```

---

# 五、V5 目标信息架构

## 5.1 主导航

```text
1. 首页
2. 数据中心
3. 股票池
4. 半导体主题
5. 因子实验室
6. 回测实验室
7. 组合推荐
8. QMT 实盘
9. Paper / Shadow
10. Live Gate
11. 报告审计
12. 系统与自动化
```

## 5.2 系统与自动化二级入口

```text
Agent Console
Roadmap
Ops Center
Session History
Feedback
Backup
Settings
```

## 5.3 当前页面迁移关系

| 当前页面           | V5 新位置                  | 处理方式                            |
| -------------- | ----------------------- | ------------------------------- |
| Dashboard      | 首页                      | 重构为投研驾驶舱                        |
| DataStatus     | 数据中心                    | 保留并增强                           |
| AgentConsole   | 系统与自动化                  | 移出主导航                           |
| Roadmap        | 系统与自动化                  | 移出主导航                           |
| Reports        | 报告审计                    | 增强 Run ID / Manifest / Artifact |
| RiskDashboard  | Live Gate / QMT / 首页风险卡 | 拆分重构                            |
| PaperDashboard | Paper / Shadow          | 合并 Shadow                       |
| Feedback       | 系统与自动化                  | 移出主导航                           |
| OpsCenter      | 系统与自动化                  | 移出主导航                           |
| SessionHistory | 系统与自动化                  | 移出主导航                           |

---

# 六、V5 前端目录重构

当前目录：

```text
src/
  App.jsx
  main.jsx
  App.css
  index.css
  hooks/
  pages/
```

V5 建议目录：

```text
src/
  app/
    App.tsx
    routes.tsx
    layout/
      MainLayout.tsx
      Sidebar.tsx
      TopStatusBar.tsx
      AgentOpsDrawer.tsx

  api/
    client.ts
    endpoints.ts
    schemas.ts
    errors.ts

  hooks/
    useHealth.ts
    useDataHealth.ts
    useUniverse.ts
    useBenchmarks.ts
    useFactors.ts
    useQmt.ts
    useLiveReadiness.ts
    useJobs.ts
    useJobStream.ts

  components/
    common/
      PageHeader.tsx
      StatusBadge.tsx
      MetricCard.tsx
      EmptyState.tsx
      ErrorState.tsx
      LoadingState.tsx
      NotReadyState.tsx
      RunIdTag.tsx
      ManifestLink.tsx

    charts/
      EquityCurveChart.tsx
      DrawdownChart.tsx
      FactorIcChart.tsx
      LayerReturnChart.tsx
      ExposureBarChart.tsx
      ThemeHeatmap.tsx
      PortfolioWeightChart.tsx
      QmtPnlChart.tsx

    tables/
      DataCoverageTable.tsx
      UniverseTable.tsx
      FactorTable.tsx
      PositionTable.tsx
      JobTable.tsx

    audit/
      AuditTrailPanel.tsx
      ManifestPanel.tsx
      GateChecklist.tsx
      ArtifactPanel.tsx

  pages/
    home/
      HomeDashboard.tsx

    data/
      DataCenter.tsx
      DataSourceProbe.tsx
      DataCoverage.tsx
      DataManifest.tsx

    universe/
      UniverseCenter.tsx
      UniverseDetail.tsx
      ThemeTagEditor.tsx

    theme/
      SemiconductorThemeDashboard.tsx

    factor/
      FactorLab.tsx
      FactorDetail.tsx
      FactorCompare.tsx

    backtest/
      BacktestLab.tsx
      BacktestResult.tsx

    portfolio/
      PortfolioRecommendation.tsx

    qmt/
      QmtLiveCenter.tsx
      QmtPositions.tsx
      QmtOrders.tsx
      QmtTrades.tsx

    paper/
      PaperShadowDashboard.tsx

    live/
      LiveReadiness.tsx

    reports/
      ReportsAuditCenter.tsx

    agentops/
      AgentConsole.tsx
      Roadmap.tsx
      OpsCenter.tsx
      SessionHistory.tsx
      Feedback.tsx
      Settings.tsx
```

---

# 七、V5 后端重构

## 7.1 保留现有后端基础

继续使用：

```text
FastAPI
uvicorn
SPA fallback
静态文件服务
SSE
```

## 7.2 新增中间件

新增：

```text
AuthMiddleware
RequestLoggingMiddleware
ErrorHandlingMiddleware
RunContextMiddleware
CorsConfig
```

## 7.3 安全要求

当前 CORS 不得继续使用：

```python
allow_origins=["*"]
```

改为环境变量：

```text
HERMES_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://127.0.0.1:8766
```

新增 UI Token：

```text
HERMES_UI_TOKEN
```

前端请求：

```text
Authorization: Bearer <token>
```

要求：

1. 本地使用也要有最小 Token 防护；
2. 不得在日志中打印 token；
3. Tushare Token、企业微信 Webhook、QMT 账户信息均需脱敏；
4. 默认只监听 `127.0.0.1`；
5. 不允许默认监听 `0.0.0.0`。

## 7.4 后端路由拆分

不要新增一个巨大的 `routes_v4.py` 或 `routes_v5.py`。

新增业务路由：

```text
routes_jobs.py
routes_audit.py
routes_universe.py
routes_benchmark.py
routes_factor.py
routes_backtest.py
routes_portfolio.py
routes_qmt.py
routes_live.py
routes_theme.py
routes_events.py
routes_settings.py
```

保留并逐步改造：

```text
routes_status.py
routes_data.py
routes_reports.py
routes_risk.py
routes_paper.py
routes_console.py
routes_roadmap.py
routes_ops.py
routes_feedback.py
```

## 7.5 新增服务层

新增：

```text
services/
  command_runner.py
  job_service.py
  artifact_service.py
  manifest_service.py
  audit_service.py
  qmt_service.py
  data_service.py
  factor_service.py
  universe_service.py
  benchmark_service.py
  portfolio_service.py
```

服务层职责：

1. API 不直接拼命令；
2. API 调用 service；
3. service 调用 Hermes CLI / Python 模块；
4. 每次任务生成 Run ID；
5. 每次任务写 Artifact、Manifest、AuditEvent。

---

# 八、统一 API 契约

## 8.1 成功响应

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "run_id": "run_xxx",
    "as_of": "2026-07-08T15:00:00",
    "source": "tushare",
    "freshness_seconds": 120,
    "manifest_id": "manifest_xxx"
  }
}
```

## 8.2 失败响应

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "DATA_STALE",
    "message": "数据超过允许新鲜度",
    "detail": {},
    "suggestion": "请运行 data:update"
  },
  "meta": {
    "run_id": "run_xxx"
  }
}
```

## 8.3 Job 模型

```json
{
  "run_id": "run_20260708_xxx",
  "type": "factor_validate",
  "status": "running",
  "started_at": "2026-07-08T09:00:00",
  "ended_at": null,
  "params": {},
  "artifacts": [],
  "manifest_ids": [],
  "audit_event_ids": [],
  "stdout_tail": "",
  "stderr_tail": ""
}
```

## 8.4 Manifest 模型

```json
{
  "manifest_id": "manifest_xxx",
  "run_id": "run_xxx",
  "source": "tushare",
  "api_name": "daily",
  "params_hash": "abc123",
  "row_count": 5528,
  "field_count": 11,
  "fetch_time": "2026-07-08T15:00:00",
  "file_path": "data/normalized/market/daily/..."
}
```

---

# 九、V5 API 规划

## 9.1 Health / Status

```text
GET /api/health
GET /api/status
GET /api/version
```

## 9.2 Jobs

```text
GET  /api/jobs
GET  /api/jobs/{run_id}
POST /api/jobs/run
POST /api/jobs/{run_id}/rerun
GET  /api/jobs/{run_id}/stream
GET  /api/jobs/{run_id}/artifacts
```

## 9.3 Data

```text
GET  /api/data/sources
GET  /api/data/health
GET  /api/data/coverage
GET  /api/data/freshness
GET  /api/data/manifests
GET  /api/data/manifests/{manifest_id}
POST /api/data/probe-source
POST /api/data/bootstrap-all-a
POST /api/data/bootstrap-fundamentals
POST /api/data/update
```

## 9.4 Universe

```text
GET  /api/universe
GET  /api/universe/{universe_id}
GET  /api/universe/{universe_id}/audit
POST /api/universe/build
POST /api/universe/tags/update
GET  /api/universe/semiconductor-core
GET  /api/universe/matched-control
```

## 9.5 Theme

```text
GET  /api/theme/semiconductor/status
GET  /api/theme/semiconductor/factors
GET  /api/theme/semiconductor/timeline
GET  /api/theme/semiconductor/subsectors
POST /api/theme/semiconductor/refresh
```

## 9.6 Benchmark

```text
GET  /api/benchmarks
POST /api/benchmarks/build
GET  /api/benchmarks/{benchmark_id}
GET  /api/benchmarks/semiconductor-peer
```

## 9.7 Factor

```text
GET  /api/factors
GET  /api/factors/{factor_id}
POST /api/factors/validate
GET  /api/factors/{factor_id}/risk-attribution
GET  /api/factors/{factor_id}/ic
GET  /api/factors/{factor_id}/layers
GET  /api/factors/{factor_id}/lineage
```

## 9.8 Backtest

```text
POST /api/backtests/run
GET  /api/backtests
GET  /api/backtests/{run_id}
GET  /api/backtests/{run_id}/trades
GET  /api/backtests/{run_id}/benchmarks
GET  /api/backtests/{run_id}/risk
```

## 9.9 Portfolio

```text
GET  /api/portfolio/recommendation/latest
POST /api/portfolio/recommendation/run
GET  /api/portfolio/risk
GET  /api/portfolio/blocked
GET  /api/portfolio/approval-history
```

## 9.10 QMT

```text
GET  /api/qmt/health
GET  /api/qmt/account
GET  /api/qmt/positions
GET  /api/qmt/orders
GET  /api/qmt/trades
GET  /api/qmt/quotes
GET  /api/qmt/reconcile
POST /api/qmt/risk-check
```

## 9.11 Paper / Shadow

```text
GET  /api/paper/status
POST /api/paper/v4-run
GET  /api/paper/dashboard
GET  /api/shadow/status
POST /api/shadow/v4-run
GET  /api/shadow/dashboard
```

## 9.12 Live Gate

```text
GET  /api/live-readiness/latest
POST /api/live-readiness/run
GET  /api/live-readiness/history
GET  /api/live-readiness/{run_id}
```

## 9.13 Reports / Audit

```text
GET /api/reports/list
GET /api/reports/view
GET /api/audit/events
GET /api/audit/run/{run_id}
GET /api/artifacts/{artifact_id}
```

## 9.14 AgentOps

保留原有：

```text
GET  /api/console/list
POST /api/console/create
GET  /api/console/{id}/stream
GET  /api/roadmap
GET  /api/ops/backup-list
POST /api/ops/backup
GET  /api/feedback/list
POST /api/feedback/submit
```

但前端移入 `系统与自动化`。

---

# 十、V5 版本 Roadmap

---

## V5.0：后端 API Contract 与安全加固

### 目标

先规范后端 API、安全和任务模型，不先做页面。

### 任务

1. 增加统一响应格式；
2. 增加统一错误格式；
3. 增加本地 Token 鉴权；
4. 限制 CORS；
5. 增加请求日志；
6. 增加 Run ID；
7. 增加 Jobs API；
8. 增加 Audit API；
9. 增加 Command Runner；
10. 保持旧 API 兼容。

### 验收标准

1. `/api/health` 正常；
2. `/api/jobs` 正常；
3. `/api/data/health` 正常；
4. 请求无 Token 时返回 401；
5. CORS 不再是 `*`；
6. 所有错误统一格式；
7. 旧前端页面不崩。

---

## V5.1：前端 TypeScript 迁移与 Shell 重构

### 目标

建立 V5 前端工程基础。

### 任务

1. React 项目迁移 TypeScript；
2. `App.jsx` → `App.tsx`；
3. 重构路由文件；
4. 新建 `MainLayout`；
5. 新建 `TopStatusBar`；
6. 新建 `Sidebar`；
7. 新建 `AgentOpsDrawer`；
8. 新建全局 `ErrorBoundary`；
9. 新建统一 Loading / Empty / Error / NotReady 组件。

### 验收标准

1. 项目可正常 `npm run build`；
2. 主导航更新；
3. AgentOps 从主导航移除；
4. AgentOps 小入口可打开；
5. 旧页面仍可访问；
6. 无白屏。

---

## V5.2：前端 API Client 与 TanStack Query

### 目标

解决裸 fetch、无缓存、无统一错误处理的问题。

### 任务

1. 引入 `@tanstack/react-query`；
2. 新建 `src/api/client.ts`；
3. 新建 `src/api/endpoints.ts`；
4. 封装 API 错误；
5. 封装 token header；
6. 封装常用 hooks；
7. 增加自动刷新；
8. 增加 stale 状态；
9. 增加全局请求失败提示。

### 核心 hooks

```text
useHealth()
useDataHealth()
useUniverseList()
useBenchmarkList()
useFactorRanking()
useQmtHealth()
useLiveReadiness()
useJobs()
useJobStream(runId)
```

### 验收标准

1. 新页面不再直接裸 fetch；
2. API 错误统一展示；
3. 支持自动刷新；
4. QMT 状态和任务状态可轮询；
5. 请求失败不白屏。

---

## V5.3：首页投研驾驶舱

### 目标

用户打开系统后第一眼知道 Hermes 是否可用。

### 页面模块

```text
系统状态
数据健康
Tushare 状态
QMT 状态
半导体主题状态
最新组合建议
Paper / Shadow 状态
Live Readiness
最新任务
最新风险预警
```

### 验收标准

1. 红色状态可点击进入详情；
2. 显示更新时间；
3. 显示数据源；
4. 显示 QMT 是否在线；
5. 显示 Live Gate READY / NOT_READY；
6. 首页不显示 Roadmap / Agent Console 主入口。

---

## V5.4：数据中心重构

### 目标

可视化 Tushare 主数据源、本地数据仓库、数据覆盖和 Manifest。

### 页面

```text
数据源能力
数据覆盖
数据新鲜度
数据缺失
Manifest 浏览器
数据血缘
```

### 功能

1. 查看 Tushare daily、fina_indicator、daily_basic 等接口能力；
2. 查看全 A 数据覆盖；
3. 查看最新交易日；
4. 查看缺失率；
5. 查看 Manifest；
6. 触发 `data:probe-source`；
7. 触发 `data:health`。

### 验收标准

1. 能看到 Tushare 接口能力；
2. 能看到本地数据覆盖；
3. 能查看 manifest；
4. 数据缺失醒目展示；
5. 不使用 mock 数据冒充真实数据。

---

## V5.5：股票池中心

### 目标

可视化 U0-U4 与 ETF 替代池。

### 页面

```text
U0 全 A
U1 用户可交易池
U2 AI/半导体广义池
U3 半导体核心池
U4 匹配对照池
ETF 替代池
标签编辑器
```

### 验收标准

1. U3 半导体核心池可按细分方向筛选；
2. 每只股票显示核心度评分；
3. 每只股票显示是否用户可交易；
4. U4 能解释匹配逻辑；
5. 标签变更写审计日志。

---

## V5.6：半导体主题看板

### 目标

展示半导体主题强弱和建议仓位。

### 页面模块

```text
半导体等权 vs 全 A 等权
半导体核心池 vs 广义池
成交额占比
上涨家数占比
细分方向热力图
ETF 篮子表现
主题状态
建议仓位
```

### 验收标准

1. 主题强弱可解释；
2. 仓位建议可追溯；
3. 必须展示全 A 和同池对比；
4. 不允许只展示单日涨跌。

---

## V5.7：因子实验室

### 目标

把因子研究从 CLI 报告变成交互式页面。

### 页面

```text
因子排行榜
因子详情
因子对比
风险暴露
分层收益
失败归因
公式查看
```

### 因子表字段

```text
factor_name
family
universe
IC
RankIC
ICIR
TopBottom
excess_vs_semiconductor_ew
cost_adjusted_return
turnover
max_drawdown
risk_flags
status
```

### 验收标准

1. 跑输半导体同池等权醒目标红；
2. 高风险暴露醒目标红；
3. 交易成本后收益必须展示；
4. 失败因子必须显示失败原因；
5. 能触发 `factor:validate-v4`。

---

## V5.8：回测实验室

### 目标

可视化回测配置、运行和结果。

### 页面

```text
回测配置
回测运行状态
净值曲线
回撤曲线
交易明细
基准对比
风险归因
Artifacts
```

### 验收标准

1. 每次回测有 run_id；
2. 可查看交易明细；
3. 可查看交易成本；
4. 可查看半导体同池等权对比；
5. 支持回测结果导出。

---

## V5.9：组合推荐

### 目标

把因子和回测结果转成可解释组合建议。

### 页面

```text
今日组合建议
核心组合
卫星组合
ETF 替代
禁止买入
减仓观察
组合风险
审批记录
```

### 验收标准

1. 每只股票显示推荐原因；
2. 每只股票显示风控结果；
3. 不可交易股票不得进入买入清单；
4. ETF 替代可见；
5. 触发审批前必须显示 Gate 状态。

---

## V5.10：QMT 实盘中心

### 目标

接入大 QMT Bridge，只读展示真实账户和持仓。

### 页面

```text
QMT Health
账户资产
真实持仓
当日委托
当日成交
实时行情
计划组合 vs 真实持仓
QMT Bridge 日志
```

### 验收标准

1. QMT 离线醒目提示；
2. 账户信息脱敏；
3. 数据超过 60 秒未更新警告；
4. 持仓触发 -5% / -8% 自动标红；
5. 无自动下单按钮。

---

## V5.11：Paper / Shadow

### 目标

可视化模拟盘和影子交易。

### 页面

```text
Paper Dashboard
Shadow Dashboard
计划交易
模拟成交
真实可交易性
执行偏差
风控拦截
日度复盘
```

### 验收标准

1. 展示最近 20 个交易日；
2. 必须和半导体同池等权对比；
3. 风控拦截原因可见；
4. 跑输同池等权不得显示 READY。

---

## V5.12：Live Gate

### 目标

可视化小资金实盘前置门禁。

### 页面

```text
READY / NOT_READY 总状态
Gate Checklist
阻塞项
证据
修复建议
历史记录
审批记录
```

### Gate

```text
DataHealthGate
UniversePurityGate
BenchmarkGate
SemiconductorPeerGate
RiskExposureGate
CostAdjustedReturnGate
PaperTradingGate
ShadowTradingGate
QMTAccountGate
TradeConstraintGate
ManualApprovalGate
KillSwitchGate
AuditTrailGate
```

### 验收标准

1. 每个 Gate 有证据；
2. NOT_READY 有修复建议；
3. 自动交易默认不允许；
4. 人工审批必须留痕；
5. 不得隐藏失败 Gate。

---

## V5.13：报告审计中心

### 目标

整合原 Reports、审计日志、Manifest、Artifacts。

### 页面

```text
报告列表
报告查看
Artifacts
Manifest
Run ID
Gate 结果
审计日志
导出
```

### 验收标准

1. 任意报告可追溯到 run_id；
2. 任意报告可追溯到 manifest；
3. 报告能按类型筛选；
4. 报告能导出；
5. 失败报告不隐藏。

---

## V5.14：任务中心

### 目标

把所有后台任务和 CLI 封装任务可视化。

### 页面

```text
任务列表
任务详情
运行日志
输入参数
输出 Artifacts
错误详情
重跑按钮
SSE 实时日志
```

### 验收标准

1. 每个任务有 run_id；
2. 每个任务有状态；
3. 失败任务显示原因；
4. 支持安全重跑；
5. 重跑生成新 run_id。

---

## V5.15：事件研报与语义增强入口

### 目标

为后续公告 PDF、研报语义、政策事件因子提供前端入口。

### 页面

```text
公告事件流
事件详情
研报库
研报摘要
产业标签
LLM 假设
证据引用
```

### 验收标准

1. 所有事件有来源；
2. 所有公告有披露时间；
3. 研报只作为假设来源；
4. 不允许未来函数；
5. 事件因子必须进入同池等权验证。

---

## V5.16：设置、安全与体验完善

### 目标

收尾生产化体验。

### 页面

```text
数据源设置
QMT Bridge 设置
企业微信设置
风险阈值设置
账户权限设置
主题偏好设置
Token 安全
审计导出
```

### 验收标准

1. 不显示完整 token；
2. 所有设置变更写审计日志；
3. 风险阈值可配置；
4. 企业微信 webhook 不明文展示；
5. 有完整用户手册。

---

# 十一、V5 MVP 范围

不要一口气做完所有页面。MVP 先完成：

```text
V5.0 后端 API Contract 与安全加固
V5.1 前端 TypeScript 迁移与 Shell 重构
V5.2 API Client 与 TanStack Query
V5.3 首页投研驾驶舱
V5.4 数据中心
V5.5 股票池中心
V5.7 因子实验室
V5.10 QMT 实盘中心
V5.13 报告审计中心
V5.14 任务中心
```

MVP 不做：

```text
复杂 Alpha Family Tree
复杂事件研报语义
自动交易
Level-2
分钟高频
复杂审批工作流
```

MVP 目标：

用户能在前端清楚看到：

1. 数据是否健康；
2. Tushare 是否正常；
3. 股票池是否构建完成；
4. 半导体同池等权是否存在；
5. 因子是否跑赢同池等权；
6. QMT 是否在线；
7. 持仓是否安全；
8. 任务是否成功；
9. 系统是否 NOT_READY。

---

# 十二、测试要求

## 12.1 后端测试

新增：

```text
test_api_health.py
test_api_auth.py
test_api_jobs.py
test_api_data.py
test_api_universe.py
test_api_factor.py
test_api_qmt.py
test_api_live_readiness.py
```

## 12.2 前端测试

使用：

```text
Vitest
React Testing Library
```

新增 smoke tests：

```text
HomeDashboard renders
DataCenter renders
UniverseCenter renders
FactorLab renders
QmtLiveCenter renders
AgentOpsDrawer renders
```

## 12.3 E2E 测试

后续使用 Playwright。

最低流程：

```text
打开首页
查看数据状态
进入股票池
进入因子实验室
进入 QMT 页面
打开 AgentOps 抽屉
查看任务中心
```

---

# 十三、V5 开发顺序

严格按顺序执行：

```text
V5.0 API Contract + 安全
→ V5.1 TypeScript + Shell + AgentOps 收纳
→ V5.2 API Client + TanStack Query
→ V5.3 首页驾驶舱
→ V5.4 数据中心
→ V5.5 股票池中心
→ V5.6 半导体主题
→ V5.7 因子实验室
→ V5.8 回测实验室
→ V5.9 组合推荐
→ V5.10 QMT 实盘中心
→ V5.11 Paper / Shadow
→ V5.12 Live Gate
→ V5.13 报告审计
→ V5.14 任务中心
→ V5.15 事件研报
→ V5.16 设置安全体验
```

不要：

```text
先做漂亮图表
先做自动交易按钮
先把 Agent Console 放回主导航
先做复杂事件研报
用 mock 数据冒充真实状态
```

---

# 十四、禁止事项

V5 禁止：

1. 推倒重写成 Next.js；
2. 改用 Node 后端；
3. 保留 CORS 全开放；
4. 无认证暴露 API；
5. 明文显示 token；
6. 明文显示企业微信 webhook；
7. 明文显示 QMT 账户敏感信息；
8. 主导航继续展示 Roadmap / Agent Console / Ops / History；
9. 新页面裸 fetch；
10. API 失败白屏；
11. mock 数据冒充真实数据；
12. 页面显示成功但没有 run_id / manifest；
13. 跑输半导体同池等权仍显示有效；
14. 未通过 Gate 仍允许审批；
15. 第一阶段提供自动下单按钮。

---

# 十五、给 Hermes 的立即执行指令

请基于现有 React + Vite + Ant Design + FastAPI 架构进行 V5 重构，不要推倒重写。

第一阶段只做：

```text
V5.0 后端 API Contract 与安全加固
V5.1 前端 TypeScript 迁移与 Shell 重构
V5.2 API Client 与 TanStack Query
V5.3 首页投研驾驶舱
V5.4 数据中心
```

立即执行以下原则：

```text
1. Agent Console / Roadmap / Ops / History / Feedback 移出主导航；
2. 新增“系统与自动化”小入口；
3. 主导航只保留投研、数据、股票池、因子、组合、QMT、Paper/Shadow、Live Gate、报告审计；
4. 后端不要新增 routes_v4.py 巨型路由，而是按业务域新增 routes_factor/routes_universe/routes_qmt 等；
5. 所有新 API 统一响应格式；
6. 所有新任务必须有 run_id；
7. 所有页面必须支持 loading / empty / error / not_ready 状态；
8. 引入 TypeScript、TanStack Query、ECharts；
9. 不允许 mock 数据冒充真实数据；
10. 第一阶段不允许自动下单。
```

V5 的核心是：

```text
保留正确的框架
修正错误的信息架构
补齐 API 契约
补齐状态管理
补齐安全
补齐任务审计
把 V4 量化能力前端化
```

最终目标是让 Hermes 从命令行驱动的投研工具，升级为一个用户可以日常使用、能看懂、能审计、能风控、能接入真实 QMT 状态的现代化量化控制塔。
