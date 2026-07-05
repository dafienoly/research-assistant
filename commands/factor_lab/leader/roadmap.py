"""V3+ Alpha Factory roadmap.

路线原则：V3 不再按“新增某类因子”排版本，而是按 Alpha Factory
生命周期排版本。原 P0/P1/P2/P3 因子方向统一挂到 V3 Alpha Factory
之下，避免继续堆 V2.x 功能。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

TradingMode = Literal["none", "paper", "human_controlled_live"]


@dataclass(frozen=True)
class RoadmapItem:
    version: str
    name: str
    objective: str
    trading_mode: TradingMode
    stage_gate: str
    owner_role: str
    required_outputs: tuple[str, ...]
    acceptance: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


ALPHA_FACTORY_ROADMAP: tuple[RoadmapItem, ...] = (
    RoadmapItem(
        version="V3.0",
        name="Alpha Factory Foundation",
        objective="建立 AlphaSpec、AlphaRegistry、生命周期、样例 Alpha，形成 Alpha 工厂底座。",
        trading_mode="none",
        stage_gate="foundation_ready",
        owner_role="foundation_engineer",
        required_outputs=("AlphaSpec", "AlphaRegistry", "Lifecycle", "SampleAlphas", "Alpha CLI"),
        acceptance=(
            "所有 Alpha 默认 enabled=false / paper_enabled=false / live_enabled=false",
            "注册、列表、查看、退役、评估计划可运行",
            "输出 manifest 与 audit，不调用 broker/miniqmt",
        ),
    ),
    RoadmapItem(
        version="V3.0.1",
        name="Existing Factor Catalog Migration",
        objective="把现有因子目录纳入 Alpha Registry，形成可治理、可审计的 Alpha Catalog。",
        trading_mode="none",
        stage_gate="catalog_migrated",
        owner_role="migration_engineer",
        required_outputs=("factor_catalog_registry.csv", "factor_migration_report.html", "factor_migration_summary.md"),
        acceptance=(
            "现有 factor_base 注册表中的因子全部生成 AlphaSpec 或明确 skipped/duplicate 原因",
            "迁移过程不触发回测、不修改 paper/live 配置、不调用交易接口",
            "重复迁移幂等：重复运行只记录 duplicates，不重复污染 registry",
        ),
    ),
    RoadmapItem(
        version="V3.1",
        name="Industry Relative Alpha Pack",
        objective="实现行业相对、行业中性、行业内排序 Alpha Pack。",
        trading_mode="none",
        stage_gate="industry_relative_alpha_ready",
        owner_role="alpha_engineer",
        required_outputs=("industry_relative_alpha_specs", "industry_neutralization_report", "industry_rank_report"),
        acceptance=(
            "AlphaSpec 只描述信号，不直接写入策略配置",
            "行业暴露、行业内排序、行业中性处理均有报告和测试",
            "每个 Alpha 都进入 Alpha Registry，默认 disabled",
        ),
    ),
    RoadmapItem(
        version="V3.2",
        name="Factor Evaluation & Orthogonality",
        objective="统一 IC、ICIR、相关性、行业暴露、OOS、Walk Forward 与评估门禁。",
        trading_mode="none",
        stage_gate="evaluation_gate_ready",
        owner_role="evaluation_engineer",
        required_outputs=("evaluation_pipeline", "orthogonality_matrix", "walk_forward_report", "gate_report"),
        acceptance=(
            "所有评估结果绑定 alpha_id/run_id/manifest/audit",
            "相关性、行业暴露、OOS、Walk Forward 可作为 GateEngine 输入",
            "报告区分 passed/warning/blocker，禁止 silent fallback",
        ),
    ),
    RoadmapItem(
        version="V3.3",
        name="Data Enrichment Alpha Pack",
        objective="接入北向、两融、资金流等增强数据，生成可审计 AlphaSpec。",
        trading_mode="none",
        stage_gate="data_enrichment_ready",
        owner_role="data_alpha_engineer",
        required_outputs=("northbound_alpha_specs", "margin_alpha_specs", "fund_flow_alpha_specs", "data_coverage_report"),
        acceptance=(
            "所有增强数据有 freshness/coverage/as-of 校验",
            "历史不足的数据标记 pending，不伪造回测结论",
            "Alpha 默认 disabled，不进入实盘链路",
        ),
    ),
    RoadmapItem(
        version="V3.4",
        name="Technical Pattern Control Pack",
        objective="把 MACD/KDJ/Bollinger 作为对照和冗余检测工具，而非核心预测因子。",
        trading_mode="none",
        stage_gate="technical_control_ready",
        owner_role="control_alpha_engineer",
        required_outputs=("technical_control_specs", "redundancy_report", "benchmark_comparison_report"),
        acceptance=(
            "技术指标只作为 control/baseline/redundancy 检测",
            "不得把常见技术形态直接包装为高置信 Alpha",
            "输出与现有 Alpha 的相关性和增量价值判断",
        ),
    ),
    RoadmapItem(
        version="V3.5",
        name="Event-driven Alpha Pack",
        objective="围绕解禁、回购、分红、业绩预告等事件构建事件驱动 Alpha。",
        trading_mode="none",
        stage_gate="event_alpha_ready",
        owner_role="event_alpha_engineer",
        required_outputs=("event_alpha_specs", "event_calendar", "event_study_report"),
        acceptance=(
            "事件日期、公告日期、可交易日期必须分离，避免未来函数",
            "事件窗口收益、覆盖率、缺失率均入报告",
            "所有信号只注册/评估，不自动交易",
        ),
    ),
    RoadmapItem(
        version="V3.6",
        name="Alpha Portfolio Intelligence",
        objective="实现多 Alpha 组合、淘汰、降权、晋级与 Paper 组合治理。",
        trading_mode="paper",
        stage_gate="paper_portfolio_ready",
        owner_role="portfolio_engineer",
        required_outputs=("alpha_portfolio_engine", "promotion_policy", "deweight_retire_report"),
        acceptance=(
            "只允许进入 Paper，不直接进入 live",
            "组合权重、淘汰、降权、晋级均需人审 Gate",
            "所有变更有 rollback 与 audit trail",
        ),
    ),
    RoadmapItem(
        version="V3.7",
        name="LLM Alpha Discovery",
        objective="让 LLM 生成 AlphaSpec 候选，不直接写策略代码或实盘策略。",
        trading_mode="none",
        stage_gate="llm_alpha_spec_ready",
        owner_role="llm_alpha_researcher",
        required_outputs=("llm_alpha_spec_generator", "candidate_review_queue", "prompt_audit"),
        acceptance=(
            "LLM 只能输出 AlphaSpec 草案，不直接改策略配置",
            "每个候选必须附 hypothesis/evidence/risk_notes",
            "候选进入人工 review queue 后才可注册",
        ),
    ),
    RoadmapItem(
        version="V4.0",
        name="Controlled Live Alpha Pipeline",
        objective="通过 V2 治理链路后进入小权限、可回滚、人工确认的实盘 Alpha Pipeline。",
        trading_mode="human_controlled_live",
        stage_gate="controlled_live_gate_ready",
        owner_role="live_governance_engineer",
        required_outputs=("controlled_live_gate", "kill_switch", "human_confirm_workflow", "live_audit_report"),
        acceptance=(
            "必须经过 V2 风控/审批/审计链路",
            "实盘只能小权限、人工确认、可回滚",
            "任何自动下单默认禁止，除非显式通过 Controlled Live Gate",
        ),
    ),
)


def roadmap_as_dicts() -> list[dict]:
    return [item.to_dict() for item in ALPHA_FACTORY_ROADMAP]


def find_roadmap_item(version: str) -> RoadmapItem | None:
    return next((item for item in ALPHA_FACTORY_ROADMAP if item.version == version), None)
