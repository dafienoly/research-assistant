# Hermes 当前能力与阻断项（自动生成）

> 生成时间：2026-07-11T21:39:35.076638+08:00。请勿手工编辑。

| 能力 | 当前状态 | 证据 / 阻断 |
|---|---|---|
| VNext 数据健康 | PARTIAL | data_gaps_remain；critical_freshness_check_failed |
| 真实确认持仓 | BLOCKED | confirmed snapshot missing |
| 日级授权 | inactive | 收盘自动失效，参数/数据/审计/风险变化自动撤销 |
| 分钟决策周期 | blocked | 统一 DecisionCycleResult + 周期锁 |
| QMT 只读账户/持仓 | BLOCKED | XtQuantTrader connect failed: -1 |
| Paper/Shadow/Live 认证 | BLOCKED | live_activation_allowed=False |
| 实盘开关 | OFF | P0/Paper/Shadow/小额白名单完成前必须 OFF |

## 当前阻断项

- data_gaps_remain
- critical_freshness_check_failed
- confirmed_positions_missing
- daily_authorization_inactive
- live_trading_disabled
