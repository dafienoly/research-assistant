# 用户手册

> **生成时间**: 2026-07-08 23:42 CST
> **项目根目录**: `/home/ly/.hermes/research-assistant`
> **CLI 入口**: `commands/hermes_cli.py` (2506 行)
> **版本**: V4.12 总验收
> **作用域**: V4 所有 CLI 命令 / 数据文件目录 / 使用示例

---

## 1. 系统概览

Hermes A 股投研助手是一个基于 CLI 的量化投研系统, 覆盖从数据采集、股票池构建、因子验证到模拟交易的门禁检查全链路。

```text
项目根目录: /home/ly/.hermes/research-assistant/
├── commands/                    # 所有可执行代码
│   ├── hermes_cli.py           # CLI 入口 (py3 hermes_cli.py <cmd>)
│   ├── config.py               # 全局配置
│   ├── universes.py            # 分层股票池 (U0-U4 + ETF)
│   ├── benchmarks_v4.py        # 基准体系 (6 基准)
│   ├── portfolio_builder.py    # 低频组合构建
│   ├── live_readiness.py       # 小资金实盘 Readiness (13 Gate)
│   ├── data_pipeline.py        # 数据采集管道
│   ├── data_audit.py           # 数据审计
│   ├── factor_commands.py      # 因子系统 CLI 路由
│   ├── leader_commands.py      # Leader 自动工作循环 CLI
│   ├── market_fetcher.py       # 行情采集
│   ├── factor_lab/             # 因子研究核心库
│   │   ├── paper/              # Paper/Shadow Trading
│   │   ├── alpha/              # Alpha Factory
│   │   ├── broker/             # QMT 券商对接
│   │   ├── risk/               # 风控引擎
│   │   ├── core/               # GateEngine / 核心工具
│   │   ├── validate_v4.py      # V4.3 同池基准校验
│   │   ├── validate_factor_v4.py # V4.4 增强因子评价
│   │   └── evolution.py        # LLM 因子进化
│   └── strategy_lab/           # 策略实验室
├── data/                       # 数据存储 (HermesData)
│   ├── market/                 # 行情数据
│   ├── fundamentals/           # 基本面数据
│   ├── tags/                   # 标签数据
│   ├── positions/              # 持仓数据
│   ├── audit/                  # 审计日志
│   └── ...                     # 其余子目录
└── docs/                       # 文档
    └── v4_验收/                # V4 验收文档
```

---

## 2. CLI 命令参考

所有命令通过以下方式运行:
```bash
cd /home/ly/.hermes/research-assistant/commands
python3 hermes_cli.py <命令> [参数]
```

### 2.1 行情类 (数据采集)

| 命令 | 说明 | 参数 |
|------|------|------|
| `market:update-daily` | 更新全 A 日 K | — |
| `market:update-live-snapshot` | 更新实时快照 | — |
| `data:pull-daily --start DATE --end DATE` | 全A日线批量拉取 (V4.2) | `--start YYYYMMDD`, `--end YYYYMMDD` |
| `data:pull-fina --start DATE --end DATE` | 全A财务指标批量拉取 (V4.2) | 同上 |
| `data:pull-valuation --start DATE --end DATE` | 全A估值数据批量拉取 (V4.2) | 同上 |
| `data:coverage` | 数据覆盖率报告 (V4.2) | — |
| `data:survivorship` | 生存偏差检查报告 (V4.2) | — |
| `data:freshness-check` | 检查数据新鲜度 | — |
| `data:gap-report` | 报告数据缺口 | — |
| `data:hub-rebuild [target]` | 补齐因子引擎时序数据 | target: fundamentals/fund-flow/sentiment/all |

### 2.2 股票池类 (V4.1)

| 命令 | 说明 | 参数 |
|------|------|------|
| `universe:build` | 构建全部 U0-U4 + ETF 池 | — |
| `universe:list` | 列出所有股票池 | — |
| `universe:show <池名>` | 查看指定池 (U0/U1/.../ETF) | — |
| `universe:audit` | 审计所有股票池纯度 | — |

### 2.3 因子验证类 (V4.3 / V4.4)

| 命令 | 说明 | 参数 |
|------|------|------|
| `factor:list [分类]` | 列出所有因子 | — |
| `factor:validate --factor <名>` | 单因子 V3 稳健性验证 | `--factor ret5`, `--start`, `--end`, `--rebalance` |
| `factor:validate-v4 --factor <名>` | V4.4 增强验证 (含基准/成本/风险) | 同上 + `--top-quantile` |
| `factor:risk-attribution --factor <名>` | V4.4 风险暴露归因 | 同上 |
| `factor:batch --factors <列表>` | 批量因子验证 → HTML/CSV/JSON | `--factors ret5,vol_ratio60` |
| `factor:composites --candidate-pool PATH` | 多因子组合验证 | `--methods equal_weight_score,...` |
| `factor:orthogonality --factors <列表>` | 因子正交性扩展 | — |
| `factor:strategies` | ret5 + 过滤器策略层验证 | `--start`, `--end`, `--top-n` |

### 2.4 信号与盘前决策类 (V1.x)

| 命令 | 说明 | 参数 |
|------|------|------|
| `factor:signal --signal-date latest` | ret5_ma20_gate 盘前信号 | `--signal-date`, `--top-n` |
| `factor:etf-selector` | ETF 替代暴露筛选 | `--from-live-signal`, `--capital` |
| `factor:premarket` | Unified 盘前决策报告 | `--capital`, `--signal-date` |
| `factor:daily-premarket` | 每日盘前编排 | `--date`, `--capital`, `--no-notify` |
| `factor:decision-log` | 人工决策记录 | `--date`, `--plan`, `--action`, `--confirm` |

### 2.5 组合构建类 (V4.7)

| 命令 | 说明 | 参数 |
|------|------|------|
| `portfolio:build-lowfreq` | V4.7 低频组合构建 | `--signal-file`, `--signal-date` |
| `portfolio:recommend` | 查看最新组合推荐 | — |
| `portfolio:risk` | 查看组合风险暴露 | — |
| `premarket:v4` | V4 盘前组合建议 (同 build-lowfreq) | — |

### 2.6 Paper / Shadow Trading (V4.8)

| 命令 | 说明 | 参数 |
|------|------|------|
| `paper:v4-run` | V4.8 Paper Trading 运行 | `--date`, `--capital`, `--top-n` |
| `paper:v4-dashboard` | Paper Trading 看板 | — |
| `shadow:v4-run` | V4.8 Shadow Trading 运行 | `--date`, `--capital`, `--top-n` |
| `shadow:v4-report` | Shadow Trading 多日报告 | — |

### 2.7 实盘 Readiness (V4.9)

| 命令 | 说明 | 参数 |
|------|------|------|
| `live-readiness:v4` | V4.9 13 道门禁检查 | `--strict` |
| `live-gate:v4-report` | 详细报告 (含证据+修复建议) | — |

### 2.8 Broker / QMT 对接

| 命令 | 说明 |
|------|------|
| `broker:miniqmt-status` | 检查 miniQMT 只读持仓状态 |
| `broker:qmt-health` | 检查 Windows QMT Bridge 状态 |
| `broker:qmt-account` | 拉取 QMT 账户资金 |
| `broker:qmt-positions` | 拉取 QMT 持仓 |
| `broker:qmt-orders` | 拉取 QMT 委托 |
| `broker:qmt-trades` | 拉取 QMT 成交 |
| `broker:qmt-sync` | 同步 QMT 全部数据 |
| `broker:qmt-place-approved` | 从已审批订单发起 QMT 委托 |
| `broker:qmt-cancel` | 撤销 QMT 委托 |
| `broker:qmt-internal-health` | 大 QMT 内置 HTTP 执行器状态 |
| `broker:qmt-internal-place-approved` | 大 QMT 内置委托 |
| `broker:qmt-internal-sync` | 大 QMT 内置同步 |
| `broker:qmt-internal-disable-live` | 关闭大 QMT 实盘开关 |

### 2.9 Alpha Factory (V3.0)

| 命令 | 说明 |
|------|------|
| `alpha:list` | 列出已注册 Alpha |
| `alpha:show --alpha-id <id>` | 查看 Alpha 详情 |
| `alpha:register --spec <path>` | 注册外部 AlphaSpec |
| `alpha:retire --alpha-id <id>` | 退役 Alpha |
| `alpha:evaluation-plan --alpha-id <id>` | 生成评估计划 |
| `alpha:init-samples` | 初始化示例 Alpha |
| `alpha:migrate-existing-factors` | 现有因子迁入 Alpha Registry |

### 2.10 数据质量与盘中监测

| 命令 | 说明 |
|------|------|
| `data:freshness-check` | 数据新鲜度检查 |
| `data:gap-report` | 数据缺口报告 |
| `intraday:prepare` | 初始化盘中状态 |
| `intraday:check-once` | 单次盘中检查 |
| `intraday:watch [interval]` | 盘中循环监测 |
| `intraday:monitor` | 低频全量监测 |
| `intraday:risk` | 指数风险 + 成交额异常 |
| `intraday:wechat-alert` | 低频监测 + 企业微信推送 |

### 2.11 企业微信通知

| 命令 | 说明 |
|------|------|
| `wechat:test` | 测试 webhook |
| `wechat:send-digest` | 发送摘要 |

### 2.12 已退役的自动开发系统

Leader 自动工作循环、固定路线图、Agent Runner、Agent Console 和版本报告命令已于 2026-07-11 退役。历史材料已归档，不再作为可执行操作入口。

### 2.13 一键本地运维

| 命令 | 说明 |
|------|------|
| `leader:ops-health` | 所有服务健康状态概览 |
| `leader:ops-status [id]` | 服务详细状态 |
| `leader:ops-start <id>` | 启动服务 |
| `leader:ops-stop <id>` | 停止服务 |
| `leader:ops-restart <id>` | 重启服务 |
| `leader:ops-backup` | 一键备份 |
| `leader:ops-diagnostics` | 全面诊断报告 |
| `leader:ops-ports` | 端口占用扫描 |
| `leader:ops-all` | 启动全部核心服务 |

### 2.14 发布类

| 命令 | 说明 |
|------|------|
| `package:publish-preopen` | 发布盘前事件 |
| `package:publish-market` | 发布行情快照 |
| `package:publish-intraday-alerts` | 发布盘中预警 |
| `package:publish-all` | 发布所有待发数据 |

---

## 3. 数据文件目录说明

### 3.1 顶层数据目录: `/home/ly/.hermes/research-assistant/data/`

| 子目录 | 说明 | 关键文件 |
|--------|------|---------|
| `market/` | 行情数据 | `daily_kline/<symbol>_daily_kline.csv`, `live_snapshot.csv`, `pool.csv` |
| `market/daily_kline/` | 个股日 K 线 | 9 个 CSV (~247 行/文件), 含 6 只个股 + 5 只 ETF 的日线 |
| `fundamentals/` | 基本面数据 | `financial_snapshot.csv`, `profit_data.csv`, `balance_data.csv`, `cash_flow_data.csv` |
| `tags/` | 标签数据 | `semiconductor_chain_tags.csv` (21 只), `stock_theme_tags.csv` (44 只) |
| `positions/` | 持仓数据 | `current_positions.csv` (3 只股票 + 现金) |
| `audit/` | 审计日志 | `data_freshness_report.json`, `data_gap_report.json`, `health/` |
| `events/` | 事件数据 | `policy_events.csv`, `preopen_events.csv` |
| `intraday/` | 盘中数据 | 实时快照 |
| `portfolio/` | 组合输出 | 组合构建结果 |
| `normalized/` | 标准化后数据 | 因子引擎时序数据 |
| `raw/` | 原始采集数据 | Tushare 原始返回 |
| `warehouse/` | 数据仓库 | 基础宽表 |
| `features/` | 因子特征 | 因子计算中间结果 |
| `staging/` | 暂存区 | 批量导入中转 |

### 3.2 Windows D: 盘数据: `/mnt/d/HermesData/`

| 子目录 | 说明 |
|--------|------|
| `paper_trading/` | Paper Trading 状态 (portfolio.json, trades.jsonl, equity.csv) |
| `alpha_registry/` | Alpha Factory 注册表 |
| `alpha_failures/` | Alpha 失效记录 |
| `risk_sentinel/` | 风控 Sentinel 日志 |
| `data_source_registry/` | 数据源注册表 |
| `manifests/` | 发布清单 |

### 3.3 Windows C: 盘只读数据: `/mnt/c/Users/ly/.codex/data/a-share-data-hub/`

该路径是 Windows 侧 Codex 数据中心的只读挂载, 包含更完整的 daily_kline, tags 等数据。

---

## 4. 使用示例

### 4.1 日常巡检流程

```bash
# 1. 检查数据新鲜度
python3 hermes_cli.py data:freshness-check

# 2. 检查数据缺口
python3 hermes_cli.py data:gap-report

# 3. 检查股票池状态
python3 hermes_cli.py universe:list
python3 hermes_cli.py universe:audit

# 4. 运行实盘 Readiness
python3 hermes_cli.py live-readiness:v4
```

### 4.2 因子验证流程

```bash
# 1. 列出所有可用因子
python3 hermes_cli.py factor:list

# 2. 单因子 V3 验证
python3 hermes_cli.py factor:validate --factor ret5 --start 2025-01-02 --end 2026-06-30

# 3. V4.4 增强验证 (含基准对比+成本+风险)
python3 hermes_cli.py factor:validate-v4 --factor ret5 --top-quantile 0.2 --rebalance monthly

# 4. 风险归因
python3 hermes_cli.py factor:risk-attribution --factor ret5

# 5. 批量验证多个因子
python3 hermes_cli.py factor:batch --factors ret5,vol_ratio60,volatility20
```

### 4.3 组合构建与模拟交易

```bash
# 1. 低频组合构建
python3 hermes_cli.py portfolio:build-lowfreq --signal-date 2026-07-08

# 2. 查看组合推荐
python3 hermes_cli.py portfolio:recommend

# 3. 运行 Paper Trading (模拟盘)
python3 hermes_cli.py paper:v4-run --date 2026-07-08 --capital 50000 --top-n 10

# 4. 运行 Shadow Trading (影子交易)
python3 hermes_cli.py shadow:v4-run --date 2026-07-08 --capital 50000 --top-n 10

# 5. 查看 Paper Trading 看板
python3 hermes_cli.py paper:v4-dashboard

# 6. 查看 Shadow 多日报告
python3 hermes_cli.py shadow:v4-report
```

### 4.4 盘前决策流程

```bash
# 1. 生成盘前信号
python3 hermes_cli.py factor:signal --signal-date 2026-07-08 --top-n 20

# 2. ETF 替代筛选
python3 hermes_cli.py factor:etf-selector --capital 50000

# 3. 生成盘前决策报告
python3 hermes_cli.py factor:premarket --capital 50000 --signal-date 2026-07-08

# 4. (可选) 每日全自动盘前编排
python3 hermes_cli.py factor:daily-premarket --date auto --capital 50000

# 5. 记录人工决策
python3 hermes_cli.py factor:decision-log --date 2026-07-08 --plan B
```

### 4.5 QMT 券商对接

```bash
# 1. 检查 QMT Bridge 状态
python3 hermes_cli.py broker:qmt-health

# 2. 拉取账户资金
python3 hermes_cli.py broker:qmt-account

# 3. 同步全部持仓/委托/成交
python3 hermes_cli.py broker:qmt-sync

# 4. 查看持仓
python3 hermes_cli.py broker:qmt-positions

# 5. 订单预览 (从组合构建结果生成)
python3 hermes_cli.py factor:order-preview --date 2026-07-08 --plan B

# 6. 风控审批
python3 hermes_cli.py factor:approval --date 2026-07-08 --plan B

# 7. 提交已审批订单 (仅大QMT内置模式)
python3 hermes_cli.py broker:qmt-internal-place-approved --approval-id ID --orders PATH
```

### 4.6 实盘 Readiness 检查

```bash
# 标准检查 (13 道 Gate)
python3 hermes_cli.py live-readiness:v4

# 严格模式 (warning 也视为阻塞)
python3 hermes_cli.py live-readiness:v4 --strict

# 详细报告 (含每项证据和修复建议)
python3 hermes_cli.py live-gate:v4-report
```

### 4.7 Alpha Factory 使用

```bash
# 1. 初始化示例 Alpha
python3 hermes_cli.py alpha:init-samples

# 2. 列出所有 Alpha
python3 hermes_cli.py alpha:list

# 3. 查看某个 Alpha 详情
python3 hermes_cli.py alpha:show --alpha-id alpha_001

# 4. 注册外部 Alpha
python3 hermes_cli.py alpha:register --spec /path/to/alpha_spec.json

# 5. 生成评估计划
python3 hermes_cli.py alpha:evaluation-plan --alpha-id alpha_001

# 6. 退役失效 Alpha
python3 hermes_cli.py alpha:retire --alpha-id alpha_001

# 7. 因子库 → Alpha Registry 同步
python3 hermes_cli.py factor:sync --dry-run
```

### 4.8 辅助系统

```bash
# 运维健康与诊断
python3 hermes_cli.py leader:ops-health
python3 hermes_cli.py leader:ops-diagnostics

# 一键启动 Dashboard
python3 hermes_cli.py leader:dashboard

# 代码审计
python3 hermes_cli.py audit:code --profile fast
python3 hermes_cli.py audit:code --profile full
```

---

## 5. 命令版本对照

| 版本 | 新增功能 | 核心命令 |
|------|---------|---------|
| V1.0-V1.13 | 因子验证/信号/盘前决策 | `factor:validate`, `factor:signal`, `factor:premarket`, `factor:daily-premarket`, `factor:decision-log` |
| V2.0-V2.14 | 持仓接入/订单预览/审批/Paper/自适应 | `factor:rebalance-diff`, `factor:order-preview`, `factor:approval`, `factor:paper-trade`, `factor:adaptive-recommend`, `factor:live-readiness` |
| V3.0 | Alpha Factory | `alpha:register`, `alpha:list`, `alpha:show`, `alpha:retire` |
| V4.0 | 数据采集 | `data:pull-daily`, `data:coverage`, `data:survivorship` |
| V4.1 | 分层股票池 | `universe:build`, `universe:list`, `universe:show`, `universe:audit` |
| V4.2 | 历史数据扩展 | `data:pull-fina`, `data:pull-valuation` |
| V4.3 | 基准体系 | 基准管理 (benchmarks_v4.py) |
| V4.4 | 因子增强评价 | `factor:validate-v4`, `factor:risk-attribution` |
| V4.7 | 低频组合构建 | `portfolio:build-lowfreq`, `portfolio:recommend` |
| V4.8 | Paper/Shadow Trading | `paper:v4-run`, `shadow:v4-run` |
| V4.9 | 实盘 Readiness | `live-readiness:v4`, `live-gate:v4-report` |
| V4.10 | 事件因子 | `event:list`, `event:factors`, `event:report` |
| V4.11 | 盘中低频监控 | `intraday:monitor`, `intraday:wechat-alert` |
| V4.12 | 总验收与生产化冻结 | `architecture:audit` |

---

## 6. 常见问题

### Q: 如何查看帮助?

```bash
python3 hermes_cli.py --help
# 或
python3 hermes_cli.py help
```

### Q: 数据目录在哪里?

项目内数据: `data/` (相对于项目根目录)
持久化输出: `/mnt/d/HermesData/` (Windows D: 盘)
Windows 只读数据: `/mnt/c/Users/ly/.codex/data/a-share-data-hub/`

### Q: Paper Trading 状态持久化在哪里?

`/mnt/d/HermesData/paper_trading/` — 包含 portfolio.json (持仓), trades.jsonl (成交), equity.csv (权益曲线)

### Q: 如何查看当前持仓?

```bash
cat data/positions/current_positions.csv
# 或使用 QMT 同步
python3 hermes_cli.py broker:qmt-positions
```

### Q: 如何确认系统是否可实盘?

运行实盘 Readiness 门禁检查:
```bash
python3 hermes_cli.py live-readiness:v4
# 全部 13 道 Gate 通过 → READY
# 存在 blockers → NOT_READY (查看具体阻塞项和修复建议)
```

### Q: V4 报告在哪里?

预期路径: `/mnt/d/HermesReports/factor_lab/v4_reports/`
生成方式: `python3 hermes_cli.py factor:validate-v4 --factor ret5`

---

## 7. 已知限制

1. **数据覆盖**: 日线仅 6 只标的 + 5 只 ETF, 约 1 年数据
2. **仅 Tushare 数据源**: 无 baostock/akshare 兜底
3. **无自动调度**: Paper/Shadow Trading 需手动触发
4. **全部默认 live_enabled=false**: 需显式启用实盘
5. **universes.json 未持久化**: 每次需重新 `universe:build`
