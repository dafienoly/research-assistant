#!/usr/bin/env python3
"""多因子组合验证主入口

用法:
    python -m factor_lab.validate_composites
        --candidate-pool reports/factor_leaderboard/20260704_155707/factor_leaderboard.json
        --start 2025-01-02 --end 2026-06-30
        --rebalance monthly --top-n 20
        --methods equal_weight_score,weighted_score,gated_score,zscore_blend,rank_blend
        --output /mnt/d/HermesReports/composite_leaderboard
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

CST = timezone(timedelta(hours=8))


def parse_args():
    p = argparse.ArgumentParser(description="多因子组合验证")
    p.add_argument("--candidate-pool", default=None, help="V1.4 factor_leaderboard.json 路径")
    p.add_argument("--factors", default=None, help="手动指定因子, 逗号分隔")
    p.add_argument("--start", default="2025-01-02", help="开始日期")
    p.add_argument("--end", default="2026-06-30", help="结束日期")
    p.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--methods", default="equal_weight_score,weighted_score,gated_score,zscore_blend,rank_blend",
                   help="组合方法, 逗号分隔")
    p.add_argument("--output", default=None, help="输出目录")
    return p.parse_args()


def main():
    args = parse_args()

    # ── 1. 确定要组合的因子 ──
    if args.factors:
        factor_names = [f.strip() for f in args.factors.split(",")]
        weights = {f: 1.0 / len(factor_names) for f in factor_names}
    elif args.candidate_pool:
        from factor_lab.pool.candidate_pool import load_from_leaderboard
        pool = load_from_leaderboard(args.candidate_pool)
        factor_names = pool.promoted_names
        weights = {f: 1.0 / len(factor_names) for f in factor_names}
        print(f"从候选池加载 {len(factor_names)} 个推荐因子: {factor_names}")
    else:
        factor_names = ["ret5", "ret10", "close_gt_ma20"]
        weights = {f: 1.0 / len(factor_names) for f in factor_names}
        print(f"使用默认因子: {factor_names}")

    if len(factor_names) < 2:
        print("❌ 至少需要 2 个因子进行组合")
        return

    methods = [m.strip() for m in args.methods.split(",")]

    print(f"\n{'='*60}")
    print(f"  多因子组合验证")
    print(f"  因子: {factor_names}")
    print(f"  方法: {methods}")
    print(f"  区间: {args.start} ~ {args.end}")
    print(f"  调仓: {args.rebalance}, Top{args.top_n}")
    print(f"{'='*60}\n")

    # ── 2. 加载数据 ──
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from strategy_lab.universe import build

    print("[1/4] 加载股票池...")
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    print(f"  股票池: {len(symbols)} 只")

    print("[2/4] 加载 K 线...")
    padding_start = pd.Timestamp(args.start) - pd.Timedelta(days=120)
    df = load_stock_kline(symbols, start_date=str(padding_start.date()), end_date=args.end)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))
    print(f"  K 线: {len(df)} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    mask = (df["date"] >= args.start) & (df["date"] <= args.end)
    df_valid = df[mask].copy()

    # ── 3. 计算基础因子 ──
    print("[3/4] 计算基础因子...")
    registry = {f["name"]: f for f in list_factors()}
    for fn in factor_names:
        if fn in registry:
            fdef = registry[fn]
            vals = fdef["func"](df, **fdef["params"])
            df_valid[fn] = vals[mask.values] if hasattr(mask, 'values') else vals[mask]
            print(f"  {fn}: 已计算")
        else:
            print(f"  ⚠️ {fn} 不在注册表")

    # ── 4. 计算相关性 ──
    from factor_lab.composite.factor_correlation import compute_correlation, compute_topn_overlap
    print("\n  计算因子相关性...")
    corr_result = compute_correlation(df_valid, factor_names)
    overlap_result = compute_topn_overlap(df_valid, factor_names, top_quantile=args.top_n / 100)
    print(f"  Avg Pearson Corr: {corr_result.get('avg_corr', 0):.4f}")
    print(f"  Avg TopN Overlap: {overlap_result.get('avg_overlap', 0):.4f}")
    for f1 in factor_names:
        for f2 in factor_names:
            if f1 < f2:
                p = corr_result.get("pearson", {}).get(f1, {}).get(f2, "?")
                o = overlap_result.get("overlap_matrix", {}).get(f1, {}).get(f2, "?")
                print(f"    {f1} vs {f2}:  pearson={p}  overlap={o}")

    # ── 5. 运行组合验证 ──
    from factor_lab.composite.composite_validator import run_composite_validation

    composites = []
    # 加上单因子基线
    baseline_method = "equal_weight_score"
    for fn in factor_names:
        print(f"\n  基线: {fn}...")
        comp = run_composite_validation(
            df_valid, close_pivot,
            composite_name=fn, factor_names=[fn],
            combine_method=baseline_method,
            top_quantile=args.top_n / 100,
            rebalance=args.rebalance,
            start_date=args.start, end_date=args.end,
        )
        composites.append(comp)
        fs = comp.get("factor_score", {})
        print(f"    Score: {fs.get('overall_score','?'):.1f}/{fs.get('grade','?')}")

    # 组合
    for method in methods:
        comp_name = f"composite_{method}"

        print(f"\n  组合: {comp_name} ({' + '.join(factor_names)})...")
        try:
            comp = run_composite_validation(
                df_valid, close_pivot,
                composite_name=comp_name,
                factor_names=factor_names,
                combine_method=method,
                weights=None,
                top_quantile=args.top_n / 100,
                rebalance=args.rebalance,
                start_date=args.start, end_date=args.end,
            )
            composites.append(comp)
            fs = comp.get("factor_score", {})
            print(f"    Score: {fs.get('overall_score','?'):.1f}/{fs.get('grade','?')}")
        except Exception as e:
            print(f"    ❌ 组合失败: {e}")

    # ── 6. 生成报告 ──
    print(f"\n[4/4] 生成排行榜报告...")
    from factor_lab.reports.composite_report import generate_composite_leaderboard
    from factor_lab.pool.candidate_pool import CandidatePool

    # 构建候选池
    cp = CandidatePool()
    for entry in composites:
        fs = entry.get("factor_score", {})
        ei = {
            "composite_name": entry.get("composite_name", ""),
            "factors": entry.get("factor_names", []),
            "combine_method": entry.get("combine_method", ""),
            "score": fs.get("overall_score", 0),
            "grade": fs.get("grade", "D"),
            "pass_gate": fs.get("pass_gate", False),
            "cumulative_return": entry.get("anti_overfit", {}).get("peer_benchmark", {}).get("strategy_cumulative_pct"),
            "max_drawdown": fs.get("absolute_max_drawdown"),
            "sharpe": None,  # 需从 metrics 重新计算 (见 baseline_audit)
            "beta_vs_hs300": fs.get("beta_vs_hs300", 0),
            "reject_reasons": fs.get("reject_reasons", []),
        }
        cp.all_entries.append(ei)
        if ei["pass_gate"]:
            cp.promoted.append(ei)
        else:
            cp.rejected.append(ei)

    out_dir = args.output or f"/mnt/d/HermesReports/composite_leaderboard/{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"

    report = generate_composite_leaderboard(
        composites=composites,
        corr_result={**corr_result, **overlap_result},
        candidate_pool=cp.to_dict(),
        output_dir=out_dir,
    )

    print(f"\n📁 输出目录: {out_dir}")
    print(f"📄 报告: {report.get('report_path', '?')}")
    print(f"📋 文件: {report.get('files', [])}")

    # 打印排行榜摘要
    _print_leaderboard(composites)

    return {
        "output_dir": out_dir,
        "report_path": report.get("report_path", ""),
        "composites": composites,
        "correlation": corr_result,
        "overlap": overlap_result,
    }


def _print_leaderboard(composites: list):
    """打印 ASCII 排行榜摘要"""
    print(f"\n{'='*60}")
    print(f"  组合排行榜")
    print(f"{'='*60}")
    print(f"  {'名称':30s} {'方法':20s} {'评分':>5s} {'等级':>3s} {'通过':>4s} {'累计收益':>8s}")
    print(f"  {'-'*30} {'-'*20} {'-'*5} {'-'*3} {'-'*4} {'-'*8}")
    for c in sorted(composites, key=lambda x: -x.get("factor_score", {}).get("overall_score", 0)):
        fs = c.get("factor_score", {})
        name = c.get("composite_name", "?")
        method = c.get("combine_method", "?")
        score = fs.get("overall_score", 0)
        grade = fs.get("grade", "?")
        passed = "✅" if fs.get("pass_gate") else "❌"
        ret = c.get("anti_overfit", {}).get("peer_benchmark", {}).get("strategy_cumulative_pct", 0) or 0
        print(f"  {name:30s} {method:20s} {score:5.1f} {grade:>3s} {passed:>4s} {ret:>7.1f}%")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
