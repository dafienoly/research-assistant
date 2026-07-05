# Hermes 投研系统开发 Roadmap

更新时间：2026-07-05

## 当前基线

已完成：

- V3.0 / V3.0.1 Alpha Factory 与既有因子迁移基础。
- V2.15.1 dry-run completion：rebalance_diff / order_preview / approval 已完成 dry-run 闭环。
- V2.15.2 自动工作循环：Leader loop、agent-runner、非 Codex 默认后端、GitHub 同步。

当前工作流：

```text
ChatGPT 规划大版本路线
→ Hermes 本地 Leader 生成阶段任务
→ Hermes agent-runner 执行 latest.json 指向的任务
→ 写 latest_completion.json
→ Leader 自动派发下一阶段
→ completed 后 GitHub 同步
```

## 核心原则

1. 先投研系统，再交易系统。
2. 先真实数据与可解释报告，再策略自动化。
3. 不接受 silent fallback；拉不到数据必须明确失败并报告原因。
4. research / dry_run / acceptance / test 可自动执行。
5. paper config / live config / broker / real execution 必须停在人工确认。
6. 每个版本完成后必须 GitHub 同步。

## 大版本路线

### V2.16 — Automation Baseline Hardening

目标：把自动工作循环从“可用”提升到“可靠”。

范围：

- 清理 ad-hoc verification 留下的 blocked 状态。
- 明确 agent-runner / leader-loop / github-sync 三者边界。
- 建立 scheduler/service 运行脚本。
- 增加状态看板：latest / completion / loop / runner / git。
- 完善失败恢复与重复执行保护。

验收：

- `leader:loop-watch --max-ticks 1` 不报错。
- `leader:agent-runner --once --backend dry-run` 不消耗模型且可写 completion。
- blocked 只在真实高风险阶段出现，不因测试残留阻断主线。
- GitHub 有 V2.16 commit。

### V2.17 — Real Data Contract & No-Fallback Data Hub

目标：建立真实数据优先的数据契约，彻底解决“页面/报告看起来能跑但其实是 demo/fallback”的问题。

范围：

- 统一 A 股日线、分钟线、实时快照、ETF、行业标签、公告/新闻数据源契约。
- Provider Matrix：akshare / baostock / eastmoney / tencent / local cache。
- 数据失败必须显式失败，报告 source、timestamp、latency、failure_reason。
- 增加 `data:freshness-check` 和 `data:provider-audit` 的门禁。

验收：

- 任何投研报告都必须带 data lineage。
- demo/fallback 数据不能进入正式报告。
- 数据不可用时前端/CLI 明确展示原因。

### V2.18 — Daily Research Pipeline

目标：形成稳定的每日盘前/盘中/盘后投研流水线。

范围：

- 盘前：昨收后新闻、政策、海外映射、A 股产业链映射、股票池影响。
- 盘中：实时异动、板块强弱、成交额、资金流、风险预警。
- 盘后：表现归因、信号兑现、错误复盘、次日观察。
- 输出 HTML/Markdown/JSON 三格式。

验收：

- 每份报告可追溯数据来源。
- 结论包含利好链条、排除理由、风险点。
- 半导体/科技主线优先覆盖，但框架可扩展。

### V3.1 — LLM Alpha Discovery, Spec Only

目标：让 LLM 生成 AlphaSpec 候选，但不直接进入交易。

范围：

- LLM 只输出 AlphaSpec。
- 必须包含假设、适用股票池、数据需求、预期失效条件。
- 禁止直接下单、禁止直接修改 live/paper config。
- 生成后进入 Alpha Registry 的 candidate/research 状态。

验收：

- 每个候选 Alpha 都可被 registry / lifecycle / evaluation hook 管理。
- 低质量、重复、不可计算、未来函数候选被拒绝。

### V3.2 — Alpha Evaluation & Anti-Overfit Gate

目标：建立 Alpha 候选的统一评估门禁。

范围：

- IC / IR / RankIC。
- Walk-forward。
- Placebo/random baseline。
- 同池等权对比。
- 正交性与因子相关性。
- 分行业/分市值/分市场环境稳定性。

验收：

- Alpha 晋级必须通过统一评分卡。
- 低于同池等权或显著过拟合的 Alpha 不得晋级。

### V3.3 — Industry Relative Alpha Pack

目标：在半导体/科技主线中加入行业相对强弱与产业链位置因子。

范围：

- 半导体设备、材料、封测、存储、PCB/CCL、光模块、服务器、EDA/IP。
- 行业内相对动量、资金流、业绩预期、公告催化。
- 产业链上游/中游/下游轮动。

验收：

- 输出 industry-relative score。
- 支持主板可买约束。
- 科创/创业板标的可作为行业温度，不进入用户不可买组合。

### V4.0 — Research-to-Paper Bridge

目标：把研究信号安全桥接到 paper trading，不触碰实盘。

范围：

- research signal → paper proposal。
- paper config 变更必须人工确认。
- paper apply 有 rollback。
- paper dashboard 评估执行质量。

验收：

- 未经人工确认不得修改 paper config。
- paper 表现达标后仍只能生成 live readiness，不直接实盘。

### V5.0 — Research UI & Control Tower

目标：解决前端不可用、不透明、无法解释失败的问题。

范围：

- 现代化投研仪表盘。
- 数据源状态、任务状态、报告状态、失败原因可视化。
- Agent run log、GitHub commit、completion、latest task 可追溯。

验收：

- 前端不再卡死且能解释失败原因。
- 每个按钮都能显示对应数据/任务/错误来源。

## 下一步推荐

立即进入：V2.16 Automation Baseline Hardening。

原因：自动化闭环刚完成，必须先固化状态、清理测试残留、建立稳定启动脚本和看板，否则后续 V2.17/V3.1 会被运行态混乱拖垮。
