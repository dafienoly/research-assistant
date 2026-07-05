"""反过拟合诊断 — IC稳定性/子样本压力/安慰剂检验/IC衰减/同池对照

用法:
    from factor_lab.validation.anti_overfit import run_anti_overfit
    report = run_anti_overfit(df, factor_name="ret5", top_quantile=0.2)
"""
import sys, os, math, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

sys.path.insert(0, str(Path(__file__).parent.parent))

CST = timezone(timedelta(hours=8))


# ─── 1. IC 稳定性 ──────────────────────────────────────────────

def check_ic_stability(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str = "ret1"
) -> dict:
    """IC 稳定性: 全样本 IC + 逐月/逐季 IC 检查"""
    dates = sorted(df["date"].unique())
    daily_ics = []
    for d in dates:
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        ic, pval = scipy_stats.spearmanr(day[factor_col], day[ret_col])
        if not np.isnan(ic):
            daily_ics.append({"date": d, "ic": ic, "pval": pval})

    ic_series = pd.DataFrame(daily_ics)
    if ic_series.empty:
        return {"ic_mean": 0, "ic_std": 0, "ic_ir": 0, "rank_ic_mean": 0,
                "rank_ic_ir": 0, "positive_ic_ratio": 0,
                "monthly_ic_series": [], "quarterly_ic_series": [],
                "verdict": "fail", "detail": "IC 数据不足"}

    ic_mean = float(ic_series["ic"].mean())
    ic_std = float(ic_series["ic"].std())
    ic_ir = ic_mean / ic_std if ic_std > 1e-8 else 0
    pos_ratio = float((ic_series["ic"] > 0).mean())

    # 月度 IC
    ic_series["date"] = pd.to_datetime(ic_series["date"])
    ic_series["year_month"] = ic_series["date"].dt.strftime("%Y-%m")
    monthly_ic = ic_series.groupby("year_month")["ic"].mean().reset_index()
    monthly_ic_list = monthly_ic.to_dict("records")

    # 季度 IC
    ic_series["quarter"] = ic_series["date"].dt.to_period("Q").astype(str)
    quarterly_ic = ic_series.groupby("quarter")["ic"].mean().reset_index()
    quarterly_ic_list = quarterly_ic.to_dict("records")

    # 判断: IC 是否稳定
    monthly_ic_values = monthly_ic["ic"].dropna().values
    if len(monthly_ic_values) >= 3:
        monthly_pos_ratio = float(np.mean(monthly_ic_values > 0))
    else:
        monthly_pos_ratio = pos_ratio

    if ic_ir > 0.15 and pos_ratio > 0.52 and monthly_pos_ratio > 0.4:
        verdict = "pass"
        detail = f"IC_IR={ic_ir:.3f}>0.15, POS={pos_ratio:.1%}>52%, 月度正IC占比{monthly_pos_ratio:.0%}"
    elif ic_ir > 0.05 and pos_ratio > 0.50:
        verdict = "warn"
        detail = f"IC_IR={ic_ir:.3f}, POS={pos_ratio:.1%}, 但月度IC波动较大"
    else:
        verdict = "fail"
        detail = f"IC_IR={ic_ir:.3f}偏低, POS={pos_ratio:.1%}"

    rank_ic_mean = ic_mean  # 已经是 Spearman Rank IC
    rank_ic_ir = ic_ir

    return {
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4),
        "rank_ic_mean": round(rank_ic_mean, 4),
        "rank_ic_ir": round(rank_ic_ir, 4),
        "positive_ic_ratio": round(pos_ratio, 4),
        "monthly_ic_series": monthly_ic_list,
        "quarterly_ic_series": quarterly_ic_list,
        "verdict": verdict,
        "detail": detail,
    }


# ─── 2. 子样本压力测试 ─────────────────────────────────────────

def _regime_split(dates: pd.DatetimeIndex, close_pivot: pd.DataFrame) -> dict:
    """切分市场状态: 上涨/下跌, 高/低波动

    返回 {"bull": [date1, ...], "bear": [...], "high_vol": [...], "low_vol": [...]}
    """
    if len(dates) < 20:
        return {}
    # 全市场等权收益
    daily_ret = close_pivot.pct_change().mean(axis=1)
    daily_ret = daily_ret.reindex(dates).dropna()
    if len(daily_ret) < 10:
        return {}

    # 上涨/下跌: 基于累计收益方向
    cum = (1 + daily_ret).cumprod()
    mid = len(cum) // 2
    first_half = cum.index[:mid]
    second_half = cum.index[mid:]

    bull = list(cum[cum > cum.iloc[0]].index)
    bear = list(cum[cum <= cum.iloc[0]].index)

    # 高/低波动: 基于20日滚动波动率
    vol = daily_ret.rolling(20, min_periods=5).std()
    vol_median = vol.median()
    high_vol = list(vol[vol >= vol_median].index) if not pd.isna(vol_median) else []
    low_vol = list(vol[vol < vol_median].index) if not pd.isna(vol_median) else []

    return {
        "bull_market": bull,
        "bear_market": bear,
        "high_volatility": high_vol,
        "low_volatility": low_vol,
        "first_half": list(first_half),
        "second_half": list(second_half),
    }


def run_stress_test(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str = "ret1",
    close_pivot: Optional[pd.DataFrame] = None,
    top_quantile: float = 0.2,
    use_strategy: bool = True,
) -> dict:
    """子样本压力测试

    切分维度:
      1. 年度(2025/2026)
      2. 上涨/下跌期
      3. 高/低波动期
      4. 前半/后半
    """
    import warnings
    warnings.filterwarnings("ignore")

    subsamples = []
    dates = sorted(df["date"].unique())

    # 维度1: 年度
    df_dates = pd.to_datetime(pd.Series(dates))
    for yr in sorted(df_dates.dt.year.unique()):
        yr_str = str(yr)
        yr_dates = [d for d in dates if str(d)[:4] == yr_str]
        if len(yr_dates) < 20:
            continue
        sub = df[df["date"].isin(yr_dates)]
        s = _calc_subsample_metrics(sub, factor_col, ret_col, yr_str, use_strategy, top_quantile)
        subsamples.append(s)

    # 维度2: 半年度
    for yr in sorted(set(str(d)[:4] for d in dates)):
        for half in ["H1", "H2"]:
            if half == "H1":
                hd = [d for d in dates if str(d)[:4] == yr and int(str(d)[5:7]) <= 6]
            else:
                hd = [d for d in dates if str(d)[:4] == yr and int(str(d)[5:7]) > 6]
            if len(hd) < 20:
                continue
            sub = df[df["date"].isin(hd)]
            s = _calc_subsample_metrics(sub, factor_col, ret_col, f"{yr}-{half}", use_strategy, top_quantile)
            subsamples.append(s)

    # 维度3: 市场状态 (需要 close_pivot)
    regimes = {}
    if close_pivot is not None:
        regimes = _regime_split(pd.DatetimeIndex(dates), close_pivot)
    for regime_name, regime_dates in regimes.items():
        regime_dates_str = [str(d.date()) if hasattr(d, 'date') else str(d)[:10] for d in regime_dates]
        str_dates = [d for d in dates if any(str(d)[:10] == r[:10] for r in regime_dates_str)]
        if len(str_dates) < 20:
            continue
        sub = df[df["date"].isin(str_dates)]
        s = _calc_subsample_metrics(sub, factor_col, ret_col, regime_name, use_strategy, top_quantile)
        subsamples.append(s)

    if not subsamples:
        return {"subsamples": [], "worst_subsample_score": 1.0, "stability_score": 0,
                "verdict": "fail", "detail": "无法分割子样本"}

    # 计算稳定性
    sharpes = [s["sharpe"] for s in subsamples if abs(s["sharpe"]) < 10]
    if len(sharpes) >= 2:
        sharpe_mean = float(np.mean(sharpes))
        sharpe_std = float(np.std(sharpes))
        stability = sharpe_mean / (sharpe_std + 0.01) * 0.3  # 变异系数倒数, 缩放到0-1
        stability = min(max(stability, 0), 1)
        worst_sharpe = min(sharpes)
        worst_score = worst_sharpe / (sharpe_mean + 0.01) if sharpe_mean > 0 else 0
        worst_score = max(min(worst_score, 1), -0.5)
    else:
        stability = 0.5
        worst_score = 0.5

    verdict = "pass" if stability > 0.3 and worst_score > -0.3 else "warn" if worst_score > -0.5 else "fail"
    detail = f"子样本稳定度={stability:.2f}, 最差Sharpe={min(sharpes) if sharpes else 0:.2f}"

    return {
        "subsamples": subsamples,
        "worst_subsample_score": round(worst_score, 4),
        "stability_score": round(stability, 4),
        "verdict": verdict,
        "detail": detail,
    }


def _calc_subsample_metrics(
    sub_df: pd.DataFrame,
    factor_col: str,
    ret_col: str,
    label: str,
    use_strategy: bool = True,
    top_quantile: float = 0.2,
) -> dict:
    """计算子样本指标: IC + Top组收益"""
    # IC
    day_ics = []
    for d in sorted(sub_df["date"].unique()):
        day = sub_df[sub_df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        ic, _ = scipy_stats.spearmanr(day[factor_col], day[ret_col])
        if not np.isnan(ic):
            day_ics.append(ic)
    ic_mean = float(np.mean(day_ics)) if day_ics else 0
    rank_ic_mean = ic_mean

    # 策略收益: 简单模拟 Top组等权
    rets = []
    for d in sorted(sub_df["date"].unique()):
        day = sub_df[sub_df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        top_n = max(1, int(len(day) * top_quantile))
        top_stocks = day.nlargest(top_n, factor_col)
        mean_ret = top_stocks[ret_col].mean()
        rets.append(mean_ret)

    ret_series = pd.Series(rets)
    cum_ret = float((1 + ret_series).prod() - 1) if len(rets) > 0 else 0
    sharpe = float(ret_series.mean() / ret_series.std() * np.sqrt(252)) if len(ret_series) > 3 and ret_series.std() > 0 else 0
    dd = _max_drawdown((1 + ret_series).cumprod()) if len(ret_series) > 0 else 0
    win_rate = float((ret_series > 0).mean()) if len(ret_series) > 0 else 0

    return {
        "label": label,
        "days": len(sub_df["date"].unique()),
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(dd * 100, 2),
        "ic_mean": round(ic_mean, 4),
        "rank_ic_mean": round(rank_ic_mean, 4),
        "win_rate_pct": round(win_rate * 100, 2),
    }


def _max_drawdown(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    return float(dd.min())


# ─── 3. 安慰剂检验 ──────────────────────────────────────────────

def run_placebo_test(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str = "ret1",
    n_trials: int = 100,
) -> dict:
    """安慰剂检验: 将真实因子 IC 与随机因子 IC 对比

    方法: 保持因子值不变, 随机打散 forward_returns, 重复 n 次
    得到随机 IC 分布, 看真实 IC 在分布中的百分位
    """
    dates = sorted(df["date"].unique())

    # 真实 IC
    real_ics = []
    for d in dates:
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        ic, _ = scipy_stats.spearmanr(day[factor_col], day[ret_col])
        if not np.isnan(ic):
            real_ics.append(ic)
    real_mean_ic = float(np.mean(real_ics)) if real_ics else 0

    if len(real_ics) < 5:
        return {"n_trials": n_trials, "factor_score_percentile": 50,
                "placebo_mean_ic": 0, "placebo_std_ic": 0, "factor_ic": real_mean_ic,
                "zscore_vs_placebo": 0, "p_value_like": 0.5,
                "verdict": "fail", "detail": "IC 数据不足"}

    # 随机试验: 打散 forward_returns
    placebo_means = []
    for _ in range(n_trials):
        trial_ics = []
        for d in dates:
            day = df[df["date"] == d].dropna(subset=[factor_col, ret_col]).copy()
            if len(day) < 10:
                continue
            # 随机打散收益
            shuffled = day[ret_col].sample(frac=1, random_state=None).values
            ic, _ = scipy_stats.spearmanr(day[factor_col], shuffled)
            if not np.isnan(ic):
                trial_ics.append(ic)
        placebo_means.append(float(np.mean(trial_ics)) if trial_ics else 0)

    placebo_mean = float(np.mean(placebo_means))
    placebo_std = float(np.std(placebo_means))

    # 真实 IC 在随机分布中的百分位
    percentile = sum(1 for p in placebo_means if p <= real_mean_ic) / n_trials * 100

    # Z-score
    zscore = (real_mean_ic - placebo_mean) / (placebo_std + 1e-8)

    # 类 p 值 (正态近似)
    p_value = 1 - scipy_stats.norm.cdf(zscore) if zscore > 0 else 0.5

    if percentile >= 95 and zscore > 2:
        verdict = "pass"
        detail = f"真实IC(perc={percentile:.0f}%)显著强于随机(zscore={zscore:.1f})"
    elif percentile >= 80 and zscore > 1:
        verdict = "warn"
        detail = f"真实IC(perc={percentile:.0f}%)略强于随机(zscore={zscore:.1f})"
    else:
        verdict = "fail"
        detail = f"真实IC(perc={percentile:.0f}%)未显著强于随机(zscore={zscore:.1f})"

    return {
        "n_trials": n_trials,
        "factor_score_percentile": round(percentile, 1),
        "placebo_mean_ic": round(placebo_mean, 4),
        "placebo_std_ic": round(placebo_std, 4),
        "factor_ic": round(real_mean_ic, 4),
        "zscore_vs_placebo": round(zscore, 4),
        "p_value_like": round(p_value, 4),
        "verdict": verdict,
        "detail": detail,
    }


# ─── 4. IC 衰减 ──────────────────────────────────────────────

def check_ic_decay(
    df: pd.DataFrame,
    factor_col: str,
    horizons: Optional[list] = None,
) -> dict:
    """IC 衰减: 不同 forward horizon 的 IC

    horizons: 1, 3, 5, 10, 20 天
    """
    if horizons is None:
        horizons = [1, 3, 5, 10, 20]

    # 计算各 horizon 的 forward return
    temp = df.sort_values(["symbol", "date"]).copy()
    horizon_ics = {}

    for h in horizons:
        ret_col = f"ret_{h}d"
        temp[ret_col] = temp.groupby("symbol")["close"].transform(lambda x: x.pct_change(h).shift(-h))

        h_ics = []
        for d in sorted(temp["date"].unique()):
            day = temp[temp["date"] == d].dropna(subset=[factor_col, ret_col])
            if len(day) < 10:
                continue
            ic, _ = scipy_stats.spearmanr(day[factor_col], day[ret_col])
            if not np.isnan(ic):
                h_ics.append(ic)
        horizon_ics[f"{h}D"] = float(np.mean(h_ics)) if h_ics else 0

    # 最佳 horizon
    best_horizon = max(horizon_ics, key=lambda k: abs(horizon_ics[k]))
    best_days = int(best_horizon.replace("D", ""))

    # 半衰期: IC 衰减到初始值一半的天数
    base_ic = abs(horizon_ics.get("1D", 0))
    if base_ic > 0.005:
        half_life = 1
        for h in sorted(horizons):
            ic_val = abs(horizon_ics.get(f"{h}D", 0))
            if ic_val >= base_ic * 0.5:
                half_life = h
            else:
                break
    else:
        half_life = 1

    # 警告: 衰减过快
    if half_life <= 3:
        decay_warn = f"半衰期仅{half_life}天, 信号衰减快"
        verdict = "warn"
    elif half_life >= 10:
        decay_warn = f"半衰期{half_life}天, 信号持久"
        verdict = "pass"
    else:
        decay_warn = f"半衰期{half_life}天, 中等衰减"
        verdict = "warn"

    return {
        "ic_decay_curve": horizon_ics,
        "best_horizon": best_days,
        "half_life_days": half_life,
        "signal_decay_warning": decay_warn,
        "verdict": verdict,
        "detail": f"最佳horizon={best_horizon}(IC={horizon_ics[best_horizon]:.4f}), 半衰期={half_life}天",
    }


# ─── 5. 同池等权对照 ──────────────────────────────────────────

def check_peer_benchmark(
    df: pd.DataFrame,
    factor_col: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """策略 vs 同池等权基准

    Sample safe=False 时为 full run, 否则仅跑 IC 级别的近似
    """
    from reports.report_schema import compute_equity_curve

    # 策略收益 (全期)
    dates = close_pivot.index
    rebal_dates = _first_trading_days(dates)
    rebal_set = set(rebal_dates)

    daily_ret = close_pivot.pct_change()
    rets = pd.Series(0.0, index=dates)
    prev_port = []
    tc = 0.0003 + 0.0005 + 10 / 10000

    for d in dates:
        if d in rebal_set:
            factor_slice = df[df["date"] == d].set_index("symbol")[factor_col].dropna().sort_values(ascending=False)
            n_stocks = max(1, int(len(factor_slice) * top_quantile))
            port = list(factor_slice.index[:n_stocks]) if len(factor_slice) > 0 else prev_port
        else:
            port = prev_port
        if not port:
            rets[d] = 0
            prev_port = port
            continue
        avail = [s for s in port if s in daily_ret.columns]
        ret = daily_ret.loc[d, avail].mean() if avail else 0
        if d in rebal_set:
            ret -= tc
        rets[d] = ret
        prev_port = port

    # 同池等权
    ew = pd.Series(0.0, index=dates)
    prev_stocks = pd.Series(dtype=float)
    for d in dates:
        if d in rebal_set:
            today_stocks = close_pivot.loc[d].dropna()
        else:
            today_stocks = prev_stocks if not prev_stocks.empty else close_pivot.loc[d].dropna()
        universe = list(today_stocks.index)
        if not universe:
            ew[d] = 0
            prev_stocks = today_stocks
            continue
        avail = [s for s in universe if s in daily_ret.columns]
        ret = daily_ret.loc[d, avail].mean() if avail else 0
        if d in rebal_set:
            ret -= tc
        ew[d] = ret
        prev_stocks = today_stocks

    rets = rets.fillna(0)
    ew = ew.fillna(0)

    strategy_cum = float(compute_equity_curve(rets).iloc[-1]) - 1
    ew_cum = float(compute_equity_curve(ew).iloc[-1]) - 1
    excess = rets - ew

    def _sharpe(s):
        return float(s.mean() / s.std() * np.sqrt(252)) if len(s) > 5 and s.std() > 0 else 0

    beats = strategy_cum > ew_cum

    verdict = "pass" if beats else "fail"
    detail = "跑赢同池等权" if beats else "未跑赢同池等权"

    return {
        "strategy_cumulative_pct": round(strategy_cum * 100, 2),
        "peer_ew_cumulative_pct": round(ew_cum * 100, 2),
        "excess_return_pct": round((strategy_cum - ew_cum) * 100, 2),
        "excess_sharpe": round(_sharpe(excess), 4),
        "beats_peer": beats,
        "verdict": verdict,
        "detail": detail,
    }


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日"""
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    first_per_month = s.groupby(dates.month).apply(lambda x: x.index[0])
    return pd.DatetimeIndex(first_per_month.values)


# ─── 6. 整合入口 ──────────────────────────────────────────────

def run_anti_overfit(
    df: pd.DataFrame,
    factor_name: str,
    close_pivot: Optional[pd.DataFrame] = None,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    placebo_trials: int = 100,
    run_full_strategy: bool = True,
) -> dict:
    """完整反过拟合诊断"""
    from factor_lab.factor_base import list_factors

    # 获取因子信息
    registry = {f["name"]: f for f in list_factors()}
    fdef = registry.get(factor_name, {})
    expression = fdef.get("description", "")

    # 1. IC 稳定性
    ic_stability = check_ic_stability(df, factor_name)

    # 2. 子样本压力测试
    stress_test = run_stress_test(df, factor_name, close_pivot=close_pivot,
                                  top_quantile=top_quantile, use_strategy=run_full_strategy)

    # 3. 安慰剂检验
    placebo = run_placebo_test(df, factor_name, n_trials=placebo_trials)

    # 4. IC 衰减
    ic_decay = check_ic_decay(df, factor_name)

    # 5. 同池等权对照
    peer = check_peer_benchmark(df, factor_name, close_pivot, top_quantile, rebalance)

    # 综合判定
    verdicts = [ic_stability["verdict"], stress_test["verdict"],
                placebo["verdict"], ic_decay["verdict"], peer["verdict"]]
    if all(v == "pass" for v in verdicts):
        overall = "pass"
    elif any(v == "fail" for v in verdicts):
        overall = "fail"
    else:
        overall = "warn"

    return {
        "factor_name": factor_name,
        "expression": expression,
        "ic_stability": ic_stability,
        "stress_test": stress_test,
        "placebo": placebo,
        "ic_decay": ic_decay,
        "peer_benchmark": peer,
        "overall_verdict": overall,
        "generated_at": datetime.now(CST).isoformat(),
    }
