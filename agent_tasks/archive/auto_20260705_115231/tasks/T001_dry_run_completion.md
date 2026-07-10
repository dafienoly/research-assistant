# T001 — dry_run_completion

- Version: V2.15.1
- Priority: P1
- Owner: governance_engineer
- Status: pending

## 描述

完成 rebalance_diff / order_preview / approval 三个模块的 real dry-run 实现。

需要依次完成:
1. rebalance_diff: 持仓加载 → 目标对比 → 调仓差异
2. order_preview: 调仓建议 → 委托预览 → 交易约束
3. approval: 委托预览 → 风控审批 → Kill Switch

## 验收标准

- rebalance_diff 完整干跑
- order_preview 完整干跑
- approval 完整干跑
- 不自动下单

## 安全边界

auto_apply=False, no_live_trade=True
