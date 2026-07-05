"""Roadmap — 固定产品路线图 V3-V9"""
ROADMAP = []

def _load():
    global ROADMAP
    if ROADMAP:
        return ROADMAP
    # V3.x
    for i, (v, n, o) in enumerate([
        ("V3.0", "Alpha Factory Foundation", "建立 AlphaSpec、AlphaRegistry、Lifecycle、CLI"),
        ("V3.0.1", "Existing Factor Catalog Migration", "迁移现有因子到 Alpha Registry"),
        ("V3.1", "Industry Relative Alpha Pack", "行业相对、行业中性 Alpha"),
        ("V3.2", "Factor Evaluation & Orthogonality", "IC/ICIR/OOS/Walk Forward"),
        ("V3.3", "Data Enrichment Alpha Pack", "北向、两融、资金流增强 Alpha"),
        ("V3.4", "Technical Pattern Control Pack", "MACD/KDJ/Boll as control"),
        ("V3.5", "Event-driven Alpha Pack", "解禁、回购、分红事件 Alpha"),
        ("V3.6", "Alpha Portfolio Intelligence", "多 Alpha 组合、降权、淘汰"),
        ("V3.7", "LLM Alpha Discovery", "LLM 生成 AlphaSpec 候选"),
        ("V3.8", "Alpha Review Queue & Governance", "候选审核、证据、风险"),
        ("V3.9", "Alpha Promotion/Retirement Engine", "Alpha 晋级、退役治理"),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": False, "trading_mode": "none"})
    # V4.x
    for i, (v, n, o, m) in enumerate([
        ("V4.0", "Controlled Live Pipeline Design", "受控实盘管线设计", False),
        ("V4.1", "Shadow Live Pipeline", "影子实盘/模拟实盘", False),
        ("V4.2", "Broker Adapter Contract & Sandbox", "broker 合约", False),
        ("V4.3", "Order Preview/Rebalance/Approval", "订单预览、审批", False),
        ("V4.4", "Kill Switch / Risk Sentinel", "熔断、风险哨兵", False),
        ("V4.5", "Human Approval Workflow", "审批工作流", False),
        ("V4.6", "Live Audit/Rollback/Incident", "审计回滚", False),
        ("V4.7", "MiniQMT Adapter Hardening", "MiniQMT 加固", False),
        ("V4.8", "Capital Safety Boundary", "资金安全边界", False),
        ("V4.9", "Controlled Live Readiness Report", "实盘就绪报告", True),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": m, "trading_mode": "sandbox_only"})
    # V5.x
    for i, (v, n, o) in enumerate([
        ("V5.0", "Data Source Registry", "数据源注册表"),
        ("V5.1", "AkShare/BaoStock Provider", "免费数据源 Provider"),
        ("V5.2", "Realtime Quote Ingest", "实时行情"),
        ("V5.3", "Minute/Daily Bar Storage", "分钟线日线存储"),
        ("V5.4", "Data Quality Gate", "数据质量门禁"),
        ("V5.5", "No-Fallback Data Contract", "禁止 fallback"),
        ("V5.6", "Data Lineage/Manifest/Audit", "数据血缘"),
        ("V5.7", "Market Calendar Engine", "交易日历"),
        ("V5.8", "Data Health Dashboard", "数据健康"),
        ("V5.9", "Paid Provider Readiness", "付费数据源预留"),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": False, "trading_mode": "none"})
    # V6.x
    for i, (v, n, o) in enumerate([
        ("V6.0", "Research Skill Runtime", "投研 skill 运行时"),
        ("V6.1", "Strategy Template Registry", "策略模板注册表"),
        ("V6.2", "Backtest Engine Integration", "回测引擎"),
        ("V6.3", "Walk Forward/OOS/Anti-overfit", "反过拟合门禁"),
        ("V6.4", "Portfolio Backtest/Benchmark", "组合回测"),
        ("V6.5", "Strategy Report Generator", "策略报告"),
        ("V6.6", "Factor Mining Agent", "因子挖掘 Agent"),
        ("V6.7", "News/Policy/Event Research", "事件研究"),
        ("V6.8", "A-share Sector Rotation", "行业轮动"),
        ("V6.9", "Strategy Promotion Board", "策略晋级"),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": False, "trading_mode": "none"})
    # V7.x
    for i, (v, n, o) in enumerate([
        ("V7.0", "Modern Frontend Dashboard", "前端总览"),
        ("V7.1", "Data Status/Provider Failure UI", "数据状态 UI"),
        ("V7.2", "AgentOps Control Tower", "控制塔"),
        ("V7.3", "Task Queue/Run History/Logs", "任务队列"),
        ("V7.4", "Roadmap Progress UI", "路线图进度"),
        ("V7.5", "Report Center", "报告中心"),
        ("V7.6", "Risk Dashboard", "风险仪表盘"),
        ("V7.7", "Paper Trading Dashboard", "纸面交易"),
        ("V7.8", "User Feedback/Task Intake UI", "用户反馈 UI"),
        ("V7.9", "One-click Local Ops", "一键运维"),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": False, "trading_mode": "none"})
    # V8.x
    for i, (v, n, o) in enumerate([
        ("V8.0", "Agent Role Registry", "角色注册"),
        ("V8.1", "Agent Router", "Agent 路由"),
        ("V8.2", "Auto Bugfix Loop", "自动 bugfix"),
        ("V8.3", "Regression Test Planner", "回归测试"),
        ("V8.4", "GitHub Issue/PR Pipeline", "Issue/PR 流水线"),
        ("V8.5", "Documentation Generator", "文档生成"),
        ("V8.6", "Release Manager", "发布管理"),
        ("V8.7", "Self-Diagnostics", "自诊断"),
        ("V8.8", "Cost/Token/Backend Policy", "成本策略"),
        ("V8.9", "Continuous Improvement Engine", "持续改进"),
    ]):
        ROADMAP.append({"version": v, "name": n, "objective": o, "auto_allowed": True, "manual_required": False, "trading_mode": "none"})
    # V9.x (backlog)
    for v, n in [("V9.0","Cloud/Local Hybrid Runner"),("V9.1","Distributed Backtest"),("V9.2","Multi-account Governance"),("V9.3","External Notification Center"),("V9.4","Enterprise-grade Audit")]:
        ROADMAP.append({"version": v, "name": n, "objective": "backlog", "auto_allowed": False, "manual_required": True, "trading_mode": "backlog"})
    return ROADMAP

def get_roadmap():
    return _load()

def get_version(ver):
    for r in _load():
        if r["version"] == ver:
            return r
    return None

def next_version(current):
    items = _load()
    for i, item in enumerate(items):
        if item["version"] == current and i+1 < len(items):
            return items[i+1]
    return None

def is_backlog(ver):
    r = get_version(ver)
    return r and r.get("trading_mode") == "backlog"

# Backward compatibility for planner.py
ALPHA_FACTORY_ROADMAP = [r["version"] for r in _load()]
def roadmap_as_dicts():
    return _load()
