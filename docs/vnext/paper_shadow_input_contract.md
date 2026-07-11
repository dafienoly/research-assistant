# Paper / Shadow 输入契约

`trading:paper-run` 与 `trading:shadow-run` 接收同一 JSON。自 VNext contract schema v1 起，Execution Service **只接受经过 HMAC-SHA256 签名的 `ApprovedOrderEnvelope`**，不再接受裸 `OrderDraft` 或 `telegram_approved=true` 这类可伪造布尔值。

运行前必须显式配置 `HERMES_APPROVAL_SIGNING_KEY`。缺失时命令返回 `BLOCKED/approval_signing_key_missing`，不会自动生成或降级为无签名审批。

```json
{
  "orders": [
    {
      "approved_envelope": {
        "approval_id": "appr_xxx",
        "order_draft_id": "draft_xxx",
        "order_draft_hash": "64位sha256",
        "order_draft": {
          "order_draft_id": "draft_xxx",
          "approval_id": "appr_xxx",
          "portfolio_run_id": "portfolio_run_xxx",
          "account_snapshot_id": "account_snapshot_xxx",
          "position_snapshot_id": "position_snapshot_xxx",
          "symbol": "600183.SH",
          "side": "BUY",
          "quantity": 100,
          "order_type": "LIMIT",
          "limit_price": 10.5,
          "rationale": "证据链摘要",
          "risk_summary": [],
          "data_snapshot_id": "data_snapshot_xxx",
          "strategy_source": "vnext-regime",
          "regime": "TECH_ATTACK",
          "semiconductor_state": "SEMI_MAINLINE_CONFIRM",
          "model_score": 0.12,
          "portfolio_impact": {},
          "data_freshness": "OK",
          "account_permission": "OK",
          "alternative_etf": null,
          "watch_only": false,
          "quality_status": "OK",
          "created_at": "2026-07-11T09:00:00+08:00",
          "expires_at": "2026-07-11T09:05:00+08:00",
          "draft_hash": "64位sha256"
        },
        "approved_by": "telegram-user-id",
        "approved_at": "2026-07-11T09:00:30+08:00",
        "expires_at": "2026-07-11T09:05:00+08:00",
        "one_time_nonce": "一次性随机值",
        "allowed_mode": "PAPER",
        "risk_snapshot_id": "risk_snapshot_xxx",
        "kill_switch_snapshot": false,
        "signature": "64位HMAC-SHA256"
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

签名必须通过 `TelegramApprovalGate`/Approval Service 生成，不能手工填写示例值。ExecutionGuard 会验证 draft hash、TTL、mode、Kill Switch、安全上下文和一次性 nonce；重复 envelope 会被 `approval_nonce_reused` 阻断。任何 watch-only/restricted 标的仍被阻断。Live 路径在本版本不可用。
