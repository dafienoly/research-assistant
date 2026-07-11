# VNext 基础设施系统审计（进行中）

生成日期：2026-07-11

## 结论

VNext 的安全门禁和决策闭环已经成形，VNext、Decision Loop 和因子核心链路现已统一到 DataHub read-only facade。历史盘中监控仍留有多套行情 fallback，尚未完全实现“DataHub 是唯一数据入口”。当前最高风险已经从数据截断和任务重叠，收敛为遗留盘中数据所有权与真实券商验收。

## P0 发现与整改

| 问题 | 证据 | 风险 | 状态 |
|---|---|---|---|
| 全量 CSV 每批重复全量覆盖 | `commands/data_pipeline.py` 原 `_append_to_csv`/`full_init_by_trade_date` | I/O 放大、异常截断 | 已改为原子替换、staging、checkpoint、单次正式归并 |
| 测试可删除生产数据 | 多个 pytest fixture 曾直接使用生产常量 | 数据误删 | 已增加全局删除保护和 CI 门禁 |
| Decision Loop 交易日历直接访问 Tushare | `decision_loop/calendar.py` | 绕过 DataHub、运行口径分叉 | 已改为只读 canonical DataHub calendar，缺失 fail-closed |
| Shadow API 自行查询交易日历 | `api_server/routes_paper.py` | API 层承担数据拉取 | 已改为 DataHub 只读访问 |
| 日期审计把 YYYYMMDD 整数解析为 1970 | `data_audit._normalize_trade_date` | freshness 误阻断 | 已修复并增加未来日期异常报告 |
| U0 空响应被解释为总需 0 | `data_audit.missing` | 虚假完整性 | 已改为 UNKNOWN |
| VNext audit 把辅助缺口等同核心缺口 | `vnext/data_audit.py` | 历史 ML 被误阻断或执行门禁口径不清 | 已使用 canonical stock_basic 5530，核心/辅助分层；ML/Shadow/保护性 SELL 数据门禁 OK，辅助 watch-only，BUY OrderDraft 继续阻断 |
| 活跃 freshness 混入退市与测试哨兵 | `data_audit.py` 原文件全集口径 | 虚假未来日期和平均滞后 | 已按 canonical `stock_basic.list_status=L` 审计；5530/5530 完整，5526 最新，4 只由官方 `suspend_d` 解释，核心阻断 0 |
| Legacy 快照 mtime 覆盖核心门禁 | `data_quality.py` / VNext audit | 收盘后永远误报核心 stale | Legacy 文件保留辅助告警；VNext 核心只读 canonical health，Shadow 数据门禁 OK，BUY OrderDraft 仍受辅助缺口阻断 |

## 尚存的 DataHub 绕过

以下模块仍直接创建或调用外部 provider，后续必须迁移到 DataHub ingestion 层：

- Snapshot 已整改：默认只注册 LocalCsvFetcher，指数/ETF 从 DataHub market-series 读取；真实 Snapshot 状态 OK，DataHub 来源 14、Tushare 来源 0。
- Policy Dataset 已整改：指数和 ETF 外部拉取迁移至 DataHub market-series ingestion，VNext 只读 canonical CSV；真实 ingestion 7/7 数据集 OK，真实构建无 Tushare source。
- Event Truth 已整改：外部调用迁移至 `factor_lab/datahub_ingestion/event_truth.py`，VNext 只读 canonical normalized 事件数据；真实 ingestion 13/13 标的为 OK。
- 停牌真值已整改：DataHub ingestion 只对活跃日线滞后标的查询官方 `suspend_d`，原子合并历史记录；4 只滞后标的均确认停牌至 2026-07-10，不改写行情 CSV。
- VNext Provider Router 已保留为不可变本地快照、冲突记录和实时/QMT adapter；未使用的 `TushareFetcher` 已删除，结构化市场 provider 只能存在于 DataHub ingestion。
- `universes.py`：股票池构建直接查询 stock_basic、daily_basic、suspend_d、namechange 和 daily。
- `etf_dive_warning.py`、`intraday_monitor.py`、`market_fetcher.py`：各自实现 AkShare/Eastmoney/Sina fallback。
- `factor_engine.py`、`validate_factor.py`、`shadow_forward.py` 已整改：日线、派生输入和行业映射统一通过 DataHub facade；空目录不再抢占真实 canonical 数据，YYYYMMDD 不再解析为 1970，市场级北向 schema 不再错误广播为个股数据。

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

## Cron 审计与整改

- 同时存在数据全量、增量、weekly refresh、独立 K 线更新、盘中 watcher 和 review cron，缺少统一 DAG/任务注册表。
- 部分任务靠进程名 `pgrep` 防重，部分靠文件锁，语义不统一。
- 需要统一 `job_id/trading_date/idempotency_key/checkpoint/depends_on/timeout/retry/backoff`。
- 所有写任务必须声明 owned datasets；调度器禁止两个任务同时写同一数据集。

第一轮曾用 15:45、16:05、16:15 等时间槽表达依赖，但 DataHub 延迟时仍会重叠。现已替换为声明式 `postmarket` DAG：任务注册表明确 `job_id/trading_date/idempotency_key/depends_on/owned_datasets/writer_id/timeout/retry/backoff`；检查点原子落盘，损坏文件保留后恢复；数据集写锁阻止跨 DAG 双写。依赖失败只阻断下游，能力状态和 D 盘备份仍独立运行。周度 DataHub 维护也通过同一 runner 执行；旧 `closing_pipeline.sh` 仅保留为兼容入口，不再维护第二套编排。

## 通知初步发现

- Decision Loop 已统一 Telegram/企业微信回执和共享确认。
- 遗留脚本仍可能直接调用企业微信或其他发送函数，需迁移为 NotificationCenter 事件投递。
- 业务模块只允许创建 notification intent，不负责网络发送、重试或关闭状态。

已完成第一轮整改：Telegram 与企业微信的网络传输、HTTPS host allow-list 和凭据读取迁移至 `factor_lab.notification_transport`；VNext 审批发送器通过注入的中央 transport 投递；架构测试禁止 VNext/Decision Loop 再次实现 `urllib/requests/httpx` 网络发送。

## 因子与研究审计

- 因子计算存在硬编码 DataHub 路径，缺少统一 snapshot/version 参数。
- 因子输入必须关联 manifest hash、as_of、复权口径和 universe version。
- 因子发现、评估、OOS、候选、人工晋级、生产版本必须保持单向状态机。
- 第二个 OOS fold 仍为负，继续禁止生产晋级。

已完成核心整改：`factor_engine.load_stock_kline` 虽影响 18 个直接调用方和 9 条流程，但在保持函数签名、返回 schema 和过滤语义不变的前提下迁入 DataHub facade，并通过 121 项因子、验证、Paper、组合、Live 和 Shadow 专项测试。真实 `000001` 烟测从 canonical `data/normalized/market` 读取 8 行 2026-07-01 至 2026-07-10 数据。行业映射只读 canonical `stock_basic`，不再调用业务层外部 provider。Standing Shadow 缺少真实收益时继续输出 `BLOCKED/null`。

## 前端基础设施

Vite/Rolldown 生产构建原有 1.14 MB 与 550 KB 大块。现按 charts、Ant Design、Markdown 和 React platform 分组，最大块降至约 175 KB，构建不再产生 500 KB 告警；lint、TypeScript、14 个文件 28 项测试及生产构建通过。应用内浏览器发现仍返回空列表，因此 console、点击和截图验收保持外部运行时阻断，不用 DOM 单测冒充浏览器证据。

## 后续整改顺序

1. 迁移 `universes.py` 及三个遗留盘中监控的 provider fallback 到 DataHub ingestion/quote adapter。
2. 扫描并迁移 VNext/Decision Loop 之外的遗留消息直发调用。
3. 为因子数据增加 snapshot/manifest/universe/version 强制字段。
4. 完成浏览器、真实持仓、连续 Shadow 和小额 QMT 验收。

## 持久化补充整改

每日 17:00 能力文档任务已负责对事件、执行审计、通知回执、周期历史和 ReviewRecord 做 90 日归档。归档实现已改为临时文件、`fsync`、`os.replace`；先安全落盘 archive，再替换当前账本，异常时不允许截断源 JSONL。
