# Hermes VNext 一次性升级实施计划

来源：用户附件 `pasted-text-1.txt`。本计划用于 anti-cheat Gate 1/5 追踪，不改变原始需求范围。

### Task 1 — 真实数据恢复与健康门禁

- 使用已接入 Tushare 完成按交易日全量初始化、资金流/财务/剩余专项回填。
- 执行 gap-plan 与 freshness-check。
- 新增真实来源、缺失字段、新鲜度和 fail-visible 状态。

### Task 2 — Regime / Policy Put / 半导体主线

- 固定/动态箱体、政策托底代理、广度背离、风格轮动矩阵。
- 12 状态半导体主线状态机。
- 8 状态 Regime Router 与风险预算。

### Task 3 — 多资产组合与 ML 增强

- 多资产注册表、账户权限与 ETF substitution。
- 相关性、下行相关、回撤重叠、假分散、边际 Sharpe/回撤。
- ML 因子筛选、横截面 score/rank、模型卡/OOS/解释/生命周期。

### Task 4 — Paper / Shadow / Telegram / miniQMT 安全闭环

- 交易模式状态机与连续 Paper/Shadow。
- Telegram 审批全信息和四动作。
- miniQMT 只读/探测/live-ready 但 no-live-trade 硬阻断。
- Kill Switch、持仓、权限、流动性等全安全门禁和审计日志。

### Task 5 — 回测与反脆弱复盘

- 1/3/5 日四假设、多基准、固定/动态阈值比较。
- 成本、滑点、冲击、调仓频率和多 Regime 稳健性。
- KEEP/TUNE/DOWNGRADE/RETIRE/ESCALATE/WATCH 复盘与训练样本。

### Task 6 — API / 12 页 UI / 报告

- 稳定 VNext API、历史日期和 Markdown/JSON/CSV 下载。
- 12 页控制台、状态降级、证据下钻、无直下单按钮。
- 总文档、UI 文档、示例产物。

### Task 7 — 验证与验收

- GitNexus impact/detect_changes。
- Python/前端测试、生产构建、lint。
- Frontend Self-Verify 逐路由浏览器证据与截图。
- traceability mapping、anti-cheat Gate 1–3/5 和最终逐项审计。
