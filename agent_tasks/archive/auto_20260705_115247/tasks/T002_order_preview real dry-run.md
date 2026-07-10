# T002 — order_preview real dry-run

- Version: V2.15.1
- Priority: P1
- Owner: governance_engineer
- Status: pending

## 描述

实现 order_preview 模块的完整干跑验证。

模块: order/order_preview.py
输入: rebalance_diff.json
输出: order_preview_report.html, tradable/blocked/review 分类

需要: 从 rebalance_diff 读取 buy/sell 建议 → 生成委托预览 → 检查交易约束

## 验收标准

- 输出 tradable/blocked 分类
- 涨停买入被 blocked
- 不自动下单

## 安全边界

auto_apply=False, no_live_trade=True
