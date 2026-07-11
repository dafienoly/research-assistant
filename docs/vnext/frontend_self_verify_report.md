# Frontend Self-Verify 报告

日期：2026-07-11
前端：`http://127.0.0.1:5173`
后端：`http://127.0.0.1:8766`

生产构建通过；VNext DOM 集成测试 12/12；12 个 Vite 路由、status API 和正式 run API 均为 HTTP 200。应用内 Browser runtime 已按技能加载，但 `agent.browsers.list()` 返回 `[]`，因此 JS console、真实点击和截图仍为 BLOCKED；未用独立 Playwright 冒充证据。

| 路由 | HTTP | DOM 非白屏 | 降级态 | JS console | 真实交互 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| `/` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/regime` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/semi` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/candidates` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/portfolio` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/ml` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/backtests` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/trading` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/approvals` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/execution` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/review` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |
| `/vnext/data-health` | ✅ | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ | BLOCKED |

## 已完成证据

- `npm run lint` exit 0（遗留页面 warning，无 error）。
- `VNextPage.test.tsx` 12/12，逐页确认标题、`.vnext-page` 非白屏和 MISSING 降级态。
- `npm run build` 成功，4,031 modules transformed；主 JS 约 2.99 MB，有 chunk-size warning。
- VNext API/UI 静态边界无 vn.py、xtquant、MiniQMTLiveBroker 或 `send_order()`。
- 审批按钮只调用审批状态 API；后端固定返回 `execution_triggered=false`。

浏览器实例出现后应主动补跑 console、DatePicker/刷新/Collapse/审批状态交互和截图；在此之前不得将本报告改为 PASS。
