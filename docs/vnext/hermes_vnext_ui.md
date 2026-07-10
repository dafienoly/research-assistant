# Hermes VNext UI 使用与 API 文档

## 启动

后端：

```bash
cd /home/ly/.hermes/research-assistant
.venv_quant/bin/python commands/hermes_cli.py leader:dashboard --host 0.0.0.0 --port 8766
```

前端开发模式：

```bash
cd /home/ly/.hermes/research-assistant/commands/frontend
npm run dev -- --host 0.0.0.0
```

访问 `http://localhost:5173/`。Vite 将 `/api` 代理到 `127.0.0.1:8766`。生产构建运行 `npm run build`，FastAPI 会服务 `commands/frontend/dist` 并提供 SPA fallback。

如需整体关闭 VNext，设置 `HERMES_VNEXT_ENABLED=false`。VNext API 将返回 503，CLI 返回 BLOCKED，旧 Hermes API/页面不受影响。

## 页面与数据源

| 页面 | 路由 | API |
|---|---|---|
| Control Tower | `/` | status、data-health、regime、policy-put、semi-mainline、portfolio-risk、execution-status、paper、shadow、approvals |
| Regime & Policy Put | `/vnext/regime` | regime、policy-put |
| Semiconductor Mainline | `/vnext/semi` | semi-mainline、candidates |
| Signal / Candidates | `/vnext/candidates` | candidates、regime、semi-mainline |
| Portfolio & Risk | `/vnext/portfolio` | portfolio-risk、regime |
| ML Factor / Ranker | `/vnext/ml` | ml-ranker |
| Backtest / Validation | `/vnext/backtests` | backtests、backtests/{run_id} |
| Paper / Shadow | `/vnext/trading` | paper、shadow、execution-status |
| Telegram Approval | `/vnext/approvals` | approvals、approval detail/actions |
| Execution / miniQMT | `/vnext/execution` | execution-status |
| Antifragile Review | `/vnext/review` | antifragile-review |
| Data Health | `/vnext/data-health` | data-health |

## 稳定 API

```text
GET /api/vnext/status?date=YYYY-MM-DD
GET /api/vnext/data-health?date=YYYY-MM-DD
GET /api/vnext/regime?date=YYYY-MM-DD
GET /api/vnext/policy-put?date=YYYY-MM-DD
GET /api/vnext/semi-mainline?date=YYYY-MM-DD
GET /api/vnext/candidates?date=YYYY-MM-DD
GET /api/vnext/portfolio-risk?date=YYYY-MM-DD
GET /api/vnext/ml-ranker?date=YYYY-MM-DD
GET /api/vnext/backtests
GET /api/vnext/backtests/{run_id}
GET /api/vnext/paper?date=YYYY-MM-DD
GET /api/vnext/shadow?date=YYYY-MM-DD
GET /api/vnext/approvals
GET /api/vnext/approvals/{approval_id}
GET /api/vnext/execution-status?date=YYYY-MM-DD
GET /api/vnext/antifragile-review?date=YYYY-MM-DD
GET /api/vnext/reports?date=YYYY-MM-DD
GET /api/vnext/reports/download?date=YYYY-MM-DD&format=md|json|csv
POST /api/vnext/approvals/{approval_id}/approve
POST /api/vnext/approvals/{approval_id}/reject
POST /api/vnext/approvals/{approval_id}/delay
POST /api/vnext/approvals/{approval_id}/modify
```

所有 GET 使用既有统一响应：

```json
{
  "ok": true,
  "data": {
    "status": "OK|MISSING|STALE|PARTIAL|WATCH_ONLY|BACKTEST_ONLY|BLOCKED",
    "as_of": "2026-07-10",
    "confidence": 0.73,
    "evidence": [],
    "missing_evidence": [],
    "data_sources": [],
    "payload": {}
  },
  "error": null,
  "meta": {}
}
```

审批动作 body：

```json
{
  "approver": "user-id",
  "reason": "审批原因",
  "modifications": {"quantity": 100}
}
```

响应固定包含 `execution_triggered: false`。Modify 会设置 `requires_reapproval: true`。

## 历史与下载

页面顶部日期选择器向各 API 传 `date`；没有对应产物时显示 MISSING。Markdown/JSON 按钮调用安全下载端点。最近报告由 `data/vnext/reports/latest.json` 定位，历史文件按日期保存。

## 状态识别

- `OK`：指定真实来源、必要字段和新鲜度均满足。
- `MISSING`：文件/字段/运行产物不存在；不会显示成功态。
- `STALE`：更新时间超过数据源阈值。
- `PARTIAL`：仅部分来源或字段可用，置信度自动降低。
- `WATCH_ONLY`：仅观察，不能进入可执行组合。
- `BACKTEST_ONLY`：仅历史研究，不能当成实时信号。
- `BLOCKED`：交易安全门禁未通过。

任何卡片都可展开“证据下钻”，查看 evidence、missing_evidence、data source 和 updated_at。

## 如何确认不会真实下单

1. 首页必须显示 `READ_ONLY` 或 PAPER/SHADOW/LIVE_DRY_RUN，不能显示 LIVE_ENABLED。
2. Execution 页必须显示 `no_live_trade=true`、`live_enabled=false`、订单通道 DISABLED。
3. UI 没有“直接下单”按钮；审批页按钮旁明确注明“不下单”。
4. 审批 API 只改变审批状态，返回 `execution_triggered=false`。
5. 后端 `MiniQMTLiveBroker.submit()` 永久返回 BLOCKED。

## Telegram 与 miniQMT

- Telegram 页展示待审批、通过、拒绝、延迟、修改及审批人/时间/理由。
- `approval:telegram-test` 默认 dry-run；没有 token/chat id 会显式 MISSING。
- miniQMT 页展示连接、账户权限、资金、持仓同步、订单/撤单/回报通道和最近 probe。
- 当前 QMT 只读/探测；所有发送通道关闭。

## 前端质量门禁

每次修改后必须：生产构建、lint、Vitest、启动后端与 Vite、逐页验证 `#root.children > 0`、无致命 console error、数据状态可见、日期/审批等交互无新错误，并把每页截图保存到 `agent_tasks/self-verify/`。

本轮自动测试另外提供 `VNextPage.test.tsx`：向 12 页注入统一 MISSING 响应，逐页验证真实 DOM 标题、非空根节点和降级状态；它用于防止“只可 import、实际渲染白屏”，但不替代内置浏览器验收。

## 后续 UI 运营项

在真实历史累积后可增加长周期可视化、回测曲线和更细的订单回放；在此之前 UI 不用假曲线占位。移动端、复杂 RBAC 和真实下单按钮不是本轮目标。
