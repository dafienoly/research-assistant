# T001 — rebalance_diff real dry-run

- Version: V2.15.1
- Priority: P1
- Owner: governance_engineer
- Status: pending

## 描述

实现 rebalance_diff 模块的完整干跑验证。

模块: portfolio/rebalance_diff.py
输入: unified_premarket_report.json + current_positions.csv
输出: rebalance_diff_report.html, hold/sell/buy/skip 分类

需要: 加载持仓 → 对比目标组合 → 生成调仓差异报告

## 验收标准

- 能读取 current_positions.csv
- 输出 hold/sell/buy 分类
- 不自动下单
- 报告可查看

## 安全边界

auto_apply=False, no_live_trade=True
