# 每日投研 SOP

## 概述

本文档定义 Hermes 每日从盘前准备到盘后发布的完整标准化操作流程。

## 时间线

```
【盘前】
08:30 ─── policy:update-events
           → 抓取昨夜至今早的政策、行业新闻
           → 生成 preopen_events.csv

09:00 ─── announcements:parse
           → 抓取当日公告
           → 提取结构化字段

09:15 ─── data:freshness-check
           → 检查所有数据是否就绪
           → 输出 data_freshness_report.json

09:20 ─── intraday:prepare
           → 读取 positions / recommendation_history / candidates / watchlist
           → 初始化 alert_state.json
           → 重置 Codex 升级预算
           → 初始化盘中监控状态
           → 输出 preopen_events package

【开盘 - 09:30】
09:25 ─── 就绪确认
           → 确认所有数据源可用
           → 确认 live_snapshot 首次可用

09:30-09:35 ─── 开盘冲击观察期
           → 只观察，不输出强操作建议
           → 记录 opening_spike 事件（L0 silent_log）

【上午盘中 - 09:35-11:30】
09:35 ─── intraday:watch 启动 (30-60s 循环)
           → 每 tick 执行：
             1. 读取 live_snapshot (P0-P5)
             2. 运行规则引擎
             3. 事件分类 L0-L4
             4. 去重冷却检查
             5. 写入 events_log.jsonl
             6. L2 推送企业微信
             7. L3/L4 升级 Codex（通过 gate）
             8. 更新 alert_state.json

10:00 ─── 盘中摘要推送（可选）
           → 汇总过去 30min 关键事件
           → wechat_digest 推送

11:00 ─── 午盘前摘要
           → intraday_digest.json 更新
           → 午盘前风险汇总

【午休 - 11:30-13:00】
11:30 ─── intraday:stop
           → 暂停高频监测
           → 保存中间状态
           → 可选：发布午盘摘要 package

12:00 ─── 数据维护窗口
           → 检查数据缺口
           → data:gap-report（如需要）
           → 非紧急数据刷新

【下午盘中 - 13:00-14:55】
13:00 ─── intraday:watch 重新启动
           → 恢复 30-60s 循环
           → 重置下午升级预算
           → 同上下午流程

14:00 ─── 盘中摘要推送（可选）

14:30 ─── 尾盘前风险扫描
           → 重点关注持仓股风险
           → 降级类事件关注

【尾盘限制 - 14:55-15:00】
14:55 ─── 禁止新开仓类 alert
           → 仅保留：
             - 风险/减仓类 alert（L2+）
             - 数据异常类 alert（L0-L1）
           → 所有新开仓信号自动降级为 L1 或丢弃

【收盘 - 15:00+】
15:00 ─── 收盘汇总
           → 最终 intraday_digest.json
           → 最终 risk_state.json
           → 输出 intraday_alerts package（最终版）

15:05 ─── intraday:stop
           → 停止监测
           → 发布 intraday summary package

15:30 ─── market:update-daily
           → 更新全 A 日 K
           → 更新估值快照
           → 发布 market_daily package

16:00 ─── fundamentals:update
           → 更新基本面数据（如有当日财报）
           → 发布 fundamentals_daily package

17:00 ─── tags:update（按需）
           → 产业链标签维护
           → 发布 tags_update package

18:00 ─── 日终审计
           → data:freshness-check
           → data:gap-report
           → 发布 audit_report package

【盘后 - Codex 工作时段】
Codex 在 Windows 侧处理 L2 研究、复盘、报告
Hermes 只提供数据包和审计报告
```

## 盘中 check-once 伪代码

```python
def check_once():
    # 1. 读取实时数据
    snapshot = read_live_snapshot()
    positions = read_positions()
    candidates = read_today_candidates()
    watchlist = read_watchlist()
    alert_state = load_alert_state()

    # 2. 检查数据新鲜度
    if snapshot_stale(snapshot):
        log_event(L0, "data_stale")
        return  # 数据延迟，跳过规则判定

    # 3. 运行规则引擎
    events = []
    for stock in positions + candidates + watchlist:
        for rule in RULES:
            if rule.matches(stock, snapshot):
                events.append(rule.create_event())

    # 4. 去重冷却
    events = deduplicate(events, alert_state)

    # 5. 分类分级
    for event in events:
        event.level = classify(event)
        event.channel = route(event.level)

    # 6. 写入日志
    append_events_log(events)

    # 7. 推送
    for event in events:
        if event.channel in ["wechat_notice", "wechat_urgent"]:
            push_wechat(event)

    # 8. 升级 Codex
    for event in events:
        if event.level in ["L3", "L4"]:
            if escalation_gate.check(event):
                append_codex_escalations(event)
                escalation_gate.consume_budget(event)

    # 9. 更新状态
    save_alert_state(alert_state)
```

## 异常处理

| 异常 | 处理 |
|------|------|
| 行情数据全部缺失 | 发出 L0 日志，阻止所有预警输出 |
| 部分股票数据缺失 | 标记缺失股票，其他正常处理 |
| 企业微信 webhook 不可达 | 降级为 dry-run 模式，重试 3 次 |
| Codex 目录不可写 | 在 WSL 侧缓存，标记 pending |
| 规则引擎异常 | 跳过本轮，记录 error 到 fetch_log |
