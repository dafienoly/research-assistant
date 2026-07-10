# Paper / Shadow 输入契约

`trading:paper-run` 与 `trading:shadow-run` 接收同一 JSON。每条记录必须同时包含订单草案和完整安全上下文：

```json
{
  "orders": [
    {
      "order": {
        "approval_id": "appr_xxx",
        "symbol": "600183.SH",
        "side": "BUY",
        "quantity": 100,
        "limit_price": 10.5,
        "strategy_source": "vnext-regime",
        "rationale": "证据链摘要",
        "regime": "TECH_ATTACK",
        "semiconductor_state": "SEMI_MAINLINE_CONFIRM",
        "model_score": 0.12,
        "portfolio_impact": {},
        "risk_summary": [],
        "data_freshness": "OK",
        "account_permission": "OK",
        "alternative_etf": null,
        "watch_only": false,
        "created_at": "2026-07-10T09:00:00+08:00"
      },
      "safety": {
        "data_status": "OK",
        "data_fresh": true,
        "account_permission": true,
        "funds_available": true,
        "positions_synced": true,
        "within_trading_session": true,
        "price_limit_clear": true,
        "suspension_clear": true,
        "st_clear": true,
        "liquidity_clear": true,
        "stock_weight_clear": true,
        "theme_exposure_clear": true,
        "portfolio_drawdown_clear": true,
        "daily_loss_clear": true,
        "kill_switch_triggered": false,
        "telegram_approved": false,
        "approval_id": "appr_xxx"
      }
    }
  ]
}
```

Paper/Shadow 不要求 Telegram 已批准才能进行研究模拟，但安全字段必须真实提供并写入审计日志。任何 watch-only 标的被 broker 阻断。Live 路径在本版本不可用。
