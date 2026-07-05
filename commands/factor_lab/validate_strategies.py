#!/usr/bin/env python3
"""V1.7 ret5 + 过滤器策略层验证 — 主入口

用法:
    python -m factor_lab.validate_strategies
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/strategy_validation")
CANONICAL_BASELINE = {
    "source": "V1.4 canonical_metrics.json (QuantStats)",
    "sharpe": 1.83,
    "cagr_pct": 70.78,
    "cumulative_return_pct": 113.9,
    "max_drawdown_pct": -14.31,
    "calmar": 4.95,
    "total_days": 358,
    "top_n": 20,
    "rebalance": "monthly",
    "benchmark": "沪深300",
    "start_date": "2025-01-02",
    "end_date": "2026-06-30",
    "commission_rate": 0.0003,
    "stamp_tax_rate": 0.001,
    "slippage_bps": 10,
    "note": "注意: canonical Sharpe=1.83 是 QuantStats 标准计算(含无风险利率)。简化计算 (~1.92) 因无风险利率=0 有偏差。本模块使用带3%无风险利率的统一公式。"
}


def main():
    args = _parse_args()
    run_strategy_validation(args)


def _parse_args():
    p = argparse.ArgumentParser(description="V1.7 ret5 策略层验证")
    p.add_argument("--start", default="2025-01-02")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--rebalance", default="monthly")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--output", default=None)
    p.add_argument("--no-execution-aware", action="store_true", help="关闭 A 股交易约束")
    p.add_argument("--no-parameter-sensitivity", action="store_true")
    return p.parse_args()


def run_strategy_validation(args=None):
    if args is None:
        args = _parse_args()

    print(f"\n{'='*60}")
    print(f"  V1.7 ret5 + 过滤器策略层验证")
    print(f"  区间: {args.start} ~ {args.end} | 调仓: {args.rebalance} | Top{args.top_n}")
    print(f"  基线: canonical_ret5_baseline (Sharpe=1.83)")
    print(f"{'='*60}\n")

    # 加载数据
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from strategy_lab.universe import build

    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)

    padding = pd.Timestamp(args.start) - pd.Timedelta(days=180)
    df = load_stock_kline(symbols, start_date=str(padding.date()), end_date=args.end)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    mask = (df["date"] >= args.start) & (df["date"] <= args.end)

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    # 算因子
    registry = {f["name"]: f for f in list_factors()}
    needed = set()
    for s in _all_strategies():
        for fn in s.factor_names:
            needed.add(fn)
    for fn in needed:
        if fn in registry:
            fdef = registry[fn]
            vals = fdef["func"](df, **fdef["params"])
            df[fn] = vals

    df_valid = df[mask].copy()

    # 运行策略
    from factor_lab.strategy.strategy_validator import StrategyValidator
    from factor_lab.strategy.execution_aware_backtester import AShareBacktester

    backtester = AShareBacktester(close_pivot) if not getattr(args, 'no_execution_aware', False) else None
    validator = StrategyValidator(df_valid, close_pivot, backtester=backtester)
    validator.canonical_baseline = CANONICAL_BASELINE

    # 全策略验证
    strategies = _all_strategies()
    result = validator.validate_all(strategies)

    # 参数敏感性
    sensitivity = {}
    if not getattr(args, 'no_parameter_sensitivity', False):
        print("\n参数敏感性测试...")
        for s in strategies[:4]:  # 只对前4个核心策略做敏感性
            grid = validator.sensitivity_grid()
            sensitivity[s.name] = validator.run_parameter_sensitivity(s, grid)

    # 输出
    out_dir = args.output or str(BASE_OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    # canonical_baseline.json
    with open(os.path.join(out_dir, "canonical_ret5_baseline.json"), "w") as f:
        json.dump(CANONICAL_BASELINE, f, indent=2)

    # 排行榜 JSON
    lb_data = {
        "generated_at": datetime.now(CST).isoformat(),
        "canonical_baseline": CANONICAL_BASELINE,
        "strategies": result.get("strategies", []),
        "best_strategy": result.get("best_strategy"),
        "parameter_sensitivity": sensitivity,
        "execution_assumptions": {
            "limit_up_exclude": True,
            "limit_down_exclude": False,
            "suspend_exclude": True,
            "st_exclude": True,
            "min_amount": 1000000,
            "lot_size": 100,
            "max_single_weight": 0.15,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.001,
            "slippage_bps": 10,
            "note": "涨停排除基于close*1.095, 停牌/ST排除基于数据可用性, 部分字段可能 partial",
        },
    }
    with open(os.path.join(out_dir, "strategy_leaderboard.json"), "w") as f:
        json.dump(lb_data, f, indent=2)

    _generate_reports(result, sensitivity, out_dir, CANONICAL_BASELINE)
    _print_summary(result)
    print(f"\n📁 输出目录: {out_dir}")


def _all_strategies():
    from factor_lab.strategy.strategy_spec import DEFAULT_STRATEGIES
    return DEFAULT_STRATEGIES


def _generate_reports(result, sensitivity, out_dir, baseline):
    entries = result.get("strategies", [])
    promoted = [e for e in entries if e.get("beats_baseline", False)]
    rejected = [e for e in entries if not e.get("beats_baseline", False)]
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # HTML
    html = _build_html(entries, baseline, now)
    with open(os.path.join(out_dir, "strategy_leaderboard.html"), "w") as f:
        f.write(html)

    # promoted/rejected
    with open(os.path.join(out_dir, "promoted_strategies.md"), "w") as f:
        f.write(_build_promoted(promoted))
    with open(os.path.join(out_dir, "rejected_strategies.md"), "w") as f:
        f.write(_build_rejected(rejected))

    # audit
    with open(os.path.join(out_dir, "audit.log"), "w") as f:
        f.write(_build_audit(entries, baseline, now))


def _build_html(entries, baseline, now):
    rows = ""
    for i, e in enumerate(entries):
        m = e.get("metrics", {})
        beats = e.get("beats_baseline", False)
        color = "#00c853" if beats else "#ff1744"
        deltas = e.get("vs_baseline", {})
        dd_ret = deltas.get("return_delta", 0)
        dd_dd = deltas.get("max_drawdown_delta", 0)
        dd_sr = deltas.get("sharpe_delta", 0)
        exec_warn = "⚠️" if e.get("execution_log") else ""
        rows += f"""<tr>
<td>{i+1}</td><td>{e['name']}</td><td>{e.get('filter_type','?')}</td>
<td class="num">{m.get('cumulative_return_pct','?')}%</td>
<td class="num">{m.get('max_drawdown_pct','?')}%</td>
<td class="num">{m.get('sharpe','?')}</td>
<td class="num">{m.get('calmar','?')}</td>
<td class="num" style="color:{'#00c853' if dd_ret>0 else '#ff1744'};">{dd_ret:+.2f}</td>
<td class="num" style="color:{'#00c853' if dd_dd<0 else '#ff1744'};">{dd_dd:+.2f}</td>
<td class="num" style="color:{'#00c853' if dd_sr>0 else '#ff1744'};">{dd_sr:+.4f}</td>
<td style="color:{color};">{'✅' if beats else '❌'}</td>
<td>{exec_warn}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>V1.7 ret5 策略层验证</title>
<style>
body {{ font-family: -apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card" style="text-align:center;">
<h1>📊 V1.7 ret5 + 过滤器策略验证</h1>
<p style="color:#aaa;">{now}</p>
<p>Canonical Basline: Sharpe={baseline['sharpe']} 收益={baseline['cumulative_return_pct']}% 回撤={baseline['max_drawdown_pct']}%</p>
</div>
<div class="card">
<h2>🏆 策略排行榜 (vs Canonical ret5)</h2>
<p style="color:#ff9100;font-size:0.85em;">⚠️ 基线 Sharpe=1.83 (QuantStats含无风险利率)。策略 Sharpe 用统一公式(3%无风险利率)计算, 与基线口径一致。</p>
<table><tr><th>#</th><th>策略</th><th>类型</th><th class="num">收益</th><th class="num">回撤</th><th class="num">Sharpe</th><th class="num">Calmar</th><th class="num">收益Δ</th><th class="num">回撤Δ</th><th class="num">SharpeΔ</th><th>优于基线?</th><th></th></tr>
{rows}</table></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>V1.7 Strategy Validation | {now}</p>
</div></body></html>"""


def _build_promoted(promoted):
    if not promoted:
        return "# 推荐策略\n\n❌ 无策略优于 canonical ret5 baseline (Sharpe=1.83)。\n"
    lines = ["# 推荐策略", ""]
    for e in promoted:
        m = e.get("metrics", {})
        lines.append(f"- **{e['name']}**: Sharpe={m.get('sharpe','?')} 收益={m.get('cumulative_return_pct','?')}%")
    return "\n".join(lines)


def _build_rejected(rejected):
    if not rejected:
        return "# 淘汰策略\n\n所有策略均通过。\n"
    lines = ["# 淘汰策略", ""]
    for e in rejected:
        m = e.get("metrics", {})
        vb = e.get("vs_baseline", {})
        lines.append(f"- **{e['name']}**: Sharpe={m.get('sharpe','?')} vs 基线={vb.get('sharpe_delta','?'):+.4f}")
    return "\n".join(lines)


def _build_audit(entries, baseline, now):
    promoted = [e for e in entries if e.get("beats_baseline", False)]
    lines = [
        f"=== V1.7 STRATEGY VALIDATION AUDIT ===",
        f"Time: {now}",
        f"Canonical Baseline: Sharpe={baseline['sharpe']} Return={baseline['cumulative_return_pct']}%",
        f"Strategies tested: {len(entries)}",
        f"Beating baseline: {len(promoted)}",
        "",
        "--- Per Strategy ---",
    ]
    for e in entries:
        m = e.get("metrics", {})
        beats = e.get("beats_baseline", False)
        lines.append(f"  {e['name']:30s} Sharpe={m.get('sharpe','?'):>6} {'BEATS' if beats else 'NO'} baseline")
    lines.append("")
    lines.append("--- End Audit ---")
    return "\n".join(lines)


def _print_summary(result):
    entries = result.get("strategies", [])
    promoted = [e for e in entries if e.get("beats_baseline", False)]
    print(f"\n{'='*60}")
    print(f"  策略验证完成")
    print(f"  Canonical Baseline Sharpe=1.83 (QuantStats)")
    print(f"  策略数: {len(entries)}")
    for e in entries:
        m = e.get("metrics", {})
        beats = e.get("beats_baseline", False)
        icon = "✅" if beats else "❌"
        print(f"  {icon} {e['name']:30s} Sharpe={m.get('sharpe','?'):>6} 收益={m.get('cumulative_return_pct','?'):>6}% 回撤={m.get('max_drawdown_pct','?'):>6}%")
    if promoted:
        print(f"\n  🏆 优于基线: {', '.join(p['name'] for p in promoted)}")
    else:
        print(f"\n  ❌ 无策略优于基线")


if __name__ == "__main__":
    main()
