# Hermes VNext 安全模型

更新时间：2026-07-11
适用状态：`no_live_trade=true`，真实委托不可达
## 单一执行入口

Execution Service 只接受 Hermes 自有 `ApprovedOrderEnvelope`：

```text
ResearchSignal
  → TargetPortfolioWeights
  → OrderDraft + draft_hash
  → Telegram/Approval Service
  → ApprovedOrderEnvelope(HMAC, TTL, nonce, allowed_mode)
  → ExecutionGuard
  → PaperBroker | ShadowBroker | LiveDryRun
```

裸 `OrderDraft`、候选、ML 分数、UI 参数或 `telegram_approved=true` 布尔值均不能进入 broker routing。

## Approval 完整性

- `OrderDraft` 使用规范化 JSON 的 SHA-256；
- `ApprovedOrderEnvelope` 绑定 approval ID、draft ID/hash、审批人、TTL、一次性 nonce、allowed mode、risk snapshot 和 Kill Switch snapshot；
- 签名算法为 HMAC-SHA256，密钥仅从 `HERMES_APPROVAL_SIGNING_KEY` 获取；
- 缺密钥时审批状态为 `APPROVED_UNSIGNABLE`，`execution_eligible=false`；
- Modify 将状态改为 `INVALIDATED_BY_MODIFICATION`，旧 hash 和签名不可复用；
- Delay 不执行，并标记 `requires_revalidation=true`；
- nonce 通过原子文件创建持久消费，重复执行被阻断。

## ExecutionGuard 顺序

1. 输入必须是 `ApprovedOrderEnvelope`；
2. `LIVE_ENABLED`/`LIVE_APPROVAL_REQUIRED` 发送路径硬阻断；
3. 验证 HMAC、draft hash、TTL 和 Kill Switch snapshot；
4. 验证 allowed mode 和 approval ID；
5. 当前 Kill Switch 优先阻断；
6. 拒绝 watch-only、非 OK quality、缺少 lineage 和账户权限不足；
7. 执行完整 data/funds/position/time/limit/ST/liquidity/portfolio safety gate；
8. 原子消费一次性 nonce；
9. 仅 PAPER/SHADOW/LIVE_DRY_RUN 可继续；LIVE_DRY_RUN 最终仍不调用 broker。

## 审计账本

`AuditJournal` 是 append-only JSONL：每条记录包含 payload hash、previous event hash 和 event hash；写入后 `fsync`。`verify_chain()` 可识别 JSON 损坏、前序 hash 断裂、event hash 或 payload hash 篡改。旧版无 hash 的记录会被标记为 legacy，整体验证状态为 PARTIAL，而不是伪装成完整链。

## 不可变安全配置

```yaml
trading:
  mode: PAPER
  no_live_trade: true
  live_broker_enabled: false
  live_send_compiled: false
  approval_required: true
  kill_switch_required: true
execution:
  accepted_input_contract: ApprovedOrderEnvelope
```

`MiniQMTLiveBroker` 即使运行时属性被篡改，仍只返回 `BLOCKED/no_live_trade_safety_invariant`。QMT Probe 只读；连接成功不等于允许下单。

## 已验证证据

- `artifacts/vnext/test_runs/pr01_contracts_security.xml`：70/70 VNext tests passed；
- `artifacts/vnext/execution_guard_report.json`：raw draft、replay、Kill Switch、错误签名、live mode 均阻断；
- `artifacts/vnext/approval_audit.jsonl`：真实代码生成的签名审批审计，hash chain 有效；
- `artifacts/vnext/schemas/`：七个核心 JSON Schema。

## 仍需加固

- 跨进程并发下的 ledger 文件锁/数据库事务；
- Telegram webhook 身份验证、callback 去重和 Delay 后行情/风险重检；
- Event Truth Lane 的订单/成交/持仓/账户事件统一使用 `ExecutionEvent`；
- CI 静态阻断 API/UI 导入 broker SDK；
- secrets、依赖漏洞、SBOM 和许可证 Gate。
