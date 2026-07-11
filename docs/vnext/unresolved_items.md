# Hermes VNext 未解决项

更新时间：2026-07-12。以下项目不会被示例、mock、静默 fallback 或“已开发”措辞掩盖。

## 阻止模型/策略晋级的真实缺口

- 数据审计仍为 `PARTIAL`：按 U0 代码集合核对，资金流匹配 5,401/5,530、缺 129，财务匹配 5,528/5,530、缺 2；精确补拉对这些代码得到上游空结果。概念 409/380、行业 511/80 已转为 OK；另有 3 个标签文件缺失。
- Canonical DataHub 核心新鲜度已为 OK：活跃股票 5,530/5,530，5,526 只最新至 2026-07-10，另 4 只由官方 `suspend_d` 解释；正式 ML 和 Shadow 数据门禁为 OK。生产 BUY OrderDraft 仍因资金流/财务/标签辅助缺口保持 BLOCKED，保护性 SELL 数据门禁为 OK。
- 市场 Event Truth 已真实拉取 13 个指数/ETF 代理，覆盖 `stk_limit`、`suspend_d`、现金分红和复权因子；公司事件已完成 166 个有效 U3 A 股标的，holdertrade 892、repurchase 493、share_float 1,412、dividend 5,363。forecast 网关持续返回非 JSON，累计三次后熔断，因此公司事件保持 `PARTIAL`，不得宣称完整。
- 行级完整性审计当前为 OK（活跃 5,530 文件、0 问题行）；曾污染的 3 个文件已从最早干净 D 盘快照恢复，污染原件保留在 `quarantine_polluted_market_20260712_0134`。该事件说明备份恢复已生效，但恢复后的连续每日门禁仍需观察。
- 监管公告 ingestion 与覆盖感知门禁已实现并安装 08:57 cron。真实 smoke 曾发现 CNINFO 缺 orgId 时返回全市场公告，原“30 条”证据已撤销；现按上游 `secCode` 验证并二阶段使用 `688012,orgId` 拉取，得到 1 条证券专属公告、覆盖 `OK`。该证据仅证明 688012，不代表全市场覆盖。
- Antifragile Review 缺 realized Regime/Semi/Style 标签、滚动模型衰减历史及连续 Paper/Shadow 权益曲线，因此相关六项指标为 null。
- vectorbt 第二个 OOS fold 收益为 -6.03%，不得用第一段或样本内结果替代。

## 外部运行条件

- Telegram 与企业微信已完成一次真实双通道 HTTP 200 发送；共享确认和单通道失败隔离已通过测试。后续仍需持续运行回执监控，实盘执行不由通知成功自动解锁。
- QMT Bridge 已配置且行情侧可用，但 `XtQuantTrader connect failed: -1`，账户/持仓不能连续读取；订单通道继续 DISABLED。
- 应用内浏览器运行时可加载，但本轮 `agent.browsers.list()` 返回空列表；HTTP、DOM、lint、Vitest 和生产构建已通过，真实浏览器 console/点击证据仍 BLOCKED。
- `scripts/mx_fetch_step.py` 曾包含硬编码高熵凭据，现已改为 `MX_APIKEY` 环境变量；旧凭据必须在提供方撤销/轮换，代码删除不能清除 Git 历史。

## 供应链与产品化剩余风险

- Core Python 使用 `requirements/core.hashed.lock` 和 `--require-hashes`；隔离研究/sidecar 锁仍需逐步补齐制品哈希，SBOM/许可证报告不能替代来源完整性证明。
- 前端已完成路由懒加载和 Rolldown vendor 分组，最大生产块约 175 KB且无 chunk-size warning；应用内浏览器不可用导致真实 console/点击/截图仍待验收。
- vectorbt 受 Apache-2.0 + Commons Clause 约束，仅批准隔离内部研究；商业托管或分发前需重新审查。
- vn.py、OpenBB、FinRL/FinRL-X、Qbot 均未装入 Core；comment-only lock 表示“未安装”，不能宣称对应运行时已适配完成。
- 无真实订单发送实现；任何未来 Live 通道必须另行授权、安全评审、Paper/Shadow 稳定性证明和小额白名单验收。
- `intraday_monitor.py`、`etf_dive_warning.py`、`monitor_588710.py`、dive live predictor、dive 历史训练 collector 和 semiconductor event 生产加载路径均已收敛为 DataHub 只读消费者；旧 provider 方法已物理删除。159516 ETF canonical 日线已通过统一 fund_daily ingestion 接入 715 行，训练 smoke 使用最近 250 行且日期正确。KOSPI canonical 数据尚未接入，588710 看板会明确显示缺失。
