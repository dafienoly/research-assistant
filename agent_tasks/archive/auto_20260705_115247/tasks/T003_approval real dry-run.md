# T003 — approval real dry-run

- Version: V2.15.1
- Priority: P1
- Owner: governance_engineer
- Status: pending

## 描述

实现 approval 模块的完整干跑验证。

模块: approval/risk_approval.py
输入: order_preview.json
输出: approval_report.html, approved/blocked/2nd_confirmation 分类

需要: 加载委托预览 → 风控审批 → Kill Switch 检查 → 输出审批结论

## 验收标准

- 输出 approved/blocked/2nd_confirmation 分类
- Kill Switch 检查
- 不自动下单

## 安全边界

auto_apply=False, no_live_trade=True
