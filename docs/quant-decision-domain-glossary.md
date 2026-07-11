# 量化决策闭环术语表

| 术语 | 定义 |
|---|---|
| `DecisionCandidate` | 通过消息、产业、基本面和技术证据形成的候选，不等于可交易订单。 |
| `TradingBook` | `catalyst`、`swing`、`core` 三种独立持有周期账簿。 |
| `ProfitHighWatermark` | 单标的或账户当日出现过的最高浮盈/权益。 |
| `GivebackPoints` | 最高浮盈收益率减当前浮盈收益率，单位为百分点。 |
| `ProfitProtectionTriggered` | 回撤达到 2/3 点或结构破位后产生的领域事件。 |
| `StructureBreak` | 跌破上午低点或 VWAP 并在确认窗口内未收回。 |
| `ReclaimConfirmed` | 放量站回 VWAP，解除 `wait_for_reclaim`，不代表自动买入。 |
| `PortfolioRiskMode` | `normal`、`no_new_positions`、`reduce_high_beta`、`reduce_only`。 |
| `DailyExecutionAuthorization` | 绑定交易日、计划哈希、预算和到期时间的一次性日级执行授权。 |
| `ProtectiveOrder` | 由已确认硬风险规则产生的减仓单，只允许 SELL。 |
| `PlanOrder` | 盘前向用户展示且包含在授权计划哈希中的订单。 |
| `DecisionEvent` | 带统一 `event_id` 的 L2/L3/L4 事件，是通知、确认和执行审计的共同主键。 |
| `DeliveryReceipt` | Telegram/企业微信各自的送达状态，不代表交易执行成功。 |
| `PositionImportPreview` | OCR/剪贴板/CSV 导入与当前组合的新增、删除、数量及成本差异。 |
| `DataDecisionGate` | 根据核心/辅助数据新鲜度决定 executable、watch-only 或 blocked。 |
| `PassList` | 0–3 个通过全部门禁的主推荐；空列表是有效结论。 |
| `MatchedBenchmark` | 根据标的类型和暴露动态选择的行业、同类 ETF、宽基或混合基准。 |
| `MFE/MAE` | 持有期最大有利/不利波动，用于分离选股、择时和退出质量。 |
| `CounterfactualReplay` | 比较实际交易与按系统建议执行的结果。 |
| `ParameterCandidate` | 复盘产生但尚未进入生产的阈值/权重候选。 |
| `WeeklyPromotion` | 样本外验证通过且人工确认后，将候选参数晋级生产。 |
