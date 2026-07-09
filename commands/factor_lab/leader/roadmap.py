"""Roadmap — 固定产品路线图 V3-V9"""
from dataclasses import dataclass


@dataclass
class RoadmapItem:
    version: str
    name: str
    objective: str
    auto_allowed: bool = True
    manual_required: bool = False
    trading_mode: str = "none"
    description: str = ""  # 详细任务描述，用于 agent-runner prompt


ROADMAP_ITEMS = []

def _build():
    global ROADMAP_ITEMS
    if ROADMAP_ITEMS:
        return ROADMAP_ITEMS
    items = [
        # V3.x
        RoadmapItem("V3.0", "Alpha Factory Foundation", "建立 AlphaSpec、AlphaRegistry、Lifecycle、CLI"),
        RoadmapItem("V3.0.1", "Existing Factor Catalog Migration", "迁移现有因子到 Alpha Registry"),
        RoadmapItem("V3.1", "Industry Relative Alpha Pack", "行业相对、行业中性 Alpha"),
        RoadmapItem("V3.2", "Factor Evaluation & Orthogonality", "IC/ICIR/OOS/Walk Forward"),
        RoadmapItem("V3.3", "Data Enrichment Alpha Pack", "北向、两融、资金流增强 Alpha"),
        RoadmapItem("V3.4", "Technical Pattern Control Pack", "MACD/KDJ/Boll as control"),
        RoadmapItem("V3.5", "Event-driven Alpha Pack", "解禁、回购、分红事件 Alpha"),
        RoadmapItem("V3.6", "Alpha Portfolio Intelligence", "多 Alpha 组合、降权、淘汰", trading_mode="paper"),
        RoadmapItem("V3.7", "LLM Alpha Discovery", "LLM 生成 AlphaSpec 候选"),
        RoadmapItem("V3.8", "Alpha Review Queue & Governance", "候选审核、证据、风险"),
        RoadmapItem("V3.9", "Alpha Promotion/Retirement Engine", "Alpha 晋级、退役治理"),
        # V4.x
        RoadmapItem("V4.0", "Controlled Live Pipeline Design", "受控实盘管线设计", trading_mode="human_controlled_live"),
        RoadmapItem("V4.1", "Shadow Live Pipeline", "影子实盘/模拟实盘", trading_mode="sandbox_only"),
        RoadmapItem("V4.2", "Broker Adapter Contract & Sandbox", "broker 合约", trading_mode="sandbox_only"),
        RoadmapItem("V4.3", "Order Preview/Rebalance/Approval", "订单预览、审批", manual_required=False),
        RoadmapItem("V4.4", "Manual Confirmation Checklist", "手动确认清单", manual_required=False),
        RoadmapItem("V4.5", "Human Approval Workflow", "审批工作流", manual_required=False),
        RoadmapItem("V4.6", "Trade Filter & Slippage Control", "交易过滤", manual_required=False),
        RoadmapItem("V4.7", "Order Book & Deep Execution Route", "订单簿", manual_required=False),
        RoadmapItem("V4.8", "Capital Safety Boundary", "资金安全边界", manual_required=False),
        RoadmapItem("V4.9", "Controlled Live Readiness Report", "实盘就绪报告", manual_required=True, trading_mode="none"),
        # V5.x
        RoadmapItem("V5.0", "Data Source Registry", "数据源注册表"),
        RoadmapItem("V5.1", "AkShare/BaoStock Provider", "免费数据源 Provider"),
        RoadmapItem("V5.2", "Realtime Quote Ingest", "实时行情"),
        RoadmapItem("V5.3", "Minute/Daily Bar Storage", "分钟线日线存储"),
        RoadmapItem("V5.4", "Data Quality Gate", "数据质量门禁"),
        RoadmapItem("V5.5", "No-Fallback Data Contract", "禁止 fallback"),
        RoadmapItem("V5.6", "Data Lineage/Manifest/Audit", "数据血缘"),
        RoadmapItem("V5.7", "Market Calendar Engine", "交易日历"),
        RoadmapItem("V5.8", "Data Health Dashboard", "数据健康"),
        RoadmapItem("V5.9", "Paid Provider Readiness", "付费数据源预留"),
        # V6.x
        RoadmapItem("V6.0", "Research Skill Runtime", "投研 skill 运行时"),
        RoadmapItem("V6.1", "Strategy Template Registry", "策略模板注册表"),
        RoadmapItem("V6.2", "Backtest Engine Integration", "回测引擎"),
        RoadmapItem("V6.3", "Walk Forward/OOS/Anti-overfit", "反过拟合门禁"),
        RoadmapItem("V6.4", "Portfolio Backtest/Benchmark", "组合回测"),
        RoadmapItem("V6.5", "Strategy Report Generator", "策略报告"),
        RoadmapItem("V6.6", "Factor Mining Agent", "因子挖掘 Agent"),
        RoadmapItem("V6.7", "News/Policy/Event Research", "事件研究"),
        RoadmapItem("V6.8", "A-share Sector Rotation", "行业轮动"),
        RoadmapItem("V6.9", "Strategy Promotion Board", "策略晋级"),
        # V7.x
        RoadmapItem("V7.0", "Modern Frontend Dashboard", "前端总览"),
        RoadmapItem("V7.1", "Data Status/Provider Failure UI", "数据状态 UI"),
        RoadmapItem("V7.2", "AgentOps Control Tower", "控制塔"),
        RoadmapItem("V7.3", "Task Queue/Run History/Logs", "任务队列"),
        RoadmapItem("V7.4", "Roadmap Progress UI", "路线图进度"),
        RoadmapItem("V7.5", "Report Center", "报告中心"),
        RoadmapItem("V7.6", "Risk Dashboard", "风险仪表盘"),
        RoadmapItem("V7.7", "Paper Trading Dashboard", "纸面交易", description="创建纸面交易（Paper Trading）前端页面：模拟交易仪表盘，包含虚拟账户余额、持仓列表、模拟下单表单、历史成交记录。后端需要 PaperTradingService 管理虚拟订单簿和成交模拟。新增 routes_paper.py、PaperDashboard.jsx、paper_trading_service.py，26+ 测试。"),
        RoadmapItem("V7.8", "User Feedback/Task Intake UI", "用户反馈 UI", description="用户反馈提交和任务录入前端页面：FeedbackForm 组件、TaskIntake 页面、反馈列表/状态追踪。后端新增强 routes_feedback.py、feedback_store.py。前端页面 Feedback.jsx、TaskIntake.jsx。20+ 测试。"),
        RoadmapItem("V7.9", "One-click Local Ops", "一键运维", description="一键运维脚本和前端页面：本地环境健康检查、一键重启/部署/备份。新增 ops_dashboard.py、routes_ops.py、OpsCenter.jsx。Shell 脚本整合。15+ 测试。"),
        # V8.x
        RoadmapItem("V8.0", "Agent Role Registry", "角色注册", description="Agent 角色注册表：定义 Agent 角色 Schema、注册/发现 API、角色分配策略。新增 agent_registry.py、routes_agents.py、AgentRegistry.jsx。20+ 测试。"),
        RoadmapItem("V8.1", "Agent Router", "Agent 路由", description="Agent 任务路由系统：根据角色和能力将任务分发到合适的 Agent 后端。新增 agent_router.py、路由策略配置、调度日志。20+ 测试。"),
        RoadmapItem("V8.2", "Auto Bugfix Loop", "自动 bugfix", description="自动 Bug 修复循环：监听测试失败 → 分析错误 → Claude Code 修复 → 重跑测试。新增 auto_bugfix.py、regression_tracker.py。15+ 测试。"),
        RoadmapItem("V8.3", "Regression Test Planner", "回归测试", description="回归测试规划器：分析代码变更影响范围 → 自动选择相关测试 → 生成测试计划。新增 regress_planner.py、impact_analyzer.py。20+ 测试。"),
        RoadmapItem("V8.4", "GitHub Issue/PR Pipeline", "Issue/PR 流水线", description="GitHub Issue/PR 自动流水线：监控 Issue → 自动分析 → 创建 PR → 代码审查 → 合并。新增 github_pipeline.py、pr_manager.py。25+ 测试。"),
        RoadmapItem("V8.5", "Documentation Generator", "文档生成", description="自动文档生成器：从代码注释和模块结构自动生成项目文档网站。新增 doc_generator.py、docs 模板。15+ 测试。"),
        RoadmapItem("V8.6", "Release Manager", "发布管理", description="版本发布管理器：版本号管理、CHANGELOG 生成、发布包构建。新增 release_manager.py、routes_release.py。15+ 测试。"),
        RoadmapItem("V8.7", "Self-Diagnostics", "自诊断", description="系统自诊断面板：组件健康检查、性能指标、错误聚合、依赖版本检查。新增 self_diagnose.py、Diagnostics.jsx。20+ 测试。"),
        RoadmapItem("V8.8", "Cost/Token/Backend Policy", "成本策略", description="API 成本和 token 使用策略管理：用量追踪、预算告警、后端切换策略。新增 cost_tracker.py、routes_cost.py。15+ 测试。"),
        RoadmapItem("V8.9", "Continuous Improvement Engine", "持续改进", description="持续改进引擎：分析过往版本失败模式 → 自动调整流程参数 → 优化 prompt。新增 improvement_engine.py。15+ 测试。"),
        # V9.x backlog → 已激活
        RoadmapItem("V9.0", "Cloud/Local Hybrid Runner", "云端+本地混合 Agent 执行环境",
                    auto_allowed=True, manual_required=False, trading_mode="none",
                    description="实现混合运行环境：云端执行重计算任务（回测/因子挖掘），本地执行轻量任务（CLI/快速验证）。"
                              "新增 hybrid_runner.py、routes_hybrid.py、对应前端页面。20+ 测试。"),
        RoadmapItem("V9.1", "Distributed Backtest", "分布式并行回测引擎",
                    auto_allowed=True, manual_required=False, trading_mode="none",
                    description="分布式回测引擎：任务分片 → 多机并行 → 结果聚合。支持多标的/多参数并行回测。"
                              "新增 distributed_backtest.py、worker_manager.py。20+ 测试。"),
        RoadmapItem("V9.2", "Multi-account Governance", "多账户治理与风控",
                    auto_allowed=True, manual_required=False, trading_mode="none",
                    description="多账户统一管理：账户注册、权限控制、独立风控策略、仓位汇总。"
                              "新增 account_registry.py、routes_accounts.py、前端账户管理页。20+ 测试。"),
        RoadmapItem("V9.3", "External Notification Center", "外部通知中心（Telegram/短信/邮件）",
                    auto_allowed=True, manual_required=False, trading_mode="none",
                    description="多渠道通知：Telegram/短信/邮件推送。通知模板、频率控制、告警规则。"
                              "新增 notification_center.py、routes_notify.py、前端通知配置页。20+ 测试。"),
        RoadmapItem("V9.4", "Enterprise-grade Audit", "企业级审计日志系统",
                    auto_allowed=True, manual_required=False, trading_mode="none",
                    description="全量操作审计：不可篡改日志、操作回放、合规报告。"
                              "新增 audit_logger.py、routes_audit.py、前端审计查询页。20+ 测试。"),
    ]
    ROADMAP_ITEMS = items
    return items


# Public API
ALPHA_FACTORY_ROADMAP = _build()

def roadmap_as_dicts():
    return [{"version": r.version, "name": r.name, "objective": r.objective,
             "auto_allowed": r.auto_allowed, "manual_required": r.manual_required,
             "trading_mode": r.trading_mode} for r in ALPHA_FACTORY_ROADMAP]

def get_roadmap():
    return ALPHA_FACTORY_ROADMAP

def get_version(ver):
    for r in ALPHA_FACTORY_ROADMAP:
        if r.version == ver:
            return r
    return None

def next_version(current):
    for i, r in enumerate(ALPHA_FACTORY_ROADMAP):
        if r.version == current and i+1 < len(ALPHA_FACTORY_ROADMAP):
            return ALPHA_FACTORY_ROADMAP[i+1]
    return None

def is_backlog(ver):
    r = get_version(ver)
    return bool(r and r.trading_mode == "backlog" if hasattr(r, 'trading_mode') else False)
