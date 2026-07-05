"""因子验证数据模型 — 所有验证模块的 canonical 数据结构"""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


# ─── IC 稳定性 ────────────────────────────────────────────────────

@dataclass
class ICStabilityReport:
    """IC 稳定性检查结果"""
    ic_mean: float = 0.0
    ic_std: float = 0.0
    ic_ir: float = 0.0
    rank_ic_mean: float = 0.0
    rank_ic_ir: float = 0.0
    positive_ic_ratio: float = 0.0
    monthly_ic_series: Optional[list] = None  # [{"year_month":"2025-01","ic":..}, ...]
    quarterly_ic_series: Optional[list] = None
    verdict: str = "fail"  # pass / warn / fail
    detail: str = ""


# ─── 子样本压力测试 ──────────────────────────────────────────────

@dataclass
class SubsampleResult:
    label: str  # e.g. "2025-H1", "bull_market", "high_vol"
    days: int = 0
    cumulative_return_pct: float = 0.0
    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    ic_mean: float = 0.0
    rank_ic_mean: float = 0.0
    win_rate_pct: float = 0.0

@dataclass
class StressTestReport:
    subsamples: List[SubsampleResult] = field(default_factory=list)
    worst_subsample_score: float = 0.0  # 最差子样本的 Sharpe / 整体基准
    stability_score: float = 0.0  # 各子样本 Sharpe 的变异系数倒数
    verdict: str = "fail"
    detail: str = ""


# ─── 安慰剂检验 ──────────────────────────────────────────────────

@dataclass
class PlaceboReport:
    n_trials: int = 100
    factor_score_percentile: float = 0.0  # 真实因子在随机因子中的百分位(0-100)
    placebo_mean_ic: float = 0.0
    placebo_std_ic: float = 0.0
    factor_ic: float = 0.0
    zscore_vs_placebo: float = 0.0
    p_value_like: float = 0.0  # 类似 p 值
    verdict: str = "fail"
    detail: str = ""


# ─── IC 衰减 ──────────────────────────────────────────────────────

@dataclass
class ICDecayReport:
    ic_decay_curve: Optional[dict] = None  # {"1D": ic, "3D": ic, "5D": ic, "10D": ic, "20D": ic}
    best_horizon: int = 1
    half_life_days: float = 0.0
    signal_decay_warning: str = ""
    verdict: str = "pass"
    detail: str = ""


# ─── 同池等权对照 ────────────────────────────────────────────────

@dataclass
class PeerBenchmarkReport:
    strategy_cumulative_pct: float = 0.0
    peer_ew_cumulative_pct: float = 0.0
    excess_return_pct: float = 0.0
    excess_sharpe: float = 0.0
    beats_peer: bool = False
    verdict: str = "fail"
    detail: str = ""


# ─── Anti-Overfit 综合 ────────────────────────────────────────────

@dataclass
class AntiOverfitReport:
    factor_name: str = ""
    expression: str = ""
    ic_stability: Optional[ICStabilityReport] = None
    stress_test: Optional[StressTestReport] = None
    placebo: Optional[PlaceboReport] = None
    ic_decay: Optional[ICDecayReport] = None
    peer_benchmark: Optional[PeerBenchmarkReport] = None
    overall_verdict: str = "fail"
    generated_at: str = ""


# ─── Walk-Forward 窗口 ─────────────────────────────────────────

@dataclass
class WFWindow:
    window_name: str = ""
    train_start: str = ""
    train_end: str = ""
    val_start: str = ""
    val_end: str = ""
    test_start: str = ""
    test_end: str = ""

    train_cumulative_return_pct: float = 0.0
    train_sharpe: float = 0.0
    train_max_drawdown_pct: float = 0.0
    train_ic_mean: float = 0.0

    val_cumulative_return_pct: float = 0.0
    val_sharpe: float = 0.0
    val_max_drawdown_pct: float = 0.0
    val_ic_mean: float = 0.0

    test_cumulative_return_pct: float = 0.0
    test_sharpe: float = 0.0
    test_max_drawdown_pct: float = 0.0
    test_ic_mean: float = 0.0

    decay_train_to_test: float = 0.0
    test_days: int = 0


# ─── Rolling Validator 综合 ────────────────────────────────────

@dataclass
class RollingValidationReport:
    factor_name: str = ""
    config: dict = field(default_factory=dict)
    windows: List[WFWindow] = field(default_factory=list)
    avg_train_sharpe: float = 0.0
    avg_val_sharpe: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_decay: float = 0.0
    oos_positive_ratio: float = 0.0  # 测试期正收益窗口比例
    overall_verdict: str = "fail"
    limitation: str = "full"  # full / limited / insufficient_data
    generated_at: str = ""


# ─── 因子评分 ────────────────────────────────────────────────────

@dataclass
class FactorScoreReport:
    factor_name: str = ""
    overall_score: float = 0.0
    grade: str = "D"  # A / B / C / D
    pass_gate: bool = False

    # 分项
    ic_stability_score: float = 0.0
    ic_weight: float = 0.25
    monotonicity_score: float = 0.0
    monotonicity_weight: float = 0.20
    peer_excess_score: float = 0.0
    peer_excess_weight: float = 0.20
    risk_control_score: float = 0.0
    risk_control_weight: float = 0.15
    walk_forward_score: float = 0.0
    walk_forward_weight: float = 0.15
    simplicity_score: float = 0.0
    simplicity_weight: float = 0.05

    reject_reasons: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    generated_at: str = ""


# ─── 完整验证报告 ──────────────────────────────────────────────

@dataclass
class ValidationResult:
    factor_name: str = ""
    expression: str = ""
    universe: str = ""
    benchmark: str = ""
    rebalance_freq: str = ""
    requested_period: str = ""
    matched_period: str = ""
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))

    anti_overfit: Optional[AntiOverfitReport] = None
    rolling_validation: Optional[RollingValidationReport] = None
    factor_score: Optional[FactorScoreReport] = None

    # 简要结论
    summary_verdict: str = ""  # passes / conditional / rejected
    summary_risks: List[str] = field(default_factory=list)
    next_step: str = ""

    # 文件路径
    report_path: str = ""
    output_dir: str = ""
    generated_at: str = ""
