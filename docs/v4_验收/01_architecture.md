# V4 系统架构总览

> **生成时间**: 2026-07-08 23:40 CST
> **版本**: V4.12 总验收
> **项目根目录**: /home/ly/.hermes/research-assistant
> **架构审计方法**: 代码审查 / 模块依赖分析 / CLI 入口追踪 / GitNexus 知识图谱 (12718 符号, 24309 关系)

---

## 1. 总体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI 入口 (hermes_cli.py)                       │
│  market:/universe:/factor:/alpha:/portfolio:/paper:/shadow:/broker: │
└──────────────┬──────────────────────┬──────────────────┬────────────┘
               │                      │                  │
               ▼                      ▼                  ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│   数据采集层           │  │   因子与研究层         │  │   执行与风控层     │
│                      │  │                      │  │                  │
│ data_pipeline.py     │  │ factor_lab/          │  │ broker/          │
│ data_manager.py      │  │  ├ alpha/            │  │  ├ qmt_client.py │
│ data_audit.py        │  │  ├ paper/            │  │  ├ qmt_execution │
│ universes.py         │  │  ├ live/             │  │  ├ pretrade_risk │
│ benchmarks_v4.py     │  │  ├ risk/             │  │  └ order/        │
│ data_providers/      │  │  ├ core/gate.py      │  │                  │
│  ├ tushare/          │  │  ├ research_loop.py  │  │ live_readiness.py│
│  ├ baostock   [计划] │  │  ├ risk_exposure.py  │  └ kill_switch.py  │
│  └ akshare    [计划] │  │  └ reports/          │                    │
└──────────┬───────────┘  └──────────┬───────────┘  └──────────────────┘
           │                        │
           ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        数据存储层                                     │
│                                                                      │
│  data/market/  │  data/fundamentals/  │  data/tags/  │  data/audit/│
│  universes.json│  research_outputs/    │  data/events/│  data/intraday/│
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心模块及关键文件

| 模块 | 关键文件 | 行数 | 功能描述 |
|------|---------|------|---------|
| CLI 入口 | `commands/hermes_cli.py` | 2473 | 所有 CLI 命令的路由中枢 |
| 分层股票池 | `commands/universes.py` | 1192 | U0-U4 + ETF 替代池构建与审计 |
| 基准体系 | `commands/benchmarks_v4.py` | 485 | 6 个基准 (半导体等权/核心/对照/全A/可交易/ETF) |
| 因子验证 V4 | `commands/factor_lab/validate_v4.py` | 408 | V4.3 同池基准校验 + 因子晋级判定 |
| 因子评价 V4.4 | `commands/factor_lab/validate_factor_v4.py` | 807 | 换手率/成本/回撤/胜率/CAGR/Calmar + 6基准 + 风险归因 |
| 风险暴露归因 | `commands/factor_lab/risk_exposure.py` | 926 | 市值/Beta/波动率/流动性/行业/Jackknife 多维度归因 |
| Paper Trading | `commands/factor_lab/paper/standing_paper_trading.py` | 989 | 持续模拟交易引擎 (状态持久化/增量调仓/滑点模型) |
| Shadow Trading | `commands/factor_lab/paper/shadow_trading.py` | 657 | 影子交易闭环 (计划vs行情/相对基准/NOT_READY判定) |
| 实盘 Readiness | `commands/live_readiness.py` | 1151 | 13道门禁检查 → READY/NOT_READY |
| LLM Alpha 发现 | `commands/factor_lab/alpha/llm_alpha_discovery.py` | ~350 | LLM 驱动的 Alpha 假设生成与映射 |
| 因子进化 | `commands/factor_lab/evolution.py` | ~200 | LLM 生成候选因子 (价量组合) |
| 未来函数检查 | `commands/factor_lab/alpha/future_leakage_gate.py` | ~150 | 未来函数检测 |
| Alpha Schema | `commands/factor_lab/alpha/schema.py` | 60 | AlphaSpec 数据类 (完整生命周期字段) |
| 门禁引擎 | `commands/factor_lab/core/gate.py` | ~500 | GateEngine / GateCheck / GateResult |
| 数据采集 | `commands/data_pipeline.py` | ~300 | 数据拉取/更新 CLI |
| 数据审计 | `commands/data_audit.py` | ~200 | 新鲜度/覆盖率/缺口审计 |
| 前端监控 | `commands/frontend/` | TSX | React 看板（投研、运维、代码审计） |
| 辅助系统 | `commands/leader_commands.py` | — | 本地运维与确定性代码审计；自动工作循环已退役 |

---

## 3. V4 版本演进对照

| 版本 | 名称 | 当前实现状态 | 关键文件 |
|------|------|------------|---------|
| V4.0 | 数据源接入与数据仓库 | ✅ 基本实现 (Tushare 5 providers, 无 baostock/akshare) | `data_providers/tushare/` |
| V4.1 | 分层股票池 | ✅ U0-U4 + ETF, universes.json 可构建 | `commands/universes.py` |
| V4.2 | 历史数据扩展 | ⚠️ 部分: CLI 存在但数据仅约1年6只标的 | `commands/data_pipeline.py` |
| V4.3 | 基准体系与同池等权 | ✅ 6 基准 + 因子晋级判定 | `benchmarks_v4.py`, `validate_v4.py` |
| V4.4 | 因子评价与风险归因 | ✅ 换手率/成本/回撤/6基准/风险归因 | `validate_factor_v4.py`, `risk_exposure.py` |
| V4.5 | 半导体专属因子库 | ❌ 未建立: 无产业链标签因子/主题择时因子 | — |
| V4.6 | LLM Alpha Factory 升级 | ⚠️ 框架具备但 LLM 仍为价量公式生成器 | `llm_alpha_discovery.py`, `evolution.py` |
| V4.7 | 低频组合构建 | ✅ portfolio_builder 存在 | `commands/portfolio_builder.py` |
| V4.8 | Paper/Shadow Trading | ✅ 完整闭环 (模拟盘+影子交易+NOT_READY) | `paper/shadow_trading.py`, `standing_paper_trading.py` |
| V4.9 | 小资金实盘 Readiness | ✅ 13 道 Gate 检查 → READY/NOT_READY | `commands/live_readiness.py` |
| V4.10 | 事件与研报语义 | ⚠️ 事件收集存在, 研报语义未接入 | `semiconductor_events.py` |
| V4.11 | 盘中低频监控 | ⚠️ 盘中监测框架存在, 低频信号/ETF触发 | `intraday/` |
| V4.12 | V4 总验收与生产化冻结 | ✅ 本文档 | `docs/v4_验收/` |

---

## 4. 数据流

```
Tushare Pro (5 providers) ──→ data/market/  &  data/fundamentals/
                                     │
                                     ▼
                             universes.py ──→ universes.json
                                     │
                                     ▼
                         benchmarks_v4.py ──→ 6 基准日收益率
                                     │
                                     ▼
                      validate_v4.py / validate_factor_v4.py
                      (因子策略 vs 基准, 含风险归因)
                                     │
                                     ▼
                     ┌── paper/shadow_trading.py
                     │   (Paper + Shadow 模拟盘)
                     │
                     └── live_readiness.py
                         (Readiness Gate → READY/NOT_READY)
```

---

## 5. 已知限制

1. **数据覆盖严重不足**: 日 K 线仅 ~6 只标的 + 约 1 年, 非全 A
2. **LLM 因子生成偏价量**: 99% 候选因子为价量技术指标组合, 无产业链/基本面因子
3. **baostock/akshare 未接入**: 仅 Tushare 数据源, 无免费兜底
4. **无实盘下单**: broker:qmt-* 命令存在但 live_enabled 全部默认 false
5. **universes.json 未持久化**: `data/universes.json` 为空文件, 需运行时构建
6. **数据新鲜度持续 stale**: `data_freshness_report.json` 显示多个数据源过期 (live_snapshot 延迟 103335s)
7. **因子约 85% 为价量**: 142 个注册因子中仅 4 个基本面因子且 IC 为负
8. **V4.5 半导体专属因子库未建立**: 当前无产业链位置/细分方向/主题择时因子
9. **研报语义未接入**: V4.10 仅事件收集, 无研报 NLP 分析

---

## 6. CLI 命令汇总

```bash
# 股票池
python3 hermes_cli.py universe:build       # 构建 U0-U4 + ETF
python3 hermes_cli.py universe:list        # 列出所有股票池
python3 hermes_cli.py universe:audit       # 审计股票池

# 数据
python3 hermes_cli.py data:pull-daily      # 拉取日线
python3 hermes_cli.py data:freshness-check # 新鲜度检查
python3 hermes_cli.py data:gap-report      # 数据缺口

# 因子验证
python3 hermes_cli.py factor:validate      # V3 因子验证
python3 hermes_cli.py factor:validate-v4   # V4.4 增强验证 (含基准/成本/风险)
python3 hermes_cli.py factor:risk-attribution  # V4.4 风险归因

# Paper / Shadow
python3 hermes_cli.py paper:v4-run         # V4.8 Paper Trading
python3 hermes_cli.py paper:v4-dashboard   # Paper 看板
python3 hermes_cli.py shadow:v4-run        # V4.8 Shadow Trading
python3 hermes_cli.py shadow:v4-report     # Shadow 多日报告

# Live Readiness
python3 hermes_cli.py live-readiness:v4    # V4.9 实盘 Readiness (13 道 Gate)
python3 hermes_cli.py live-gate:v4-report  # Readiness 详细报告

# Alpha Factory
python3 hermes_cli.py alpha:list           # 列出 Alpha
python3 hermes_cli.py alpha:register       # 注册 Alpha
python3 hermes_cli.py alpha:retire         # 退役 Alpha

# 基准
python3 benchmarks_v4.py list              # 列出所有基准
python3 benchmarks_v4.py report semiconductor_ew  # 半导体等权报告
```
