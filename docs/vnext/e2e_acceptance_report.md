# Hermes VNext 端到端验收报告

日期：2026-07-10

## 结论

VNext 的真实数据读取、分析编排、报告、API、CLI、Paper/Shadow、审批、QMT 安全边界和前端构建/DOM 测试已形成闭环。系统保持 `READ_ONLY`、`no_live_trade=true`、`live_enabled=false`；缺失或陈旧数据均为 fail-visible。

## 数据恢复

- U0：5,530 只，来源为已接入 Tushare `stock_basic`。
- 日线：5,738 个文件；估值：5,816；资金流：5,383。
- 财务：5,473 个文件。补齐任务逐股查询 5,402 个缺失代码，新增成功 5,345，57 只接口真实空结果，0 次失败。
- legacy 日线兼容层：5,738 个文件，schema/freshness 测试 7/7 通过。
- 概念/行业：`MX_APIKEY` 已配置且真实调用成功，但仅返回概念 16/目标 380、行业 1/目标 80，状态为 PARTIAL，不按“非空即完成”处理。
- 最新 VNext 数据健康：日线/估值/财务 OK，资金流 PARTIAL，盘中/事件 STALE，港股/海外代理 MISSING。

## 功能闭环

| 环节 | 证据 | 结果 |
|---|---|---|
| Policy Put / 箱体 / 广度 | CLI 真实快照运行 | `policy_support_proxy_score=0.4887`、`breadth_divergence_score=0.3256` |
| 半导体状态机 | CLI 真实快照运行 | `SEMI_FAILURE`、`exit_or_avoid`，无缺失证据 |
| 组合风险 | CLI 真实快照运行 | 输出 marginal Sharpe、科技 beta、假分散判断 |
| ML Ranker | 模型注册表 + score CLI | OOS RankIC 0.00114，`PARTIAL/WATCH`，不晋级，不输出 buy/sell |
| Paper | 文档订单契约 | kill switch 阻断，`real_broker_called=false` |
| Shadow | 文档订单契约 | kill switch 阻断，`real_broker_called=false` |
| Telegram 审批 | 凭据只读校验 + dry-run 审批测试 | Bot token 有效、私聊 chat 可读；`credentials_configured=true`、`execution_triggered=false`，未发送测试消息 |
| miniQMT | `broker:qmt-probe` | Bridge 已连接，账户/持仓可读；订单通道禁用，`no_live_trade=true`、`real_broker_called=false` |
| VNext 禁用 | CLI/API 环境开关 | CLI BLOCKED；API 503；旧系统不受影响 |
| 报告下载 | API TestClient | JSON 下载 HTTP 200 |

端到端测试发现并修复了 `hermes_cli.py` 切换到 `commands/` 后相对 `--input` 路径失效的问题，以及项目根 `.env` 只被 API 加载、CLI 无法读取凭据的问题。VNext CLI 现在从项目根解析相对输入路径，并在命令分派前以 `override=false` 加载 `.env`；显式 shell 环境变量仍具有更高优先级。

## 自动测试

- VNext 后端：55/55 通过。
- legacy K 线 schema/freshness：7/7 通过。
- VNext API/报告下载：16/16 HTTP 200；禁用态 503。
- 数据管道与缺口判定：22/22 通过；测试目录已与真实 `data/normalized` 隔离。
- CLI `.env` 自动加载与优先级：3/3 通过。
- 前端：生产构建通过；16 个测试文件、27 个测试通过，其中 VNext 12 页 DOM 验收 12/12。
- `git diff --check`：通过。

## 浏览器验收状态

在用户重装 Chrome Codex 插件并重启 Codex/Chrome 后已重试。宿主 Chrome 与扩展已启用，但 Native Messaging Host 的注册项/manifest 仍不可用，浏览器客户端继续返回 `Browser is not available: extension`。因此浏览器 console、真实点击和截图证据仍为 BLOCKED；未使用独立 Playwright 冒充内置浏览器验收。详见 `docs/vnext/frontend_self_verify_report.md`。

## 已知降级项

- 57 只股票财务接口真实空结果。
- 资金流覆盖 93.81%，状态 PARTIAL。
- 概念/行业覆盖不足（16/380、1/80）；港股和海外代理数据缺失。
- 盘中与事件快照陈旧。
- 旧版 TopN 历史收益已删除，回测对照保持 PARTIAL。
- Telegram 凭据、QMT Bridge 与 MX_APIKEY 均已配置并通过只读验证；QMT 订单通道仍按设计禁用。

以上降级项不会被填入 mock/fallback 值，也不会被解释为可交易证据。
