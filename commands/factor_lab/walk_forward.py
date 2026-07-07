"""Walk-Forward 样本外验证 — 因子 Top-N 回测的过拟合诊断

使用场景:
  对单个因子（如 ret5）做滚动时间窗验证，检测因子是否过拟合。

方法:
  将全区间划分为多个 train/val 对，每个窗口：
    - Train:  计算因子值 → 选 TopN → 记录样本内收益/IC
    - Val:    用 Train 期的选股逻辑（TopN 分位数）→ 样本外表现
    - 对比 IS vs OOS 的 Sharpe/IC/收益一致性

输出:
  - walk_forward_report.json: 结构化验证结果
  - overfitting_diagnostics: Sharpe 通胀、IC 衰减、PSR、Deflated SR
"""
import sys, os, json, math
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from scipy import stats as scipy_stats

CST = timezone(timedelta(hours=8))
BASE = Path("/home/ly/.hermes/research-assistant")
OUTPUT = Path("/mnt/d/HermesReports/walk_forward")

# ─── Window Definitions ────────────────────────────────────────────
# 2025-01-02 ~ 2026-06-30, 约 18 个月
# 6 个滚动窗口，每窗口 train:val ≈ 2:1
WINDOWS = [
    # (name, train_start, train_end, val_start, val_end)
    ("w1", "2025-01-02", "2025-06-30", "2025-07-01", "2025-09-30"),
    ("w2", "2025-04-01", "2025-09-30", "2025-10-01", "2025-12-31"),
    ("w3", "2025-07-01", "2025-12-31", "2026-01-01", "2026-03-31"),
    ("w4", "2025-10-01", "2026-03-31", "2026-04-01", "2026-06-30"),
]

# ─── Core Functions ────────────────────────────────────────────────


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日
    
    用 groupby month 取当月第一个日期，解决 is_month_start 不识别交易日的问题。
    """
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    first_per_month = s.groupby(dates.month).apply(lambda x: x.index[0])
    return pd.DatetimeIndex(first_per_month.values)


def compute_sharpe(returns: pd.Series, annual_factor: float = 252) -> float:
    """年化 Sharpe Ratio (无风险利率≈0)"""
    if len(returns) < 5 or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(annual_factor))


def compute_max_drawdown(equity: pd.Series) -> float:
    """最大回撤"""
    if len(equity) < 2:
        return 0.0
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    return float(dd.min())


def compute_psr(sharpe: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Probabilistic Sharpe Ratio — 给定 Sharpe 为正的概率

    PSR = Phi( (SR - SR_target) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )
    SR_target 通常取 0.
    """
    if n_obs < 3 or sharpe <= 0:
        return 0.0
    numerator = sharpe * np.sqrt(n_obs - 1)
    denominator = np.sqrt(1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2)
    if denominator <= 0:
        return 0.0
    return float(scipy_stats.norm.cdf(numerator / denominator))


def compute_deflated_sharpe(sharpe: float, n_obs: int, n_trials: int = 100) -> float:
    """Deflated Sharpe Ratio — 考虑多重测试后的修正

    近似: DSR = PSR with SR_target = E[max(SR)] under null
    简化实现: 用 E[max(z)] ≈ sqrt(2*log(N)) 近似
    """
    if n_obs < 3 or sharpe <= 0:
        return 0.0
    # 零假设下 max SR 的期望近似
    max_sr_null = np.sqrt(2 * np.log(n_trials)) / np.sqrt(n_obs - 1)
    if sharpe <= max_sr_null:
        return 0.0
    numerator = (sharpe - max_sr_null) * np.sqrt(n_obs - 1)
    # 保守假设 skew=0, kurt=3
    denominator = np.sqrt(1 + 0.5 * (sharpe - max_sr_null) ** 2) if abs(sharpe) < 2 else np.sqrt(1 + 0.5 * max_sr_null ** 2)
    if denominator <= 0:
        return 0.0
    return float(scipy_stats.norm.cdf(numerator / denominator))


def load_data(factor_name: str = "ret5") -> pd.DataFrame:
    """加载 K 线并计算指定因子"""
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors

    # 从 universe 加载股票池
    from strategy_lab.universe import build
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    print(f"  股票池: {len(symbols)} 只")

    # 加载 K 线（覆盖全区间 + 因子计算需要的 padding）
    df = load_stock_kline(symbols, start_date="2024-10-01", end_date="2026-06-30")
    print(f"  K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")

    # 排序
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 计算下期收益
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))

    # 计算指定因子
    registry = {f["name"]: f for f in list_factors()}
    if factor_name not in registry:
        raise ValueError(f"因子 {factor_name} 不在注册表中。可用: {list(registry.keys())}")

    fdef = registry[factor_name]
    factor_values = fdef["func"](df, **fdef["params"])
    df[factor_name] = factor_values

    return df


def run_window_backtest(
    df: pd.DataFrame,
    factor_name: str,
    train_start: str,
    train_end: str,
    val_start: str,
    val_end: str,
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
) -> dict:
    """在单个 train/val 窗口上运行回测"""
    from reports.report_schema import compute_equity_curve

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    # 确保日期排序
    close_pivot = close_pivot.sort_index()

    # ── 训练期: 确定 TopN cutoff ──
    train_df = df[(df["date"] >= train_start) & (df["date"] <= train_end)].copy()
    val_df = df[(df["date"] >= val_start) & (df["date"] <= val_end)].copy()

    if train_df.empty or val_df.empty:
        return {"error": "空区间"}

    # Train 期选股排序（按月调仓）
    close_train = close_pivot.loc[train_start:train_end].copy()
    close_val = close_pivot.loc[val_start:val_end].copy()

    # ── 生成交易日期序列 ──
    all_dates_train = close_train.index
    all_dates_val = close_val.index

    # 调仓日: 按月  (使用每月第一个交易日，不是 is_month_start)
    rebal_dates_train = _first_trading_days(all_dates_train)
    rebal_dates_val = _first_trading_days(all_dates_val)

    # ── 训练期表现 (样本内) ──
    train_ret, _ = _run_portfolio(df, factor_name, rebal_dates_train, all_dates_train, close_pivot, top_quantile, rebalance)
    val_ret, _ = _run_portfolio(df, factor_name, rebal_dates_val, all_dates_val, close_pivot, top_quantile, rebalance)

    # ── 同池等权基准 ──
    commission_rate = 0.0003
    stamp_tax_rate = 0.0005
    slippage_bps = 10
    tc = commission_rate + stamp_tax_rate + slippage_bps / 10000

    ew_train = _compute_ew(close_train, rebal_dates_train, tc)
    ew_val = _compute_ew(close_val, rebal_dates_val, tc)

    # ── 指标计算 ──
    metrics = _compute_metrics(train_ret, val_ret, ew_train, ew_val, factor_name, train_start, train_end, val_start, val_end)
    return metrics


def _run_portfolio(
    df, factor_name, rebal_dates, all_dates, close_pivot, top_quantile, rebalance
):
    """在给定日期序列上运行 Top-Quantile 组合"""
    daily_ret = close_pivot.pct_change()
    rebal_set = set(rebal_dates) if hasattr(rebal_dates, '__iter__') else set()
    rets = pd.Series(0.0, index=all_dates)
    prev_portfolio = []

    for d in all_dates:
        if d in rebal_set:
            # 取该日的因子值
            factor_slice = df[df["date"] == d].set_index("symbol")[factor_name].dropna().sort_values(ascending=False)
            if len(factor_slice) > 0:
                n_stocks = max(1, int(len(factor_slice) * top_quantile))
                portfolio = list(factor_slice.index[:n_stocks])
            else:
                portfolio = prev_portfolio
        else:
            portfolio = prev_portfolio

        if not portfolio:
            rets[d] = 0
            prev_portfolio = portfolio
            continue

        if d in daily_ret.index and d in close_pivot.index:
            tradeable = [s for s in portfolio if s in daily_ret.columns]
            ret = daily_ret.loc[d, tradeable].mean() if tradeable else 0
            # 调仓日扣交易成本
            if d in rebal_set:
                tc = 0.0003 + 0.0005 + 10 / 10000
                ret -= tc
            rets[d] = ret
        prev_portfolio = portfolio

    return rets, prev_portfolio


def _compute_ew(close_pivot, rebal_dates, tc):
    """同池等权基准"""
    daily_ret = close_pivot.pct_change()
    rebal_set = set(rebal_dates) if hasattr(rebal_dates, '__iter__') else set()
    ew = pd.Series(0.0, index=close_pivot.index)
    prev_stocks = pd.Series(dtype=float)
    for d in close_pivot.index:
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
    return ew


def _compute_metrics(train_ret, val_ret, ew_train, ew_val, factor_name, ts, te, vs, ve):
    """计算单窗口的完整指标"""
    from reports.report_schema import compute_equity_curve, compute_drawdown

    train_ret = train_ret.fillna(0)
    val_ret = val_ret.fillna(0)

    # 净值
    train_eq = compute_equity_curve(train_ret)
    val_eq = compute_equity_curve(val_ret)
    ew_train_eq = compute_equity_curve(ew_train.fillna(0))
    ew_val_eq = compute_equity_curve(ew_val.fillna(0))

    # 样本内指标
    train_cum = float(train_eq.iloc[-1]) - 1 if len(train_eq) > 0 else 0
    train_cagr = float((1 + train_cum) ** (252 / max(len(train_ret), 1)) - 1) if len(train_ret) > 0 else 0
    train_sharpe = compute_sharpe(train_ret)
    train_max_dd = compute_max_drawdown(train_eq)
    train_win_rate = float((train_ret > 0).mean()) if len(train_ret) > 0 else 0

    # 样本外指标
    val_cum = float(val_eq.iloc[-1]) - 1 if len(val_eq) > 0 else 0
    val_cagr = float((1 + val_cum) ** (252 / max(len(val_ret), 1)) - 1) if len(val_ret) > 0 else 0
    val_sharpe = compute_sharpe(val_ret)
    val_max_dd = compute_max_drawdown(val_eq)
    val_win_rate = float((val_ret > 0).mean()) if len(val_ret) > 0 else 0

    # 超额 vs 同池等权
    train_excess = (train_ret - ew_train.fillna(0)).fillna(0)
    val_excess = (val_ret - ew_val.fillna(0)).fillna(0)
    train_excess_sharpe = compute_sharpe(train_excess)
    val_excess_sharpe = compute_sharpe(val_excess)

    # IC 统计
    train_days = len(train_ret)
    val_days = len(val_ret)

    # 回撤区间
    train_dd = compute_drawdown(train_eq)
    val_dd = compute_drawdown(val_eq)

    return {
        "train_start": ts, "train_end": te,
        "val_start": vs, "val_end": ve,
        "train_days": train_days,
        "val_days": val_days,
        # --- 样本内 ---
        "train_cumulative_return_pct": round(train_cum * 100, 2),
        "train_cagr_pct": round(train_cagr * 100, 2),
        "train_sharpe": round(train_sharpe, 4),
        "train_max_drawdown_pct": round(train_max_dd * 100, 2),
        "train_win_rate_pct": round(train_win_rate * 100, 2),
        "train_excess_sharpe": round(train_excess_sharpe, 4),
        # --- 样本外 ---
        "val_cumulative_return_pct": round(val_cum * 100, 2),
        "val_cagr_pct": round(val_cagr * 100, 2),
        "val_sharpe": round(val_sharpe, 4),
        "val_max_drawdown_pct": round(val_max_dd * 100, 2),
        "val_win_rate_pct": round(val_win_rate * 100, 2),
        "val_excess_sharpe": round(val_excess_sharpe, 4),
    }


def run_walk_forward(
    factor_name: str = "ret5",
    top_quantile: float = 0.2,
    rebalance: str = "monthly",
    output_dir: str = None,
) -> dict:
    """全流程 Walk-Forward 验证"""
    print(f"\n{'='*60}")
    print(f"  Walk-Forward 验证: {factor_name}")
    print(f"  Top分位数: {top_quantile:.0%}, 调仓: {rebalance}")
    print(f"{'='*60}\n")

    # Step 1: 加载数据
    print("[1/4] 加载数据...")
    df = load_data(factor_name)

    # Step 2: 运行每个窗口
    print(f"[2/4] 运行 {len(WINDOWS)} 个滚动窗口...")
    window_results = []
    for name, ts, te, vs, ve in WINDOWS:
        print(f"  窗口 {name}: train=[{ts}, {te}]  val=[{vs}, {ve}]")
        r = run_window_backtest(df, factor_name, ts, te, vs, ve, top_quantile, rebalance)
        r["window_name"] = name
        window_results.append(r)
        if "error" in r:
            print(f"    ⚠  {r['error']}")
        else:
            print(f"    Train Sharpe={r.get('train_sharpe', '?'):>8}  "
                  f"Val Sharpe={r.get('val_sharpe', '?'):>8}  "
                  f"Train Cum={r.get('train_cumulative_return_pct', '?'):>6}%  "
                  f"Val Cum={r.get('val_cumulative_return_pct', '?'):>6}%")

    # Step 3: 过拟合诊断
    print("[3/4] 计算过拟合诊断指标...")
    diagnostics = compute_overfitting_diagnostics(window_results)

    # Step 4: 输出
    out_dir = output_dir or str(OUTPUT / f"{factor_name}_walk_forward")
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "factor_name": factor_name,
        "top_quantile": top_quantile,
        "rebalance": rebalance,
        "universe": "all_watchlist + today_candidates",
        "total_windows": len(window_results),
        "windows": window_results,
        "diagnostics": diagnostics,
        "generated_at": datetime.now(CST).isoformat(),
        "data_range": f"{df['date'].min()} ~ {df['date'].max()}",
    }

    report_path = os.path.join(out_dir, "walk_forward_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[4/4] 报告已保存: {report_path}")

    _print_summary(factor_name, window_results, diagnostics)
    return report


def compute_overfitting_diagnostics(window_results: list) -> dict:
    """计算过拟合诊断指标"""
    valid = [r for r in window_results if "error" not in r]
    n = len(valid)
    if n == 0:
        return {"error": "所有窗口均无效"}

    train_sharpes = [r["train_sharpe"] for r in valid]
    val_sharpes = [r["val_sharpe"] for r in valid]
    train_cums = [r["train_cumulative_return_pct"] for r in valid]
    val_cums = [r["val_cumulative_return_pct"] for r in valid]
    train_days = [r["train_days"] for r in valid]
    val_days = [r["val_days"] for r in valid]

    # 1. Sharpe 通胀比 (越小越好, >2 严重过拟合)
    sr_inflation = []
    for tr, vr in zip(train_sharpes, val_sharpes):
        if vr > 0 and tr > 0:
            sr_inflation.append(tr / vr)
        elif vr <= 0 and tr > 0:
            sr_inflation.append(float("inf"))
        else:
            sr_inflation.append(1.0)
    avg_sr_inflation = np.mean([s for s in sr_inflation if s != float("inf")]) if any(s != float("inf") for s in sr_inflation) else float("inf")

    sr_inflation_rating = (
        "严重过拟合" if avg_sr_inflation > 3 else
        "明显过拟合" if avg_sr_inflation > 2 else
        "轻度过拟合" if avg_sr_inflation > 1.5 else
        "正常" if avg_sr_inflation <= 1.5 else "无法判断"
    )

    # 2. IC 衰减: 收益从 IS 到 OOS 的衰减比例
    return_decay = []
    for tc, vc in zip(train_cums, val_cums):
        if abs(tc) > 0.01:
            # 收益衰减 = 1 - (OOS收益/IS收益)，收益都用绝对值防止符号混淆
            decay = 1 - min(abs(vc) / abs(tc), 2)  # 最高衰减2倍
            return_decay.append(decay)
    avg_return_decay = float(np.mean(return_decay)) if return_decay else 0

    # 3. 正收益窗口比例
    oos_positive_windows = sum(1 for v in val_cums if v > 0) / n if n > 0 else 0

    # 4. 相对基准表现
    oos_excess_windows = sum(1 for r in valid if r.get("val_excess_sharpe", 0) > 0) / n if n > 0 else 0

    # 5. Val vs Train 收益相关性 (越高越好，说明策略稳定)
    if len(train_cums) > 1 and len(val_cums) > 1:
        try:
            stability_corr = float(np.corrcoef(train_cums, val_cums)[0, 1])
            if np.isnan(stability_corr):
                stability_corr = 0
        except Exception:
            stability_corr = 0  # walk_forward non-critical error
    else:
        stability_corr = 0

    # 6. PSR (Probabilistic Sharpe Ratio) — 逐窗口取最小保守值
    psr_values = []
    for r in valid:
        w_sharpe = max(r.get("val_sharpe", 0), 0)
        w_days = r.get("val_days", 20)
        if w_days > 3 and w_sharpe > 0:
            psr_values.append(compute_psr(w_sharpe, w_days))
    min_psr = min(psr_values) if psr_values else 0.0
    avg_psr = float(np.mean(psr_values)) if psr_values else 0.0
    val_sharpe_avg = float(np.mean(val_sharpes)) if val_sharpes else 0.0
    avg_val_days = int(np.mean(val_days)) if val_days else 0

    # 7. Deflated Sharpe Ratio — 分别计算后取最小
    dsr_values = []
    for r in valid:
        w_sharpe = max(r.get("val_sharpe", 0), 0)
        w_days = r.get("val_days", 20)
        if w_days > 3 and w_sharpe > 0:
            dsr_values.append(compute_deflated_sharpe(w_sharpe, w_days, n_trials=27 * 4))
    min_dsr = min(dsr_values) if dsr_values else 0.0
    avg_dsr = float(np.mean(dsr_values)) if dsr_values else 0.0

    # 8. 最大回撤稳定性
    val_dd = [r["val_max_drawdown_pct"] for r in valid]
    avg_val_dd = float(np.mean(val_dd)) if val_dd else 0

    return {
        "sharpe_inflation_ratio": round(avg_sr_inflation, 4) if avg_sr_inflation != float("inf") else "inf",
        "sharpe_inflation_rating": sr_inflation_rating,
        "sharpe_inflation_details": [round(s, 4) if s != float("inf") else "inf" for s in sr_inflation],
        "return_decay_mean": round(avg_return_decay, 4),
        "oos_positive_window_ratio_pct": round(oos_positive_windows * 100, 1),
        "oos_excess_benchmark_ratio_pct": round(oos_excess_windows * 100, 1),
        "is_oos_stability_correlation": round(stability_corr, 4),
        "avg_val_sharpe": round(val_sharpe_avg, 4),
        "avg_train_sharpe": round(float(np.mean(train_sharpes)), 4),
        "avg_val_max_drawdown_pct": round(avg_val_dd, 2),
        "avg_val_cumulative_return_pct": round(float(np.mean(val_cums)), 2),
        "avg_train_cumulative_return_pct": round(float(np.mean(train_cums)), 2),
        "probabilistic_sharpe_ratio": round(min_psr, 4),
        "deflated_sharpe_ratio": round(min_dsr, 4),
        "n_windows": n,
        "n_observations_avg": avg_val_days,
    }


def _print_summary(factor_name, window_results, diagnostics):
    """输出人类可读的摘要"""
    d = diagnostics
    if "error" in d:
        print(f"\n❌ 诊断出错: {d['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  Walk-Forward 验证报告: {factor_name}")
    print(f"{'='*60}")

    print(f"\n📊 各窗口表现:")
    print(f"  {'窗口':>6} | {'Train Cum':>10} | {'Val Cum':>10} | {'Train SR':>9} | {'Val SR':>9} | {'SR通胀':>7}")
    print(f"  {'-'*6}-+-{'-'*10}-+-{'-'*10}-+-{'-'*9}-+-{'-'*9}-+-{'-'*7}")
    for r in window_results:
        if "error" in r:
            print(f"  {r.get('window_name','?'):>6} | {'ERROR':>10}")
            continue
        tc = f"{r['train_cumulative_return_pct']:>8.1f}%"
        vc = f"{r['val_cumulative_return_pct']:>8.1f}%"
        ts = f"{r['train_sharpe']:>7.2f}"
        vs = f"{r['val_sharpe']:>7.2f}"
        sr_infl = f"{r['train_sharpe']/r['val_sharpe']:>5.1f}" if r.get('val_sharpe', 0) > 0 else " N/A"
        print(f"  {r['window_name']:>6} | {tc} | {vc} | {ts}  | {vs}  | {sr_infl}")

    print(f"\n🔍 过拟合诊断:")
    print(f"  Sharpe 通胀比:          {d.get('sharpe_inflation_ratio', 'N/A')}  → {d.get('sharpe_inflation_rating', 'N/A')}")
    print(f"  收益衰减系数:           {d.get('return_decay_mean', 'N/A')}  (0=无衰减, 1=完全衰减)")
    print(f"  OOS 正收益窗口比例:     {d.get('oos_positive_window_ratio_pct', 'N/A')}%")
    print(f"  IS/OOS 收益相关性:      {d.get('is_oos_stability_correlation', 'N/A')}  (越接近+1越稳定)")
    print(f"  平均 Train Sharpe:      {d.get('avg_train_sharpe', 'N/A')}")
    print(f"  平均 Val Sharpe:        {d.get('avg_val_sharpe', 'N/A')}")
    print(f"  平均 Val 最大回撤:      {d.get('avg_val_max_drawdown_pct', 'N/A')}%")
    print(f"  PSR (最小-保守):        {d.get('probabilistic_sharpe_ratio', 'N/A')}  (Probabilistic Sharpe Ratio)")
    print(f"  DSR (最小-保守):        {d.get('deflated_sharpe_ratio', 'N/A')}  (Deflated Sharpe Ratio, 考虑多重测试)")

    print(f"\n{'='*60}")
    # 判断结论
    if d.get('oos_positive_window_ratio_pct', 0) >= 75:
        print(f"  ✅ 结论: ret5 因子稳健性良好 — 样本外多数窗口正收益")
    elif d.get('oos_positive_window_ratio_pct', 0) >= 50:
        print(f"  ⚠️  结论: ret5 因子样本外表现中性 — 约半数窗口正收益")
    else:
        print(f"  ❌ 结论: ret5 因子可能存在过拟合 — 样本外表现弱于样本内")
    if d.get('sharpe_inflation_rating', '') == '严重过拟合':
        print(f"  🚨 Sharpe 通胀比过高, 请考虑简化因子或增加样本外验证")
    elif d.get('sharpe_inflation_rating', '') == '明显过拟合':
        print(f"  ⚠️  Sharpe 有一定通胀, 建议进行参数缩减")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Walk-Forward 样本外验证")
    parser.add_argument("factor", nargs="?", default="ret5", help="因子名 (默认 ret5)")
    parser.add_argument("--top-quantile", type=float, default=0.2, help="Top 组分位数 (默认 0.2)")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"], help="调仓频率")
    args = parser.parse_args()
    run_walk_forward(args.factor, args.top_quantile, args.rebalance)
