# Big QMT 内部 HTTP 执行器

本文件夹包含 Hermes 在 `QMT_BRIDGE_MODE=internal_http` 模式下使用的
Big QMT 内置 Python 策略执行器。

## 文件

- `qmt_http_executor_strategy.py`: 粘贴到 Big QMT Python 策略编辑器中。
- `qmt_http_executor_config.example.json`: 复制到
  `D:\HermesQMTBridge\qmt_http_executor_config.json` 并在本地编辑。

## Big QMT 设置

1. 创建 `D:\HermesQMTBridge\qmt_http_executor_config.json`。
2. 设置一个长随机字符串作为 `TOKEN`，填写你的 QMT `ACCOUNT_ID`，
   首次干跑保持 `LIVE_TRADING_ENABLED=false` 和
   `FUNCTION_TRADING_ENABLED=false`。
3. Big QMT → 新建 Python 策略 → 粘贴 `qmt_http_executor_strategy.py`。
4. 绑定股票账户，挂载到 1 分钟或 Tick 图表上，启动策略。
5. 在 Hermes 中设置：

```bash
export QMT_BRIDGE_MODE=internal_http
export QMT_INTERNAL_HTTP_BASE_URL=http://127.0.0.1:18765
export QMT_INTERNAL_HTTP_TOKEN=<相同-token>
```

6. 验证：

```bash
python3 hermes_cli.py broker:qmt-internal-health
```

## 安全说明

- 策略只绑定到 `127.0.0.1`。
- 每个 HTTP 请求必须携带 `X-Hermes-Token`。
- HTTP 永不直接调用 `passorder(...)`。订单先排队，在
  `handlebar(ContextInfo)` 中统一发送。
- Hermes 仍然需要 `QMT_LIVE_TRADING_ENABLED=1`、人工审批、Kill Switch
  武装就绪和本地风控检查，才能发送订单。
- QMT 策略本身也需要在配置中设置 `LIVE_TRADING_ENABLED=true`
  或通过 `/control/enable-live` 启用。
- 真实 `passorder(...)` 还需要 QMT 函数交易权限，并且配置中必须显式设置
  `FUNCTION_TRADING_ENABLED=true`。如果没有函数交易下单权限，保持 false，
  执行器只做 HTTP 健康检查、审计和拒单保护，不会尝试自动下单。
- 第一版禁用真实撤单，保持 `ALLOW_CANCEL=false`。

## 审计文件

执行器会写入：

- `D:\HermesQMTBridge\state\executed_ids.json`
- `D:\HermesQMTBridge\state\queued_orders.json`
- `D:\HermesQMTBridge\audit\http_requests.jsonl`
- `D:\HermesQMTBridge\audit\order_events.jsonl`
- `D:\HermesQMTBridge\audit\deal_events.jsonl`
- `D:\HermesQMTBridge\audit\error_events.jsonl`
