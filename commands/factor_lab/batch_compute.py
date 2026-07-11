"""
Batch factor computation — runs all registered factors against available daily kline data,
computes IC/RankIC/ICIR/Top-Bottom spread, and caches results.

Usage:
    from factor_lab.batch_compute import compute_all_and_cache
    compute_all_and_cache()
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from factor_lab.datahub_access import daily_kline_index

BASE = Path(__file__).resolve().parent.parent.parent  # .../research-assistant
sys.path.insert(0, str(BASE / "commands"))

CST = timezone(timedelta(hours=8))
CACHE_FILE = BASE / "data" / "factor_results.json"


def _load_kline_data() -> pd.DataFrame:
    """从 daily_kline CSV 加载数据，返回 (date, symbol, close, high, low, volume, amount)。"""
    try:
        sources = daily_kline_index()
    except FileNotFoundError:
        return pd.DataFrame()
    if not sources:
        return pd.DataFrame()

    frames = []
    for code, source in sorted(sources.items()):
        try:
            df = pd.read_csv(source, encoding="utf-8-sig", low_memory=False)
            df.rename(columns={"code": "symbol", "ts_code": "symbol", "timeString": "date", "trade_date": "date", "vol": "volume"}, inplace=True)
            if "date" not in df or "close" not in df:
                continue
            if "symbol" not in df:
                df["symbol"] = code
            df["symbol"] = df["symbol"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(code)
            df["symbol_raw"] = df["symbol"]  # 保留原始格式
            # 补齐交易所后缀
            if not df["symbol"].str.contains(r"\.").any():
                # 6开头=SH, 0/3/4/8/9开头=SZ(NQ)
                cond_sh = df["symbol"].str.match(r"^6")
                df.loc[cond_sh, "symbol"] = df.loc[cond_sh, "symbol"] + ".SH"
                df.loc[~cond_sh, "symbol"] = df.loc[~cond_sh, "symbol"] + ".SZ"
            raw_dates = df["date"].astype("string").str.replace(r"\.0$", "", regex=True)
            compact = raw_dates.str.fullmatch(r"\d{8}", na=False)
            parsed = pd.to_datetime(raw_dates.where(compact), format="%Y%m%d", errors="coerce")
            df["date"] = parsed.fillna(pd.to_datetime(raw_dates.where(~compact), format="mixed", errors="coerce"))
            df = df.dropna(subset=["date"])
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values(["date", "symbol"], inplace=True)
    return combined


def _load_fundamentals_data() -> pd.DataFrame:
    """加载 fundamentals_timeseries.csv，返回 (date, symbol, roe, net_margin, gross_margin, eps, debt_ratio)。"""
    fpath = BASE / "data" / "fundamentals" / "fundamentals_timeseries.csv"
    if not fpath.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(fpath, dtype={"symbol": str})
        df.rename(columns={"report_date": "date"}, inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        # 保留因子需要的列
        keep = {"date", "symbol", "roe", "net_margin", "gross_margin", "eps", "debt_ratio"}
        existing = [c for c in keep if c in df.columns]
        df = df[existing].drop_duplicates(subset=["date", "symbol"])
        df.sort_values(["date", "symbol"], inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def _load_valuation_data() -> pd.DataFrame:
    """加载 normalized/market/valuation_*.csv，返回 (date, symbol, pe_ttm, pb, turnover_rate)。"""
    vdir = BASE / "data" / "normalized" / "market"
    if not vdir.exists():
        return pd.DataFrame()
    frames = []
    for f in sorted(vdir.glob("valuation_*.csv")):
        try:
            df = pd.read_csv(f, dtype={"ts_code": str})
            df.rename(columns={"ts_code": "symbol", "trade_date": "date",
                               "pe_ttm": "pe_ttm", "pb": "pb",
                               "turnover_rate": "turnover_rate"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            keep = [c for c in ["date", "symbol", "pe_ttm", "pb", "turnover_rate"] if c in df.columns]
            frames.append(df[keep])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined.dropna(subset=["date"], inplace=True)
    combined.sort_values(["date", "symbol"], inplace=True)
    return combined


def _load_fund_flow_data() -> pd.DataFrame:
    """加载 normalized/fund_flow/*.csv，返回 (date, symbol, net_main_force, net_super_large, net_large, net_medium, net_small)。"""
    fdir = BASE / "data" / "normalized" / "fund_flow"
    if not fdir.exists():
        return pd.DataFrame()
    frames = []
    for f in sorted(fdir.glob("*.csv")):
        try:
            df = pd.read_csv(f, dtype={"ts_code": str}, low_memory=False)
            df.rename(columns={"ts_code": "symbol", "trade_date": "date",
                               "net_mf_amount": "net_main_force"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            # Map column names: buy_elg/sell_elg = super large, buy_lg/sell_lg = large, buy_md/sell_md = medium, buy_sm/sell_sm = small
            if "buy_elg_amount" in df.columns and "sell_elg_amount" in df.columns:
                df["net_super_large"] = df["buy_elg_amount"] - df["sell_elg_amount"]
            if "buy_lg_amount" in df.columns and "sell_lg_amount" in df.columns:
                df["net_large"] = df["buy_lg_amount"] - df["sell_lg_amount"]
            if "buy_md_amount" in df.columns and "sell_md_amount" in df.columns:
                df["net_medium"] = df["buy_md_amount"] - df["sell_md_amount"]
            if "buy_sm_amount" in df.columns and "sell_sm_amount" in df.columns:
                df["net_small"] = df["buy_sm_amount"] - df["sell_sm_amount"]
            keep = [c for c in ["date", "symbol", "net_main_force",
                                "net_super_large", "net_large", "net_medium", "net_small"]
                    if c in df.columns]
            frames.append(df[keep])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined.dropna(subset=["date"], inplace=True)
    combined.sort_values(["date", "symbol"], inplace=True)
    return combined


def compute_all_and_cache() -> dict:
    """
    对所有注册因子计算 IC/RankIC/ICIR/Top-Bottom 等指标，
    写入缓存文件，返回结果 dict {factor_name: metrics}。
    """
    from factor_lab.factor_base import REGISTRY

    # 加载所有数据源并合并
    kline = _load_kline_data()
    if kline.empty:
        return {"error": "No kline data available", "factors_computed": 0}

    # 计算下一日收益（用于 IC）
    kline["ret1"] = kline.groupby("symbol")["close"].transform(
        lambda x: x.pct_change(1).shift(-1)
    )

    # 加载附加数据并合并
    dfs = [kline]
    for loader, label in [(_load_fundamentals_data, "fundamentals"),
                           (_load_valuation_data, "valuation"),
                           (_load_fund_flow_data, "fund_flow")]:
        extra = loader()
        if not extra.empty:
            dfs.append(extra)

    df = dfs[0]
    for extra in dfs[1:]:
        df = pd.merge(df, extra, on=["date", "symbol"], how="left", suffixes=("", "_dup"))
        # 去除合并产生的重复列
        dup_cols = [c for c in df.columns if c.endswith("_dup")]
        df.drop(columns=dup_cols, inplace=True, errors="ignore")

    df.sort_values(["date", "symbol"], inplace=True)

    results = {}
    total = len(REGISTRY)
    computed = 0

    for i, fdef in enumerate(REGISTRY):
        fname = fdef["name"]
        try:
            # 计算因子值
            factor_series = fdef["func"](df, **fdef.get("params", {}))

            # 合并到 DataFrame 算 IC
            temp = df[["date", "symbol", "ret1"]].copy()
            temp["factor"] = factor_series
            temp.dropna(subset=["factor", "ret1"], inplace=True)

            if len(temp) < 20:
                results[fname] = _empty_metrics("数据不足")
                continue

            # 逐日 IC (Pearson) + RankIC (Spearman)
            daily_pearson_ics = []
            daily_spearman_ics = []
            for d, grp in temp.groupby("date"):
                if len(grp) < 5:
                    continue
                fv = grp["factor"].values
                rv = grp["ret1"].values
                # Pearson IC
                pc, _ = scipy_stats.pearsonr(fv, rv)
                if not np.isnan(pc):
                    daily_pearson_ics.append(pc)
                # RankIC (Spearman)
                sc, _ = scipy_stats.spearmanr(fv, rv)
                if not np.isnan(sc):
                    daily_spearman_ics.append(sc)

            if len(daily_pearson_ics) < 3 or len(daily_spearman_ics) < 3:
                results[fname] = _empty_metrics("IC 期数不足")
                continue

            # IC (Pearson) 汇总
            p_arr = np.array(daily_pearson_ics)
            ic_mean = float(np.mean(p_arr))
            ic_std = float(np.std(p_arr, ddof=1)) if len(p_arr) > 1 else 0.0
            icir = ic_mean / ic_std if ic_std > 1e-8 else 0.0

            # RankIC (Spearman) 汇总
            s_arr = np.array(daily_spearman_ics)
            rank_ic_mean = float(np.mean(s_arr))

            # Top-Bottom: 按因子值分 5 组，算 top - bottom 平均收益
            temp["quintile"] = temp.groupby("date")["factor"].transform(
                lambda x: pd.qcut(x, 5, labels=False, duplicates="drop")
            )
            tb_grp = temp.groupby(["date", "quintile"])["ret1"].mean().reset_index()
            tb_pivot = tb_grp.pivot(index="date", columns="quintile", values="ret1")

            # Top-Bottom 收益 + 逐日序列
            daily_spread = None
            if 4 in tb_pivot.columns and 0 in tb_pivot.columns:
                top_bottom = float(tb_pivot[4].mean() - tb_pivot[0].mean())
                daily_spread = tb_pivot[4] - tb_pivot[0]
            else:
                top_bottom = 0.0

            # 最大回撤: 从 Top-Bottom 日收益序列计算净值回撤
            if daily_spread is not None and len(daily_spread) >= 5:
                cum = (1 + daily_spread.fillna(0)).cumprod()
                peak = cum.expanding().max()
                dd = (cum - peak) / peak
                max_drawdown = round(float(dd.min()), 4)
            else:
                max_drawdown = 0.0

            # 换手率 = 因子排名变化率（近似）
            temp["rank"] = temp.groupby("date")["factor"].rank(pct=True)
            temp["prev_rank"] = temp.groupby("symbol")["rank"].shift(1)
            turnover = float(temp["rank"].sub(temp["prev_rank"]).abs().mean()) if len(temp) > 0 else 0.0

            # 风险暴露: 因子对常见风格维度的截面暴露
            risk_flags = _compute_risk_exposure(temp)

            # 半导体等权超额收益
            excess_vs_semi = _compute_semiconductor_excess(temp, daily_spread)

            results[fname] = {
                "ic": round(ic_mean, 4),                       # Pearson IC
                "rank_ic": round(rank_ic_mean, 4),             # Spearman RankIC
                "icir": round(icir, 4),                        # IR (基于 Pearson)
                "top_bottom": round(top_bottom, 4),
                "cost_adjusted_return": round(top_bottom * 0.998, 4),
                "turnover": round(turnover, 4),
                "max_drawdown": max_drawdown,
                "excess_vs_semiconductor_ew": round(excess_vs_semi, 4),
                "risk_flags": risk_flags,
                "computed_at": datetime.now(CST).isoformat(),
            }
            computed += 1
        except Exception as e:
            results[fname] = _empty_metrics(str(e)[:60])

    # 写缓存
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return {
        "computed_at": datetime.now(CST).isoformat(),
        "total_factors": total,
        "computed": computed,
        "failed": total - computed,
    }


def _empty_metrics(reason: str = "") -> dict:
    return {
        "ic": None, "rank_ic": None, "icir": None,
        "top_bottom": None, "cost_adjusted_return": None,
        "turnover": None, "max_drawdown": None,
        "excess_vs_semiconductor_ew": None,
        "risk_flags": [],
        "computed_at": None,
        "_fail_reason": reason,
    }


# ═════════════════════════════════════════════════════════════════
# 风险暴露分析
# ═════════════════════════════════════════════════════════════════

_RISK_DIMENSIONS = [
    ("波动率", "vol_20d"),
    ("动量", "mom_20d"),
    ("流动性", "turnover_rate"),
]


def _compute_risk_exposure(temp: pd.DataFrame) -> list[str]:
    """计算因子对各风格维度的截面暴露，返回 flag 列表"""
    df = temp.copy()

    # 计算风险代理变量
    df["vol_20d"] = df.groupby("symbol")["ret1"].transform(
        lambda x: x.rolling(20, min_periods=5).std()
    )
    df["mom_20d"] = df.groupby("symbol")["ret1"].transform(
        lambda x: x.rolling(20, min_periods=5).sum()
    )

    flags = []
    for risk_name, risk_col in _RISK_DIMENSIONS:
        if risk_col not in df.columns:
            continue
        exposures = []
        for d, grp in df.dropna(subset=["factor", risk_col]).groupby("date"):
            if len(grp) < 5:
                continue
            c, _ = scipy_stats.spearmanr(grp["factor"].values, grp[risk_col].values)
            if not np.isnan(c):
                exposures.append(c)
        if exposures:
            avg_exp = float(np.mean(exposures))
            if abs(avg_exp) > 0.3:
                direction = "高" if avg_exp > 0 else "负向高"
                flags.append(f"{direction}{risk_name}暴露: {avg_exp:.2f}")

    return flags


# ═════════════════════════════════════════════════════════════════
# 半导体等权超额收益
# ═════════════════════════════════════════════════════════════════

def _load_semiconductor_stocks() -> list[str]:
    """加载半导体核心池股票代码（带交易所后缀）"""
    try:
        from benchmarks_v4 import _get_universe_codes as _b4_codes
        codes = _b4_codes("U3")
        if codes:
            return codes
    except Exception:
        pass
    # 回退: 从 tags CSV 加载
    csv_path = BASE / "data" / "tags" / "semiconductor_chain_tags.csv"
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
            codes = df["code"].astype(str).str.strip().tolist()
            # 补齐交易所后缀 (6开头=SH, 其他=SZ)
            result = []
            for c in codes:
                if "." in c:
                    result.append(c)
                elif c.startswith("6"):
                    result.append(f"{c}.SH")
                else:
                    result.append(f"{c}.SZ")
            return result
        except Exception:
            pass
    return []


def _compute_semiconductor_excess(temp: pd.DataFrame,
                                  daily_spread: pd.Series | None) -> float:
    """计算因子 Top-Bottom 相对半导体等权基准的超额收益"""
    if daily_spread is None or len(daily_spread) < 3:
        return 0.0

    semi_codes = _load_semiconductor_stocks()
    if not semi_codes:
        return 0.0

    semi_ret = temp[temp["symbol"].isin(semi_codes)].groupby("date")["ret1"].mean()
    if semi_ret.empty:
        return 0.0

    common_dates = daily_spread.index.intersection(semi_ret.index)
    if len(common_dates) < 3:
        return 0.0

    excess = (daily_spread.loc[common_dates] - semi_ret.loc[common_dates]).mean()
    return round(float(excess), 4)


if __name__ == "__main__":
    result = compute_all_and_cache()
    print(json.dumps(result, ensure_ascii=False, indent=2))
