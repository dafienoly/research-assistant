# Hermes A股投研系统 — 功能手册 & 使用指引

> 最后更新: 2026-07-07
> 项目路径: `/home/ly/.hermes/research-assistant`

---

## 一、系统概览

Hermes A股投研系统是一个面向 A 股量化交易的**全栈投研平台**，覆盖从数据采集、因子挖掘、策略回测、盘前决策到实盘执行的全链路。系统运行在 WSL (Ubuntu) 环境中，前后端分离，核心代码位于 `commands/` 目录。

### 核心能力矩阵

| 领域 | 能力 | 实现方式 |
|------|------|---------|
| **数据层** | 日K/分钟K/实时行情、基本面、资金流、北向、两融 | `mx:data` / DataHub / jqdata |
| **因子层** | 142+ 因子 × 18 类，IC 计算，因子进化 | `factor_lab/` Alpha Registry |
| **回测层** | Walk-Forward、分位数回测、正交性检验 | `backtest:factor-top` / `backtest:walk-forward` |
| **决策层** | 盘前信号、ETF 选择器、持仓权重、调仓指令 | `factor:daily-premarket` / `factor:order-preview` |
| **执行层** | QMT 委托、Paper Trading、风控审批、Kill Switch | `broker:qmt-*` / `factor:paper-trade` |
| **自开发层** | 固定路线图自动开发、Agent 工作循环、版本推进 | `leader:auto-run-once` / `auto_executor.py` |

<!-- SKILLS_COUNT_START -->
（共 126 个 skill）
<!-- SKILLS_COUNT_END -->

<!-- SKILLS_TABLE_START -->
| Skill 名称 | 分类 | 用途 |
|------------|------|------|
| `a-share-data-collector` | a-share-research | A 股 L0 数据采集 — 行情、基本面、政策事件、公告解析。只输出原始和轻度清洗的事实数据，不做选股判断。 |
| `a-share-data-quality` | a-share-research | A 股 L1 数据质量 — 新鲜度检查、数据缺口检测、产业链/主题标签维护。只做质量审计，不做预警或建议。 |
| `a-share-datahub-pipeline` | — | DataHub 全量初始化、每日增量更新、每周维护、CSV 持久化去重策略、定时任务编排。覆盖 Tushare Pro ... |
| `a-share-intraday-monitor` | a-share-research | A 股 L3 盘中实时监测 — 高频轮询 P0-P5、规则引擎、L0-L4 分级预警、告警去重冷却、企业微信推送、Cod... |
| `airtable` | — | Airtable REST API via curl. Records CRUD, filters, upserts. |
| `alpha-factory` | — | V3 Alpha Factory — Alpha 注册表、生命周期、LLM 发现、治理审核、晋级管道、退役引擎。管理 A... |
| `anti-cheat-audit` | — | (no description) |
| `apple-notes` | — | Manage Apple Notes via memo CLI: create, search, edit. |
| `apple-reminders` | — | Apple Reminders via remindctl: add, list, complete. |
| `architecture-diagram` | — | Dark-themed SVG architecture/cloud/infra diagrams as HTML. |
| `arxiv` | — | Search arXiv papers by keyword, author, category, or ID. |
| `ascii-art` | — | ASCII art: pyfiglet, cowsay, boxes, image-to-ascii. |
| `ascii-video` | — | ASCII video: convert video/audio to colored ASCII MP4/GIF. |
| `ashare-data-pipeline` | data-science | 设计并实施 A 股数据源的周期性刷新管线——分层策略(日增量/周维护/季度全量)、Tushare API 优化(按 tr... |
| `ashare-package-publisher` | a-share-research | A 股数据包发布与发布后完整性验证 — 发布流程、原子写入协议、手动/脚本化验证方法。基于 a-share-packag... |
| `audiocraft` | — | AudioCraft: MusicGen text-to-music, AudioGen text-to-sound. |
| `auto-development-orchestration` | — | (no description) |
| `backtest-engine` | — | Design, implement, and review trading strategy backtests wit... |
| `baoyu-infographic` | — | Infographics: 21 layouts x 21 styles (信息图, 可视化). |
| `blogwatcher` | — | Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool. |
| `broker-bridge-pattern` | software-development | FastAPI backend routes that bridge to external broker/tradin... |
| `claude-code` | — | Security-focused code review |
| `claude-design` | — | Design one-off HTML artifacts (landing, deck, prototype). |
| `codebase-inspection` | — | Inspect codebases w/ pygount: LOC, languages, ratios. |
| `codex` | — | Delegate coding to OpenAI Codex CLI (features, PRs). |
| `comfyui` | — | Generate images, video, and audio with ComfyUI — install, la... |
| `computer-use` | — | | |
| `cron-pipeline-manager` | — | (no description) |
| `daily-review-report` | quant-ops | Build daily/periodic review reports that aggregate live stat... |
| `data-provider-authoring` | — | (no description) |
| `datahub-pipeline` | — | A 股数据管线全生命周期管理：按交易日全量初始化、每日增量更新、每周维护、CSV 持久层设计、Tushare API 限... |
| `design-md` | — | Architectural minimalism meets journalistic gravitas. |
| `dogfood` | — | Exploratory QA of web apps: find bugs, evidence, reports. |
| `domain-modeling` | — | Structured domain modeling for A-share research system — Eve... |
| `etf-dive-warning` | — | ETF 跳水预测系统 — 多源特征工程(技术指标+龙头个股+新闻情绪) + Walk-Forward 验证 + 9标的联... |
| `excalidraw` | — | Hand-drawn Excalidraw JSON diagrams (arch, flow, seq). |
| `factor-lab` | — | Systematic factor mining, IC analysis, factor evolution, and... |
| `factor-mining` | — | Factor mining, IC analysis, factor evolution, unified premar... |
| `fastapi-backend-pattern` | software-development | Architect production FastAPI backends with middleware chain ... |
| `findmy` | — | Track Apple devices/AirTags via FindMy.app on macOS. |
| `frontend-e2e-test` | — | (no description) |
| `frontend-self-verify` | — | (no description) |
| `frontend-spa-debugging` | — | Debug React/SPA frontend issues: blank pages, API contract m... |
| `gif-search` | — | Search/download GIFs from Tenor via curl + jq. |
| `github-auth` | — | GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. |
| `github-code-review` | — | Review PRs: diffs, inline comments via gh or REST. |
| `github-issues` | — | Create, triage, label, assign GitHub issues via gh or REST. |
| `github-pr-workflow` | — | GitHub PR lifecycle: branch, commit, open, CI, merge. |
| `github-repo-management` | — | Clone/create/fork repos; manage remotes, releases. |
| `gitnexus-explorer` | — | Index a codebase with GitNexus and serve an interactive know... |
| `google-workspace` | — | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. |
| `grill-with-docs` | — | A relentless interview to sharpen a plan or design, which al... |
| `heartmula` | — | HeartMuLa: Suno-like song generation from lyrics + tags. |
| `hermes-agent-skill-authoring` | — | Use when <trigger>. <one-line behavior>. |
| `hermes-agent` | — | Configure, extend, or contribute to Hermes Agent. |
| `hermes-daemon` | — | Deploy and maintain Hermes gateway as a reliable background ... |
| `hermes-frontend-dashboard` | — | Build React+Vite dashboard pages for Hermes auto-version-sys... |
| `hermes-leader-workloop` | — | Use when working with the Hermes-Leader auto-task-loop: cons... |
| `himalaya` | — | Himalaya CLI: IMAP/SMTP email from terminal. |
| `huggingface-hub` | — | HuggingFace hf CLI: search/download/upload models, datasets. |
| `humanizer` | — | Humanize text: strip AI-isms and add real voice. |
| `imessage` | — | Send and receive iMessages/SMS via the imsg CLI on macOS. |
| `interactive-web-ui` | — | Build interactive web UIs with SSE streaming, answer/diagnos... |
| `jupyter-live-kernel` | — | Iterative Python via live Jupyter kernel (hamelnb). |
| `leader-driven-automation` | — | Fixed-roadmap continuous auto-development pipeline. Hermes d... |
| `leader-workloop` | — | Hermes ↔ Leader 自治工作循环 — 自动派发、可插拔后端执行、完成信号、GitHub 同步 |
| `llama-cpp` | — | llama.cpp local GGUF inference + HF Hub model discovery. |
| `llm-wiki` | — | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| `lm-evaluation-harness` | — | lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.). |
| `manim-video` | — | Manim CE animations: 3Blue1Brown math/algo videos. |
| `maps` | — | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. |
| `monitor-588170` | a-share-research | 科创板半导体设备ETF 盘中监测看板 — 实时行情+权重股承接+北向资金+KOSPI+美股影响，全数据走 datahub |
| `mx-data` | — | 基于东方财富权威数据库的金融数据查询工具，支持行情、财务及关联关系数据。 |
| `mx-search` | — | 本skill基于东方财富妙想搜索能力，基于金融场景进行信源智能筛选，用于获取涉及时效性信息或特定事件信息的任务，包括新闻... |
| `mx-xuangu` | — | 本 Skill 支持基于股票选股条件，如行情指标、财务指标等，筛选满足条件的股票；可查询指定行业 / 板块内的股票、上市... |
| `nano-pdf` | — | Edit PDF text/typos/titles via nano-pdf CLI (NL prompts). |
| `node-inspect-debugger` | — | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. |
| `notion` | — | Notion API + ntn CLI: pages, databases, markdown, Workers. |
| `obsidian` | — | Read, search, create, and edit notes in the Obsidian vault. |
| `ocr-and-documents` | — | Extract text from PDFs/scans (pymupdf, marker-pdf). |
| `opencode` | — | Delegate coding to OpenCode CLI (features, PR review). |
| `openhue` | — | Control Philips Hue lights, scenes, rooms via OpenHue CLI. |
| `p5js` | — | p5.js sketches: gen art, shaders, interactive, 3D. |
| `package-publisher` | a-share-research | A 股数据包发布 — 将 WSL 侧数据打包为标准发布格式，含 manifest、sha256、_SUCCESS，原子写... |
| `parallel-subagent-development` | — | (no description) |
| `petdex` | — | Install and select animated petdex mascots for Hermes. |
| `plan` | — | Plan mode: write an actionable markdown plan to .hermes/plan... |
| `policy-monitor` | — | Monitor financial regulation, macro policy, exchange rules, ... |
| `polymarket` | — | Query Polymarket: markets, prices, orderbooks, history. |
| `popular-web-designs` | — | 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS. |
| `powerpoint` | — | Create, read, edit .pptx decks, slides, notes, templates. |
| `pretext` | — | Use when building creative browser demos with @chenglou/pret... |
| `python-debugpy` | — | Debug Python: pdb REPL + debugpy remote (DAP). |
| `quant-kb` | — | Compact quantitative finance knowledge base for strategies, ... |
| `quant-maturity-audit` | quality | 四层量化成熟度模型 — 评估量化交易系统从"野鸡量化"到"生产级量化"的完整成熟度审计方法论。包含分层判断标准、模块级缺... |
| `react-component-optimization` | software-development | Systematic optimization patterns for React/TypeScript page c... |
| `report-extractor` | — | Extract key information from financial reports, research PDF... |
| `requesting-code-review` | — | Pre-commit review: security scan, quality gates, auto-fix. |
| `requirement-traceability` | — | 需求追溯 — grilling 结束后产出一份需求追溯清单，每项标注状态，实现过程逐步更新，阻塞项必须回到用户确认。确保... |
| `research-paper-writing` | — | Write ML papers for NeurIPS/ICML/ICLR: design→submit. |
| `roadmap-compliance` | — | (no description) |
| `segment-anything` | — | SAM: zero-shot image segmentation via points, boxes, masks. |
| `simplify-code` | — | Parallel 3-agent cleanup of recent code changes. |
| `sketch` | — | Throwaway HTML mockups: 2-3 design variants to compare. |
| `songsee` | — | Audio spectrograms/features (mel, chroma, MFCC) via CLI. |
| `songwriting-and-ai-music` | — | Songwriting craft and Suno AI music prompts. |
| `spike` | — | Throwaway experiments to validate an idea before build. |
| `stock-analyst` | — | Analyze individual stocks across fundamentals, valuation, te... |
| `strategy-lab` | a-share-research | 策略说明 |
| `subagent-output-verification` | — | Verify subagent (delegate_task) outputs are real data, not h... |
| `system-architecture-review` | — | Systematic architecture benchmarking — clone benchmark repo,... |
| `system-audit` | — | Systematic self-audit of the auto version advancement + A-sh... |
| `systematic-debugging` | — | 4-phase root cause debugging: understand bugs before fixing. |
| `teams-meeting-pipeline` | — | Operate the Teams meeting summary pipeline via Hermes CLI — ... |
| `test-driven-development` | — | TDD: enforce RED-GREEN-REFACTOR, tests before code. |
| `touchdesigner-mcp` | — | Control a running TouchDesigner instance via twozero MCP — c... |
| `typescript-defensive-patterns` | software-development | Safe data handling patterns for TypeScript frontends consumi... |
| `ui-ux-pro-max-skill` | — | (no description) |
| `v3-quant-studio` | — | Hermes V3 量化研究平台 — 全链路因子研究、风控、模拟交易、复盘。2026-07-08 开发完成，覆盖量化成熟... |
| `v5-ui-optimizer` | — | (no description) |
| `vllm` | — | vLLM: high-throughput LLM serving, OpenAI API, quantization. |
| `weights-and-biases` | — | W&B: log ML experiments, sweeps, model registry, dashboards. |
| `workloop-automation` | — | Agent-Leader automatic workloop: lock → dispatch → consume →... |
| `xurl` | — | X/Twitter via xurl CLI: post, search, DM, media, v2 API. |
| `youtube-content` | — | YouTube transcripts to summaries, threads, blogs. |
| `yuanbao` | — | Yuanbao (元宝) groups: @mention users, query info/members. |
<!-- SKILLS_TABLE_END -->

---

## 二、项目结构

```
research-assistant/
├── commands/                          # 主要代码目录
│   ├── hermes_cli.py                  # CLI 入口（~200 个命令）
│   ├── config.py                      # 全局配置：路径、常量
│   ├── leader_commands.py             # leader: 命令实现
│   ├── factor_commands.py             # factor: 命令实现
│   ├── rsscast_mcp.py                 # DataHub 数据管线
│   ├── factor_lab/                    # 因子实验室
│   │   ├── leader/                    # 自动开发管线
│   │   │   ├── roadmap.py             # 固定路线图
│   │   │   ├── roadmap_cursor.py      # 版本游标
│   │   │   ├── auto_executor.py       # 自动执行器主循环
│   │   │   ├── task_intake.py         # 任务入口
│   │   │   ├── agent_runner.py        # Agent 后端执行器
│   │   │   ├── workloop.py            # 锁 + 完成信号 + 派发
│   │   │   ├── audit_push.py          # ADR-022 审计门禁
│   │   │   ├── acceptance.py          # 验收门禁
│   │   │   ├── version_detail.py      # 版本完成详情
│   │   │   ├── version_report.py      # 版本报告
│   │   │   └── version_notify.py      # 版本通知
│   │   ├── audit/                     # 反偷工减料审计（4 闸门）
│   │   │   ├── git_utils.py           # 共享 git 工具
│   │   │   ├── base.py                # AuditFinding/AuditReport
│   │   │   ├── gate1_traceability.py  # 需求→代码追溯
│   │   │   ├── gate2_stub_detect.py   # 虚假实现检测
│   │   │   ├── gate3_test_coverage.py # 测试覆盖检查
│   │   │   ├── gate4_independent_review.py # 独立需求审计
│   │   │   └── runner.py              # 统一调度 + CLI
│   │   ├── alpha/                     # Alpha Factory (V3.x)
│   │   ├── api_server/                # FastAPI 后端 (:8766)
│   │   ├── agent_console/             # Agent Console 会话管理
│   │   ├── factor_mining/             # 因子挖掘引擎
│   │   ├── research_loop/             # 6 阶段自动研究循环
│   │   ├── research_skill/            # 投研 Skill 运行时
│   │   ├── sector_rotation/           # 板块轮动
│   │   ├── etf/                       # ETF 分析
│   │   └── ...                        # 30+ 子模块
│   ├── dive_prediction/               # ETF 跳水预测（XGBoost）
│   ├── tests/                         # pytest 测试（41+ 个测试文件）
│   ├── frontend/                      # React + Vite 前端
│   │   └── src/pages/                 # Dashboard / Agent Console / 路线图 / 报告
│   ├── scripts/                       # 运维脚本
│   │   ├── pre-push.sh                # push 前审计 hook
│   │   ├── pre-commit.sh              # commit 前语法检查
│   │   ├── crontab/                   # 定时任务
│   │   └── windows/                   # Windows QMT 桥接
│   └── strategy_lab/                  # 策略实验室
├── data/                              # 数据存储
│   ├── market/                        # 行情数据
│   ├── fundamentals/                  # 基本面数据
│   ├── features/                      # 因子数据
│   ├── etf/                           # ETF 数据
│   ├── intraday/                      # 盘中快照
│   ├── positions/                     # 持仓数据
│   ├── events/                        # 事件数据
│   └── exports/                       # 导出数据
├── strategies/                        # 策略仓库
│   ├── active/                        # 活跃策略
│   ├── candidates/                    # 候选策略
│   ├── archived/                      # 归档策略
│   └── templates/                     # 策略模板
├── research_outputs/                  # 研究输出
│   ├── backtests/                     # 回测报告
│   ├── factor_ic/                     # IC 分析
│   ├── strategy_mining/               # 策略挖掘
│   └── strategy_review_material/      # 评审材料
├── docs/                              # 文档
│   ├── adr/                           # 架构决策记录
│   └── gitnexus-wiki/                 # GitNexus 知识图谱
├── agent_tasks/                       # 自动开发任务状态
│   ├── audit_reports/                 # 审计报告
│   ├── agent_logs/                    # Agent 日志
│   └── archive/                       # 归档
├── .hermes/                           # Hermes 配置
│   └── plans/                         # 实施计划（plan.md）
└── .venv_quant/                       # Python 虚拟环境
```

---

## 三、CLI 命令全表

### 行情 & 数据

| 命令 | 说明 |
|------|------|
| `market:update-daily` | 更新全 A 日 K |
| `market:update-live-snapshot` | 更新实时快照 |
| `fundamentals:update-from-baostock` | 更新 Baostock 基本面 |
| `data:freshness-check` | 检查数据新鲜度 |
| `data:quality-report` | 数据质量报告 |

### 妙想金融数据（东方财富）

| 命令 | 说明 |
|------|------|
| `mx:data <问句>` | 金融数据查询（行情/资金流/财务） |
| `mx:search <关键词>` | 资讯搜索（公告/新闻/研报/政策） |
| `mx:xuangu <条件>` | 智能选股（自然语言条件） |

### 个股分析

| 命令 | 说明 |
|------|------|
| `stock:context <股票代码>` | 读取个股全维度分析上下文 |

### 量化因子 & 回测

| 命令 | 说明 |
|------|------|
| `factor:list` | 列出所有因子 |
| `factor:mine [top_n]` | 因子挖掘 Agent |
| `factor:mine-register [top_n]` | 注册挖掘结果 |
| `factor:evolve` | LLM 生成新因子 |
| `factor:validate [--factor ret5]` | 因子完整稳健性验证 |
| `factor:batch [--factors f1,f2,...]` | 批量因子验证 → 排行榜 |
| `factor:composites [--candidate-pool PATH]` | 多因子组合验证 |
| `factor:orthogonality [--factors f1,f2,...]` | 因子正交性检验 |
| `backtest:factor-top <因子名> [--rebalance]` | 因子 Top 组分位数回测 |
| `backtest:walk-forward <因子名>` | Walk-Forward 样本外验证 |

### 盘前决策 & 交易

| 命令 | 说明 |
|------|------|
| `factor:strategies [--top-n 20]` | ret5 + 过滤器策略层验证 |
| `factor:signal [--signal-date latest]` | 盘前信号生成 |
| `factor:etf-selector [--capital 50000]` | ETF 选择器 |
| `factor:premarket [--capital 50000]` | 统一盘前决策报告 |
| `factor:daily-premarket [--date auto]` | 每日盘前编排（自动链） |
| `factor:order-preview --date --plan` | 委托预览 |
| `factor:approval --date --plan` | 风控审批 + Kill Switch |
| `factor:paper-trade --date --plan` | 模拟执行 |
| `factor:paper-review` | Paper 复盘 |
| `factor:paper-dashboard` | Paper 看板 |
| `factor:adaptive-recommend` | 策略参数自适应建议 |
| `factor:live-readiness` | 实盘前门禁检查 |
| `factor:rebalance-diff --date --positions --plan` | 调仓差异分析 |
| `factor:position-import --source` | 持仓导入 |
| `factor:decision-log --date --plan` | 人工决策记录 |
| `factor:review-decisions` | 决策复盘 |
| `factor:manual-approval` | 人工审批候选策略 |
| `factor:shadow-forward` | 影子前向测试 |
| `factor:paper-apply` | Paper Apply：候选→Paper |
| `factor:paper-promotion-review` | Paper 晋级评审 |

### QMT 桥接

| 命令 | 说明 |
|------|------|
| `broker:miniqmt-status` | 检查 miniQMT 只读状态 |
| `broker:qmt-health` | 检查 Windows QMT Bridge |
| `broker:qmt-account` | 拉取 QMT 账户资金 |
| `broker:qmt-positions` | 拉取 QMT 持仓 |
| `broker:qmt-orders` | 拉取 QMT 委托 |
| `broker:qmt-trades` | 拉取 QMT 成交 |
| `broker:qmt-sync` | 全量同步 |
| `broker:qmt-place-approved` | 从审批单发起 QMT 委托 |
| `broker:qmt-internal-*` | 大 QMT 内置执行器操作 |

### Alpha Factory (V3.x)

| 命令 | 说明 |
|------|------|
| `alpha:register --spec <path>` | 注册外部 AlphaSpec |
| `alpha:list` | 列出已注册 Alpha |
| `alpha:show --alpha-id <id>` | 查看 Alpha 详情 |
| `alpha:retire --alpha-id <id>` | 退役 Alpha |
| `alpha:evaluation-plan` | 生成评估计划 |
| `alpha:init-samples` | 初始化示例 Alpha |
| `alpha:migrate-existing-factors` | 因子目录迁移→Alpha Registry |
| `factor:sync [--dry-run]` | 因子→Alpha 同步 |
| `factor:list --alpha` | 统一视图（含 Alpha 状态） |

### 策略实验室

| 命令 | 说明 |
|------|------|
| `strategy-lab:init` | 初始化实验室目录 |
| `strategy-lab:build-universe` | 构建股票池 |
| `strategy-lab:mine-candidates` | 挖掘候选策略 |
| `strategy-lab:run-backtest` | 运行全部策略回测 |
| `strategy-lab:build-latest-signals` | 最新信号生成 |
| `strategy-lab:build-review-material` | 评审材料生成 |

### 策略报告

| 命令 | 说明 |
|------|------|
| `strategy:report [--from-portfolio-result]` | 生成策略报告 |
| `strategy:report-list` | 列出已生成报告 |
| `strategy:run-skill` | 通过 Research Skill 生成报告 |

### 知识库 & 研究循环

| 命令 | 说明 |
|------|------|
| `research:list-skills` | 列出投研 Skills |
| `research:show-skill --skill-id` | 查看 Skill 详情 |
| `research:run-skill --skill-id` | 执行投研 Skill |
| `research:run-history` | 执行历史 |
| `research:init-registry` | 初始化注册表 |
| `research:knowledge-list` | 列出知识条目 |
| `research:knowledge-add` | 添加知识条目 |
| `research:knowledge-search` | 搜索知识库 |
| `research:knowledge-stats` | 知识库统计 |
| `research:loop [--rounds 5]` | 自动因子研究循环 |
| `research:mcp [--port 8767]` | 启动 MCP 工具服务器 |

### 投资系统管理 (leader:*)

| 命令 | 说明 |
|------|------|
| `leader:automation-status` | 后台自动工作流健康检查 |
| `leader:roadmap-status` | 路线图进度 |
| `leader:auto-run-once` | 自动执行器：读取 cursor，执行当前版本 |
| `leader:auto-status` | 自动执行器详细状态 |
| `leader:dashboard [--port 8766]` | 启动 Dashboard + Agent Console |
| `leader:dashboard-json` | 输出 dashboard 状态 JSON |
| `leader:audit-and-push [--version] [--mode]` | ADR-022 审计 + git push |
| **`leader:anti-cheat-audit [--skip gate4]`** | **反偷工减料审计（4 闸门）** |
| `leader:lock-status` | 任务锁状态 |
| `leader:task-list` | 待办任务 |
| `leader:task-submit --text --title` | 提交新任务 |
| `leader:version-report` | 版本开发报告 |
| `leader:backup-list` | 备份列表 |
| `leader:recover --backup-id` | 恢复版本状态 |
| `leader:inspect` | 只读检查 |
| `leader:dispatch [--dry-run]` | 按路线图生成任务包 |
| `leader:accept [--full-tests]` | 自动验收 |
| `leader:github-sync` | 版本完成→提交→推送 |

### 后台任务

| 命令 | 说明 |
|------|------|
| `bg:list` | 列出所有后台任务 |
| `bg:status <id>` | 任务状态 |
| `bg:log <id> [--tail 100]` | 任务日志 |
| `bg:kill <id>` | 终止任务 |
| `bg:clean [--hours 168]` | 清理已完成任务 |

### 架构审计

| 命令 | 说明 |
|------|------|
| `architecture:audit` | 全局架构审计 |

---

## 四、核心工作流

### 4.1 每日盘前流程

```bash
# 1. 数据更新
hermes market:update-daily                          # 日K更新
hermes fundamentals:update-from-baostock             # 基本面更新

# 2. 盘前信号（自动链）
hermes factor:daily-premarket --date auto            # 信号+ETF+报告+推送
```

### 4.2 因子挖掘与验证

```bash
# 1. 因子挖掘
hermes factor:mine 20                                # 自动发现 Top-20
hermes factor:mine-register 20                       # 注册到因子库

# 2. 因子验证
hermes factor:validate --factor ret5                 # 单因子验证
hermes factor:batch --factors ret5,vol_ratio60       # 批量验证

# 3. 策略验证
hermes factor:strategies --top-n 20                  # 策略层验证
hermes factor:orthogonality --factors f1,f2          # 正交性检验
```

### 4.3 Paper Trading 流程

```bash
# 1. 信号生成
hermes factor:daily-premarket --date YYYY-MM-DD

# 2. 调仓分析
hermes factor:rebalance-diff --date YYYY-MM-DD --positions data/positions/current_positions.csv --plan B

# 3. 委托预览 + 审批
hermes factor:order-preview --date YYYY-MM-DD --plan B
hermes factor:approval --date YYYY-MM-DD --plan B

# 4. 模拟执行
hermes factor:paper-trade --date YYYY-MM-DD --plan B

# 5. 复盘
hermes factor:paper-review --start YYYY-MM-DD --end YYYY-MM-DD
```

### 4.4 自动版本开发 (Auto-Development)

系统按固定路线图自动推进版本（由 `auto_executor.py` 驱动）：

```bash
# 查看版本进度
hermes leader:roadmap-status
hermes leader:auto-status

# 手动触发一次版本推进
hermes leader:auto-run-once

# 启动 Dashboard
hermes leader:dashboard
```

每个版本的自动流程：
1. Task Intake → 读取路线图 cursor
2. Backend Policy → 选择编码后端
3. Agent Runner → Claude Code 开发
4. Test → pytest 验证
5. **ADR-022 审计** → `leader:audit-and-push`
6. **Anti-Cheat 审计** → `leader:anti-cheat-audit`（4 闸门）
7. Advance → 推进 cursor 到下一版本

### 4.5 交互式开发（无 plan 文件）

在日常对话中发开发需求时：

```
你: "帮我实现因子排序功能，按 IC 值降序"
Agent 会:
  1. 内部生成需求清单
  2. 开始实现
  3. 实现完毕 → 自动运行 anti-cheat 4 闸门
  4. 有 FAIL → 先修再报告完成
  5. 全部通过 → "已完成 ✅"
```

如需手动触发审计：

```bash
hermes leader:anti-cheat-audit --skip gate4
```

### 4.6 质量控制流程

```
开发完成
    ↓
requesting-code-review ← 独立 reviewer 审查 git diff
    ↓
leader:audit-and-push  ← ADR-022 语法/安全/进程检查
    ↓
leader:anti-cheat-audit ← 4 闸门：需求追溯/stub/测试/独立审计
    ↓
pytest                  ← 全量测试
    ↓
git push (pre-push hook 触发以上全部)
```

---

## 五、反偷工减料审计系统 (Anti-Cheat Audit)

### 5.1 4 道闸门

| 闸门 | 检测什么 | 技术手段 | 触发方式 |
|------|---------|---------|---------|
| **Gate 1** 需求→代码追溯 | plan 中的文件/函数是否真实存在 | Plan Markdown 解析 + git diff + 文件系统 | auto/CLI/pre-push |
| **Gate 2** 虚假实现检测 | pass/硬编码/return 常量/圈复杂度极低 | AST + radon + semgrep | auto/CLI/pre-push |
| **Gate 3** 测试覆盖检查 | 新代码是否有对应新测试 | AST 函数扫描 + pytest-cov | auto/CLI/pre-push |
| **Gate 4** 独立需求审计 | 第三方视角审查需求 vs 实现 | delegate_task + 规则引擎 | 仅 Agent 模式 |

### 5.2 使用方式

**方式 A: 自动（推荐）**
- auto_executor 在 version advance 前自动跑
- git push 时 pre-push hook 自动跑
- Agent 完成开发后自动跑

**方式 B: 手动 CLI**
```bash
hermes leader:anti-cheat-audit                    # 完整 3 闸门
hermes leader:anti-cheat-audit --skip gate2       # 跳过某闸门
hermes leader:anti-cheat-audit --version V3.1     # 指定版本
hermes leader:anti-cheat-audit --json             # JSON 输出
```

**方式 C: 阅读审计报告**
```bash
cat /home/ly/.hermes/research-assistant/agent_tasks/audit_reports/anti_cheat_latest.json
```

### 5.3 审计报告示例

```
═══ Anti-Cheat Audit Report ═══
Version: V3.1
Status:  ❌ FAIL
Gates:   gate1, gate2, gate3

  Gate 1 — 需求→代码追溯: 1 pass | 0 fail | 1 warn
  Gate 2 — 虚假实现检测: 1 pass | 0 fail | 3 warn
  Gate 3 — 测试覆盖检查: 1 pass | 6 fail | 0 warn

❌ FAIL Items:
  ❌ [gate3/NO_TEST_FILE] commands/foo.py — 没有对应测试文件
  ❌ [gate3/NO_TEST_FILE] commands/bar.py — 没有对应测试文件
⚠️ WARN Items:
  ⚠️ [gate2/STUB_TOO_SIMPLE] commands/bar.py:42 — 函数名暗示复杂逻辑但仅 1 条语句
```

---

## 六、配套 Skill 使用指引

<!-- USAGE_GUIDE_START -->
| Skill | 什么时候用 | 怎么用 |
|-------|-----------|--------|
| `a-share-data-collector` | A 股 L0 数据采集 | Agent 自动按策略调用 |
| `a-share-data-quality` | 数据质量审计 | Agent 自动按策略调用 |
| `a-share-intraday-monitor` | 盘中实时监测 | Agent 自动按策略调用 |
| `anti-cheat-audit` | 开发完成后防偷工减料 | `hermes leader:anti-cheat-audit` |
| `auto-development-orchestration` | 了解自动开发架构 | `load skill auto-development-orchestration` |
| `etf-dive-warning` | ETF 跳水风险预警 | Agent 自动盘前/盘中运行 |
| `factor-lab` | 因子挖掘、IC 分析 | `factor:mine` / `factor:validate` |
| `factor-mining` | 50+ 因子计算、盘前信号 | `factor:list` / `factor:signal` |
| `hermes-agent` | 配置 Hermes Agent 自身 | `hermes config set ...` |
| `hermes-daemon` | WSL 守护进程管理 | `bash ~/.hermes/hermes-daemon.sh start` |
| `leader-driven-automation` | 系统按路线图自动开发 | `hermes leader:auto-run-once` |
| `mx-data` | 东方财富数据查询 | `mx:data <问句>` |
| `mx-search` | 资讯搜索（公告/新闻/研报） | `mx:search <关键词>` |
| `mx-xuangu` | 智能选股（自然语言条件） | `mx:xuangu <条件>` |
| `plan` | 复杂任务需要先写计划 | Agent 自动加载：`/plan "实现因子排序"` |
| `requesting-code-review` | 开发完成准备提交 | Agent 自动在 git commit 前调用 |
| `requirement-traceability` | 需求确认后跟踪实现 | Agent 自动在 grilling 后产出清单 |
| `simplify-code` | 代码太乱需要清理 | `load skill simplify-code` → 描述问题 |
| `spike` | 需要快速验证技术方案 | `/spike "验证 jqdata 的 K 线接口"` |
| `stock-analyst` | 个股全维度分析 | `stock:context` + Agent 自动调用 |
| `subagent-output-verification` | delegate_task 完成 | Agent 自动验证子任务输出 |
| `system-audit` | 需要全面检查系统健康 | `run full audit`（7 Phase） |
| `systematic-debugging` | 根因分析复杂 Bug | Agent 自动按 4 阶段排查 |
| `test-driven-development` | 新功能的开发过程 | Agent 自动遵守 RED-GREEN-REFACTOR |
| `workloop-automation` | 需要派发任务给 Agent | `leader:dispatch` |
<!-- USAGE_GUIDE_END -->

---

## 七、环境信息

| 项目 | 值 |
|------|-----|
| 系统 | WSL (Ubuntu) on Windows |
| Python | 3.14.4 (venv: `.venv_quant`) |
| CLI 入口 | `commands/hermes_cli.py` |
| Venv 路径 | `/home/ly/.hermes/research-assistant/.venv_quant` |
| Dashboard | `http://127.0.0.1:8766` (FastAPI) |
| MCP Server | `:8767` (stdio/HTTP) |
| 企业微信推送 | `$WECHAT_WEBHOOK_URL` (在 `.bashrc`) |
| 数据盘 | `/mnt/d/HermesReports/` |
| 守护进程 | `~/.hermes/hermes-daemon.sh` (tmux 3 窗口) |
| 任务状态 | `agent_tasks/latest.json` (Hermes cron 驱动) |
| 版本游标 | `agent_tasks/roadmap_cursor.json` |
| 测试命令 | `cd commands && .venv_quant/bin/python3 -m pytest ...` |
| 数据发布 | `ashare-package-publisher` skill（原子写入） |

---

> 本手册由 Hermes Agent 自动维护。`skill_view(name='skill-name')` 可查看每个 Skill 的完整文档。
