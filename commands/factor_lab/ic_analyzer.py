"""IC 分析 — 因子有效性评估"""
import numpy as np
import pandas as pd
from scipy import stats

def calc_ic(factor_series: pd.Series, forward_ret: pd.Series) -> float:
    """计算 Rank IC（Spearman）"""
    mask = factor_series.notna() & forward_ret.notna()
    if mask.sum() < 10:
        return 0.0
    return stats.spearmanr(factor_series[mask], forward_ret[mask])[0]

def calc_daily_ic(df: pd.DataFrame, factor_col: str, ret_col: str = "ret1") -> pd.DataFrame:
    """逐日计算截面 IC"""
    dates = df["date"].unique()
    ic_list = []
    for d in sorted(dates):
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < 10:
            continue
        ic, pval = stats.spearmanr(day[factor_col], day[ret_col])
        ic_list.append({"date": d, "ic": ic, "pval": pval})
    return pd.DataFrame(ic_list)

def calc_rankic_ir(ic_df: pd.DataFrame) -> dict:
    """RankIC 的均值/标准差/IR"""
    if ic_df.empty:
        return {"mean_ic": 0, "std_ic": 0, "ir": 0, "pos_ratio": 0}
    mean_ic = ic_df["ic"].mean()
    std_ic = ic_df["ic"].std()
    ratio = (ic_df["ic"] > 0).mean()
    return {
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4),
        "ir": round(mean_ic / std_ic, 4) if std_ic > 0 else 0,
        "pos_ratio": round(ratio, 4),
    }

def layer_test(df: pd.DataFrame, factor_col: str, ret_col: str = "ret1",
               n_layers: int = 5) -> dict:
    """分层回测：按因子值分组，算每组平均收益"""
    day_result = []
    for d in sorted(df["date"].unique()):
        day = df[df["date"] == d].dropna(subset=[factor_col, ret_col])
        if len(day) < n_layers * 3:
            continue
        day["layer"] = pd.qcut(day[factor_col].rank(method="first"), n_layers, labels=False, duplicates="drop")
        for l in range(n_layers):
            grp = day[day["layer"] == l]
            day_result.append({"date": d, "layer": l, "ret": grp[ret_col].mean()})
    rdf = pd.DataFrame(day_result)
    if rdf.empty:
        return {}
    summary = rdf.groupby("layer")["ret"].agg(["mean", "std", "count"])
    long_short = rdf[rdf["layer"] == n_layers - 1].groupby("date")["ret"].mean() - \
                 rdf[rdf["layer"] == 0].groupby("date")["ret"].mean()
    return {
        "layer_returns": summary.to_dict(),
        "long_short_mean": float(long_short.mean()),
        "long_short_sharpe": float(long_short.mean() / long_short.std() * np.sqrt(252)) if long_short.std() > 0 else 0,
    }