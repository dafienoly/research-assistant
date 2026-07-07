"""Adversarial Validation — 4 项破坏性检验

补充现有 anti_overfit.py，提供 4 项攻击性检验:
1. Label Permutation — 打乱 forward returns，检验因子显著性
2. Temporal Shuffle — block shuffle 破坏时序结构
3. Random Universe — 随机股票子集，检验泛化能力
4. Noise Injection — 高斯噪声注入，测 IC 衰减率

基于 QuantGPT adversarial_validator.py 移植。
"""

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from dataclasses import dataclass, field


@dataclass
class AdvTestResult:
    name: str
    passed: bool
    details: dict = field(default_factory=dict)


@dataclass
class AdversarialResult:
    score: float = 0.0        # 0-100
    recommendation: str = ""
    tests: list = field(default_factory=list)
    passed_count: int = 0
    total_count: int = 4


def _daily_spearman_ic(df: pd.DataFrame, factor_col: str = "factor_value",
                       ret_col: str = "fwd_ret") -> pd.Series:
    """计算每日 Spearman IC"""
    valid = df.dropna(subset=[factor_col, ret_col])
    if valid.empty:
        return pd.Series(dtype=float)

    def _sp(g):
        if len(g) < 5 or g[factor_col].nunique() < 2:
            return np.nan
        corr, _ = sp_stats.spearmanr(g[factor_col], g[ret_col])
        return corr if not np.isnan(corr) else 0.0

    return valid.groupby("trade_date", group_keys=False).apply(_sp).dropna()


def _prepare_forward_returns(df: pd.DataFrame, holding_period: int = 5) -> pd.DataFrame:
    """准备 forward N-day return"""
    result = df.sort_values(["stock_code", "trade_date"]).copy()
    result["fwd_ret"] = (
        result.groupby("stock_code")["daily_ret"]
        .transform(lambda s: s.shift(-1)
                   .rolling(holding_period, min_periods=holding_period)
                   .sum()
                   .shift(-(holding_period - 1)))
    )
    return result


class AdversarialValidator:
    """对抗性验证器 — 4 项破坏性检验"""

    def __init__(self, factor_df: pd.DataFrame, holding_period: int = 5):
        self.df = _prepare_forward_returns(factor_df, holding_period)
        self.df["trade_date"] = pd.to_datetime(self.df["trade_date"])
        self.holding_period = holding_period

    def run_all(self) -> AdversarialResult:
        tests = [
            self.test_label_permutation(),
            self.test_temporal_shuffle(),
            self.test_random_universe(),
            self.test_noise_injection(),
        ]
        passed = sum(1 for t in tests if t.passed)
        score = passed / 4 * 100

        if score >= 80:
            rec = "通过"
        elif score >= 60:
            rec = "基本通过"
        elif score >= 40:
            rec = "存疑"
        else:
            rec = "高风险"

        return AdversarialResult(
            score=score,
            recommendation=rec,
            tests=[{"name": t.name, "passed": t.passed, "details": t.details} for t in tests],
            passed_count=passed,
            total_count=4,
        )

    # ── Test 1: Label Permutation ──────────────────────────────────

    def test_label_permutation(self, n_perms: int = 50) -> AdvTestResult:
        """打标检验：打乱 forward returns 后因子应失去显著性

        通过条件：真实 |IC| > 打乱后 95% 分位数 |IC|
        """
        real_ic_series = _daily_spearman_ic(self.df)
        if len(real_ic_series) < 20:
            return AdvTestResult("标签置换检验", False, {"error": "IC 数据不足"})

        real_ic = float(real_ic_series.mean())
        rng = np.random.RandomState(42)

        valid = self.df.dropna(subset=["factor_value", "fwd_ret"])
        sampled_dates = sorted(valid["trade_date"].unique())[::3]
        valid_sampled = valid[valid["trade_date"].isin(sampled_dates)]

        perm_ics = []
        for _ in range(n_perms):
            shuffled = valid_sampled.copy()
            shuffled["fwd_ret"] = shuffled.groupby("trade_date")["fwd_ret"].transform(
                lambda s: rng.permutation(s.values)
            )
            pic = _daily_spearman_ic(shuffled)
            if len(pic) > 0:
                perm_ics.append(float(pic.mean()))

        if len(perm_ics) < 10:
            return AdvTestResult("标签置换检验", False, {"error": "置换数据不足"})

        perm_95 = float(np.percentile([abs(x) for x in perm_ics], 95))
        passed = abs(real_ic) > perm_95

        return AdvTestResult("标签置换检验", passed, {
            "real_ic": round(real_ic, 4),
            "perm_95th_abs": round(perm_95, 4),
            "perm_mean_abs": round(float(np.mean([abs(x) for x in perm_ics])), 4),
            "n_perms": len(perm_ics),
        })

    # ── Test 2: Temporal Shuffle ───────────────────────────────────

    def test_temporal_shuffle(self, block_size: int = 20) -> AdvTestResult:
        """时序打乱检验：block shuffle 破坏时序后因子应失效

        通过条件：真实 |IC| / 打乱后 |IC| > 1.5
        """
        real_ic_series = _daily_spearman_ic(self.df)
        if len(real_ic_series) < 40:
            return AdvTestResult("时序打乱检验", False, {"error": "数据不足"})

        real_ic = abs(float(real_ic_series.mean()))
        if real_ic < 1e-6:
            return AdvTestResult("时序打乱检验", False, {"error": "原始 IC 接近零"})

        dates = sorted(self.df["trade_date"].unique())
        n_blocks = len(dates) // block_size
        if n_blocks < 3:
            return AdvTestResult("时序打乱检验", False, {"error": "时间跨度不足"})

        rng = np.random.RandomState(42)
        shuffle_ics = []

        for _ in range(30):
            blocks = [dates[i * block_size:(i + 1) * block_size] for i in range(n_blocks)]
            rng.shuffle(blocks)
            new_date_order = [d for block in blocks for d in block]
            date_map = dict(zip(dates[:len(new_date_order)], new_date_order))

            shuffled = self.df[self.df["trade_date"].isin(date_map.keys())].copy()
            shuffled["trade_date"] = shuffled["trade_date"].map(date_map)
            shuffled = shuffled.sort_values(["stock_code", "trade_date"])

            shuffled["fwd_ret"] = (
                shuffled.groupby("stock_code")["daily_ret"]
                .transform(lambda s: s.shift(-1)
                           .rolling(self.holding_period, min_periods=self.holding_period)
                           .sum()
                           .shift(-(self.holding_period - 1)))
            )

            sic = _daily_spearman_ic(shuffled)
            if len(sic) > 0:
                shuffle_ics.append(abs(float(sic.mean())))

        if len(shuffle_ics) < 10:
            return AdvTestResult("时序打乱检验", False, {"error": "打乱数据不足"})

        mean_shuffled = float(np.mean(shuffle_ics))
        ratio = real_ic / mean_shuffled if mean_shuffled > 1e-6 else 999.0
        passed = ratio > 1.5

        return AdvTestResult("时序打乱检验", passed, {
            "real_ic_abs": round(real_ic, 4),
            "shuffled_ic_mean": round(mean_shuffled, 4),
            "ratio": round(ratio, 2),
            "n_shuffles": len(shuffle_ics),
        })

    # ── Test 3: Random Universe ────────────────────────────────────

    def test_random_universe(self, n_trials: int = 30, sample_frac: float = 0.3) -> AdvTestResult:
        """随机股票池检验：因子应在随机子集上保持一致

        通过条件：>= 70% 子集与全量 IC 同号
        """
        real_ic_series = _daily_spearman_ic(self.df)
        if len(real_ic_series) < 20:
            return AdvTestResult("随机股票池检验", False, {"error": "IC 数据不足"})

        real_ic = float(real_ic_series.mean())
        real_sign = np.sign(real_ic)
        if real_sign == 0:
            return AdvTestResult("随机股票池检验", False, {"error": "原始 IC 为零"})

        stocks = self.df["stock_code"].unique()
        if len(stocks) < 20:
            return AdvTestResult("随机股票池检验", False, {"error": "股票数量不足"})

        n_sample = max(10, int(len(stocks) * sample_frac))
        rng = np.random.RandomState(42)
        subset_ics = []

        for _ in range(n_trials):
            sampled = rng.choice(stocks, size=n_sample, replace=False)
            subset = self.df[self.df["stock_code"].isin(sampled)]
            sic = _daily_spearman_ic(subset)
            if len(sic) >= 10:
                subset_ics.append(float(sic.mean()))

        if len(subset_ics) < 10:
            return AdvTestResult("随机股票池检验", False, {"error": "子集数据不足"})

        same_sign = sum(1 for ic in subset_ics if np.sign(ic) == real_sign)
        consistency = same_sign / len(subset_ics)
        passed = consistency >= 0.7

        return AdvTestResult("随机股票池检验", passed, {
            "real_ic": round(real_ic, 4),
            "consistency": round(consistency, 4),
            "subset_ic_mean": round(float(np.mean(subset_ics)), 4),
            "subset_ic_std": round(float(np.std(subset_ics)), 4),
            "n_trials": len(subset_ics),
        })

    # ── Test 4: Noise Injection ────────────────────────────────────

    def test_noise_injection(self, noise_levels: list[float] = None) -> AdvTestResult:
        """噪声注入检验：添加高斯噪声，稳健因子应缓慢衰减

        通过条件：0.5 倍噪声下 |IC| 保留 >= 50%
        """
        if noise_levels is None:
            noise_levels = [0.1, 0.2, 0.5, 1.0, 2.0]

        real_ic_series = _daily_spearman_ic(self.df)
        if len(real_ic_series) < 20:
            return AdvTestResult("噪声注入检验", False, {"error": "IC 数据不足"})

        real_ic = abs(float(real_ic_series.mean()))
        if real_ic < 1e-6:
            return AdvTestResult("噪声注入检验", False, {"error": "原始 IC 接近零"})

        rng = np.random.RandomState(42)
        factor_std = self.df["factor_value"].std()
        if factor_std < 1e-10:
            return AdvTestResult("噪声注入检验", False, {"error": "因子值无变异"})

        noise_ics = {}
        for level in noise_levels:
            noisy = self.df.copy()
            noise = rng.normal(0, factor_std * level, size=len(noisy))
            noisy["factor_value"] = noisy["factor_value"] + noise
            nic = _daily_spearman_ic(noisy)
            if len(nic) > 0:
                noise_ics[level] = abs(float(nic.mean()))

        if 0.5 not in noise_ics:
            return AdvTestResult("噪声注入检验", False, {"error": "0.5 倍噪声计算失败"})

        retention_50 = noise_ics[0.5] / real_ic if real_ic > 1e-10 else 0
        passed = retention_50 >= 0.5

        return AdvTestResult("噪声注入检验", passed, {
            "real_ic_abs": round(real_ic, 4),
            "retention_at_0.5x": round(retention_50, 4),
            "noise_decay_curve": {str(k): round(v, 4) for k, v in sorted(noise_ics.items())},
            "factor_std": round(float(factor_std), 6),
        })


# ── CLI 便捷入口 ──────────────────────────────────────

def run_adversarial_validation(factor_df: pd.DataFrame, holding_period: int = 5) -> dict:
    """运行全部 4 项对抗性验证

    Args:
        factor_df: DataFrame 含 trade_date, stock_code, factor_value, daily_ret
        holding_period: 持有期（交易日）

    Returns:
        {score, recommendation, passed_count, total_count, tests}
    """
    validator = AdversarialValidator(factor_df, holding_period)
    result = validator.run_all()
    return {
        "score": result.score,
        "recommendation": result.recommendation,
        "passed_count": result.passed_count,
        "total_count": result.total_count,
        "tests": result.tests,
    }
