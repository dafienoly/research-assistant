# Hermes 量化投研系统

自动化因子挖掘 · 策略回测 · 信号生成 · 版本推进

---

## 目录

1. [系统概览](#系统概览)
2. [投研系统（核心功能）](#投研系统核心功能)
3. [自动版本推进系统（开发运维）](#自动版本推进系统开发运维)
4. [快速开始](#快速开始)
5. [前端页面](#前端页面)
6. [数据平台](#数据平台)
7. [安全边界](#安全边界)
8. [目录结构](#目录结构)

---

## 系统概览

Hermes 由两个子系统组成，职责分离：

| 子系统 | 职责 | 用户 |
|--------|------|------|
| **投研系统** | 因子挖掘、策略回测、信号生成、盘前分析 | 量化研究员 |
| **自动版本推进系统** | 按路线图自动开发、测试、部署 Hermes 本身 | Hermes 自身 |

两者通过同一个 FastAPI 后端和前端页面呈现，但互不依赖：
- 投研系统可以独立运行，不需要版本推进
- 版本推进系统开发的是 Hermes 自身的功能，不影响投研系统运行

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

## 自动版本推进系统（开发运维）

用于 Hermes 自身的持续开发和版本管理。

### 当前路线图进度

```bash
hermes leader:roadmap-status
```

输出示例：
```
Version: V6.6
Status: running
Completed: 38 versions
Auto allowed until: V8.9
```

### 路线图覆盖

| 系列 | 版本 | 状态 | 说明 |
|------|------|------|------|
| V3.x | V3.0-V3.9 | ✅ | Alpha Factory |
| V4.x | V4.0-V4.9 | ✅ | 受控执行治理 |
| V5.x | V5.0-V5.9 | ✅ | 数据平台 |
| V6.x | V6.0-V6.5 | ✅ | 投研自动化 |
| V6.x | V6.6-V6.9 | ⏸️ | 因子挖掘Agent/新闻/行业轮动/看板 |
| V7.x-V8.x | V7.0-V8.9 | ⏸️ | 产品UI/Agent生态 |
| V9.x | V9.0-V9.4 | ⏸️ | Backlog |

### 自动推进系统命令

```bash
# ===== 状态查看 =====
hermes leader:roadmap-status               # 路线图进度
hermes leader:automation-status            # 自动推进健康检查
hermes leader:version-report               # 版本开发报告

# ===== 版本操作 =====
hermes leader:backup-list                  # 列出备份
hermes leader:recover --backup-id <id>     # 从备份恢复

# ===== 手动触发 =====
hermes leader:auto-run-once                # 触发一次版本推进
hermes leader:task-list                    # 待办任务

# ===== 前端页面 =====
hermes leader:dashboard --port 8766       # 启动 FastAPI 后端
```

### 自动推进工作流

```
cron (每3分钟)
  → run_hermes_agent_runner.sh
    → tick() 心跳 (auto_loop_state.json)
    → leader:auto-run-once
      → 读取 roadmap_cursor (当前 V6.6)
      → 获取当前版本定义
      → 创建 Agent Console session
      → 运行 agent-runner (Claude/dry-run)
      → 运行测试
      → 通过则: advance cursor + git commit + 备份
      → 失败则: partial + 记录错误
    → leader:loop-once (派发下一版本)
```

### 暂停 / 恢复

```bash
# 暂停（投研系统不受影响）
crontab -r

# 恢复
crontab scripts/crontab/hermes-crontab
```

---

## 快速开始

### 启动后端

```bash
cd /home/ly/.hermes/research-assistant/commands
../.venv_quant/bin/python3 hermes_cli.py leader:dashboard --port 8766
```

访问:
- 前端页面: http://127.0.0.1:8766
- API 文档: http://127.0.0.1:8766/docs
- Agent Console: http://127.0.0.1:8766/console

### 启动 React 前端（开发模式）

```bash
cd commands/frontend && npm run dev
# http://localhost:5173（热更新）
```

### 一键脚本

```bash
bash scripts/start_hermes_auto_version.sh    # 启动
bash scripts/stop_hermes_auto_version.sh     # 停止
bash scripts/restart_hermes_auto_version.sh  # 重启
```

---

## 前端页面

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | 总览 | 版本推进状态、系统健康、版本列表 |
| `/console` | Agent Console | Session 列表 + 实时输出查看 |
| `/roadmap` | 路线图编辑 | V3-V9 版本列表、手动标记完成/失败 |
| `/reports` | 版本报告 | 完成版本详情、Git 记录、Agent 输出、备份 |
| `/history` | Session 历史 | 全部 session + 备份/恢复 |

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

```
/home/ly/.hermes/research-assistant/
├── README.md                    ← 本文档
├── data/                        投研数据 CSV 文件
│
├── commands/                    可执行代码
│   ├── hermes_cli.py            CLI 入口（投研 + 版本推进全部命令）
│   ├── factor_lab/              投研系统核心
│   │   ├── factor_base.py       142 因子注册表
│   │   ├── factor_engine.py     因子计算引擎
│   │   ├── alpha/               Alpha Factory (registry, packs, lifecycle)
│   │   ├── strategy/            策略层
│   │   ├── live/                盘前信号
│   │   ├── paper/               Paper trading
│   │   ├── portfolio/           组合分析
│   │   ├── broker/              Broker 适配器
│   │   ├── approval/            审批/风控
│   │   ├── backtest/            回测引擎
│   │   ├── data_contract.py     数据契约 V5.5
│   │   ├── data_health.py       数据健康 V5.8
│   │   ├── leader/              自动版本推进系统
│   │   │   ├── roadmap.py       固定路线图
│   │   │   ├── roadmap_cursor.py 进度追踪
│   │   │   ├── auto_executor.py  自动执行器
│   │   │   ├── workloop.py       工作循环
│   │   │   ├── agent_runner.py   Agent 执行后端
│   │   │   ├── version_report.py 版本报告
│   │   │   ├── version_detail.py 版本完成详情
│   │   │   ├── roadmap_backup.py 备份/恢复
│   │   │   └── auto_health.py    健康检查
│   │   ├── api_server/          FastAPI 后端
│   │   ├── agent_console/       Agent Console
│   │   ├── data_source_registry/ 数据源注册
│   │   ├── realtime_market/     实时行情框架
│   │   ├── minute_storage/      分钟线存储
│   │   ├── data_lineage/        数据血缘
│   │   ├── paid_data/           付费数据源接口
│   │   ├── event/               事件驱动因子
│   │   ├── review/              审核队列
│   │   ├── promotion/           晋级/退役
│   │   └── miniqmt/             MiniQMT 沙箱
│   │
│   ├── frontend/                React 前端
│   │   └── src/pages/
│   │       ├── Dashboard.jsx    总览
│   │       ├── AgentConsole.jsx Agent Console
│   │       ├── Roadmap.jsx      路线图
│   │       ├── Reports.jsx      版本报告
│   │       └── SessionHistory.jsx 历史
│   │
│   ├── DESIGN.md                设计规范
│   └── scripts/                 运维脚本
│       ├── run_hermes_agent_runner.sh  cron 入口
│       ├── start/stop/restart*.sh      一键脚本
│       └── windows/                    Windows schtasks
│
├── agent_tasks/                 运行时状态 (不提交)
│   ├── latest.json              当前任务
│   ├── roadmap_cursor.json      路线图进度
│   └── agent_console_sessions/  Console session
│
└── /mnt/d/HermesReports/        报告输出
    ├── version_reports/         版本开发报告
    ├── roadmap_backups/         路线图备份
    └── session_backups/         Console session 备份
```
