#!/usr/bin/env python3
"""因子验证主入口 — 反过拟合 + Walk-Forward + 评分

用法:
    python -m factor_lab.validate_factor \\
        --factor ret5 \\
        --universe all_watchlist \\
        --start 2025-01-02 --end 2026-06-30 \\
        --rebalance monthly \\
        --top-n 20 \\
        --run-anti-overfit \\
        --run-walk-forward \\
        --output /mnt/d/HermesReports/factor_validation
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

CST = timezone(timedelta(hours=8))

# 确保模块路径
sys.path.insert(0, str(Path(__file__).parent))


def parse_args():
    p = argparse.ArgumentParser(description="因子稳健性验证系统")
    p.add_argument("--factor", default="ret5", help="因子名称 (默认 ret5)")
    p.add_argument("--universe", default="all_watchlist", help="股票池名称")
    p.add_argument("--start", default="2025-01-02", help="回测开始日期")
    p.add_argument("--end", default="2026-06-30", help="回测结束日期")
    p.add_argument("--benchmark", default="000300.SH", help="市场基准代码")
    p.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"], help="调仓频率")
    p.add_argument("--top-n", type=int, default=20, help="选股数量")
    p.add_argument("--run-anti-overfit", action="store_true", default=True, help="运行反过拟合检查")
    p.add_argument("--run-walk-forward", action="store_true", default=True, help="运行 Walk-Forward")
    p.add_argument("--output", default=None, help="输出目录")
    return p.parse_args()


def run_validation(args) -> dict:
    """全流程: 加载数据 → 反过拟合 → Walk-Forward → 评分 → 报告"""
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from factor_lab.validation.anti_overfit import run_anti_overfit
    from factor_lab.validation.rolling_validator import run_rolling_validation
    from factor_lab.scoring.factor_score import score_factor
    from factor_lab.reports.validation_report import generate_validation_report
    from strategy_lab.universe import build

    factor_name = args.factor
    start_date = args.start
    end_date = args.end
    top_quantile = args.top_n / 100 if args.top_n < 100 else 0.2

    print(f"\n{'='*60}")
    print(f"  因子验证: {factor_name}")
    print(f"  区间: {start_date} ~ {end_date}")
    print(f"  调仓: {args.rebalance}, Top分位数: {top_quantile:.0%}")
    print(f"{'='*60}\n")

    # ── 1. 加载数据 ──
    print("[1/6] 加载股票池...")
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    print(f"  股票池: {len(symbols)} 只")

    print("[2/6] 加载 K 线及因子...")
    padding_start = pd.Timestamp(start_date) - pd.Timedelta(days=120)
    df = load_stock_kline(symbols, start_date=str(padding_start.date()), end_date=end_date)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))
    print(f"  K 线: {len(df)} 行, {df['date'].min()} ~ {df['date'].max()}")

    # 计算因子
    registry = {f["name"]: f for f in list_factors()}
    if factor_name not in registry:
        raise ValueError(f"因子 {factor_name} 不在注册表。可用: {list(registry.keys())}")
    fdef = registry[factor_name]
    df[factor_name] = fdef["func"](df, **fdef["params"])

    # Pivot
    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    # 过滤到有效区间
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    df = df[mask].copy()

    expression = fdef.get("description", "")
    extra = {
        "factor_name": factor_name,
        "expression": expression,
        "universe": args.universe,
        "benchmark": args.benchmark,
        "rebalance_freq": args.rebalance,
        "requested_period": f"{start_date} ~ {end_date}",
        "matched_period": f"{df['date'].min()} ~ {df['date'].max()}",
    }

    anti_overfit = None
    rolling_valid = None

    # ── 2. 反过拟合检查 ──
    if args.run_anti_overfit:
        print("\n[3/6] 反过拟合诊断...")
        anti_overfit = run_anti_overfit(
            df, factor_name, close_pivot=close_pivot,
            top_quantile=top_quantile, rebalance=args.rebalance,
        )
        _print_anti_overfit_summary(anti_overfit)

    # ── 3. Walk-Forward ──
    if args.run_walk_forward:
        print("\n[4/6] Walk-Forward 滚动验证...")
        rolling_valid = run_rolling_validation(
            df, factor_name, close_pivot,
            top_quantile=top_quantile, rebalance=args.rebalance,
            start_date=start_date, end_date=end_date,
        )
        _print_rolling_summary(rolling_valid)

    # ── 4. 评分 ──
    print("\n[5/6] 因子评分...")
    from factor_lab.scoring.factor_family import classify_factor
    family_info = classify_factor(factor_name, fdef.get("category", ""), expression)
    family = family_info.get("family", "unknown")
    factor_score = score_factor(
        anti_overfit or {},
        rolling_validation=rolling_valid,
        expression=expression,
        family=family,
    )
    _print_score_summary(factor_score)

    # ── 5. 报告 ──
    print("\n[6/6] 生成报告...")
    report_result = generate_validation_report(
        anti_overfit or {},
        factor_score,
        rolling_validation=rolling_valid,
        output_dir=args.output,
        extra=extra,
    )

    print(f"\n📄 报告已生成: {report_result['report_path']}")
    print(f"📁 输出目录: {report_result['output_dir']}")
    print(f"📋 文件: {', '.join(report_result['files'])}")

    return {
        "report": report_result,
        "anti_overfit": anti_overfit,
        "rolling_validation": rolling_valid,
        "factor_score": factor_score,
        "extra": extra,
    }


def _print_anti_overfit_summary(ao: dict):
    if not ao:
        return
    print(f"  总体判定: {ao.get('overall_verdict', '?')}")
    ic = ao.get("ic_stability", {})
    print(f"  IC: IR={ic.get('ic_ir','?'):.4f}, POS={ic.get('positive_ic_ratio','?'):.1%}  [{ic.get('verdict','?')}]")
    pb = ao.get("placebo", {})
    print(f"  Placebo: perc={pb.get('factor_score_percentile','?'):.0f}%, Z={pb.get('zscore_vs_placebo','?'):.2f}  [{pb.get('verdict','?')}]")
    pr = ao.get("peer_benchmark", {})
    print(f"  同池对照: 超额={pr.get('excess_return_pct','?'):.1f}%  [{pr.get('verdict','?')}]")


def _print_rolling_summary(rv: dict):
    if not rv:
        return
    print(f"  Limitation: {rv.get('limitation','?')}")
    print(f"  窗口: {len(rv.get('windows',[]))} 个")
    print(f"  Avg Test Sharpe: {rv.get('avg_test_sharpe','?'):.4f}")
    print(f"  Avg Decay: {rv.get('avg_decay','?'):.4f}")
    print(f"  OOS Positive: {rv.get('oos_positive_ratio',0)*100:.0f}%")
    print(f"  Verdict: {rv.get('overall_verdict','?')}")


def _print_score_summary(fs: dict):
    if not fs:
        return
    print(f"  Score: {fs.get('overall_score','?'):.1f} / {fs.get('grade','?')}")
    print(f"  Pass Gate: {fs.get('pass_gate','?')}")
    for r in fs.get("reject_reasons", []):
        print(f"    ❌ {r}")


if __name__ == "__main__":
    args = parse_args()
    result = run_validation(args)
