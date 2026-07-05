# Hermes Product Roadmap V3-V9 — Leader Fixed Plan

> 本路线图由 Leader 固定。Hermes 不得自行重排大版本、不准把所有 V2/V3 安全任务回退到固定 dry_run_completion，也不得因为没有用户传话而停止安全研发自动化。

## 总原则

1. 用户只提出目标和约束，不再承担版本规划和任务搬运。
2. Hermes 只执行本路线图、自动拆任务、自动开发、自动测试、自动验收、自动提交。
3. 自动化允许范围：代码开发、测试、文档、报告、数据质量检查、回测 dry-run、paper trading、mock/sandbox broker、UI、AgentOps、任务队列、Git commit。
4. 自动化禁止范围：真实下单、真实资金、broker live、capital、real_execution、绕过人工确认、fallback 假数据冒充真实数据。
5. 所有版本必须有 manifest、audit、acceptance report、test report、git commit。
6. dry-run backend 不能把代码开发任务标记 completed；真实开发必须有 coding backend。

## V3.x — Alpha Factory / Alpha Research System

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V3.0 | Alpha Factory Foundation | 建立 AlphaSpec、AlphaRegistry、Lifecycle、CLI、样例 Alpha | yes | no live/no broker |
| V3.0.1 | Existing Factor Catalog Migration | 迁移现有因子到 Alpha Registry，形成可治理目录 | yes | migration acceptance |
| V3.1 | Industry Relative Alpha Pack | 行业相对、行业中性、行业内排序 Alpha | yes | registry disabled by default |
| V3.2 | Factor Evaluation & Orthogonality | IC/ICIR、OOS、Walk Forward、相关性、行业暴露门禁 | yes | gate report |
| V3.3 | Data Enrichment Alpha Pack | 北向、两融、资金流等增强数据 Alpha | yes | freshness/coverage gate |
| V3.4 | Technical Pattern Control Pack | MACD/KDJ/Boll 等只作 control/baseline/redundancy | yes | incremental value report |
| V3.5 | Event-driven Alpha Pack | 解禁、回购、分红、业绩预告等事件 Alpha | yes | event date separation |
| V3.6 | Alpha Portfolio Intelligence | 多 Alpha 组合、降权、淘汰、paper 组合治理 | yes | paper only |
| V3.7 | LLM Alpha Discovery | LLM 只生成 AlphaSpec 候选，不直接改策略配置 | yes | review queue |
| V3.8 | Alpha Review Queue & Governance | 候选 Alpha 审核、证据、风险、拒绝原因治理 | yes | human review optional |
| V3.9 | Alpha Promotion / Retirement Engine | Alpha 晋级、降权、退役、回滚治理 | yes | no live auto |

## V4.x — Controlled Execution Governance

V4 允许自动开发治理系统，但不允许自动实盘。所有 live/broker/capital/real_execution 必须 manual_required。

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V4.0 | Controlled Live Pipeline Design | 受控实盘管线设计，不执行实盘 | yes | manual live gate |
| V4.1 | Shadow Live Pipeline | 影子实盘/模拟实盘，不下单 | yes | shadow only |
| V4.2 | Broker Adapter Contract & Sandbox | broker 合约和 sandbox adapter | yes | sandbox only |
| V4.3 | Order Preview / Rebalance Diff / Approval Center | 订单预览、调仓差异、审批中心 | yes | human approval |
| V4.4 | Kill Switch / Risk Sentinel | 熔断、风险哨兵、紧急停止 | yes | no live action |
| V4.5 | Human Approval Workflow | 企业微信/本地 UI 审批工作流 | yes | explicit confirm |
| V4.6 | Live Audit / Rollback / Incident Report | 审计、回滚、事故报告 | yes | audit complete |
| V4.7 | MiniQMT Adapter Hardening | miniQMT 适配器加固，禁止真实下单 | yes | mock/sandbox only |
| V4.8 | Capital Safety Boundary | 资金安全边界、额度、权限、异常保护 | yes | capital manual gate |
| V4.9 | Controlled Live Readiness Report | 实盘就绪报告，只输出报告 | yes | manual_required stop |

## V5.x — Data Platform & Real Market Data

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V5.0 | Data Source Registry | 数据源注册表、优先级、能力矩阵 | yes | no fallback contract |
| V5.1 | AkShare / BaoStock / Tencent Provider Layer | 免费 A 股数据源 Provider 层 | yes | provider tests |
| V5.2 | Realtime Quote Ingest | 实时行情 ingest | yes | freshness gate |
| V5.3 | Minute / Daily Bar Storage | 分钟线、日线统一存储 | yes | schema contract |
| V5.4 | Data Quality Gate | freshness、coverage、missing、延迟门禁 | yes | fail closed |
| V5.5 | No-Fallback Data Contract | 禁止 demo/fallback 冒充真实数据 | yes | visible failure |
| V5.6 | Data Lineage / Manifest / Audit | 数据血缘、manifest、audit | yes | reproducibility |
| V5.7 | Market Calendar / Trading Session Engine | 交易日历、交易时段、节假日 | yes | calendar tests |
| V5.8 | Data Health Dashboard | 数据健康可视化 | yes | UI status |
| V5.9 | Paid Provider Readiness | 付费数据源适配预留 | yes | adapter only |

## V6.x — Research Automation & Strategy Factory

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V6.0 | Research Skill Runtime | 投研 skill 运行时 | yes | no trade |
| V6.1 | Strategy Template Registry | 策略模板注册表 | yes | disabled by default |
| V6.2 | Backtest Engine Integration | 回测引擎接入 | yes | no future leakage |
| V6.3 | Walk Forward / OOS / Anti-overfit Gate | 反过拟合门禁 | yes | OOS required |
| V6.4 | Portfolio Backtest / Benchmark Compare | 组合回测、基准比较 | yes | benchmark report |
| V6.5 | Strategy Report Generator | 策略报告生成器 | yes | report manifest |
| V6.6 | Factor Mining Agent | 因子挖掘 Agent | yes | gate before registry |
| V6.7 | News / Policy / Event Research Agent | 新闻、政策、事件研究 Agent | yes | evidence required |
| V6.8 | A-share Sector Rotation Engine | A 股行业轮动研究 | yes | paper only |
| V6.9 | Strategy Promotion Board | 策略晋级看板 | yes | no live auto |

## V7.x — Product UI / Ops / Control Tower

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V7.0 | Modern Frontend Dashboard | 现代化前端总览 | yes | live data status visible |
| V7.1 | Data Status / Provider Failure UI | 数据失败明确展示，禁止静默 fallback | yes | visible error |
| V7.2 | AgentOps Control Tower | AgentOps 控制塔 | yes | run trace |
| V7.3 | Task Queue / Run History / Logs | 任务队列、运行历史、日志 | yes | audit trail |
| V7.4 | Roadmap Progress UI | 路线图进度 UI | yes | cursor sync |
| V7.5 | Report Center | 报告中心 | yes | artifact links |
| V7.6 | Risk Dashboard | 风险仪表盘 | yes | no live trade |
| V7.7 | Paper Trading Dashboard | 纸面交易仪表盘 | yes | paper only |
| V7.8 | User Feedback / Task Intake UI | 用户反馈和任务入口 UI | yes | intake tests |
| V7.9 | One-click Local Ops | 本地一键运维 | yes | safe commands only |

## V8.x — Multi-Agent Engineering System

| Version | Name | Objective | Auto | Gate |
|---|---|---|---|---|
| V8.0 | Agent Role Registry | PM/架构/开发/测试/审计角色注册 | yes | role contract |
| V8.1 | Agent Router | 多 Agent 路由和 fallback policy | yes | no fake complete |
| V8.2 | Auto Bugfix Loop | 自动 bugfix 循环 | yes | regression tests |
| V8.3 | Regression Test Planner | 回归测试规划器 | yes | coverage report |
| V8.4 | GitHub Issue / PR Pipeline | GitHub Issue/PR 流水线 | yes | protected branch |
| V8.5 | Documentation Generator | 文档生成器 | yes | docs updated |
| V8.6 | Release Manager | release note、版本标记、发布检查 | yes | acceptance pass |
| V8.7 | Self-Diagnostics | 自诊断和修复建议 | yes | health report |
| V8.8 | Cost / Token / Backend Policy | 成本、token、backend 策略 | yes | budget policy |
| V8.9 | Continuous Improvement Engine | 持续改进引擎 | yes | no unsafe auto |

## V9.x — Future Backlog

V9 作为后续 backlog，不要求当前自动完成，但必须可被 task intake 路由。

- V9.0 Cloud / Local Hybrid Runner
- V9.1 Distributed Backtest
- V9.2 Multi-account Governance
- V9.3 External Notification Center
- V9.4 Enterprise-grade Audit

## 自动执行策略

1. 默认自动推进 V3.0-V8.9 的安全研发任务。
2. V4.x 只开发治理系统，不进行真实交易。
3. V4.9 后进入真实资金或实盘 readiness 时必须 manual_required。
4. 用户新增任务必须进入 task_intake，不得要求用户手动搬运到 latest.json。
5. Hermes 不得自行改变本路线图顺序。如发现当前实现与本路线图冲突，应生成 remediation，而不是重排版本。
