"""Rolling Walk-Forward Validation — 滚动三窗口 (Train/Val/Test) 验证

对单个因子做 rolling walk-forward 验证:
  - 每次一个 train/val/test 三窗口 (6/3/3 月, 步长 1 个月)
  - train 期选股, val 期验证, test 期样本外检验
  - 各窗口用各自区间的因子值重新排序选股 (无未来泄漏)
  - 逐月滚动, 报告各窗口的收益/Sharpe/最大回撤/IC
  - 计算 decay_train_to_test = 1 - (test_sharpe / train_sharpe)
  - 数据限制判断: insufficient_data / limited / full
"""

import sys, os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # → commands/
from reports.report_schema import compute_equity_curve, compute_drawdown

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parents[3]
OUTPUT = Path(os.environ.get("HERMES_ROLLING_VALIDATION_REPORT_ROOT", "/mnt/d/HermesReports/rolling_validation"))


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════


def _first_trading_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """获取每个月的第一个交易日

    用 groupby year-month 取当月第一个日期, 解决 is_month_start
    不识别交易日的问题, 并修正跨年同月被错误归组的 bug。
    """
    if len(dates) == 0:
        return dates
    s = pd.Series(index=dates, data=1)
    # 使用 to_period('M') 按年-月分组, 避免跨年同月的 bug
    first_per_month = s.groupby(dates.to_period('M')).apply(lambda x: x.index[0])
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


# ═══════════════════════════════════════════════════════════════════
# 组合回测与基准
# ═══════════════════════════════════════════════════════════════════


def _run_portfolio(
    df: pd.DataFrame,
    factor_name: str,
    rebal_dates: pd.DatetimeIndex,
    all_dates: pd.DatetimeIndex,
    close_pivot: pd.DataFrame,
    top_quantile: float,
) -> tuple[pd.Series, list]:
    """在给定日期序列上运行 Top-Quantile 组合

    参数:
        df: 因子数据 (已按窗口切片避免未来泄漏)
        factor_name: 因子列名
        rebal_dates: 调仓日序列
        all_dates: 所有交易日序列
        close_pivot: pivot 表 (date × symbol)
        top_quantile: 选股分位数

    返回:
        (returns_series, positions_list)
    """
    daily_ret = close_pivot.pct_change()
    rebal_set = set(rebal_dates) if hasattr(rebal_dates, '__iter__') else set()
    rets = pd.Series(0.0, index=all_dates)
    positions_list = []
    prev_portfolio = []

    for d in all_dates:
        if d in rebal_set:
            # 取该日的因子值排序选股
            factor_slice = (
                df[df["date"] == d]
                .set_index("symbol")[factor_name]
                .dropna()
                .sort_values(ascending=False)
            )
            if len(factor_slice) > 0:
                n_stocks = max(1, int(len(factor_slice) * top_quantile))
                portfolio = list(factor_slice.index[:n_stocks])
            else:
                portfolio = prev_portfolio
        else:
            portfolio = prev_portfolio

        positions_list.append(list(portfolio))

        if not portfolio:
            rets[d] = 0
            prev_portfolio = portfolio
            continue

        if d in daily_ret.index:
            tradeable = [s for s in portfolio if s in daily_ret.columns]
            ret = daily_ret.loc[d, tradeable].mean() if tradeable else 0
            # 调仓日扣交易成本 (佣金+印花税+滑点)
            if d in rebal_set:
                tc = 0.0003 + 0.0005 + 10 / 10000
                ret -= tc
            rets[d] = ret
        prev_portfolio = portfolio

    return rets, positions_list


def _compute_ew(close_pivot: pd.DataFrame, rebal_dates: pd.DatetimeIndex, tc: float) -> pd.Series:
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


# ═══════════════════════════════════════════════════════════════════
# 指标计算
# ═══════════════════════════════════════════════════════════════════


def _compute_window_metrics(
    returns_series: pd.Series,
    ew_series: pd.Series,
    factor_df: pd.DataFrame,
    factor_name: str,
    period_dates: pd.DatetimeIndex,
) -> dict:
    """计算单窗口指标

    返回:
        cumulative_return_pct, sharpe, max_drawdown_pct,
        win_rate_pct, ic_mean
    """
    returns = returns_series.fillna(0)
    ew = ew_series.fillna(0)

    equity = compute_equity_curve(returns)

    cum_ret = float(equity.iloc[-1]) - 1 if len(equity) > 0 else 0
    sharpe = compute_sharpe(returns)
    max_dd = compute_max_drawdown(equity)
    win_rate = float((returns > 0).mean()) if len(returns) > 0 else 0

    # — IC: 在每一日计算截面 Spearman rank correlation —
    #   因子值 vs 下期收益 (ret1), 然后取均值
    ic_values = []
    for d in period_dates:
        day_data = factor_df[factor_df["date"] == d]
        if len(day_data) < 10:
            continue
        day_data = day_data.set_index("symbol")
        if factor_name not in day_data.columns or "ret1" not in day_data.columns:
            continue
        vals = day_data[[factor_name, "ret1"]].dropna()
        if len(vals) < 10:
            continue
        ic = vals[factor_name].corr(vals["ret1"], method="spearman")
        if not np.isnan(ic):
            ic_values.append(ic)

    ic_mean = float(np.mean(ic_values)) if ic_values else 0.0

    return {
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate * 100, 2),
        "ic_mean": round(ic_mean, 4),
    }


# ═══════════════════════════════════════════════════════════════════
# 窗口生成逻辑
# ═══════════════════════════════════════════════════════════════════


def _generate_windows(
    all_dates: pd.DatetimeIndex,
    start_date: str,
    end_date: str,
    train_months: int,
    val_months: int,
    test_months: int,
    step_months: int,
) -> list[dict]:
    """生成滚动窗口列表

    每个窗口:
      train_start ~ train_end  (train_months 个月)
      val_start   ~ val_end    (val_months 个月)
      test_start  ~ test_end   (test_months 个月)
    然后以 step_months 步长向右滑动。
    跳过不足 train 的初始部分和超出 end_date 的部分。
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # 限定到总区间内
    mask = (all_dates >= start) & (all_dates <= end)
    if not mask.any():
        return []
    working_dates = all_dates[mask]

    def first_ge(ref: pd.Timestamp):
        m = working_dates >= ref
        return working_dates[m][0] if m.any() else None

    def last_lt(ref: pd.Timestamp):
        m = working_dates < ref
        return working_dates[m][-1] if m.any() else None

    def first_gt(ref: pd.Timestamp):
        m = working_dates > ref
        return working_dates[m][0] if m.any() else None

    windows = []
    current = start

    while True:
        train_start = first_ge(current)
        if train_start is None:
            break

        train_end_cutoff = train_start + pd.DateOffset(months=train_months)
        train_end = last_lt(train_end_cutoff)
        if train_end is None or train_end <= train_start:
            break

        val_start = first_gt(train_end)
        if val_start is None:
            break

        val_end_cutoff = val_start + pd.DateOffset(months=val_months)
        val_end = last_lt(val_end_cutoff)
        if val_end is None or val_end <= val_start:
            break

        test_start = first_gt(val_end)
        if test_start is None:
            break

        test_end_cutoff = test_start + pd.DateOffset(months=test_months)
        test_end = last_lt(test_end_cutoff)
        if test_end is None or test_end <= test_start:
            break

        if test_end > end:
            break

        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "val_start": val_start,
            "val_end": val_end,
            "test_start": test_start,
            "test_end": test_end,
        })

        # 向右滑动 step_months 个月 (从 train_start 算起)
        current = train_start + pd.DateOffset(months=step_months)

    return windows


# ═══════════════════════════════════════════════════════════════════
# 单窗口运行
# ═══════════════════════════════════════════════════════════════════


def _run_single_window(
    df: pd.DataFrame,
    factor_name: str,
    close_pivot: pd.DataFrame,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    val_start: pd.Timestamp,
    val_end: pd.Timestamp,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    top_quantile: float,
    tc: float,
) -> dict:
    """运行单个 train/val/test 窗口

    各期使用各自区间的因子值重新排序选股 (top_quantile 固定),
    避免未来函数泄漏。
    """
    # ── 切片 df (避免未来泄漏的关键) ──
    train_df = df[(df["date"] >= train_start) & (df["date"] <= train_end)].copy()
    val_df = df[(df["date"] >= val_start) & (df["date"] <= val_end)].copy()
    test_df = df[(df["date"] >= test_start) & (df["date"] <= test_end)].copy()

    # ── 交易日序列与调仓日 ──
    all_dates_train = close_pivot.loc[train_start:train_end].index
    all_dates_val = close_pivot.loc[val_start:val_end].index
    all_dates_test = close_pivot.loc[test_start:test_end].index

    rebal_dates_train = _first_trading_days(all_dates_train)
    rebal_dates_val = _first_trading_days(all_dates_val)
    rebal_dates_test = _first_trading_days(all_dates_test)

    # ── 运行组合 ──
    train_ret, _ = _run_portfolio(
        train_df, factor_name, rebal_dates_train,
        all_dates_train, close_pivot, top_quantile,
    )
    val_ret, _ = _run_portfolio(
        val_df, factor_name, rebal_dates_val,
        all_dates_val, close_pivot, top_quantile,
    )
    test_ret, _ = _run_portfolio(
        test_df, factor_name, rebal_dates_test,
        all_dates_test, close_pivot, top_quantile,
    )

    # ── 同池等权基准 ──
    ew_train = _compute_ew(close_pivot.loc[train_start:train_end], rebal_dates_train, tc)
    ew_val = _compute_ew(close_pivot.loc[val_start:val_end], rebal_dates_val, tc)
    ew_test = _compute_ew(close_pivot.loc[test_start:test_end], rebal_dates_test, tc)

    # ── 指标 ──
    train_metrics = _compute_window_metrics(train_ret, ew_train, train_df, factor_name, all_dates_train)
    val_metrics = _compute_window_metrics(val_ret, ew_val, val_df, factor_name, all_dates_val)
    test_metrics = _compute_window_metrics(test_ret, ew_test, test_df, factor_name, all_dates_test)

    # ── 衰减: 1 - test_Sharpe / train_Sharpe ──
    train_sharpe = train_metrics["sharpe"]
    test_sharpe = test_metrics["sharpe"]
    if train_sharpe > 0:
        decay = 1.0 - (test_sharpe / train_sharpe)
    else:
        decay = 0.0

    def _fmt(ts):
        return ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)

    return {
        "train_start": _fmt(train_start),
        "train_end": _fmt(train_end),
        "val_start": _fmt(val_start),
        "val_end": _fmt(val_end),
        "test_start": _fmt(test_start),
        "test_end": _fmt(test_end),

        "train_days": len(all_dates_train),
        "val_days": len(all_dates_val),
        "test_days": len(all_dates_test),

        "train_cumulative_return_pct": train_metrics["cumulative_return_pct"],
        "train_sharpe": train_metrics["sharpe"],
        "train_max_drawdown_pct": train_metrics["max_drawdown_pct"],
        "train_win_rate_pct": train_metrics["win_rate_pct"],
        "train_ic_mean": train_metrics["ic_mean"],

        "val_cumulative_return_pct": val_metrics["cumulative_return_pct"],
        "val_sharpe": val_metrics["sharpe"],
        "val_max_drawdown_pct": val_metrics["max_drawdown_pct"],
        "val_win_rate_pct": val_metrics["win_rate_pct"],
        "val_ic_mean": val_metrics["ic_mean"],

        "test_cumulative_return_pct": test_metrics["cumulative_return_pct"],
        "test_sharpe": test_metrics["sharpe"],
        "test_max_drawdown_pct": test_metrics["max_drawdown_pct"],
        "test_win_rate_pct": test_metrics["win_rate_pct"],
        "test_ic_mean": test_metrics["ic_mean"],

        "decay_train_to_test": round(decay, 4),
    }


# ═══════════════════════════════════════════════════════════════════
# 主验证流程
# ═══════════════════════════════════════════════════════════════════


def run_rolling_validation(
    df: pd.DataFrame,
    factor_name: str,
    close_pivot: pd.DataFrame,
    top_quantile: float = 0.2,
    rebalance: str = 'monthly',
    train_window_months: int = 6,
    val_window_months: int = 3,
    test_window_months: int = 3,
    step_months: int = 1,
    start_date: str = '2025-01-02',
    end_date: str = '2026-06-30',
) -> dict:
    """滚动三窗口 Walk-Forward 验证

    步骤:
      1. 数据量检查 → 判断 limitation
      2. 生成滚动窗口 (含生成逻辑)
      3. 运行每个窗口 (train/val/test)
      4. 汇总统计 + 综合判定
      5. 返回结构化 dict

    limitation 判断:
      - total_days < 200 (≈9个月) → 'insufficient_data'
      - windows < 2               → 'limited'
      - 否则                     → 'full'
    """
    all_dates = close_pivot.index.sort_values()

    # ── 1. 数据量判断 ──
    total_days = len(all_dates)
    if total_days < 200:
        return {
            "factor_name": factor_name,
            "limitation": "insufficient_data",
            "total_days": total_days,
            "windows": [],
            "generated_at": datetime.now(CST).isoformat(),
        }

    # ── 2. 生成窗口 ──
    raw_windows = _generate_windows(
        all_dates, start_date, end_date,
        train_window_months, val_window_months,
        test_window_months, step_months,
    )

    if len(raw_windows) < 2:
        return {
            "factor_name": factor_name,
            "limitation": "limited",
            "total_windows": len(raw_windows),
            "total_days": total_days,
            "windows": [],
            "generated_at": datetime.now(CST).isoformat(),
        }

    limitation = "full"
    tc = 0.0003 + 0.0005 + 10 / 10000  # 佣金 + 印花税 + 滑点

    # ── 3. 运行每个窗口 ──
    window_results = []
    for i, w in enumerate(raw_windows):
        win = _run_single_window(
            df, factor_name, close_pivot,
            w["train_start"], w["train_end"],
            w["val_start"], w["val_end"],
            w["test_start"], w["test_end"],
            top_quantile, tc,
        )
        win["window_name"] = f"w{i + 1}"
        window_results.append(win)

    # ── 4. 汇总 ──
    _extract = lambda key: [r[key] for r in window_results if key in r]

    train_sharpes = _extract("train_sharpe")
    val_sharpes = _extract("val_sharpe")
    test_sharpes = _extract("test_sharpe")
    decays = [r["decay_train_to_test"] for r in window_results]
    test_cums = _extract("test_cumulative_return_pct")

    avg_train_sharpe = float(np.mean(train_sharpes)) if train_sharpes else 0.0
    avg_val_sharpe = float(np.mean(val_sharpes)) if val_sharpes else 0.0
    avg_test_sharpe = float(np.mean(test_sharpes)) if test_sharpes else 0.0
    avg_decay = float(np.mean(decays)) if decays else 0.0
    oos_positive_ratio = (
        sum(1 for c in test_cums if c > 0) / len(test_cums)
        if test_cums else 0.0
    )

    # 综合判定
    if avg_test_sharpe > 0.5 and oos_positive_ratio >= 0.5:
        overall_verdict = "pass"
    elif avg_test_sharpe > 0 and oos_positive_ratio >= 0.3:
        overall_verdict = "warn"
    else:
        overall_verdict = "fail"

    result = {
        "factor_name": factor_name,
        "config": {
            "top_quantile": top_quantile,
            "rebalance": rebalance,
            "train_window_months": train_window_months,
            "val_window_months": val_window_months,
            "test_window_months": test_window_months,
            "step_months": step_months,
            "start_date": start_date,
            "end_date": end_date,
        },
        "windows": window_results,
        "avg_train_sharpe": round(avg_train_sharpe, 4),
        "avg_val_sharpe": round(avg_val_sharpe, 4),
        "avg_test_sharpe": round(avg_test_sharpe, 4),
        "avg_decay": round(avg_decay, 4),
        "oos_positive_ratio": round(oos_positive_ratio, 4),
        "overall_verdict": overall_verdict,
        "limitation": limitation,
        "total_days": total_days,
        "total_windows": len(window_results),
        "generated_at": datetime.now(CST).isoformat(),
    }

    return result


# ═══════════════════════════════════════════════════════════════════
# 数据加载与包装器
# ═══════════════════════════════════════════════════════════════════


def load_data(factor_name: str) -> pd.DataFrame:
    """加载 K 线并计算指定因子

    与 walk_forward.py 的 load_data 保持一致的逻辑。
    """
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from strategy_lab.universe import build

    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    print(f"  股票池: {len(symbols)} 只")

    df = load_stock_kline(symbols, start_date="2024-10-01", end_date="2026-06-30")
    print(f"  K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    # 下期收益
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))

    # 计算因子
    registry = {f["name"]: f for f in list_factors()}
    if factor_name not in registry:
        raise ValueError(
            f"因子 {factor_name} 不在注册表中。可用: {list(registry.keys())}"
        )

    fdef = registry[factor_name]
    factor_values = fdef["func"](df, **fdef["params"])
    df[factor_name] = factor_values

    return df


def _make_serializable(obj):
    """递归将 Timestamp/Period 转为字符串"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (pd.Timestamp, pd.Period)):
        return str(obj)
    return obj


def _print_summary(factor_name: str, result: dict):
    """打印人类可读的摘要"""
    if result.get("limitation") in ("insufficient_data", "limited"):
        print(f"\n⚠  数据不足: limitation={result['limitation']}")
        return

    windows = result.get("windows", [])
    print(f"\n📊  窗口数: {len(windows)}")
    print(f"    平均 Train Sharpe: {result.get('avg_train_sharpe', 'N/A')}")
    print(f"    平均 Val Sharpe:   {result.get('avg_val_sharpe', 'N/A')}")
    print(f"    平均 Test Sharpe:  {result.get('avg_test_sharpe', 'N/A')}")
    print(f"    平均 Train→Test 衰减: {result.get('avg_decay', 'N/A')}")
    print(f"    Test 正收益比例:   {result.get('oos_positive_ratio', 'N/A')}")
    print(f"    综合判定:          {result.get('overall_verdict', 'N/A')}")
    print(f"    数据限制:          {result.get('limitation', 'N/A')}")
    print()

    # 表格
    header = f"  {'窗口':>6} | {'Train SR':>8} | {'Val SR':>8} | {'Test SR':>8} | {'衰减':>6} | {'Test Cum':>8}"
    sep = f"  {'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*6}-+-{'-'*8}"
    print(header)
    print(sep)
    for w in windows:
        wname = w.get("window_name", "?")
        ts = f"{w['train_sharpe']:>7.2f}" if isinstance(w.get("train_sharpe"), (int, float)) else "  N/A  "
        vs = f"{w['val_sharpe']:>7.2f}" if isinstance(w.get("val_sharpe"), (int, float)) else "  N/A  "
        tes = f"{w['test_sharpe']:>7.2f}" if isinstance(w.get("test_sharpe"), (int, float)) else "  N/A  "
        decay = f"{w['decay_train_to_test']:>5.2f}" if isinstance(w.get("decay_train_to_test"), (int, float)) else " N/A "
        tc = f"{w['test_cumulative_return_pct']:>7.2f}%" if isinstance(w.get("test_cumulative_return_pct"), (int, float)) else "  N/A  "
        print(f"  {wname:>6} | {ts} | {vs} | {tes} | {decay} | {tc}")


def run_rolling_validation_wrapper(factor_name: str, **kwargs) -> dict:
    """全流程包装: 加载数据 → 运行验证 → 输出

    参数:
        factor_name: 因子名
        **kwargs: 传递给 run_rolling_validation 的参数

    返回:
        结构化的验证结果 dict
    """
    print(f"\n{'=' * 60}")
    print(f"  Rolling Walk-Forward 验证: {factor_name}")
    print(f"{'=' * 60}\n")

    # Step 1: 加载数据
    print("[1/3] 加载数据...")
    df = load_data(factor_name)

    # Step 2: 运行验证
    print("[2/3] 构建 close_pivot 并运行滚动验证...")
    close_pivot = df.pivot_table(index="date", columns="symbol", values="close").sort_index()

    result = run_rolling_validation(df, factor_name, close_pivot, **kwargs)

    # Step 3: 输出
    print("[3/3] 输出结果...")
    out_dir = kwargs.get("output_dir") or str(OUTPUT / f"{factor_name}_rolling_validation")
    os.makedirs(out_dir, exist_ok=True)

    result_serializable = _make_serializable(result)

    report_path = os.path.join(out_dir, "rolling_validation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result_serializable, f, ensure_ascii=False, indent=2)
    print(f"  报告已保存: {report_path}")

    _print_summary(factor_name, result)

    return result


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rolling Walk-Forward 验证 (Train/Val/Test)")
    parser.add_argument("factor", nargs="?", default="ret5", help="因子名 (默认 ret5)")
    parser.add_argument("--top-quantile", type=float, default=0.2, help="Top 组分位数")
    parser.add_argument("--train-months", type=int, default=6, help="训练窗口月数")
    parser.add_argument("--val-months", type=int, default=3, help="验证窗口月数")
    parser.add_argument("--test-months", type=int, default=3, help="测试窗口月数")
    parser.add_argument("--step-months", type=int, default=1, help="滚动步长(月)")
    parser.add_argument("--start-date", default="2025-01-02", help="回测开始日期")
    parser.add_argument("--end-date", default="2026-06-30", help="回测结束日期")
    parser.add_argument("--output-dir", default=None, help="输出目录 (可选)")
    args = parser.parse_args()

    kwargs = {
        "top_quantile": args.top_quantile,
        "train_window_months": args.train_months,
        "val_window_months": args.val_months,
        "test_window_months": args.test_months,
        "step_months": args.step_months,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "output_dir": args.output_dir,
    }

    run_rolling_validation_wrapper(args.factor, **kwargs)
