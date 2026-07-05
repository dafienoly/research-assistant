# Leader Dispatch — V2.15.1 Dry Run Completion

生成时间：2026-07-05

## 上游完成信号

Hermes 已报告：V2.15 Governed Dry Run 完成。

已通过：

- signal：真实运行，Raw:16 / Self:15 / Restricted:19
- etf_selector：真实运行，2 个主题，Top ETF 已生成
- unified_report：真实运行，状态 usable_with_warning

仍为骨架：

- rebalance_diff
- order_preview
- approval

报告目录：`/mnt/d/HermesReports/dry_run/20260705_113735/`

## Leader 阶段判断

当前阶段：**V2.15 functional_complete_partial**  
下一阶段：**V2.15.1 dry_run_completion**

结论：继续 V2.15.1。暂不进入 V3.1，也暂不进入更靠近实盘的阶段。

理由：干跑链路前半段已经真实运行，但调仓差异、委托预览、审批仍为骨架。一个完整投研系统必须先把「信号 → ETF → 统一报告 → 调仓差异 → 委托预览 → 审批」串成全链路干跑闭环，再谈 LLM Alpha Discovery 或更高阶自动化。

## 派发任务

| Task | Version | Priority | Owner | Title | Status |
|------|---------|----------|-------|-------|--------|
| T001 | V2.15.1 | P0 | dry_run_engineer | 补齐 rebalance_diff dry-run | pending |
| T002 | V2.15.1 | P0 | dry_run_engineer | 补齐 order_preview dry-run | pending |
| T003 | V2.15.1 | P0 | governance_engineer | 补齐 approval dry-run | pending |
| T004 | V2.15.1 | P0 | ci_engineer | 接入自动完成信号与下一轮 dispatch | pending |

## T001 — 补齐 rebalance_diff dry-run

目标：让 dry run 从 unified_report 输出继续生成可审计的调仓差异报告。

要求：

1. 读取 dry_run run_id 下的 unified_report / plan / signal artifacts。
2. 读取当前持仓快照；无持仓时生成 empty-position 场景，不失败。
3. 输出目标组合、当前组合、差异、限制原因、资金占用、blocked/review/tradable 分组。
4. 写入 `/mnt/d/HermesReports/dry_run/<run_id>/rebalance_diff/`。
5. 生成 manifest、audit、summary。
6. 不修改任何 paper/live 配置。
7. 不调用券商、miniQMT 或真实委托能力。

验收：

- dry_run latest run 中 rebalance_diff 状态从 skeleton 变为 real。
- 缺持仓、空持仓、持仓字段缺失均有明确状态，不 silent fallback。

## T002 — 补齐 order_preview dry-run

目标：基于 rebalance_diff 生成只读委托预览。

要求：

1. 输入来自 rebalance_diff，不直接重新算信号。
2. 输出拟买、拟卖、保持、blocked、manual_review。
3. 所有委托必须标记 shadow_only / preview_only。
4. 做 100 股整数倍、价格偏移、涨跌停、停牌、流动性、账户权限检查。
5. 写入 `/mnt/d/HermesReports/dry_run/<run_id>/order_preview/`。
6. 不产生真实委托文件，不调用任何交易接口。

验收：

- order_preview 状态从 skeleton 变为 real。
- 所有 preview order 均含 shadow_only=true。
- blocked 原因可追踪。

## T003 — 补齐 approval dry-run

目标：让 dry run 能对 order_preview 生成审批门禁结果，但不执行审批应用。

要求：

1. 输入来自 order_preview。
2. 输出 6 gate 结果：signal、etf_selector、unified_report、rebalance_diff、order_preview、approval。
3. approval 只产出 approved/review/blocker 状态，不触发应用。
4. Kill Switch、单日亏损、回撤、数据延迟、委托异常等规则仅做模拟检查。
5. 写入 `/mnt/d/HermesReports/dry_run/<run_id>/approval/`。

验收：

- approval 状态从 skeleton 变为 real。
- 任一上游模块为 blocker 时，approval 必须 blocker。
- 无人工确认时不得推进任何配置变更。

## T004 — 自动完成信号与下一轮 dispatch

目标：解决当前最大问题：Hermes 完成任务后 Leader 没自动收到，也没自动派发下一步。

要求：

1. Hermes 每次任务完成后写入统一状态文件：
   - `/home/ly/.hermes/research-assistant/agent_tasks/latest_completion.json`
2. 字段至少包括：version、stage、status、report_dir、summary、next_question、generated_at。
3. Leader 新增读取 completion 的命令或逻辑：
   - `leader:ingest-completion`
   - 或 `leader:dispatch --from-latest-completion`
4. 若 completion.status=completed 且 next_question 存在，Leader 自动生成下一阶段任务包。
5. 若 completion.status=partial，Leader 只补齐缺口任务，不跳阶段。

验收：

- V2.15 completion 被读取后，自动生成 V2.15.1 任务包。
- V2.15.1 完成后，Leader 自动判断是否进入 V2.15.2 full dry-run acceptance 或 V3.1。
- 不需要用户手动在 Hermes 与 ChatGPT 之间复制粘贴状态。

## 安全边界

- 不下单。
- 不修改生产配置。
- 不修改 paper 配置。
- 不调用券商接口。
- 不调用 miniQMT。
- 所有输出仅为 dry-run artifacts。

## 推荐执行命令

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:dispatch --from-latest-completion
```

如果该命令尚未实现，先执行 T004。