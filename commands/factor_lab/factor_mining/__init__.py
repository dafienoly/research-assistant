"""Factor Mining Agent V6.6 — 因子挖掘 Agent

Factor Mining Agent 是一个可编程的因子自动发现系统，能够：
  1. 分析已有因子注册表，发现覆盖不足的领域
  2. 基于数据驱动方法生成新的因子候选
  3. 通过 IC/ICIR/Walk-Forward 快速验证候选因子
  4. 报告挖掘结果，支持将优质因子注册到正式注册表

模块结构:
  candidate_generator    因子候选生成器（窗口变体、横截面、组合）
  evaluator              候选因子快速评估（IC/ICIR/排名）
  miner                  挖掘引擎，编排完整挖掘流程

用法:
    from factor_lab.factor_mining import FactorMiningEngine

    engine = FactorMiningEngine()
    report = engine.mine(df=klines_df)

    # 或使用 Research Skill:
    # python3 hermes_cli.py research:run-skill --skill-id factor-mining --params top_n=10
"""

from factor_lab.factor_mining.miner import FactorMiningEngine, MiningReport, MiningConfig
from factor_lab.factor_mining.candidate_generator import (
    FactorCandidate,
    CandidateGenerator,
    WindowVariationGenerator,
    CrossSectionalGenerator,
    CombinationGenerator,
)
from factor_lab.factor_mining.evaluator import CandidateEvaluator, EvaluationResult

__all__ = [
    "FactorMiningEngine",
    "MiningReport",
    "MiningConfig",
    "FactorCandidate",
    "CandidateGenerator",
    "WindowVariationGenerator",
    "CrossSectionalGenerator",
    "CombinationGenerator",
    "CandidateEvaluator",
    "EvaluationResult",
]
