"""Alpha Schema V3.0 — Alpha 规格定义"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, field

CST = timezone(timedelta(hours=8))


@dataclass
class AlphaSpec:
    alpha_id: str = ""
    name: str = ""
    description: str = ""
    hypothesis: str = ""
    universe: str = "all_watchlist"
    data_requirements: list = field(default_factory=lambda: ["close", "volume", "amount"])
    factor_expression: str = ""
    signal_direction: str = "long"  # long / short / long_short
    rebalance_frequency: str = "monthly"
    risk_constraints: dict = field(default_factory=lambda: {"max_position_weight": 0.25, "max_drawdown": 0.15})
    author: str = "system"
    source: str = "manual"
    version: str = "0.0.1"
    status: str = "draft"
    enabled: bool = False
    paper_enabled: bool = False
    live_enabled: bool = False
    created_at: str = ""
    updated_at: str = ""
    tags: list = field(default_factory=list)

    # 自动管线扩展字段
    last_validated: str = ""          # 上次验证日期 ISO
    shadow_status: str = "pending"    # pending / observing / available / unstable
    shadow_start: str = ""            # 影子观察开始日期
    shadow_end: str = ""              # 影子观察结束日期
    ic_decay_rate: float = 0.0        # IC 衰减率 (0~1)
    holding_period: int = 5           # 持仓周期（交易日）
    validation_history: list = field(default_factory=list)  # [{date, ic, sharpe}]

    # V3.2.5 新增 — 扩展元数据
    delay: int = 0
    cost_assumption: dict = field(default_factory=lambda: {
        "commission": 0.0003,
        "slippage_bps": 10,
        "min_commission": 5.0,
        "stamp_tax_sell": 0.001,
    })
    valid_period: str = ""
    audit_log: list = field(default_factory=list)
    ic_mean_history: list = field(default_factory=list)
    peer_benchmark_result: dict = field(default_factory=dict)

    # V4.6 LLM Alpha Factory 新增 — 试验计数与归因
    trial_count: int = 0              # 尝试次数（+1 每次生成/迭代）
    parent_factor_id: str = ""        # 父代因子 ID（演化来源）
    failure_reason: str = ""          # 失败原因（若被淘汰）
    next_iteration_suggestion: str = ""  # 下一代建议
    industry_hypothesis: str = ""     # 产业假设
    non_pv_fields_used: list = field(default_factory=list)  # 使用的非价量字段列表
