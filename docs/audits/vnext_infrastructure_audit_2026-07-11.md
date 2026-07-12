# VNext 基础设施系统审计（进行中）

生成日期：2026-07-11；最近复核：2026-07-12

## 结论

VNext 的安全门禁和决策闭环已经成形，VNext、Decision Loop、股票池、动态基准、因子核心、主盘中监控、ETF/dive 实时与历史训练链路现已统一到 DataHub read-only facade。审计发现并恢复了 3 个活跃行情文件中的旧测试污染行，同时补上行级完整性门禁。监管公告已完成真实标的覆盖验证，公司事件除 forecast 上游故障外已形成可恢复快照。当前最高风险收敛为少数遗留政策/消息入口、真实券商验收、连续 Shadow 证据和外部 forecast 数据源。

## 2026-07-12 第二轮系统复核与整改

本轮不是基于旧结论抽样，而是重新检查生产可达 DataHub、cron、通知、账本、因子晋级和盘中监控路径。新增发现及处理如下：

| 发现 | 风险 | 整改 |
|---|---|---|
| VNext 路由测试未适配真实 UI Token，单测顺序改变后出现 401 | CI 可能误报或诱导关闭生产鉴权 | 测试使用进程启动时真实 token；无 token 的 CI 不伪造；生产鉴权未放宽 |
| 能力状态生成器同时归档 18 类账本 | 状态查询产生隐藏写副作用、职责耦合 | 生成器恢复为纯状态读取＋文档输出；新增独立 `decision_ledger_archive` DAG job |
| JSONL 锁超过 120 秒会被无条件删除 | 通知积压时重复投递、并发写损坏 | `DecisionLoopStore` 改为内核 `flock`，锁文件年龄不再影响所有权；旧锁抢占故障注入通过 |
| JSONL 任意坏行使整个 outbox/回执/执行账本不可读 | 一行损坏阻断完整安全闭环 | 逐行验证，合法行继续使用；坏行原文、SHA、行号写入 quarantine，幂等去重且不删除证据 |
| 通知回执与 outbox 独立归档会使旧消息重新可投递 | 重复风险告警或重复运维消息 | 关联压缩先移走终态 outbox，再移走回执/dead-letter；仅已确认且全通道终态事件成组归档 |
| `check_volume_anomaly` 子进程调用 `mx.py`，并以 3 个股票文件/`today×0.85` 合成 20 日均 | DataHub 绕过、虚假成交额告警 | 新增 canonical `derived/market_turnover` 投影和 manifest；实时端只读 DataHub，历史缺失时明确 MISSING、不告警 |
| 日线 amount 千元与实时 amount 元未统一 | 偏离放大 1,000 倍 | 投影统一为 CNY 元，manifest 明示 source/unit；真实 60 日投影和 SHA 已生成 |
| 日线 facade 按首个含 CSV 目录静默择根 | 不同机器/时点读取不同 truth | 股票批量根固定 `data/normalized/market`；fund/index 为声明数据集；同代码多根哈希冲突时 fail-closed |
| live snapshot reader 不验证 manifest/hash，provider 覆盖无冲突记录 | 篡改或覆盖差异进入盘中判断 | reader 强制 `status/observed_at/sha256`；ingestion 记录字段级 provider 冲突及确定性优先级 |
| Reference ingestion 写 `ts_code`，名称/行业 reader 只认 `symbol` | 真实名称/行业静默缺失 | producer 物化 symbol；reader 兼容历史 ts_code；增加 producer→consumer 契约测试和 manifest SHA |
| Shadow IC 按数值排序；人工确认提前 `enabled=True` | 衰减率失真、绕过 Shadow/OOS | IC 按 validated_at 排序；人工确认状态为 `human_approved_shadow`，enabled/paper/live 均保持 false |
| ST/监管消费者只看文件存在或 mtime | 陈旧或篡改风险 truth 仍可能放行 BUY | 强制 sidecar `status/generated_at/sha256/conflicts`；过期、哈希不符或未覆盖标的全部 fail-closed |
| Alpha Registry、pending 和 Shadow 直接 JSON 读改写 | 并发注册/确认可能丢 index 条目 | 新增共享 `flock + atomic replace + fsync` 事务存储；并发注册和 100 写者回归覆盖 |
| LLM Alpha Discovery 测试删除 D 盘 candidate 根并在审批时写真实 Registry | 测试误删/污染生产研究状态 | 模块级 autouse fixture 同时隔离 candidate、report、registry；复验 31 项通过且 D 盘 registry mtime/size 不变 |

真实复核结果：市场成交额投影 60 个交易日、5,738 个有效源分区，最近 20 日均约 3.27 万亿元；关键路径新增/回归专项 131 项通过。QMT 账户连接、连续 Shadow、小额白名单和浏览器证据仍属于外部运行验收，不由上述单测替代。

测试隔离复核期间，在完成 Registry root 隔离前有两条审批测试新增了两个 disabled Alpha：`alpha_20260712_074545343540`、`alpha_20260712_074546936924`。它们没有启用 Paper/Live，也未覆盖既有记录；遵循数据严禁删除约束，原件保留并明确登记，不由自动化清理。

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

Live readiness 的通知门禁原来只检查企业微信，并通过启动 shell/source `~/.bashrc` 查找 webhook，导致服务环境与交互环境分叉。现门禁同时要求企业微信、Telegram token 和 chat ID 均存在于受控进程环境；不执行 shell、不读取 `.bashrc`，任一通道缺失即 blocker。

股票图片卡片原来在 CLI 内把 PNG base64 后同步直发企业微信，Telegram 无对应通道。现 PNG 以 SHA-256 内容寻址、原子写入 decision-loop 状态根，outbox 只保存相对路径、SHA、MIME 和大小；worker 发送前强制检查根目录约束、2 MiB 上限与哈希。企业微信使用 image payload，Telegram 使用受 allow-list 保护的 multipart `sendPhoto`，各自生成独立回执；旧附件永不因同名发布被覆盖或删除。

VNext `TelegramApprovalGate` 原来默认同步单发 Telegram，与用户要求的共享双通道确认不一致。现保留可注入 sender 的认证测试接口，但生产默认以 `approval_id` 作为共享 `event_id` 写入 Telegram＋企业微信 outbox；返回状态为 `QUEUED`、`sent=false`，审批有效性和订单执行从不依赖消息网络送达。

## 因子与研究审计

- 因子计算存在硬编码 DataHub 路径，缺少统一 snapshot/version 参数。
- 因子输入必须关联 manifest hash、as_of、复权口径和 universe version。
- 因子发现、评估、OOS、候选、人工晋级、生产版本必须保持单向状态机。
- 第二个 OOS fold 仍为负，继续禁止生产晋级。

已完成核心整改：`factor_engine.load_stock_kline` 虽影响 18 个直接调用方和 9 条流程，但在保持函数签名、返回 schema 和过滤语义不变的前提下迁入 DataHub facade，并通过 121 项因子、验证、Paper、组合、Live 和 Shadow 专项测试。真实 `000001` 烟测从 canonical `data/normalized/market` 读取 8 行 2026-07-01 至 2026-07-10 数据。行业映射只读 canonical `stock_basic`，不再调用业务层外部 provider。Standing Shadow 缺少真实收益时继续输出 `BLOCKED/null`。

一次性 `scripts/register_strategy_alpha.py` 原来能直接把固定策略标为 `backtested`，写入硬编码的 272.1% 收益、49.31% 回撤和 IC 历史，完全绕过 OOS、Paper/Shadow 与人工批准。该入口已退役并 fail-loud；自动版本推荐/Agent 自动开发系统不通过旧脚本复活，策略只能走受治理晋级状态机。

因子 pipeline、walk-forward、rolling validation、正交性验证、validate_factor、事件加载和行业映射仍把项目根绑定到开发机 `/home/ly`。现项目/数据根全部由模块位置或统一 DataHub facade 推导，研究报告根提供环境变量覆盖；算法、窗口和输出 schema 未改变，跨机器运行不再静默读取另一个用户目录。

`alpha/event_loader.py` 虽已改为可移植路径，仍分别读取 `announcements_extracted.csv`、`adjust_factor.csv` 和 `forecast_report.csv` 三份旧派生数据，绕过公司事件 manifest。现解禁、回购、分红、业绩预告只读 canonical `normalized/events/corporate_events` 分区，保留原因子列 schema；forecast 上游当前缺失时状态为 PARTIAL/MISSING，不回退旧 CSV，也不伪造股息率价格分母。

`alpha/industry_mapper.py` 在 canonical stock_basic 失败时仍用 `tag_features.csv` 的 style 猜行业，再从 `pool.csv` 补 unknown，并允许写独立 `stock_industry.csv` 缓存。现行业映射 canonical-only：读取失败暴露 `status=MISSING/error`，未知标的按调用返回 `unknown`，但不制造伪映射；`save_cache` 明确拒绝，DataHub 是唯一 reference owner。

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

内置 Research Skill 的“数据质量”原来只统计 `fetch_log.jsonl` 行数，无法证明数据可用；Registry/Runtime 又把运行状态写入源码树 `agent_tasks`。现 Skill 强制读取有时效限制的 canonical coverage/freshness/integrity 并输出 OK/BLOCKED；运行状态默认迁至 `~/.hermes/state/research-assistant/research-skills`，支持环境覆盖，旧源码树内容保留不删。

## VNext 健康状态与实时快照收口

`VNextService.build_data_health` 原来硬编码开发机共享目录，并用目录文件数量和 CSV mtime 猜测“Tushare/AkShare/腾讯/东方财富”等 provider 健康。这既无法证明数据属于哪个 snapshot，也会把目录存在误报为数据可用。现仅消费 DataHub 生成的 `coverage.json`、`freshness.json`、`integrity.json` 与 VNext data audit；保留生成时间、覆盖/阻断证据和恢复信息。证据缺失、损坏或超过两天均 fail-visible，辅助缺口继续使整体为 `PARTIAL`。

`HubSnapshotBuilder` 的默认实时行情路径现由 `datahub_access.LIVE_SNAPSHOT_PATH` 统一解析。读取 CSV 前强制通过 canonical manifest 状态、SHA-256、观测时间和 schema 校验；验证失败返回 `MISSING`，不再绕过 DataHub 或从其他 provider 回退。架构测试同时禁止 VNext 重新引入用户目录绝对路径和目录扫描式健康判断。

## Promotion Engine 并发持久化收口

Promotion Queue 原来由各进程分别读取整个 JSON 后覆盖写回，`add/remove/update/clear` 并发时会互相覆盖；Promotion history 也直接无锁 append，异常被静默吞掉。现队列操作复用 Alpha storage 的跨进程 `flock`，在同一临界区完成完整读改写，并通过临时文件、`fsync`、`os.replace` 发布。历史使用加锁 `O_APPEND`、文件与目录 `fsync`，以 `candidate_id + alpha_id` 为幂等键；已存在的坏行保持原字节，不因重写或归档被删除。60 路并发队列写与 120 次含重复历史追加测试均证明无丢项、无重复。

## 盘前与分钟调度收口

盘前 PassList 与监管真值原来分别由 08:55/08:57 cron 直接启动，只有时间假设、没有依赖边，PassList 延迟时监管任务会读取旧 watchlist。现新增声明式 `premarket` DAG：`vnext_passlist → regulatory_events`，分别声明 watchlist 与 regulatory dataset 的唯一 writer、超时、重试、checkpoint 和数据集锁；休市日由 canonical DataHub 日历整体跳过，日历缺失则 fail-closed 并进入现有运维告警链。

分钟实时快照仍需每分钟执行，不能使用日级 checkpoint DAG；其唯一 ingestion 入口现于获取全市场行情前读取同一 canonical 交易日历。休市日返回 `SKIPPED/non_trading_day`，日历缺失返回 FAILED，不访问上游、不覆盖上一个有效快照。Decision Cycle 自身的第二道交易日门禁保持不变。

通知 worker 原来仅在工作日 09:00–15:59 消费 outbox，15:45 启动的 postmarket DAG 常在 worker 停止后才产生告警，周日 weekly DAG 也没有消费者。现 worker 每天 08:00–20:59 运行；盘后和周末运维失败可以在同一运行窗口投递，Telegram 与企业微信仍共享事件关闭状态并保留独立回执。

## Active Python 供应链哈希闭环

Core 已有 `--require-hashes`，但隔离 vectorbt 环境仍从 plain exact-pin lock 安装，审批清单和运行结果也只引用 plain lock。现为 vectorbt 的 55 个实际安装依赖生成完整 PyPI release SHA-256 lock，CI 使用 `pip install --require-hashes`；依赖审批清单同时固定 plain/hashed 两个文件的 SHA，VNext CI Gate 验证每个 exact pin 至少有一个包哈希。SBOM 同时记录两个 active 环境的 plain/hashed lock 摘要，Vectorbt worker 运行证据引用 hashed lock。三个 comment-only 未安装 sidecar 不生成虚假空哈希锁。

## 因子失败归因 DataHub 边界

`alpha/failure_db.py` 正常使用 canonical benchmark，但在 benchmark 模块导入失败时会改走 `mx_data.get_index_daily` 直接联网，形成异常路径的第二套数据实现。该 fallback 已物理删除：canonical benchmark 不可用时 regime 诚实返回 `unknown`。Provider boundary 架构测试现把 `mx_data` 与 Tushare/AkShare/Baostock/JQData 同等视为下游禁止导入的 provider wrapper。

## Events API 真实性与 DataHub lineage

`GET /api/events` 原来在每次请求中构造固定的虚假指数涨幅、波动率、卖单、资金流和 provider 超时，并盖上当前时间；返回 schema 也与 Events 前端所需的公司事件字段不一致。现列表与新增详情接口只读 canonical `normalized/events/corporate_events`：要求 manifest `COMPLETE`，逐分区验证 SHA-256 和 schema，再从真实 payload 生成稳定 event ID、类型、方向、标题、观测时间和 `partition#sha256` 来源引用。真实烟测验证 166 个分区并返回 3,910 条事件；forecast 上游缺失时不生成业绩预告。没有已验证事件时返回空列表，事件后收益在尚无权威计算结果时保持空数组。

## Legacy Backtest Lab 随机执行器退役

`POST /api/backtests/run` 原来等待固定秒数后随机生成 Sharpe、CAGR、最大回撤、净值、交易、基准、费用和风险归因，每次刷新都会得到不同的虚假“回测”。现随机执行器已物理删除；在 canonical universe/date/cost/OOS runner 尚未接入该 legacy 请求契约前，提交明确返回 `503 BACKTEST_ENGINE_NOT_INTEGRATED`，不创建 job、不写结果。列表响应暴露 `execution_available=false` 和 VNext 已验证产物入口 `/api/vnext/backtests`。这不是用较小实现替代回测，而是阻止未完成能力伪装为已完成。

## Live / Portfolio / Theme 辅助 API 真实性

Live Readiness 原来固定返回 QMT 正常、余额 850 万和“可以切换实盘”，run 接口等待两秒后伪造五项通过。现 run 调用真实 13 门禁并将报告原子持久化；API 额外叠加 QMT trader、confirmed positions、当日授权和三阶段 certification 四项 P0 blocker，避免旧门禁遗漏执行条件。当前真实烟测四项均失败，`overall=NOT_READY`、`live_activation_allowed=false`。

Portfolio latest 原来固定展示虚假股票、收益和 Sharpe，run 等待三秒后返回静态 15 持仓。现 latest 读取真实 VNext `portfolio_optimization.json` 的 cost-aware 权重、snapshot/hash、约束与 artifact SHA；真实烟测 4 个资产/现金权重合计 100%，不生成订单、不调用券商。legacy run 在 governed optimizer 未接请求契约前返回 503。

Theme API 原来固定 ETF 价格、主题强弱、事件、重仓、基本面和细分表现，并用正弦函数合成历史曲线。现 history 逐一验证 `semiconductor_ew/ew_a_share/semiconductor_core_ew` DataHub manifest SHA，用真实日收益生成 60 日 NAV；静态 status 返回 503，subsector 在没有 canonical 投影时返回 `MISSING + []`，不再用零值或样例冒充。

## 策略与组合信号真实性收口

`strategy-lab:build-latest-signals` 原来无论策略和行情如何，都会写入固定的中微公司、72.5 分和 `buy_watch`；`portfolio:build-lowfreq` 在没有 `--signal-file` 时又会从股票池随机生成因子，失败后继续使用内置股票清单。两条路径会把“尚未接入真实 runner”伪装为“已有投资信号”，并可能继续流入 Paper/Shadow。

固定和随机信号生成器现已物理删除。策略 latest 命令在 canonical runner 接入前明确抛出阻断且不写文件；组合命令必须显式提供经 DataHub 门禁验证的信号文件；Paper/Shadow 收到 `None` 时同样 fail-closed。此前生成的 `data/portfolio` 运行产物按数据保护要求原样保留，但不作为当前真实组合或执行输入，不能用于解锁生产门禁。

组合回测 `run` 原来默认启用 synthetic benchmark，调用方只要传入基准规格就可能在不知情时得到随机基准。默认值现改为真实 API/canonical 路径；合成基准只保留给明确传入 `synthetic_benchmark=True` 的隔离测试。真实基准失败会留下 warning 并保持基准结果为空，不再静默降级。

公开研究 CLI 还存在两层重叠分发：`factor_commands.handle` 先于 `hermes_cli.main` 的同名分支执行，导致后层整改看似生效、实际命令仍走旧路径。旧 `factor:mine` 默认截取前 500 个文件并把固定日期当作正式 universe，`factor:mine-register` 调用不存在的注册函数；策略报告、行业轮动和排名则在缺少输入时生成随机收益。现以真实执行顺序为准收紧第一层分发，因子挖掘/注册在 snapshot、universe version、forward return 和 governed candidate 接入前 fail-visible；策略报告必须提供含 `date/returns` 的 CSV；行业 CLI 在 DataHub 行业收益与版本化映射接入前阻断。重复分发本身仍需后续物理合并为单一 command registry。

相同问题还存在于可被自动调度的内置 Research Skill：`strategy-report`、`factor-mining`、`sector-rotation` 默认生成随机数据并返回 `completed`，其危险性高于人工 CLI。三个 handler 现无条件返回结构化 `BLOCKED`，即使调用方显式传 `source=demo` 或 `generate_demo=true` 也不能产出报告、候选或绩效。下一阶段需以 snapshot ID、manifest SHA、universe version 和真实收益文件契约重建 handler；在此之前宁可缺能力，不允许随机数据进入研究账本。

用户已明确退役的自动 Agent 开发系统仍可通过 `research:loop` 启动，内部候选评估生成随机 OHLCV，并可向 incoming pipeline 和 Alpha Registry 写入候选；同时 `research_loop.py` 与 `research_loop/__init__.py` 保留两份漂移实现。两个公开启动函数 `cmd_research_loop/cmd_auto_research` 现均只返回 `BLOCKED`，不会实例化循环、评估、入队或注册。专项检查同时修复包实现中未定义 `start_date` 和无效 `pd` 注解；重复历史实现保留供迁移审计，但不再有公共启动路径。

## Live Readiness 状态契约修复

`PaperTradingGate` 原来导入不存在的 `get_paper_trading_status`，因此真实 Paper 数据无论是否存在都会被误报为“模块未实现”。现新增只读状态函数：仅消费持续 Paper 的 `equity.csv`，验证 schema、日期、正权益并计算交易日、累计收益、Sharpe 和最大回撤；缺失/损坏返回 `MISSING/INVALID`，不实例化引擎、不创建空文件。真实证据为 21 个交易日，截至 2026-07-08，Paper gate 已通过。

`BenchmarkGate` 又导入不存在的 `get_benchmark`，此前只因 ImportError 降为 warning。现直接消费 `benchmarks_v4.list_benchmarks()` 提供的 canonical projection 证据，要求至少 6 个基准且每个 `available_days > 0`；真实检查六个基准全部可用，其中五个 1,335 日、ETF basket 608 日。基础 13 门禁因此由 11 pass/1 blocker/1 warning 改为 12 pass/1 blocker/0 warning；唯一 blocker 是当前受控进程未注入 Telegram 凭据。API 额外执行门禁仍因 QMT、确认持仓、当日授权和三阶段认证保持 NOT_READY。

Telegram token/chat ID 实际存在于 Windows 用户级环境，但 WSL cron 不继承；原 worker 命令也没有受控 secrets 入口。现将 Windows 用户环境中的 Telegram/企业微信三项凭据一次性桥接到 `~/.config/hermes/runtime.env`，目录权限 700、文件权限 600，文件不在仓库且测试/日志不输出值；tracked 与实际 crontab 的通知 worker 显式 `source` 该文件。基础 13 门禁真实复跑为 13 pass/0 blocker/0 warning。该 READY 只表示可申请下一阶段，API 额外四项 P0 执行门禁仍保持 `live_activation_allowed=false`，不会自动打开 QMT 实盘。

用户确认没有 MiniQMT 权限，因此真实账户/持仓/小额白名单不再作为本次必须实测项；接口、撤权、人工确认和 fail-closed 自动化仍保留，Live 永久关闭。认证脚本在 Windows 临时目录空间不足时正确失败，切换到 WSL `/tmp` 后 Stage 1 通过：半导体设备 ETF 案例的 2 点 L2、3 点减半、结构破位 10 分钟退出及事件去重均成立。Stage 2 仍诚实暴露连续 Shadow、真实盯市、配对 Paper/Shadow fill 和权益历史缺失，不通过周末临时运行或伪造产物晋级。

## 截图持仓与 QMT 账户边界

同花顺远航版银河证券窗口曾显示 8 个持仓、账户总资产 425,191.27、可用资金 210,370.07 和股票市值 214,821.20；同时弹出 Hevo 日志因 C 盘空间不足写入失败，随后应用退出。持仓已按人工转录生成只读预览 `preview_23ce2b95135847a0a07362893b9e541d`，8 个标的，`confirmed=false`、`requires_correction=true`。PositionSnapshot 新增 `source_broker/source_application/source_account` 结构化字段，明确记录银河证券/同花顺远航版/截图账户未核验；该预览绝不覆盖国金 QMT 的确认快照，也不进入执行链。国金 QMT 当前仅可看到策略研究界面，账户/持仓读取仍因无 MiniQMT 权限跳过实测。
