# Hermes 当前能力与阻断项（自动生成）

> 生成时间：2026-07-12T03:20:03.921582+08:00。请勿手工编辑。

| 能力 | 当前状态 | 证据 / 阻断 |
|---|---|---|
| VNext 数据健康 | PARTIAL | 无 |
| 行情行级完整性 | OK | 问题文件=0，缺失活跃文件=0 |
| 动态基准投影 | OK | canonical DataHub derived/benchmarks |
| 盘中 canonical 快照 | OK | rows=5529，observed_at=2026-07-12T02:52:06.889268+08:00 |
| ETF 权重真值 | OK | rows=379，etf_count=4 |
| 监管公告真值 | MISSING | 缺失时 PreTrade BUY fail-closed |
| 公司事件真值 | MISSING | forecast/holdertrade/repurchase/share_float/dividend |
| 真实确认持仓 | BLOCKED | confirmed snapshot missing |
| 日级授权 | inactive | 收盘自动失效，参数/数据/审计/风险变化自动撤销 |
| 分钟决策周期 | blocked | 统一 DecisionCycleResult + 周期锁 |
| QMT 只读账户/持仓 | BLOCKED | XtQuantTrader connect failed: -1 |
| Paper/Shadow/Live 认证 | BLOCKED | live_activation_allowed=False |
| 实盘开关 | OFF | P0/Paper/Shadow/小额白名单完成前必须 OFF |

## 当前阻断项

- confirmed_positions_missing
- daily_authorization_inactive
- live_trading_disabled
- regulatory_truth_unavailable
