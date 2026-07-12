# Hermes 量化投研系统

自动化因子挖掘 · 策略回测 · 信号生成 · 可审计运维

---

## 目录

1. [系统概览](#系统概览)
2. [投研系统（核心功能）](#投研系统核心功能)
3. [辅助系统](#辅助系统)
4. [快速开始](#快速开始)
5. [前端页面](#前端页面)
6. [数据平台](#数据平台)
7. [安全边界](#安全边界)
8. [目录结构](#目录结构)

---

## 系统概览

Hermes 将投研主链与辅助能力严格分离：

| 子系统 | 职责 | 用户 |
|--------|------|------|
| **投研系统** | 因子挖掘、策略回测、信号生成、盘前分析 | 量化研究员 |
| **辅助系统** | 本地服务运维、确定性代码审计、操作审计 | 工程维护者 |

两者通过同一个 FastAPI 后端和前端页面呈现，但互不依赖。自动版本推进、Roadmap、Agent Console、任务队列与通用 Runner 已退役。

---

## 投研系统（核心功能）

### 因子发现与评估

| 版本 | 功能 | 状态 |
|------|------|------|
| V1.1-V1.5 | 因子注册、IC 分析、多因子组合 | ✅ |
| V1.6 | 正交性分析、增量价值评分 | ✅ |
| V1.7 | 策略层验证（ret5 + close_gt_ma20 gate） | ✅ |
| V3.0-V3.9 | Alpha Factory 142 因子全生命周期管理 | ✅ |

**已注册因子：142 个**

| 分类 | 数量 | 示例 |
|------|------|------|
| 动量 (momentum) | 6 | ret5, ret10, ret20 |
| 趋势 (trend) | 7 | ma5, ma10, ma20_uptrend |
| 波动率 (volatility) | 6 | volatility20, atr20 |
| 反转 (reversal) | 5 | close_to_high20, pullback |
| 量价 (volume/breakout) | 12 | volume_ratio, high_20_breakout |
| 流动性 (liquidity) | 7 | amount_rank20, turnover |
| ret5_penalty | 5 | 高波动/高换手惩罚 |
| 行业相对 (industry_relative) | 10 | 行业内标准化动量 |
| 技术形态 (technical) | 12 | MACD, KDJ, Bollinger |
| 事件驱动 (event) | 13 | 解禁、回购、分红、业绩预告 |
| 资金流向 (fund_flow) | 11 | 主力净流入、超大单 |
| 北向资金 | 6 | 北向净流入、持仓 |
| 两融 (margin) | 8 | 融资余额、杠杆 |
| 新闻情绪 (sentiment) | 3 | 情感评分 |
| 基本面 (quality) | 3 | ROE、毛利率、净利率 |
| 复合因子 (composite) | 30+ | 多因子合成 |

### 投研系统命令

```bash
# ===== 因子操作 =====
hermes factor:list                          # 列出所有因子
hermes factor:list --category momentum      # 按分类筛选
hermes factor:signal                        # 盘前信号生成
hermes factor:validate                      # 因子验证（IC/IR）
hermes factor:evolve                        # LLM 因子进化

# ===== 策略回测 =====
hermes strategy:run                         # 运行策略
hermes strategy:backtest                    # 回测 + QuantStats 报告

# ===== 盘前分析 =====
hermes factor:daily-premarket               # 每日盘前信号 + ETF + 报告

# ===== Alpha Factory =====
hermes alpha:list                           # Alpha Registry 列表
hermes alpha:show --alpha-id <id>           # 查看 Alpha 详情
hermes alpha:retire --alpha-id <id>         # 退役 Alpha
hermes alpha:evaluation-plan --alpha-id <id>  # 生成评估计划
hermes alpha:migrate-existing-factors       # 现有因子迁入 Registry
```

### 投研工作流

```
1. 因子挖掘
   factor:list → 查看已有因子
   factor:evolve → LLM 生成候选因子
   factor:validate → IC/Walk-Forward 验证

2. 策略开发
   factor:signal → 盘前信号
   strategy:run → 策略回测
   治理流水线 → 审批/影子/Paper

3. 每日运行
   factor:daily-premarket → 信号 + ETF + 报告
```

### 回测报告

回测完成后自动生成 HTML 报告，包含：
- 82 项绩效指标（QuantStats）
- 三线对比图：策略 vs 同池 vs 沪深300
- 中文双语标注

输出目录：`/mnt/d/HermesReports/`

---

## 辅助系统

投研主链之外仅保留运维中心与代码审计中心。自动版本推进、Roadmap、Agent Console、任务队列和通用 Runner 已退役；历史归档位于 `~/.hermes/archive/research-assistant/`。

- 运维：`hermes leader:ops-health`、`hermes leader:ops-diagnostics`
- 大版本源码审计：`commands/scripts/major_code_audit.sh 2.0.0 origin/main`
- 普通 `audit:code`/pre-commit/pre-push 已停用，不扫描数据、临时文件或生成物

## 快速开始

### 启动后端

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:dashboard --port 8766
```

访问:
- 前端页面: http://127.0.0.1:8766
- API 文档: http://127.0.0.1:8766/docs
- 代码审计中心: http://127.0.0.1:8766/code-audit

### 启动 React 前端（开发模式）

```bash
cd commands/frontend && npm run dev
# http://localhost:5173（热更新）
```

### 守护进程

```bash
bash ~/.hermes/hermes-daemon.sh start
bash ~/.hermes/hermes-daemon.sh status
```

守护进程只维护 Gateway 与 Dashboard。

---

## 前端页面

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | VNext 总览 | 投研系统状态与证据 |
| `/reports` | 投研报告 | 回测和策略报告 |
| `/ops` | 运维中心 | 服务、端口、诊断与备份 |
| `/code-audit` | 代码审计中心 | fast/full/security 审计记录 |

---

## 数据平台

### 数据源注册表

| 数据源 | 类型 | 状态 |
|--------|------|------|
| Baostock K 线 | kline | ✅ |
| 东方财富资金流向 | fund_flow | ✅ |
| 东方财富因子数据 | factor | ✅ |
| 北向资金 | northbound | ✅ |
| 两融数据 | margin | ✅ |
| 事件驱动 | event | ✅ |
| 新闻情绪 | sentiment | ✅ |

### 数据文件位置

```
data/                                    # 项目根目录
├── fund_flow_timeseries.csv             # 资金流向
├── north_flow_timeseries.csv            # 北向资金
├── margin_timeseries.csv                # 两融
├── event_timeseries.csv                 # 事件驱动
└── news_sentiment_timeseries.csv        # 新闻情绪
```

### 数据契约 (V5.5)
- 字段含 NaN 时抛出 `DataContractViolation` 异常，不静默 fillna(0)
- 因子计算前先验证数据完整性

---

## 安全边界

- 所有 Alpha 默认 `enabled=false, paper_enabled=false, live_enabled=false`
- 实盘交易 / 资金账户 / broker 实盘 → **自动停在人工确认点**
- 仅 `research / dry_run / acceptance / test` 安全阶段自动执行
- 不修改系统 DNS / Clash 配置
- 不删除项目 `.pyc` 缓存

---

## 目录结构

```text
research-assistant/
├── commands/factor_lab/vnext/      VNext 投研主链
├── commands/factor_lab/audit/      双速代码审计
├── commands/factor_lab/leader/     本地运维实现
├── commands/factor_lab/api_server/ FastAPI API
├── commands/frontend/                React 前端
├── configs/audit/                    本地安全规则
└── agent_tasks/traceability/         明确需求的追溯映射
```

运行态审计写入 `~/.hermes/state/research-assistant/`，不写入 Git 工作树。
