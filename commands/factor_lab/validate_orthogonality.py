#!/usr/bin/env python3
"""V1.6 正交性扩展 + ret5 过滤验证 — 主入口

用法:
    python -m factor_lab.validate_orthogonality
        --factors ret5,volatility20,downside_volatility20,max_drawdown20,...
        --start 2025-01-02 --end 2026-06-30
"""
import sys, os, json, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))


def parse_args():
    p = argparse.ArgumentParser(description="因子正交性扩展 + ret5 过滤验证")
    p.add_argument("--factors", default=None, help="待评估因子, 逗号分隔")
    p.add_argument("--start", default="2025-01-02")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly"])
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--output", default=None)
    return p.parse_args()


def main():
    args = parse_args()

    # 默认候选因子列表
    default_factors = [
        "volatility20", "volatility60", "downside_volatility20", "max_drawdown20", "intraday_range20",  # volatility
        "amount_rank20", "amount_stability20", "volume_stability20", "low_liquidity_penalty", "high_turnover_penalty",  # liquidity
        "high_20_breakout", "high_60_breakout", "close_to_high20", "close_to_high60", "distance_to_high20", "distance_to_high60",  # breakout
        "pullback_5_in_ma20_uptrend", "pullback_10_in_ma20_uptrend", "low_volume_pullback", "ma20_uptrend_pullback",  # pullback
        "ret5_penalty_volatility20", "ret5_penalty_turnover20", "ret5_penalty_vol_ratio20", "ret5_penalty_gap", "ret5_penalty_limit_up_recent",  # ret5_penalty
        "ret5", "ret10", "close_gt_ma20",
    ]
    candidate_factors = [f.strip() for f in (args.factors or ",".join(default_factors)).split(",")]

    print(f"\n{'='*60}")
    print(f"  V1.6 因子正交性扩展 + ret5 过滤验证")
    print(f"  候选因子数: {len(candidate_factors)}")
    print(f"  区间: {args.start} ~ {args.end}")
    print(f"{'='*60}\n")

    # ── 1. 加载数据 ──
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors
    from strategy_lab.universe import build

    print("[1/5] 加载股票池...")
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)

    print("[2/5] 加载 K 线...")
    padding_start = pd.Timestamp(args.start) - pd.Timedelta(days=180)
    df = load_stock_kline(symbols, start_date=str(padding_start.date()), end_date=args.end)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    mask = (df["date"] >= args.start) & (df["date"] <= args.end)
    print(f"  K 线: {len(df)} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    # ── 3. 计算所有因子 ──
    print("[3/5] 计算候选因子...")
    registry = {f["name"]: f for f in list_factors()}
    
    available = []
    unavailable = []
    for fn in candidate_factors:
        if fn in registry:
            try:
                fdef = registry[fn]
                vals = fdef["func"](df, **fdef["params"])
                df[fn] = vals
                available.append(fn)
                print(f"  ✅ {fn}")
            except Exception as e:
                print(f"  ❌ {fn}: {e}")
                unavailable.append({"name": fn, "reason": str(e)})
        else:
            print(f"  ❌ {fn}: 不在注册表")
            unavailable.append({"name": fn, "reason": "not in registry"})

    df_valid = df[mask].copy()
    
    # 检查 ret5 是否存在
    if "ret5" not in df_valid.columns:
        print("❌ ret5 不在可用因子中, 无法继续")
        return

    print(f"\n  可用: {len(available)}, 不可用: {len(unavailable)}")

    # ── 4. 正交性分析 ──
    print("[4/5] 正交性分析...")
    from factor_lab.orthogonality.orthogonality_analyzer import (
        compute_orthogonality, compute_incremental_value,
    )

    # 排除 ret5 自身
    ortho_candidates = [f for f in available if f != "ret5"]
    ortho_result = compute_orthogonality(df_valid, ortho_candidates, reference_factor="ret5")

    # 对最正交的 Top15 做增量价值评估
    inc_results = {}
    sorted_ortho = sorted(
        [c for c in ortho_result["candidates"] if "error" not in c],
        key=lambda c: -c.get("orthogonality_score", 0),
    )
    top15 = sorted_ortho[:15]
    for c in top15:
        name = c["name"]
        print(f"  增量价值: {name}...")
        try:
            iv = compute_incremental_value(df_valid, close_pivot, name)
            inc_results[name] = iv
        except Exception as e:
            print(f"    ❌ {e}")

    # ── 5. 过滤策略 ──
    print("[5/5] 过滤策略验证...")
    from factor_lab.orthogonality.ret5_filter_validator import validate_filter_strategies

    filters_config = [
        {"name": "ret5_close_gt_ma20_gate", "desc": "ret5 + close_gt_ma20 门控",
         "type": "gate", "params": {"primary": "ret5", "secondary": "close_gt_ma20", "threshold": 0.0}},
        {"name": "ret5_vol_filter", "desc": "排除高波动股(volatility20 top20%)",
         "type": "vol_filter", "params": {"primary": "ret5", "secondary": "volatility20"}},
        {"name": "ret5_turn_filter", "desc": "排除高换手+低成交",
         "type": "turn_filter", "params": {"primary": "ret5"}},
        {"name": "ret5_crowding_filter", "desc": "排除异常放量股",
         "type": "crowding_filter", "params": {"primary": "ret5", "secondary": "vol_ratio20"}},
        {"name": "ret5_pullback_filter", "desc": "趋势中偏好回调股",
         "type": "pullback_filter", "params": {"primary": "ret5"}},
        {"name": "ret5_regime_filter", "desc": "市场下行减仓",
         "type": "regime_filter", "params": {"primary": "ret5"}},
    ]
    filter_results = validate_filter_strategies(
        df_valid, close_pivot,
        ret5_name="ret5",
        filters=filters_config,
        top_quantile=args.top_n / 100,
        rebalance=args.rebalance,
        start_date=args.start,
        end_date=args.end,
    )

    # ── 输出 ──
    out_dir = args.output or f"/mnt/d/HermesReports/orthogonality/{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(out_dir, exist_ok=True)

    full_result = {
        "generated_at": datetime.now(CST).isoformat(),
        "config": {
            "n_factors_requested": len(candidate_factors),
            "n_available": len(available),
            "n_unavailable": len(unavailable),
            "period": f"{args.start} ~ {args.end}",
            "rebalance": args.rebalance,
            "top_n": args.top_n,
        },
        "unavailable_factors": unavailable,
        "orthogonality": ortho_result,
        "incremental_value": inc_results,
        "filter_strategies": filter_results,
    }

    # 保存 JSON
    with open(os.path.join(out_dir, "orthogonality_leaderboard.json"), "w", encoding="utf-8") as f:
        json.dump(full_result, f, ensure_ascii=False, indent=2)

    # 生成报告
    _generate_reports(full_result, out_dir)
    _print_summary(ortho_result, filter_results, unavailable)

    print(f"\n📁 输出目录: {out_dir}")
    return full_result


def _generate_reports(result: dict, out_dir: str):
    """生成报告文件"""
    # HTML
    html = _build_html(result)
    with open(os.path.join(out_dir, "orthogonality_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # audit.log
    audit = _build_audit(result)
    with open(os.path.join(out_dir, "audit.log"), "w", encoding="utf-8") as f:
        f.write(audit)

    # promoted filters
    filters = result.get("filter_strategies", {}).get("filters", [])
    promoted = [f for f in filters if f.get("beats_baseline", False)]
    rejected = [f for f in filters if not f.get("beats_baseline", False)]
    with open(os.path.join(out_dir, "promoted_filters.md"), "w", encoding="utf-8") as f:
        f.write(_build_promoted_md(promoted))
    with open(os.path.join(out_dir, "rejected_filters.md"), "w", encoding="utf-8") as f:
        f.write(_build_rejected_md(rejected))

    # CSV
    _write_csv(out_dir, result)


def _build_html(result: dict) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    ortho = result.get("orthogonality", {})
    inc = result.get("incremental_value", {})
    filters = result.get("filter_strategies", {}).get("filters", [])
    baseline = result.get("filter_strategies", {}).get("baseline", {})

    # 正交性排行
    ortho_rows = ""
    for i, c in enumerate(sorted(ortho.get("candidates", []), key=lambda x: -x.get("orthogonality_score", 0))):
        if "error" in c:
            ortho_rows += f"<tr><td>{i+1}</td><td>{c['name']}</td><td colspan=5 style='color:#ff1744;'>{c['error']}</td></tr>"
            continue
        vc = {"high": "#00c853", "medium": "#ff9100", "low": "#ff1744"}.get(c.get("orthogonality_verdict", ""), "#888")
        ortho_rows += f"""<tr>
<td>{i+1}</td><td>{c['name']}</td>
<td class="num">{c.get('pearson_corr','--')}</td>
<td class="num">{c.get('top20_overlap','--')}</td>
<td class="num">{c.get('top50_overlap','--')}</td>
<td class="num">{c.get('orthogonality_score','--')}</td>
<td style="color:{vc};">{c.get('orthogonality_verdict','?')}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>V1.6 正交性扩展 + ret5 过滤验证</title>
<style>
body {{ font-family: -apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.green {{ color:#00c853; }} .red {{ color:#ff1744; }} .orange {{ color:#ff9100; }}
</style></head><body>
<div class="card" style="text-align:center;">
<h1>📊 V1.6 因子正交性 + ret5 过滤验证</h1>
<p style="color:#aaa;">{now} | 候选:{result['config']['n_factors_requested']} 可用:{result['config']['n_available']} 不可用:{result['config']['n_unavailable']}</p>
</div>

<div class="card">
<h2>🔍 与 ret5 的正交性排行 ↓(越低越好)</h2>
<table><tr><th>#</th><th>因子</th><th class="num">Pearson</th><th class="num">Top20重叠</th><th class="num">Top50重叠</th><th class="num">正交分</th><th>判定</th></tr>
{ortho_rows}</table></div>

<div class="card">
<h2>🔄 ret5 过滤策略验证</h2>
<p><strong>ret5 基线</strong>: 收益={baseline.get('cumulative_return_pct','?')}% 回撤={baseline.get('max_drawdown_pct','?')}% Sharpe={baseline.get('sharpe','?')} Calmar={baseline.get('calmar','?')}</p>
<table><tr><th>策略</th><th class="num">收益</th><th class="num">回撤</th><th class="num">Sharpe</th><th class="num">收益Δ</th><th class="num">回撤Δ</th><th class="num">SharpeΔ</th><th>优于ret5?</th></tr>"""
    for f in filters:
        vb = f.get("vs_baseline", {})
        beats = f.get("beats_baseline", False)
        color = "#00c853" if beats else "#ff1744"
        metric = f.get("metrics", {})
        html_delta = ""
        for k in ["return_delta", "max_drawdown_delta", "sharpe_delta"]:
            v = vb.get(k, 0)
            c = "#00c853" if (k == "max_drawdown_delta" and v < 0) or (k != "max_drawdown_delta" and v > 0) else "#ff1744"
            html_delta += f'<td class="num" style="color:{c};">{v:+.2f}</td>'

    html_delta_all = ""
    for f in filters:
        vb = f.get("vs_baseline", {})
        beats = f.get("beats_baseline", False)
        color = "#00c853" if beats else "#ff1744"
        m = f.get("metrics", {})
        html_delta_all += f"""<tr>
<td>{f['name']}</td>
<td class="num">{m.get('cumulative_return_pct','?')}%</td>
<td class="num">{m.get('max_drawdown_pct','?')}%</td>
<td class="num">{m.get('sharpe','?')}</td>
<td class="num" style="color:{'#00c853' if vb.get('return_delta',0) > 0 else '#ff1744'};">{vb.get('return_delta',0):+.2f}</td>
<td class="num" style="color:{'#00c853' if vb.get('max_drawdown_delta',0) < 0 else '#ff1744'};">{vb.get('max_drawdown_delta',0):+.2f}</td>
<td class="num" style="color:{'#00c853' if vb.get('sharpe_delta',0) > 0 else '#ff1744'};">{vb.get('sharpe_delta',0):+.4f}</td>
<td style="color:{color};">{'✅ 是' if beats else '❌ 否'}</td>
</tr>"""

    return html + html_delta_all + """</table></div>

<div class="card">
<h2>⚠️ 不可用因子</h2>
<ul>""" + "".join(f"<li class='red'><strong>{u['name']}</strong>: {u['reason']}</li>" for u in result.get("unavailable_factors", [])) + """</ul></div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V1.6 Orthogonality Report | """ + now + """</p></div>
</body></html>"""


def _build_audit(result: dict) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    filters = result.get("filter_strategies", {}).get("filters", [])
    promoted = [f for f in filters if f.get("beats_baseline", False)]
    rejected = [f for f in filters if not f.get("beats_baseline", False)]
    ortho = result.get("orthogonality", {})
    high_ortho = sum(1 for c in ortho.get("candidates", []) if c.get("orthogonality_verdict") == "high")

    lines = [
        f"=== V1.6 ORTHOGONALITY AUDIT LOG ===",
        f"Time: {now}",
        f"Requested factors: {result['config']['n_factors_requested']}",
        f"Available: {result['config']['n_available']}",
        f"Unavailable: {result['config']['n_unavailable']}",
        f"High-orthogonality factors: {high_ortho}",
        f"Filters tested: {len(filters)}",
        f"Filters beating ret5: {len(promoted)}",
        f"Filters rejected: {len(rejected)}",
        f"",
        f"--- Unavailable Factors ---",
    ]
    for u in result.get("unavailable_factors", []):
        lines.append(f"  {u['name']}: {u['reason']}")
    lines.append("")
    lines.append("--- Filter Results ---")
    for f in filters:
        beats = f.get("beats_baseline", False)
        lines.append(f"  {f['name']}: {'BEATS' if beats else 'NO'} ret5")
    lines.append("")
    lines.append("--- End Audit ---")
    return "\n".join(lines)


def _build_promoted_md(promoted: list) -> str:
    if not promoted:
        return "# 推荐过滤策略\n\n❌ 无过滤策略优于 ret5 基线。\n"
    lines = ["# 推荐过滤策略", "", f"共 {len(promoted)} 个策略优于 ret5 基线:", ""]
    for f in promoted:
        m = f.get("metrics", {})
        vb = f.get("vs_baseline", {})
        lines.append(f"- **{f['name']}** ({f.get('desc','')})")
        lines.append(f"  - 收益={m.get('cumulative_return_pct','?')}% | 回撤={m.get('max_drawdown_pct','?')}% | Sharpe={m.get('sharpe','?')}")
        lines.append(f"  - vs ret5: 收益{vb.get('return_delta',0):+.2f}pp 回撤{vb.get('max_drawdown_delta',0):+.2f}pp Sharpe{vb.get('sharpe_delta',0):+.4f}")
    lines.append("")
    return "\n".join(lines)


def _build_rejected_md(rejected: list) -> str:
    if not rejected:
        return "# 淘汰策略\n\n所有策略均通过。\n"
    lines = ["# 淘汰的过滤策略", "", f"共 {len(rejected)} 个未超越 ret5:", ""]
    for f in rejected:
        m = f.get("metrics", {})
        vb = f.get("vs_baseline", {})
        lines.append(f"- **{f['name']}** ({f.get('desc','')})")
        lines.append(f"  - 收益={m.get('cumulative_return_pct','?')}% | Sharpe={m.get('sharpe','?')}")
        lines.append(f"  - vs ret5: Sharpe{vb.get('sharpe_delta',0):+.4f}")
    return "\n".join(lines)


def _write_csv(out_dir: str, result: dict):
    import csv as csv_mod
    path = os.path.join(out_dir, "orthogonality_leaderboard.csv")
    ortho = result.get("orthogonality", {}).get("candidates", [])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv_mod.DictWriter(f, fieldnames=["name", "pearson_corr", "top20_overlap", "top50_overlap",
                                                "orthogonality_score", "orthogonality_verdict"], extrasaction="ignore")
        w.writeheader()
        for c in sorted(ortho, key=lambda x: -x.get("orthogonality_score", 0)):
            w.writerow(c)


def _print_summary(ortho, filters_result, unavailable):
    print(f"\n{'='*60}")
    print(f"  正交性分析摘要")
    print(f"{'='*60}")
    for c in sorted(ortho.get("candidates", []), key=lambda x: -x.get("orthogonality_score", 0)):
        v = c.get("orthogonality_verdict", "?")
        icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(v, "❓")
        print(f"  {icon} {c['name']:30s} Top20={c.get('top20_overlap','?'):.1%} 正交分={c.get('orthogonality_score','?'):.0f} [{v}]")

    filters = filters_result.get("filters", [])
    baseline = filters_result.get("baseline", {})
    print(f"\n  ret5基线: 收益={baseline.get('cumulative_return_pct','?')}% 回撤={baseline.get('max_drawdown_pct','?')}% Sharpe={baseline.get('sharpe','?')}")
    print(f"\n  过滤策略:")
    for f in filters:
        m = f.get("metrics", {})
        beats = f.get("beats_baseline", False)
        icon = "✅" if beats else "❌"
        print(f"  {icon} {f['name']:40s} 收益={m.get('cumulative_return_pct','?'):>6}% Sharpe={m.get('sharpe','?'):>6} {'BEATS ret5' if beats else ''}")

    if unavailable:
        print(f"\n  ⚠️ 不可用因子: {', '.join(u['name'] for u in unavailable)}")


if __name__ == "__main__":
    main()
