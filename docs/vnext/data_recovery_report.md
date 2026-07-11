# Hermes VNext 数据恢复与不可变快照报告

**审计日期：** 2026-07-11（Asia/Shanghai）
**数据基准日：** 2026-07-10
**结论：** 恢复机制与不可变快照已落地并通过真实演练；全量数据健康仍为 `PARTIAL`，正式 ML、Shadow 和订单草案继续 `BLOCKED`。

## 当前真实覆盖

以 `data/universes.json` 中 U0 的 5,530 只在市股票为当前基线。2026-07-11 重新执行 `data:gap-plan`，并由 VNext 代码集合审计复核后得到：

| 数据集 | 当前数量 | 基线/目标 | 缺口 | 状态 |
|---|---:|---:|---:|---|
| 日线 K 线 | 5,738 文件 | 5,530 | 0（含历史/额外标的 208） | OK |
| 日度估值 | 5,816 文件 | 5,530 | 0（含历史/额外标的 286） | OK |
| 个股资金流 | 5,606 文件（5,401 个 U0 匹配） | 5,530 | 129（另有历史/额外标的 205） | PARTIAL |
| 财务指标 | 5,528 文件（全部匹配 U0） | 5,530 | 2 | PARTIAL |
| 概念目录 | 409 行（Tushare `ths_index`） | 380 | 0（额外 29） | OK |
| 行业目录 | 511 行（申万 2021 L1/L2/L3） | 80 | 0（额外 431） | OK |

结构审计还确认缺少 `industry_chain_tags.csv`、`semiconductor_chain_tags.csv` 和 `stock_theme_tags.csv`，三项均为 `partial`，没有被伪造内容补齐。

## 新鲜度门禁

`data:freshness-check` 与 `data:audit` 均真实执行。旧 DataHub 关键文件门禁返回 `stale` 且 `blocking=true`：

- `market/pool.csv`、`market/live_snapshot.csv`、`events/preopen_events.csv` 和 `intraday/live_snapshot_priority.csv` 超过各自阈值；
- `fundamentals/financial_snapshot.csv` 在 7 日阈值内；
- VNext 2026-07-10 日报使用的独立快照清单为 `OK`，但它不能替代系统级数据健康门禁。

因此 `artifacts/vnext/data_audit_report.json` 明确保持：

```text
formal_ml_status = BLOCKED
shadow_status = BLOCKED
order_draft_status = BLOCKED
```

## Checkpoint、幂等与批次清单

现有 `batch_daily`、`batch_fina`、`batch_valuation` 保留原调用签名和返回结构，并新增：

- 请求身份哈希形成稳定 `run_id`；
- 每只股票记录 API、请求起止日、响应行数、持久行数、最小/最大日期、内容 SHA-256、错误和输出路径；
- 每只股票完成后原子写 checkpoint 与 manifest；
- 重跑时仅在文件存在且内容哈希一致时恢复；
- 输出被改动或缺失时重新拉取；
- 新响应与已有历史按代码和业务日期合并，不截断请求区间外的有效历史；
- 限频和指数退避继续由现有 Tushare Client 负责，批次层保留 10 只/批与 1.5 秒批间隔。

真实演练使用 `688012.SH`，请求区间为 2021-01-02 至 2026-07-10：首次返回 1,327 行并持久化 1,327 行，立即重跑只做哈希验证，`resume_hits=1`，未再次请求 Provider。

2026-07-11 又按 U0 代码集合执行精确补拉，而不是按文件总数误判覆盖：

- 资金流识别 352 个当前 U0 缺失代码，223 个成功、写入 73,062 行，129 个由 Tushare 明确返回空结果，0 次请求失败；
- 财务识别 57 个缺失代码，55 个成功、写入 2,027 行，`601880.SH` 与 `688023.SH` 明确为空，0 次请求失败；
- 概念由 Tushare `ths_index` 返回 409 行，行业由 `index_classify(src=SW2021)` 的 L1/L2/L3 返回 511 行；两者均保存具名来源、`quality_status=OK`、观测时间与内容 SHA-256；
- VNext 覆盖率改为 U0 代码集合交集，历史/退市额外文件不再抵消当前缺失代码。

演练期间曾发现旧 CSV 的 `YYYYMMDD` 与新响应的 `YYYY-MM-DD` 未归一导致重复。该问题没有被隐藏：初次清单保留 `persisted_rows=2654` 且当前输出哈希验证失败；修复日期归一后再次真实拉取，文件恢复为 1,327 行，新清单哈希验证通过。这个失败记录作为恢复审计链的一部分保留。

## 不可变 Provider 快照

2026-07-10 VNext 日报已重建 Provider schema v1.1 快照：

- `data_snapshot_id = vnext-2026-07-10-3645917185de479e2cdc`；
- 29 个 Provider manifest，29 个内容哈希全部通过；
- Tushare：上证指数和 13 个 ETF/代理序列；
- Local CSV：实时全 A 快照、核心锚点与风格篮子历史；
- `silent_fallback_used=false`；
- 实时快照 `observed_at=2026-07-10T08:00:19+08:00`，不再错误使用请求发生时间；
- 聚合清单可由 manifest 路径重算出相同 `data_snapshot_id`。

旧 schema v1.0 快照没有被覆盖或篡改；v1.1 使用新的查询身份生成新目录。

## 备份与恢复演练

执行 `vnext:data-recovery-drill` 后，5 个真实文件被归档到隔离 ZIP，并恢复到 `artifacts/vnext/data_backups/restored_*`：

- 688012.SH 日线；
- 聚合快照清单；
- 数据审计报告；
- 两份真实恢复 manifest。

归档 SHA-256 为 `91806813d70cb7557320cab57aec7ca3c38b3c32370213bf13b27db51ef1bc49`，5/5 恢复文件逐一与源哈希一致。演练没有覆盖生产目录，`production_restore_performed=false`。

## 可复现命令

```bash
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py data:gap-plan
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py data:freshness-check
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py data:audit
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py report:vnext-premarket --date 2026-07-10
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py vnext:snapshot-manifest --date 2026-07-10
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py vnext:data-audit-export --date 2026-07-10
PYTHONPATH=commands .venv_quant/bin/python commands/hermes_cli.py vnext:data-recovery-drill --date 2026-07-10
```

## 未完成项

- 资金流 129 只、财务 2 只仍由当前 Tushare 接口明确无数据；需等待上游覆盖或接入具名、可审计替代源，不能创建空文件冒充补齐；
- 三份主题/产业链标签文件仍缺失；
- 旧 DataHub 实时与事件文件需由各自采集器刷新；
- 没有使用 mock、demo 或替代 Provider 把这些缺口标为成功。
