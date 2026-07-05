# Hermes V3+ Alpha Factory Roadmap

## 路线原则

V3 不再按“新增某类因子”排版本，而是按 Alpha Factory 生命周期排版本。

现有 P0/P1/P2/P3 因子方向全部挂到 V3 Alpha Factory 下面，不再继续作为 V2.x 功能堆叠。依据：

- V2.14.1 已判断 V3 为 `conditionally_ready`，必要重构包括统一 Pipeline/Gate/Audit/Report、Alpha Registry、CLI、ConfigManager、ArtifactManifest。
- V2.14.2 已抽出 AlphaSpec、AlphaRegistry、RunContext、GateEngine、AuditTrail、ArtifactManifest 等基础模块。

## 版本规划

| 版本 | 名称 | 目标 | 是否做交易 |
|------|------|------|------------|
| V3.0 | Alpha Factory Foundation | AlphaSpec、AlphaRegistry、生命周期、样例 Alpha | 否 |
| V3.0.1 | Existing Factor Catalog Migration | 把现有因子纳入 Alpha Registry | 否 |
| V3.1 | Industry Relative Alpha Pack | 行业相对、行业中性、行业内排序 | 否 |
| V3.2 | Factor Evaluation & Orthogonality | IC、ICIR、相关性、行业暴露、OOS、Walk Forward | 否 |
| V3.3 | Data Enrichment Alpha Pack | 北向、两融、资金流增强 | 否 |
| V3.4 | Technical Pattern Control Pack | MACD/KDJ/Bollinger，只做对照和冗余检测 | 否 |
| V3.5 | Event-driven Alpha Pack | 解禁、回购、分红、业绩预告 | 否 |
| V3.6 | Alpha Portfolio Intelligence | 多 Alpha 组合、淘汰、降权、晋级 | 仍先 Paper |
| V3.7 | LLM Alpha Discovery | LLM 生成 AlphaSpec，不直接写策略 | 否 |
| V4.0 | Controlled Live Alpha Pipeline | 通过 V2 治理链路后进入小权限实盘 | 人工确认 |

## Leader 派发规则

1. 先检查本地报告、Alpha Registry、factor_base 因子目录、CLI handler、测试文件。
2. 若 V3.0 CLI/Leader 治理入口不完整，优先派发 V3.0-hardening。
3. 若 Alpha Registry 数量小于现有因子目录数量，优先派发 V3.0.1。
4. V3.0.1 完成后，再进入 V3.1 行业相对 Alpha Pack。
5. V3.6 之前不进入 Paper；V4.0 之前不进入实盘。
6. 任何任务都必须默认 `no_live_trade=true`、`requires_human_approval=true`。

## CLI

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:inspect
../.venv_quant/bin/python3 hermes_cli.py leader:dispatch
../.venv_quant/bin/python3 hermes_cli.py leader:dispatch --dry-run
```

派发输出目录：

```text
/home/ly/.hermes/research-assistant/agent_tasks/<run_id>/
├── leader_inspection.json
├── leader_dispatch_plan.md
├── tasks.json
└── tasks/
    ├── T001_*.md
    ├── T002_*.md
    └── ...
```

## 安全边界

- Leader 只读检查与生成任务，不触发回测。
- 不修改 paper/live 配置。
- 不调用 broker、miniQMT 或任何下单接口。
- 不自动应用策略配置。
- 所有任务都必须可审计、可测试、可人工验收。
