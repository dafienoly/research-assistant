# A股数据输出契约

## 概述

本文档定义 Hermes 生成的所有标准数据文件的格式规范。

## 目录结构

```
/home/ly/.hermes/research-assistant/data/
  market/
    pool.csv                    -- 全 A 股票池
    daily_kline/                -- 日 K 数据（按日期/股票分片）
    minute_kline_priority/      -- 重点池分钟线
    live_snapshot.csv           -- 全 A 实时快照
    valuation_snapshot.csv      -- 估值快照
  fundamentals/
    financial_snapshot.csv      -- 财务快照
    earnings_forecast.csv       -- 业绩预告
    announcements_extracted.csv -- 公告字段提取
    report_extracts.jsonl       -- 财报原文提取
  events/
    preopen_events.csv          -- 盘前事件
    policy_events.csv           -- 政策事件
    industry_news.csv           -- 行业新闻
    exchange_notices.csv        -- 交易所公告
    announcement_events.csv     -- 公司公告事件
  tags/
    industry_chain_tags.csv     -- 产业链标签
    semiconductor_chain_tags.csv-- 半导体产业链详细标签
    cxmt_ymtc_chain.csv         -- 长鑫/长江存储产业链
    stock_theme_tags.csv        -- 主题标签
  intraday/
    events_log.jsonl            -- 所有事件日志
    intraday_digest.json        -- 盘中摘要
    codex_escalations.jsonl     -- Codex 升级事件
    risk_state.json             -- 风险状态快照
    live_snapshot_priority.csv  -- 优先池实时快照
    wechat_push_log.jsonl       -- 推送日志
    alert_state.json            -- 告警去重状态
  audit/
    data_freshness_report.json  -- 新鲜度报告
    fetch_log.jsonl             -- 采集日志
    data_gap_report.json        -- 数据缺口报告
```

## 文件格式规范

### CSV 规范
- 编码：UTF-8 with BOM（兼容 Excel 直接打开）
- 分隔符：逗号 `,`
- 字符串引号：双引号 `"`
- 表头：第一行
- 日期格式：`YYYY-MM-DD`
- 时间格式：`YYYY-MM-DDTHH:mm:ss+08:00`

### JSONL 规范
- 每行一个完整 JSON 对象
- 无外层数组包裹
- 尾行必须有换行符

### JSON 规范
- UTF-8 编码
- 2 空格缩进
- 必须包含 `last_updated` 顶层字段（时间格式同上）

## 关键字段定义

### pool.csv
```
code,name,sector,sub_sector,list_date,market,is_st,is_北交所
```

### live_snapshot.csv
```
code,name,price,change_pct,volume,turnover,amplitude,turnover_rate,pe_ttm,pb,update_time,data_stale
```

### financial_snapshot.csv
```
code,name,report_date,revenue,revenue_yoy,net_profit,net_profit_yoy,roe,gross_margin,debt_ratio,pe_ttm,pb,market_cap,data_date
```

### preopen_events.csv
```
event_id,source,title,content,related_symbols,sectors,publish_time,impact_level,data_source
```

### codex_escalations.jsonl
```json
{
  "event_id": "esc_20260702_104230_001",
  "created_at": "2026-07-02T10:42:30+08:00",
  "level": "L3",
  "alert_type": "position_drop_5pct",
  "symbol": "600XXX",
  "name": "XX公司",
  "sector": "semiconductor",
  "price": 45.20,
  "change_pct": -5.3,
  "trigger_rule": "持仓股跌幅>5%",
  "data_freshness_seconds": 15,
  "reason": "持仓股跌幅超过5%，风险等级high",
  "suggested_action": "建议 Codex 复核是否需要调整",
  "force_judgment_blocked": false
}
```

## 数据新鲜度标注

所有实时数据必须标注 `data_stale` 字段：

| 数据延迟 | data_stale | 影响 |
|----------|------------|------|
| < 30s | false | 正常使用 |
| 30-60s | "warning" | 谨慎使用 |
| > 60s | true | 禁止强判断 |

`force_judgment_blocked: true` 的字段将阻断 Codex 进行任何操作建议。
