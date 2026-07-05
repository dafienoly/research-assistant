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
