# Frontend Self-Verify 报告

日期：2026-07-10
前端：`http://127.0.0.1:5173`
后端：`http://127.0.0.1:8766`

生产构建通过；VNext 12 页 DOM 集成测试 12/12 通过；Vite 12 路由与相邻旧首页路由 HTTP 均为 200；16 个 VNext API/下载请求均为 200。2026-07-10 在用户安装 Chrome Codex 插件后再次按 Browser skill 重试，浏览器客户端仍返回 `Browser is not available: extension`；诊断显示当前 Codex/WSL 执行环境 `Chrome running=false`、`installed_browsers=[]`，因此 console、真实点击和截图列暂时不能给出浏览器证据，也不会用独立 Playwright 冒充。

| 路由 | HTTP | DOM 非白屏测试 | 降级态 | 浏览器 JS console | 真实交互 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| `/` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/regime` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/semi` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/candidates` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/portfolio` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/ml` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/backtests` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/trading` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/approvals` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/execution` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/review` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/vnext/data-health` | ✅ 200 | ✅ | ✅ | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |
| `/legacy-dashboard` | ✅ 200 | N/A | N/A | ⚠️ 无浏览器实例 | ⚠️ 无浏览器实例 | BLOCKED |

## 已验证交互边界

- DOM 集成测试逐页等待主标题出现并确认 `.vnext-page` 有子节点。
- MISSING 响应逐页显示降级状态，不会渲染伪成功数据。
- 审批 API 集成测试确认 `execution_triggered=false`。
- `HERMES_VNEXT_ENABLED=false` 时 VNext API 503，而旧 `/api/health` 200。
- 完整浏览器验收需要 Codex 应用提供一个可用的内置浏览器实例后补跑。
