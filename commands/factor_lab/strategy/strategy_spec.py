"""策略规格定义 — ret5 过滤策略的配置化描述

每个策略定义包含:
  - name: 唯一名称
  - factors: [主因子, 过滤因子...]
  - filter_type: gate/vol/turn/crowding/regime/combined
  - params: 参数
  - execution: 交易约束
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategySpec:
    name: str
    description: str
    factor_names: list  # [主因子, 过滤因子1, 过滤因子2, ...]
    filter_type: str = "none"  # none/gate/vol/turn/crowding/regime/combined
    filter_params: dict = field(default_factory=dict)
    top_n: int = 20
    rebalance: str = "monthly"
    execution_aware: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "factor_names": self.factor_names,
            "filter_type": self.filter_type,
            "filter_params": self.filter_params,
            "top_n": self.top_n,
            "rebalance": self.rebalance,
            "execution_aware": self.execution_aware,
        }


# 默认策略列表
DEFAULT_STRATEGIES = [
    StrategySpec("ret5_baseline", "ret5 单因子基线 (Top20 月调仓)", ["ret5"]),
    StrategySpec("ret5_ma20_gate", "ret5 + close_gt_ma20 门控",
                 ["ret5", "close_gt_ma20"], "gate",
                 {"gate_threshold": 0, "penalty_value": -999}),
    StrategySpec("ret5_low_vol", "ret5 + 排除高波动 (volatility20 top20%)",
                 ["ret5", "volatility20"], "vol_filter",
                 {"exclude_top_pct": 0.2}),
    StrategySpec("ret5_liquidity", "ret5 + 排除低流动+高换手",
                 ["ret5"], "turn_filter",
                 {"exclude_low_pct": 0.2, "exclude_high_pct": 0.95}),
    StrategySpec("ret5_crowding", "ret5 + 排除异常放量 (vol_ratio20 top20%)",
                 ["ret5", "vol_ratio20"], "crowding_filter",
                 {"exclude_top_pct": 0.2}),
    StrategySpec("ret5_regime", "ret5 + 市场趋势过滤 (HS300 MA20)",
                 ["ret5"], "regime_filter",
                 {"regime_type": "hs300_ma20"}),
    StrategySpec("ret5_combined", "ret5 + ma20门控 + 低波动 + 低流动",
                 ["ret5", "close_gt_ma20", "volatility20"], "combined",
                 {}),
]


def get_strategy(name: str) -> Optional[StrategySpec]:
    for s in DEFAULT_STRATEGIES:
        if s.name == name:
            return s
    return None
