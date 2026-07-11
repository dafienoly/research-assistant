# VNext 基础设施系统审计（进行中）

生成日期：2026-07-11

## 结论

VNext 的安全门禁和决策闭环已经成形，但基础设施尚未完全实现“DataHub 是唯一数据入口”。历史演进留下多套拉取器、硬编码目录、业务模块内 provider fallback 和重复调度入口。当前最高风险不是策略逻辑，而是数据所有权、运行态口径和任务编排不统一。

## P0 发现与整改

| 问题 | 证据 | 风险 | 状态 |
|---|---|---|---|
| 全量 CSV 每批重复全量覆盖 | `commands/data_pipeline.py` 原 `_append_to_csv`/`full_init_by_trade_date` | I/O 放大、异常截断 | 已改为原子替换、staging、checkpoint、单次正式归并 |
| 测试可删除生产数据 | 多个 pytest fixture 曾直接使用生产常量 | 数据误删 | 已增加全局删除保护和 CI 门禁 |
| Decision Loop 交易日历直接访问 Tushare | `decision_loop/calendar.py` | 绕过 DataHub、运行口径分叉 | 已改为只读 canonical DataHub calendar，缺失 fail-closed |
| Shadow API 自行查询交易日历 | `api_server/routes_paper.py` | API 层承担数据拉取 | 已改为 DataHub 只读访问 |
| 日期审计把 YYYYMMDD 整数解析为 1970 | `data_audit._normalize_trade_date` | freshness 误阻断 | 已修复并增加未来日期异常报告 |
| U0 空响应被解释为总需 0 | `data_audit.missing` | 虚假完整性 | 已改为 UNKNOWN |

## 尚存的 DataHub 绕过

以下模块仍直接创建或调用外部 provider，后续必须迁移到 DataHub ingestion 层：

- `factor_lab/vnext/snapshot.py`：`HubSnapshotBuilder` 名称表示 Hub，但默认注册 `TushareFetcher`。
- `factor_lab/vnext/datasets.py`：指数和基金历史数据直接 `_query` Tushare。
- `factor_lab/vnext/event_truth_sources.py`：Event Truth 直接调用 Tushare。
- `factor_lab/vnext/providers.py`：VNext 内部维护独立 provider/router/snapshot 体系，与 DataHub manifest 重叠。
- `universes.py`：股票池构建直接查询 stock_basic、daily_basic、suspend_d、namechange 和 daily。
- `etf_dive_warning.py`、`intraday_monitor.py`、`market_fetcher.py`：各自实现 AkShare/Eastmoney/Sina fallback。
- `factor_engine.py`、`validate_factor.py`、`shadow_forward.py`：硬编码共享 DataHub 绝对路径。

## 目标数据流

```text
External Providers
        │
        ▼
DataHub ingestion adapters
        │ raw response + source metadata
        ▼
raw → staging → normalized → manifest/conflict/freshness
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
        VNext research   Decision Loop     Factor/Backtest
            │                 │                 │
            └──────── versioned artifacts ──────┘
                              │
                              ▼
                    Paper → Shadow → Live
```

下游模块不得导入 provider SDK、直接发网络请求或自行选择 fallback。DataHub ingestion 是唯一允许访问外部结构化市场数据的层。

## Cron 初步发现

- 同时存在数据全量、增量、weekly refresh、独立 K 线更新、盘中 watcher 和 review cron，缺少统一 DAG/任务注册表。
- 部分任务靠进程名 `pgrep` 防重，部分靠文件锁，语义不统一。
- 需要统一 `job_id/trading_date/idempotency_key/checkpoint/depends_on/timeout/retry/backoff`。
- 所有写任务必须声明 owned datasets；调度器禁止两个任务同时写同一数据集。

已完成第一轮整改：补回 15:45 DataHub 日增量任务；复盘、realized、Event Truth、认证、因子和能力文档改为顺序执行；关键任务使用独立 `flock`；周日增加 DataHub 维护任务；修正了 cron 脚本中的失效 CLI 命令。

## 通知初步发现

- Decision Loop 已统一 Telegram/企业微信回执和共享确认。
- 遗留脚本仍可能直接调用企业微信或其他发送函数，需迁移为 NotificationCenter 事件投递。
- 业务模块只允许创建 notification intent，不负责网络发送、重试或关闭状态。

已完成第一轮整改：Telegram 与企业微信的网络传输、HTTPS host allow-list 和凭据读取迁移至 `factor_lab.notification_transport`；VNext 审批发送器通过注入的中央 transport 投递；架构测试禁止 VNext/Decision Loop 再次实现 `urllib/requests/httpx` 网络发送。

## 因子与研究初步发现

- 因子计算存在硬编码 DataHub 路径，缺少统一 snapshot/version 参数。
- 因子输入必须关联 manifest hash、as_of、复权口径和 universe version。
- 因子发现、评估、OOS、候选、人工晋级、生产版本必须保持单向状态机。
- 第二个 OOS fold 仍为负，继续禁止生产晋级。

## 后续整改顺序

1. 将 VNext snapshot/datasets/event truth 的外部读取迁入 DataHub ingestion。
2. 建立统一 DataHub read-only facade，移除下游硬编码路径。
3. 建立 Cron DAG 注册表和 owned-dataset 冲突检查。
4. 扫描并迁移遗留消息直发调用。
5. 为因子数据增加 snapshot/manifest/universe/version 强制字段。
6. 完成浏览器、真实通知、真实持仓、连续 Shadow 和小额 QMT 验收。
