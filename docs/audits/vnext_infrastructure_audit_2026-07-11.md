# VNext 基础设施系统审计（进行中）

生成日期：2026-07-11；最近复核：2026-07-12

## 结论

VNext 的安全门禁和决策闭环已经成形，VNext、Decision Loop、股票池、动态基准、因子核心、主盘中监控、ETF/dive 实时与历史训练链路现已统一到 DataHub read-only facade。审计发现并恢复了 3 个活跃行情文件中的旧测试污染行，同时补上行级完整性门禁。监管公告已完成真实标的覆盖验证，公司事件除 forecast 上游故障外已形成可恢复快照。当前最高风险收敛为少数遗留政策/消息入口、真实券商验收、连续 Shadow 证据和外部 forecast 数据源。

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
| 行情 CSV 混入测试/合成行 | `000001.SZ`、`600519.SH`、`688012.SH` 各多出 15/25/20 行非 canonical 日期 | 回测收益畸变、审计误判 | 当前污染文件完整隔离到 D 盘；从 `research-assistant-data_20260711_003538` 原子恢复；有效行数/最新日期/SHA 验证通过；未直接删行 |
| 覆盖率审计不检查行级不变量 | 原审计只检查文件、日期范围和 freshness | “5530/5530”仍可能包含污染 | 新增 `integrity.json`：检查 8 位交易日、交易日历、代码一致、有限正数、OHLC、不一致重复日；5530 文件当前全部 OK |
| 通知先于保护性执行 | `decision_loop/cycle.py` 原先同步双通道 `notify` 后才执行 SELL | 网络超时延迟风险处置 | 操作卡先持久化 durable outbox，再提交受控执行；独立 minute worker 异步投递，执行路径不再等待网络 |
| 恢复、备份与 DataHub 后半段写入锁不统一 | recovery 仅靠不完整 `pgrep` | 恢复覆盖正在写入的数据 | DataHub cron、benchmark projection、恢复、还原和备份统一使用 `datahub-global.lock`；保留扩展 pgrep 作为第二道防线 |
| 通用 PositionLoader 绕过 QMT Bridge | `portfolio/position_loader.py` 原调用旧 `factor_lab.miniqmt` 并吞异常/缓存空仓 | 静默空持仓、账户口径分叉 | 已统一调用 `MiniQMTPositionAdapter`；Bridge 不可用或返回空响应时记录 error+partial，禁止静默成功 |
| 旧 miniqmt 模块仍可绕开 Bridge | `factor_lab/miniqmt/__init__.py` 直接调用 xtdata、吞异常并缓存空持仓 | 人工入口可重新引入口径分叉 | 已降为兼容 facade：账户/持仓只经 QMT Bridge，实时/日线只读 DataHub，分钟数据缺失显式失败，缓存 fallback 物理删除 |

## 尚存的 DataHub 绕过

以下模块仍直接创建或调用外部 provider，后续必须迁移到 DataHub ingestion 层：

- Snapshot 已整改：默认只注册 LocalCsvFetcher，指数/ETF 从 DataHub market-series 读取；真实 Snapshot 状态 OK，DataHub 来源 14、Tushare 来源 0。
- Policy Dataset 已整改：指数和 ETF 外部拉取迁移至 DataHub market-series ingestion，VNext 只读 canonical CSV；真实 ingestion 7/7 数据集 OK，真实构建无 Tushare source。
- Event Truth 已整改：外部调用迁移至 `factor_lab/datahub_ingestion/event_truth.py`，VNext 只读 canonical normalized 事件数据；真实 ingestion 13/13 标的为 OK。
- 停牌真值已整改：DataHub ingestion 只对活跃日线滞后标的查询官方 `suspend_d`，原子合并历史记录；4 只滞后标的均确认停牌至 2026-07-10，不改写行情 CSV。
- VNext Provider Router 已保留为不可变本地快照、冲突记录和实时/QMT adapter；未使用的 `TushareFetcher` 已删除，结构化市场 provider 只能存在于 DataHub ingestion。
- `universes.py` 已整改：只读 DataHub reference/calendar/suspend/market；U0-U4 在同一构建上下文复用依赖；批量索引后真实全量构建由 94 秒未完成降至 10.75 秒。
- 动态基准已整改：组合基准只读 `market_series/index`；U0/U1/U3/U4/ETF 等权基准由 ingestion 物化到 `normalized/derived/benchmarks`，消费请求不再逐文件重算或联网。
- 行业、股票名称和 ETF Universe 已整改：分别只读 canonical `stock_basic` 与 `market_series/fund`，缺失值显式标记 `MISSING`，不再静默 AkShare fallback。
- ST 名单已整改：交易侧只读 canonical `stock_basic`。监管公告由 ingestion 针对当前持仓/计划标的从 CNINFO/SSE/SZSE 拉取，snapshot 显式记录 `covered_symbols`；PreTrade 对未覆盖标的继续 `regulatory_truth_unavailable`，不会把“部分抓取为空”误判为安全。
- `intraday_monitor.py` 已整改：持仓、ETF、U3、指数与全 A 情绪统一只读 canonical `market/live_snapshot.csv`，同一进程只解析一次；过期/缺失返回空并 fail-closed。唯一 writer 位于 `datahub_ingestion/live_snapshot.py`，空响应不覆盖旧数据，原子写 CSV+SHA manifest，并与备份/恢复共用全局锁。
- `etf_dive_warning.py` 已整改：只读相同 canonical live snapshot；资金流真值未进入快照时显式 `MISSING`，不再把缺失当作净流入 0 的完整证据，也不再调用 AkShare/mx fallback。
- `monitor_588710.py` 已整改：行情、ETF 权重和北向资金分别只读 canonical live snapshot、normalized ETF holdings 和 north-flow；KOSPI 未入 DataHub 时显式 MISSING，不再联网拼接。ETF holdings 周任务修复到声明的 normalized owned dataset，空响应不覆盖旧快照并生成 SHA manifest；真实刷新 4/4 ETF、379 行为 OK，588710 最新披露期可读 15 行并取前十。
- dive live predictor 与历史训练 collector 已整改：实时价和市场广度只读 canonical live snapshot，历史训练跨股票/基金 canonical 根读取日线；159516 已由 fund_daily ingestion 统一拥有，不再调用 AkShare、清空代理或写 `_hist.csv` 副本。
- semiconductor event 生产加载路径已整改：`CorporateEventIngestion` 统一拉取 forecast/holdertrade/repurchase/share_float/dividend，按 symbol 原子发布 long-format canonical CSV；研究引擎的 `load_all_events` 只读该快照和 DataHub 日历，不再在运行时查询 provider。旧私有 `_fetch_*` 方法及兼容 provider hook 已物理删除。
- 旧 `market:update-*` / `fundamentals:update` CLI 已改为 DataHub ingestion 兼容入口；`market_fetcher.py` 不再调用 RSScast、Sina、AkShare，不再写独立日线、分钟线、板块或财务副本。
- 遗留 `update_kline_daily.py` 已从 Baostock/RSScast 双路逐文件重写器降为兼容包装器，只能委托 canonical DataHub 日增量管线；旧入口不再拥有 provider、去重或 CSV 写入责任。
- `scripts/refresh_kline_data.py` 仍残留另一套 Tushare provider、旧 CSV 覆盖、schema 就地修改和 `_hist.csv` 清理逻辑，且不持有 DataHub 全局锁。现已降为与 `update_kline_daily.py` 相同的兼容 facade，只能调用 `cmd_update_daily`；provider、覆盖、清理和机器绝对路径全部物理移除。
- `commands/tushare_datahub.py` 名称虽似正式 DataHub，实际曾是独立的行情、估值、资金流和财务 provider/writer，拥有第二套目录、合并和重试策略。现 `run_full/run_incremental` 均仅委托 canonical daily owner；业务脚本不再能够选择这套平行数据管线。
- `commands/scripts/v5_data_integrity_check.py` 原来继续扫描已退役的 `data/market/daily_kline`，使用旧 schema 和自然日阈值，可能与正式数据审计给出相反结论。现 K 线检查只消费 24 小时内的 canonical coverage/freshness/integrity 报告；真实运行返回 5,530/5,530、freshness OK、integrity OK，任一报告缺失或过期即 FAIL。
- 真实运行新增整改：Event Truth 全失败不再用空日历覆盖旧 CSV；Market Series 增量 manifest 按 dataset+symbol 合并；Tushare 严格模式区分上游异常与合法空结果；公司事件按数据集累计三次异常熔断并逐标的检查点；限流窗口由错误的约 120 秒校正为 60 秒。
- U3 复合代码 `0981.HK / 688981.SH` 过去被误解析为无效 `0981.SZ`，现统一选择六位 A 股分量 688981；该约束同时保护基准、因子、Paper/Shadow 与事件 ingestion。
- 监管 ingestion 同时发布完整公告与风险事件视图；`announcement_parser.py` 只读 canonical snapshot，不再自行调用三交易所 provider。
- 监管真实 smoke 发现 CNINFO 请求缺少 orgId 时返回全市场最近公告，旧实现又把请求代码写入每条记录，形成假覆盖。现强制校验上游 `secCode`，无来源代码的记录丢弃；CNINFO 先发现匹配 orgId，再以 `代码,orgId` 请求证券专属页。688012 复验只保留 1 条匹配公告，原 30 条错误证据已撤销。
- `policy:update-events` 已删除无效 Tavily 调用（此前消耗配额但结果未写入），改为只读监管 canonical 公告视图；preopen/policy 派生 CSV 原子发布并附 coverage manifest。真实 688012 覆盖下无风险类事件时发布 `EMPTY`，不会继续沿用旧事件。
- `factor_engine.py`、`validate_factor.py`、`shadow_forward.py` 已整改：日线、派生输入和行业映射统一通过 DataHub facade；空目录不再抢占真实 canonical 数据，YYYYMMDD 不再解析为 1970，市场级北向 schema 不再错误广播为个股数据。
- `data_hub_rebuilder.py` 已降为兼容 facade：基本面宽表、资金流宽表和公告情绪宽表由 `FactorInputProjection` 从 normalized fundamentals/fund-flow/regulatory snapshot 物化，原子发布并记录 SHA 与覆盖 manifest；CLI 不再直接访问 MX、Baostock、新闻搜索或自行去重写 CSV。缺失 canonical 输入时保留旧输出并标记 BLOCKED。
- `tag_maintainer.py` 已移除 Baostock 登录、行业查询和基本面副本写入：名称/行业只读 canonical `stock_basic`，标签 CSV 原子发布；旧 fundamentals 命令仅委托 `FactorInputProjection`。手工产业链语义仍保留为受版本控制的研究输入。
- 独立 Python writer 新增统一 `datahub_write_lock`；FactorInputProjection 与三类标签写入和 shell cron、D 盘备份、恢复共用 `datahub-global.lock`，锁竞争直接 fail-closed，避免“经 cron 安全、直接 CLI 不安全”的入口差异。
- 真实 factor-input 物化暴露资金流兼容宽表达到 4,623,229 行/373 MB，仍属于全量重写放大。现将资金流定义为 `PARTITIONED`：`load_stock_kline` 保持签名/schema 不变，只为当前有效 symbols 读取 canonical 分区；单标的 124 行真实烟测耗时约 0.55 秒且资金流全命中，维护命令约 0.36 秒只更新分区 manifest，不再重写宽表。旧 373 MB 文件保留但不再作为生产入口，遵守不删除数据约束。
- `load_stock_kline` 为 CRITICAL blast radius（18 个直接调用、10 条执行流）。整改后因子、组合、Paper、Shadow、Live、验证、正交性专项全链 781 项通过；同时修复测试套件在启用真实 `HERMES_UI_TOKEN` 时未携带 Bearer token 的顺序依赖，并将 Paper API 断言更新到统一 response envelope。生产鉴权没有被关闭或绕过。
- `dive_prediction/datahub_supplement.py` 曾包含明文 JoinQuant 账号密码、全局删除 proxy 环境、先 unlink 旧 K 线再写入、追加资金流宽表等高风险行为。现已删除全部 provider/凭据/直写逻辑：股票与资金流只委托一次 daily DataHub ingestion，931743 指数由 MarketSeriesIngestion 在全局锁内拥有。旧 JoinQuant 密码仍必须在提供方轮换，因为删除工作树代码不能清除 Git 历史。
- `baostock_data.py` 原为完整的第二套基本面、现金流、预告、复权、行业、指数、宏观和特征写入系统，且使用机器绝对路径。仓库内无外部调用方，现仅保留脚本兼容 facade：运行一次 canonical daily ingestion，再由 FactorInputProjection 物化基本面；所有 Baostock provider、独立 schema、特征写入和逐代码刷新函数已物理删除。
- 新增全仓 provider-boundary AST 门禁：AkShare/Baostock/JoinQuant/Tushare SDK 只能出现在 DataHub ingestion、provider adapter 或明确列出的底层 provider 文件。门禁首次运行发现 `industry_relative/factors.py` 是无法解析且无人导入的截断重复文件；实际 13 个行业相对因子均由 `factor_base.py` 注册，故删除损坏副本。无人引用的全局 `dns_patch.py` 也已退役，网络/代理策略归 ingestion adapter 所有。
- `factor_lab/batch_compute.py` 原来硬编码扫描无效的 `data/market/daily_kline/*_daily_kline.csv` 副本，可能静默得到空批次。现通过 `daily_kline_index()` 一次索引 canonical 分区，统一兼容 `trade_date/timeString`、`vol/volume` 和代码后缀；批量因子 API 专项 30 项通过。
- Strategy Lab 回测、SSE regime、universe、publisher、参数搜索、walk-forward、ranker 与 orchestrator 原来分别硬编码共享 K 线、项目根和旧 Baostock 行业副本。现回测/regime 通过 `daily_kline_path()` 读取并规范 canonical schema，主题池使用 canonical `stock_basic` 行业和版本控制标签；策略、performance、research_outputs 和跨系统 handoff 根统一由 `strategy_lab.paths` 推导，不再绑定开发机器绝对路径；本批路径专项 4 项通过。
- Strategy Lab publisher 原来在同秒包名冲突时会 `rmtree` 既有暂存目录甚至完成目录，违反数据只增不删约束。现使用 UUID 唯一包 ID、独立 staging 目录和拒绝覆盖策略；连续两次发布测试证明第一份包和人工 marker 均被保留。
- `live_readiness.DataHealthGate` 原来只要任一候选目录存在 CSV 就会通过，既不验证覆盖率、新鲜度，也不识别污染，属于伪安全门禁。现强制读取 24 小时内的 canonical coverage/freshness/integrity 审计，任一缺失、过期或失败即 fail-closed；`factor_commands` 的沪深 300 基准和因子挖掘股票索引也已改走 `daily_kline_path/index` facade。
- 遗留 `fund_flow.py` 原来由业务 CLI 启动浏览器直连东方财富并现场解析页面，完全绕过 DataHub。现个股接口只读 canonical moneyflow 分区并携带 `source/observed_at/data_status`；市场汇总在没有 owned dataset 前显式 `MISSING`，不再用网页结果伪装生产数据。

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

第一轮曾用 15:45、16:05、16:15 等时间槽表达依赖，但 DataHub 延迟时仍会重叠。现已替换为声明式 `postmarket` DAG：任务注册表明确 `job_id/trading_date/idempotency_key/depends_on/owned_datasets/writer_id/timeout/retry/backoff`；检查点原子落盘，损坏文件保留后恢复；数据集写锁阻止跨 DAG 双写。`benchmark_projection` 显式依赖 `datahub_daily`，盘后 review 再依赖 benchmark；备份显式依赖数据更新成功。能力状态保持可在研究失败时报告，但至少依赖数据任务完成。周度 DataHub 维护也通过同一 runner 执行；旧 `closing_pipeline.sh` 仅保留为兼容入口，不再维护第二套编排。

`postmarket` 入口现先读取 canonical DataHub 交易日历：休市日输出 `SKIPPED/non_trading_day`，不启动任何写任务；日历缺失或无对应日期时 fail-closed，并进入双通道运维 outbox。`weekly_datahub` 属于维护任务，不受交易日门禁影响。

## 通知初步发现

- Decision Loop 已统一 Telegram/企业微信回执和共享确认。
- 遗留脚本仍可能直接调用企业微信或其他发送函数，需迁移为 NotificationCenter 事件投递。
- 业务模块只允许创建 notification intent，不负责网络发送、重试或关闭状态。

已完成第一轮整改：Telegram 与企业微信的网络传输、HTTPS host allow-list 和凭据读取迁移至 `factor_lab.notification_transport`；VNext 审批发送器通过注入的中央 transport 投递；架构测试禁止 VNext/Decision Loop 再次实现 `urllib/requests/httpx` 网络发送。

第二轮整改增加 durable outbox、`event_id:channel` 幂等键、指数退避、最大尝试和 dead-letter。L2 摘要改为每通道独立 cursor：Telegram 成功不会掩盖企业微信失败，失败通道下次继续投递。共享确认只接受已登记事件；未知 event_id 返回 `not_found`。实际 crontab 已统一使用 `.venv_quant`，不再混用 `/usr/bin/python3`。

第三轮整改将调度 DAG 的最终 FAILED/BLOCKED 状态写入 `scheduler/alerts.jsonl` 和现有双通道 durable outbox；调度进程不等待网络，通知 worker 负责幂等重试和 dead-letter。相同 `dag_id+trading_date` 不会重复创建消息，运维告警账本纳入 90 日归档。

遗留 `factor_lab.notify` 第一轮 blast radius 为 CRITICAL（27 个符号）；本轮对实际网络汇聚点 `_send_wecom_markdown` 复核为 HIGH（4 个直接调用方，kill switch/risk sentinel/盘中监控三条流程）。现保持函数签名、布尔返回、冷却和 Markdown 截断不变，但业务调用只向 Telegram＋企业微信 durable outbox 写入带内容哈希的幂等 intent；每分钟 worker 负责网络、重试和 dead-letter，盘中风险调用不再同步等待 webhook。布尔 `True` 的语义明确为“持久化成功”，不是“已送达”。

旧 `WeChatPusher` 的 L2/L3/L4 文本与 Markdown 入口也已迁入相同双通道 outbox；日志新增 `queued` 并保持 `sent=false`，不再把排队成功冒充网络送达。显式 `wechat:test` 仍作为人工连通性诊断调用中央 transport，不属于业务事件发送。

股票图片卡片原来在 CLI 内把 PNG base64 后同步直发企业微信，Telegram 无对应通道。现 PNG 以 SHA-256 内容寻址、原子写入 decision-loop 状态根，outbox 只保存相对路径、SHA、MIME 和大小；worker 发送前强制检查根目录约束、2 MiB 上限与哈希。企业微信使用 image payload，Telegram 使用受 allow-list 保护的 multipart `sendPhoto`，各自生成独立回执；旧附件永不因同名发布被覆盖或删除。

VNext `TelegramApprovalGate` 原来默认同步单发 Telegram，与用户要求的共享双通道确认不一致。现保留可注入 sender 的认证测试接口，但生产默认以 `approval_id` 作为共享 `event_id` 写入 Telegram＋企业微信 outbox；返回状态为 `QUEUED`、`sent=false`，审批有效性和订单执行从不依赖消息网络送达。

## 因子与研究审计

- 因子计算存在硬编码 DataHub 路径，缺少统一 snapshot/version 参数。
- 因子输入必须关联 manifest hash、as_of、复权口径和 universe version。
- 因子发现、评估、OOS、候选、人工晋级、生产版本必须保持单向状态机。
- 第二个 OOS fold 仍为负，继续禁止生产晋级。

已完成核心整改：`factor_engine.load_stock_kline` 虽影响 18 个直接调用方和 9 条流程，但在保持函数签名、返回 schema 和过滤语义不变的前提下迁入 DataHub facade，并通过 121 项因子、验证、Paper、组合、Live 和 Shadow 专项测试。真实 `000001` 烟测从 canonical `data/normalized/market` 读取 8 行 2026-07-01 至 2026-07-10 数据。行业映射只读 canonical `stock_basic`，不再调用业务层外部 provider。Standing Shadow 缺少真实收益时继续输出 `BLOCKED/null`。

一次性 `scripts/register_strategy_alpha.py` 原来能直接把固定策略标为 `backtested`，写入硬编码的 272.1% 收益、49.31% 回撤和 IC 历史，完全绕过 OOS、Paper/Shadow 与人工批准。该入口已退役并 fail-loud；自动版本推荐/Agent 自动开发系统不通过旧脚本复活，策略只能走受治理晋级状态机。

扩大测试时发现 `test_alpha_governance.py` 直接把候选和报告写入 D 盘真实目录，并在 teardown 递归删除；删除保护成功阻止了清理，但首个测试已产生一份真实候选残留，按“严禁删除”要求保留现场。测试现通过 autouse fixture 将 discovery/governance 的候选、索引和报告根全部重定向到 pytest 临时目录，31 项治理/退役专项通过，后续不再触碰 D 盘生产研究数据。

## 前端基础设施

Vite/Rolldown 生产构建原有 1.14 MB 与 550 KB 大块。现按 charts、Ant Design、Markdown 和 React platform 分组，最大块降至约 175 KB，构建不再产生 500 KB 告警；lint、TypeScript、14 个文件 28 项测试及生产构建通过。应用内浏览器发现仍返回空列表，因此 console、点击和截图验收保持外部运行时阻断，不用 DOM 单测冒充浏览器证据。

## 后续整改顺序

1. 继续扫描剩余研究/辅助入口的机器绝对路径与旧数据副本；外部来源只能进入 DataHub ingestion adapter。
2. 为 forecast 接入可验证替代源并保留来源冲突；持续观察监管公告多源覆盖，不把单标的 smoke 当作全市场证明。
3. 扫描并迁移 VNext/Decision Loop 之外的遗留消息直发调用，并增加独立运维 heartbeat/失败告警。
4. 为因子数据增加 snapshot/manifest/universe/version 强制字段。
5. 完成浏览器、真实持仓、连续 Shadow 和小额 QMT 验收。

## 持久化补充整改

能力文档任务已负责对事件、执行、通知、授权、持仓、对账、参数、认证、周期和 ReviewRecord 做 90 日归档。归档时间识别已覆盖 `attempted_at/started_at/completed_at/acknowledged_at/as_of` 等运行字段；无可识别时间的记录保留在当前账本，不再错误视为过期。归档实现使用临时文件、`fsync`、`os.replace`；先安全落盘 archive，再替换当前账本，异常时不允许截断源 JSONL。

代码审计协调器原来按 change-set 同时缓存 PASS 和 FAIL，环境性失败（例如临时盘满）在环境恢复后仍会永久阻断且不重跑。现只复用已通过结果；失败和异常每次重新执行完整门禁。测试临时目录统一可由 `TMPDIR/TEMP/TMP` 指向 WSL `/tmp`，不通过删除 Windows 临时数据解决容量问题。
