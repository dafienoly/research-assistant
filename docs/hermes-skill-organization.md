# Hermes A股投研助手 — Skill 组织规范

## 概述

本文档定义 Hermes（WSL 侧）的 Skill 组织结构、职责边界和协作关系。

## Skill 全景图

```
Hermes WSL 侧 — 数据采集层 (L0) + 数据质量层 (L1) + 盘中监测层 (L3)
┌─────────────────────────────────────────────────────────────────┐
│                    采集层 (L0)                                    │
│  market-data-fetcher    fundamental-data-fetcher                 │
│  policy-event-fetcher   announcement-parser                     │
├─────────────────────────────────────────────────────────────────┤
│                    数据质量层 (L1)                                │
│  freshness-checker      data-gap-reporter                       │
│  tag-maintainer                                                 │
├─────────────────────────────────────────────────────────────────┤
│                    盘中监测层 (L3)                                │
│  intraday-realtime-monitor    intraday-alert-deduplicator        │
│  wechat-alert-publisher       codex-escalation-gate              │
├─────────────────────────────────────────────────────────────────┤
│                    发布层                                         │
│  package-publisher                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Skill 文件位置

所有 Hermes skill 存放在 `~/.hermes/skills/` 目录，每个 skill 一个子目录：

```
~/.hermes/skills/
  market-data-fetcher/SKILL.md
  fundamental-data-fetcher/SKILL.md
  policy-event-fetcher/SKILL.md
  announcement-parser/SKILL.md
  tag-maintainer/SKILL.md
  freshness-checker/SKILL.md
  data-gap-reporter/SKILL.md
  intraday-realtime-monitor/SKILL.md
  intraday-alert-deduplicator/SKILL.md
  wechat-alert-publisher/SKILL.md
  codex-escalation-gate/SKILL.md
  package-publisher/SKILL.md
```

## Skill 职责矩阵

| Skill | L0/L1/L3 | 输入 | 输出 | 是否调用 Codex |
|--------|----------|------|------|----------------|
| market-data-fetcher | L0 | 行情源 | market/ 数据 | 否 |
| fundamental-data-fetcher | L0 | 财报源 | fundamentals/ 数据 | 否 |
| policy-event-fetcher | L0 | 新闻/政策源 | events/ 数据 | 否 |
| announcement-parser | L0 | 公告源 | announcement_events | 否 |
| tag-maintainer | L1 | 产业链映射 | tags/ CSV | 否 |
| freshness-checker | L1 | 所有数据 | 新鲜度报告 | 否 |
| data-gap-reporter | L1 | 所有数据 | 缺口报告 | 否 |
| intraday-realtime-monitor | L3 | 实时行情 | 预警事件 | 通过 escalation gate |
| intraday-alert-deduplicator | L3 | 预警事件 | 去重状态 | 否 |
| wechat-alert-publisher | L3 | 预警事件 | 企业微信推送 | 否 |
| codex-escalation-gate | L3 | 高等级事件 | codex_escalations | 写入 codex |
| package-publisher | L1 | 各 skill 输出 | 发布包 | 否 |

## 层级隔离原则

1. L0 skill **不产生**任何预警/建议，只输出原始或轻度清洗的数据
2. L1 skill **只检查**数据质量和新鲜度，不产生预警
3. L3 skill **只产生**预警/通知/风险分级，不修改 L0 数据
4. codex-escalation-gate **唯一**负责写入 codex_escalations.jsonl

## 与 Codex 的边界

| 能力 | Hermes 持有 | Codex 持有 |
|------|-------------|------------|
| 数据采集 L0 | ✅ | ❌ |
| 数据质量 L1 | ✅ | ❌ |
| 研究选股 L2 | ❌ | ✅ |
| 盘中监测 L3 | ✅ | ❌ |
| 风险解释 L3 | 事实+等级 | 深度推理 |
| 操作约束 L3-L4 | ❌ | ✅ |
| 复盘评估 L4 | ❌ | ✅ |
| 正式报告 L5 | ❌ | ✅ |
