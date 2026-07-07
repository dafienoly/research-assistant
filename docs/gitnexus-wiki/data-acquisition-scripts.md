# Data Acquisition — scripts

# `mx_fetch_step.py` — 步进式数据采集

## 概述

`mx_fetch_step.py` 是 Hermes Research Assistant 的数据采集入口之一，通过 [mx:data](https://muxidata.com) API 以**增量步进**方式拉取三类关键市场数据：**两融（融资融券）**、**北向资金流向**和**公司事件**（限售解禁、分红、回购）。

每日每表仅拉取约 20 只股票，逐日推进，直至覆盖全部关注池（约 310 只）。这种步进策略避免了对 API 的单次大压力，也适合每日运行作为持续补全机制。

## 执行方式

```bash
cd /home/ly/.hermes/research-assistant/commands
source /home/ly/.hermes/research-assistant/.venv_quant/bin/activate
python3 /home/ly/.hermes/research-assistant/scripts/mx_fetch_step.py
```

## 整体架构

```
  strategy_lab.universe.build()
           │
           ▼
  get_pool()         ─── 关注池 ~310 只股票
           │
           ▼
  TABLE_DEFS  ─── 三张表的配置：margin / north_flow / events
           │
           ▼
  fetch_table()
      ├─ get_existing()   ─── 检查 CSV 已有数据
      ├─ 分批查询 mx:data  ─── 每批 5 只，每日 20 只
      ├─ subprocess.run(mx_data.py)
      ├─ find_json()       ─── 定位输出文件
      ├─ parser()          ─── 解析 JSON → list[dict]
      └─ 合并写入 CSV
```

每个 `TABLE_DEF` 对应一张 CSV 文件和一套解析逻辑，`main()` 串行调度三表，最后输出覆盖率报告。

## 关键函数

### `get_pool() → list[str]`

从 `strategy_lab.universe.build()` 获取关注池。合并两个子池：

- **`manual_watchlist`**：手动维护的重点关注列表
- **`today_candidates`**：基于策略筛选的当日候选股

去重后返回排序的股票代码列表。

### `get_existing(path) → set[str]`

读取 CSV 文件的 `symbol` 列，返回已覆盖的股票代码集合。用于决定哪些股票需要本轮补齐。CSV 编码为 `utf-8-sig`。

### `fetch_table(defn) → int`

核心拉取循环。对每个 `TABLE_DEF`：

1. 计算缺失股票（`pool - existing`）
2. 取前 `limit` 只（默认 20）作为本轮批次
3. 按 `BATCH = 5` 分组，每组发起一次 `subprocess.run`，调用 `mx_data.py` 查询
4. 调用对应的 parser 解析返回的 JSON
5. 合并新旧数据后写回 CSV

每次 API 调用间隔 2 秒，避免频率限制。

### `parse_margin(json_path) → list[dict]`

解析两融数据。输入 JSON 的典型结构：

```json
{
  "data": {"data": {"searchDataResultDTO": {
    "entityTagDTOList": [...],
    "dataTableDTOList": [
      {
        "nameMap": {"0": "融资买入额", "1": "融资偿还额", ...},
        "rawTable": {"headName": ["2026-07-06", "2026-07-03", ...], "0": [...], "1": [...]},
        "entityTagDTO": {"secuCode": "000001"}
      }
    ]
  }}}
}
```

根据 `nameMap` 中的关键字（"融资买入额"、"融资偿还额"、"融资余额"等）找到对应数据列的 key，然后按日期索引逐行抽取。

返回字段：

| 字段 | 说明 |
|------|------|
| `symbol` | 股票代码 |
| `date` | 交易日（YYYYMMDD） |
| `margin_buy` | 融资买入额（元） |
| `margin_repay` | 融资偿还额（元） |
| `margin_balance` | 融资余额（元） |
| `margin_ratio` | 融资余额占比（暂未填充） |
| `sec_lending_volume` | 融券卖出量（股） |
| `sec_lending_balance` | 融券余额（元） |

### `parse_north_flow(json_path) → list[dict]`

解析北向资金流向数据。处理两种 JSON 布局：

- **标准格式**：`headName` 为日期列表，`rawTable` key 为指标编码，通过 `nameMap` 找到"主力净流入"列
- **转置格式（transposed）**：`headName` 为指标列表（如 `["涨跌幅(%)", "成交额(万元)", "主力净流入金额(万元)"]`），`nameMap` key 为日期。检测依据是 3 个以上的 nameMap 值匹配 `YYYY-MM-DD` 格式

转置格式的处理是此函数中最复杂的逻辑，核心思路是先找到"主力净流入"在 `headName` 中的索引位置，再遍历每个日期 key 取出对应位置的值。

返回字段：

| 字段 | 说明 |
|------|------|
| `symbol` | 股票代码 |
| `date` | 交易日 |
| `nb_net_flow` | 主力资金净流入（元） |
| `nb_total_buy` | 买入总额（暂未填充） |
| `nb_total_sell` | 卖出总额（暂未填充） |
| `nb_holding_value` | 持股市值（暂未填充） |
| `nb_holding_ratio` | 持股比例（暂未填充） |

当前仅使用 `nb_net_flow`，其余字段保留为 0 作为扩展预留。

### `parse_events(json_path) → list[dict]`

解析公司事件数据，支持三种事件类型：

- **`share_unlock`（限售解禁）**：识别 `nameMap` 中包含"解禁"、"限售"等关键字。提取解禁股数和占流通 A 股比例，`impact_score = 0.3`
- **`dividend`（分红）**：识别"分红"、"股利"、"股息"。从 `headName` 中提取报告期（如 "2025年度分配" → 2025-12-31），并查找"每股股利"列。`impact_score = 0.2`
- **`share_buyback`（回购）**：识别"回购"。提取回购数量和均价。`impact_score = 0.5`

每种事件的 `headName` 和 `rawTable` 布局差异很大，解析器通过 `nameMap` 值的关键字匹配来判断事件类型并选择对应的解析策略。

### 工具函数

| 函数 | 作用 |
|------|------|
| `parse_amount(val) → float` | 解析可能带单位的金额字符串。"亿元"/"亿"→ ×1e8，"万元"/"万"→ ×1e4，纯数字直接转换 |
| `parse_date(d) → str` | 统一日期格式为 `YYYYMMDD`。支持 `YYYY-MM-DD` 和 `YYYYMMDD` 两种输入 |
| `find_json(out_dir) → str` | 在 mx:data 的输出目录中查找 `_raw.json` 文件 |
| `log(msg)` | 带 `HH:MM:SS` 时间戳的标准输出日志 |

## 数据文件

三张 CSV 文件位于 `data/` 目录下：

| 标签 | 文件 | 每行包含 |
|------|------|----------|
| 两融 | `margin_timeseries.csv` | symbol, date, margin_buy, margin_repay, margin_balance, margin_ratio, sec_lending_volume, sec_lending_balance |
| 北向 | `north_flow_timeseries.csv` | symbol, date, nb_net_flow, nb_total_buy, nb_total_sell, nb_holding_value, nb_holding_ratio |
| 事件 | `event_timeseries.csv` | symbol, date, event_type, event_desc, impact_score |

写入时采用**全量合并**策略：读入旧数据 → 追加新数据 → 全部写回。CSV 编码为 `utf-8-sig`，带 BOM。

## 增量逻辑

```
关注池: 310 只
          │
          ▼
检查已覆盖: 200 只  ─── 跳过
          │
          ▼
待补: 110 只
          │
          ▼
本轮拉取: 前 20 只
          │
          ▼
每批 5 只 → 4 次 API 调用 → 解析 → 写入 CSV
```

这种设计适合每日运行的定时任务：每日跑一次，每表补 20 只，大约 5–6 天即可完整覆盖全部关注池。首次运行后，后续每次仅处理新增股票。

## 与代码库的衔接

- **上游依赖**：`strategy_lab.universe.build()` — Hermes 策略实验室的股票池引擎，通过 `commands/` 目录的 Python path 引入
- **API 调用**：通过 `subprocess.run` 调起 `.hermes/skills/mx-data/mx_data.py`，这是 mx:data 的 CLI 封装，接收查询字符串和输出目录参数
- **下游消费**：生成的 CSV 由 Hermes 因子实验室和策略回测模块读取，作为 alpha 因子计算的输入数据源
  - `margin_timeseries.csv` 用于计算融资情绪类因子（杠杆变化率、融资买入强度等）
  - `north_flow_timeseries.csv` 用于计算外资流向类因子（资金流强度、持仓比例变化等）
  - `event_timeseries.csv` 用于事件驱动策略的触发判断

## 注意事项

- **API Key**：硬编码在模块底部的 `APIKEY` 常量中（`mkt_pWU9CKf9B...`），生产环境应考虑环境变量传入
- **超时处理**：每组查询有 30 秒超时窗口，超时直接跳过该批次，不影响后续股票
- **容错**：JSON 解析失败时返回空列表，不会导致整个任务中断
- **幂等性**：基于 `get_existing()` 的增量检查保证重复运行安全的——已覆盖的股票不会重复查询，仅追加尚未拉取过的数据