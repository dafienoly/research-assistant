"""批量因子验证与排行榜

用法:
    from factor_lab.scoring.leaderboard import run_batch_validation
    result = run_batch_validation(factors=["ret5", "vol_ratio60", ...])
"""
import sys, os, json, csv, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/factor_leaderboard")


def run_batch_validation(
    factors: list,
    start_date: str = "2025-01-02",
    end_date: str = "2026-06-30",
    rebalance: str = "monthly",
    top_n: int = 20,
    run_anti_overfit: bool = True,
    run_walk_forward: bool = True,
    output_dir: Optional[str] = None,
) -> dict:
    """批量验证多个因子，返回排行榜

    对每个因子:
      1. 加载数据 (共享, 只加载一次)
      2. 计算因子值
      3. run_anti_overfit
      4. run_rolling_validation
      5. factor_score
      6. 汇总
    """
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.factor_base import list_factors, REGISTRY
    from factor_lab.validation.anti_overfit import run_anti_overfit
    from factor_lab.validation.rolling_validator import run_rolling_validation
    from factor_lab.scoring.factor_score import score_factor
    from factor_lab.scoring.factor_family import classify_factor
    from strategy_lab.universe import build

    print(f"\n{'='*60}")
    print(f"  批量因子验证: {len(factors)} 个因子")
    print(f"  区间: {start_date} ~ {end_date}")
    print(f"  调仓: {rebalance}, Top{top_n}")
    print(f"{'='*60}\n")

    # ── 1. 加载股票池 (共享) ──
    print("[1/5] 加载股票池...")
    pool = set()
    for u_name in ["manual_watchlist", "today_candidates"]:
        stocks, meta = build(u_name)
        for s in stocks:
            pool.add(s["symbol"])
    symbols = sorted(pool)
    print(f"  股票池: {len(symbols)} 只")

    # ── 2. 加载 K 线 (共享) ──
    print("[2/5] 加载 K 线...")
    padding_start = pd.Timestamp(start_date) - pd.Timedelta(days=120)
    df = load_stock_kline(symbols, start_date=str(padding_start.date()), end_date=end_date)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["ret1"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(-1))
    print(f"  K 线: {len(df)} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")

    close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
    close_pivot.index = pd.to_datetime(close_pivot.index)
    close_pivot = close_pivot.sort_index()

    # 过滤到有效区间
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    df_valid = df[mask].copy()

    # ── 3. 因子注册表 ──
    registry = {f["name"]: f for f in list_factors()}
    factor_defs = []
    for fn in factors:
        if fn in registry:
            factor_defs.append(registry[fn])
        else:
            print(f"  ⚠️ 因子 {fn} 不在注册表, 跳过")

    if not factor_defs:
        raise ValueError("没有有效因子可验证")

    # ── 4. 逐因子验证 ──
    print(f"[3/5] 逐因子验证 ({len(factor_defs)} 个)...")
    entries = []

    for i, fdef in enumerate(factor_defs):
        fn = fdef["name"]
        desc = fdef.get("description", "")
        print(f"  [{i+1}/{len(factor_defs)}] {fn}...")

        try:
            # 计算因子值
            factor_values = fdef["func"](df, **fdef["params"])
            df_valid[fn] = factor_values[mask.values] if hasattr(mask, 'values') else factor_values[mask]

            # 因子家族
            family_info = classify_factor(fn, fdef.get("category", ""), desc)
            family = family_info.get("family", "unknown")

            # 反过拟合
            ao = None
            if run_anti_overfit:
                ao = run_anti_overfit(
                    df_valid, fn, close_pivot=close_pivot,
                    top_quantile=top_n / 100, rebalance=rebalance,
                )

            # Walk-Forward
            rv = None
            if run_walk_forward:
                rv = run_rolling_validation(
                    df_valid, fn, close_pivot,
                    top_quantile=top_n / 100, rebalance=rebalance,
                    start_date=start_date, end_date=end_date,
                )

            # 评分
            fs = score_factor(
                ao or {},
                rolling_validation=rv,
                expression=desc,
                family=family,
            )

            entry = {
                "factor_name": fn,
                "factor_family": family,
                "expression": desc,
                "score": fs.get("overall_score", 0),
                "grade": fs.get("grade", "D"),
                "pass_gate": fs.get("pass_gate", False),
                "reject_reasons": fs.get("reject_reasons", []),
                "improvement_suggestions": fs.get("improvement_suggestions", []),
                # 绩效
                "cumulative_return": ao.get("peer_benchmark", {}).get("strategy_cumulative_pct") if ao else None,
                "max_drawdown": abs(fs.get("absolute_max_drawdown", 0)),
                "peer_max_drawdown": fs.get("peer_max_drawdown"),
                "relative_drawdown_vs_peer": fs.get("relative_drawdown_vs_peer"),
                "excess_return_vs_peer": fs.get("excess_return_vs_peer"),
                "calmar": fs.get("calmar"),
                # IC
                "ic_mean": ao.get("ic_stability", {}).get("ic_mean") if ao else None,
                "rank_ic_mean": ao.get("ic_stability", {}).get("rank_ic_mean") if ao else None,
                "ic_ir": ao.get("ic_stability", {}).get("ic_ir") if ao else None,
                "positive_ic_ratio": ao.get("ic_stability", {}).get("positive_ic_ratio") if ao else None,
                # Placebo
                "placebo_percentile": ao.get("placebo", {}).get("factor_score_percentile") if ao else None,
                "placebo_pass": ao.get("placebo", {}).get("verdict") == "pass" if ao else None,
                # Walk-Forward
                "walk_forward_pass": rv.get("overall_verdict") == "pass" if rv else None,
                "walk_forward_test_return": rv.get("avg_test_cumulative_return_pct") if rv else None,
                # Beta
                "beta_vs_hs300": fs.get("beta_vs_hs300"),
                # 详情
                "anti_overfit_verdict": ao.get("overall_verdict") if ao else None,
                "fs_report": fs,
            }
            entries.append(entry)
            grade_icon = "✅" if entry["pass_gate"] else "❌"
            print(f"    评分: {entry['score']:.1f}/{entry['grade']} {grade_icon}")

        except Exception as e:
            print(f"    ❌ 验证失败: {e}")
            entries.append({
                "factor_name": fn,
                "factor_family": "unknown",
                "expression": desc,
                "score": 0,
                "grade": "D",
                "pass_gate": False,
                "error": str(e),
                "reject_reasons": [f"验证异常: {e}"],
                "improvement_suggestions": [],
            })

    # ── 5. 排序输出 ──
    print(f"\n[4/5] 生成排行榜...")
    entries.sort(key=lambda e: -e.get("score", 0))

    # 分类
    promoted = [e for e in entries if e.get("pass_gate") and e.get("grade", "D") in ("A", "B")]
    rejected = [e for e in entries if not e.get("pass_gate") or e.get("grade", "D") not in ("A", "B")]
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        grade_counts[e.get("grade", "D")] = grade_counts.get(e.get("grade", "D"), 0) + 1

    # 家族汇总
    family_summary = {}
    for e in entries:
        fam = e.get("factor_family", "unknown")
        if fam not in family_summary:
            family_summary[fam] = {"count": 0, "scores": [], "pass_count": 0, "drawdowns": [], "excess": []}
        family_summary[fam]["count"] += 1
        family_summary[fam]["scores"].append(e.get("score", 0))
        if e.get("pass_gate"):
            family_summary[fam]["pass_count"] += 1
        if e.get("max_drawdown"):
            family_summary[fam]["drawdowns"].append(e.get("max_drawdown", 0))
        if e.get("excess_return_vs_peer") is not None:
            family_summary[fam]["excess"].append(e.get("excess_return_vs_peer", 0))

    fam_summary_out = {}
    for fam, data in family_summary.items():
        fam_summary_out[fam] = {
            "count": data["count"],
            "avg_score": round(float(np.mean(data["scores"])), 1) if data["scores"] else 0,
            "pass_rate": round(data["pass_count"] / data["count"] * 100, 1) if data["count"] > 0 else 0,
            "avg_max_drawdown": round(float(np.mean(data["drawdowns"])), 2) if data["drawdowns"] else None,
            "avg_excess_return": round(float(np.mean(data["excess"])), 2) if data["excess"] else None,
        }

    result = {
        "generated_at": datetime.now(CST).isoformat(),
        "config": {
            "n_factors": len(factors),
            "n_valid": len(entries),
            "start_date": start_date,
            "end_date": end_date,
            "rebalance": rebalance,
            "top_n": top_n,
        },
        "summary": {
            "total": len(entries),
            "grade_counts": grade_counts,
            "passed": len(promoted),
            "rejected": len(rejected),
            "errors": sum(1 for e in entries if "error" in e),
        },
        "entries": entries,
        "promoted": [e["factor_name"] for e in promoted],
        "rejected": [e["factor_name"] for e in rejected],
        "family_summary": fam_summary_out,
    }

    # ── 输出文件 ──
    print(f"[5/5] 保存报告...")
    out_dir = Path(output_dir or str(BASE_OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S")))
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(out_dir / "factor_leaderboard.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # CSV
    csv_fields = [
        "factor_name", "factor_family", "expression", "score", "grade", "pass_gate",
        "cumulative_return", "max_drawdown", "peer_max_drawdown",
        "relative_drawdown_vs_peer", "excess_return_vs_peer", "calmar",
        "ic_mean", "rank_ic_mean", "ic_ir", "positive_ic_ratio",
        "placebo_percentile", "placebo_pass", "walk_forward_pass",
        "walk_forward_test_return", "beta_vs_hs300",
    ]
    with open(out_dir / "factor_leaderboard.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for e in entries:
            w.writerow(e)

    # promoted_factors.md
    with open(out_dir / "promoted_factors.md", "w", encoding="utf-8") as f:
        f.write(_build_promoted_md(promoted, result["summary"]))

    # rejected_factors.md
    with open(out_dir / "rejected_factors.md", "w", encoding="utf-8") as f:
        f.write(_build_rejected_md(rejected, result["summary"]))

    # family_summary.json
    with open(out_dir / "factor_family_summary.json", "w", encoding="utf-8") as f:
        json.dump(fam_summary_out, f, ensure_ascii=False, indent=2)

    # audit.log
    with open(out_dir / "audit.log", "w", encoding="utf-8") as f:
        f.write(_build_audit_log(result))

    # HTML
    html = _build_leaderboard_html(result)
    with open(out_dir / "factor_leaderboard.html", "w", encoding="utf-8") as f:
        f.write(html)

    _print_summary(entries, promoted, rejected, grade_counts)
    result["output_dir"] = str(out_dir)
    return result


# ─── 报告输出 ──────────────────────────────────────────────────

def _build_promoted_md(promoted: list, summary: dict) -> str:
    if not promoted:
        return "# 推荐因子\n\n当前批次无推荐因子。\n"
    lines = ["# 推荐进入下一轮的因子", "", f"共 {len(promoted)} 个通过门禁的因子:", ""]
    for e in promoted:
        r = "; ".join(e.get("reject_reasons", [])[:2])
        lines.append(f"- **{e['factor_name']}** ({e['factor_family']}) 评分={e['score']:.1f}/{e['grade']}")
        if r:
            lines.append(f"  - ⚠️ {r}")
    lines.append("")
    lines.append("---")
    lines.append(f"_批量验证: {summary['passed']} 通过, {summary['rejected']} 淘汰_")
    return "\n".join(lines)


def _build_rejected_md(rejected: list, summary: dict) -> str:
    if not rejected:
        return "# 淘汰因子\n\n所有因子均通过验证。\n"
    lines = ["# 淘汰因子", "", f"共 {len(rejected)} 个未通过:", ""]
    for e in rejected:
        reasons = "; ".join(e.get("reject_reasons", [])[:3])
        lines.append(f"- **{e['factor_name']}** ({e['factor_family']}) 评分={e['score']:.1f}/{e['grade']}")
        if reasons:
            lines.append(f"  - ❌ {reasons}")
    lines.append("")
    lines.append(f"_淘汰率: {summary['rejected']}/{summary['total']}_")
    return "\n".join(lines)


def _build_audit_log(result: dict) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    cfg = result["config"]
    lines = [
        f"=== BATCH VALIDATION AUDIT LOG ===",
        f"Time: {now}",
        f"Factors requested: {cfg['n_factors']}",
        f"Factors validated: {cfg['n_valid']}",
        f"Period: {cfg['start_date']} ~ {cfg['end_date']}",
        f"Rebalance: {cfg['rebalance']}, Top-N: {cfg['top_n']}",
        f"",
        f"--- Summary ---",
        f"Total: {result['summary']['total']}",
        f"A: {result['summary']['grade_counts'].get('A',0)}",
        f"B: {result['summary']['grade_counts'].get('B',0)}",
        f"C: {result['summary']['grade_counts'].get('C',0)}",
        f"D: {result['summary']['grade_counts'].get('D',0)}",
        f"Passed: {result['summary']['passed']}",
        f"Rejected: {result['summary']['rejected']}",
        f"Errors: {result['summary'].get('errors',0)}",
        f"",
        f"--- Per Factor ---",
    ]
    for e in result["entries"]:
        lines.append(f"{e['factor_name']:20s} | {e.get('factor_family','?'):15s} | score={e.get('score',0):5.1f} | grade={e.get('grade','?'):1s} | pass={e.get('pass_gate',False)}")
    lines.append(f"")
    lines.append(f"--- End Audit ---")
    return "\n".join(lines)


def _build_leaderboard_html(result: dict) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    cfg = result["config"]
    summary = result["summary"]

    grade_color_map = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}

    # 排行表行
    table_rows = ""
    for i, e in enumerate(result["entries"]):
        gc = grade_color_map.get(e.get("grade", "D"), "#888")
        pass_icon = "✅" if e.get("pass_gate") else "❌"
        reasons = "; ".join(e.get("reject_reasons", [])[:2])
        table_rows += f"""<tr>
<td>{i+1}</td><td>{e['factor_name']}</td><td>{e.get('factor_family','?')}</td>
<td class="num">{e.get('score',0):.1f}</td>
<td><span class="grade" style="color:{gc}">{e.get('grade','?')}</span></td>
<td>{pass_icon}</td>
<td class="num">{e.get('cumulative_return','--')}%</td>
<td class="num">{e.get('max_drawdown','--')}%</td>
<td class="num">{e.get('relative_drawdown_vs_peer','--')}</td>
<td class="num">{e.get('excess_return_vs_peer','--')}%</td>
<td class="num">{e.get('ic_ir','--')}</td>
<td class="num">{e.get('placebo_percentile','--')}%</td>
<td style="font-size:0.8em;color:#aaa;">{reasons}</td>
</tr>"""

    # 家族汇总行
    family_rows = ""
    for fam, data in sorted(result.get("family_summary", {}).items()):
        family_rows += f"""<tr><td>{fam}</td><td>{data['count']}</td><td class="num">{data['avg_score']}</td>
<td class="num">{data['pass_rate']}%</td><td class="num">{data['avg_max_drawdown'] if data['avg_max_drawdown'] else '--'}%</td>
<td class="num">{data['avg_excess_return'] if data['avg_excess_return'] else '--'}%</td></tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>因子排行榜 — 批量验证报告</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; background: #1a1a2e; color: #e0e0e0; margin:0; padding:20px; }}
.card {{ background: #16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color: #00bcd4; }} h2 {{ color: #00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.grade {{ font-weight:bold; font-size:1.1em; }}
.summary-box {{ display:inline-block; padding:10px 20px; margin:4px; border-radius:6px; text-align:center; }}
.summary-num {{ font-size:1.8em; font-weight:bold; }}
.summary-label {{ font-size:0.8em; color:#aaa; }}
</style></head><body>

<div class="card" style="text-align:center;">
<h1>📊 因子排行榜</h1>
<p style="color:#aaa;">{now} | {cfg['n_valid']} 个因子 | {cfg['start_date']} ~ {cfg['end_date']} | 调仓: {cfg['rebalance']}</p>
<div class="summary-box" style="background:#00c85322;"><div class="summary-num">{summary['grade_counts'].get('A',0)}</div><div class="summary-label">A 级</div></div>
<div class="summary-box" style="background:#64dd1722;"><div class="summary-num">{summary['grade_counts'].get('B',0)}</div><div class="summary-label">B 级</div></div>
<div class="summary-box" style="background:#ff910022;"><div class="summary-num">{summary['grade_counts'].get('C',0)}</div><div class="summary-label">C 级</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{summary['grade_counts'].get('D',0)}</div><div class="summary-label">D 级</div></div>
<div class="summary-box" style="background:#00bcd422;"><div class="summary-num">{summary['passed']}</div><div class="summary-label">✅ 通过</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{summary['rejected']}</div><div class="summary-label">❌ 淘汰</div></div>
</div>

<div class="card">
<h2>🏆 因子排行 (按评分降序)</h2>
<div style="overflow-x:auto;">
<table>
<tr><th>#</th><th>因子</th><th>家族</th><th class="num">评分</th><th>等级</th><th>通过</th><th class="num">累计收益</th><th class="num">回撤</th><th class="num">相对回撤</th><th class="num">超额收益</th><th class="num">IC_IR</th><th class="num">Placebo</th><th>淘汰原因</th></tr>
{table_rows}
</table></div></div>

<div class="card">
<h2>📋 因子类型分布</h2>
<table>
<tr><th>家族</th><th>数量</th><th class="num">平均分</th><th class="num">通过率</th><th class="num">平均回撤</th><th class="num">平均超额</th></tr>
{family_rows}
</table></div>

<div class="card">
<h2>💡 为什么不能只看累计收益？</h2>
<ul>
<li><strong>同池等权对照</strong>: 如果因子没跑赢同池里所有股票等权买入, 说明选股能力弱于买入并持有同池。</li>
<li><strong>动量因子允许更高回撤</strong>: 动量因子天然高Beta高波动, 因此用 relative_drawdown_vs_peer (相对同池等权的回撤比) 而非绝对回撤来评估。</li>
<li><strong>没跑赢同池等权的因子不能评 A/B</strong>: 这是硬性下限。如果一个因子不能提供超越平均的 alpha, 不值得投入。</li>
<li><strong>安慰剂检验</strong>: 确保因子表现显著强于随机, 排除偶然性。</li>
<li><strong>Walk-Forward 样本外</strong>: 防止因子只在历史数据上有效。</li>
</ul>
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>Factor Lab Leaderboard | {now}</p>
</div>

</body></html>"""
    return html


def _print_summary(entries, promoted, rejected, grade_counts):
    print(f"\n{'='*60}")
    print(f"  批量验证完成")
    print(f"  A: {grade_counts.get('A',0)}  B: {grade_counts.get('B',0)}  C: {grade_counts.get('C',0)}  D: {grade_counts.get('D',0)}")
    print(f"  ✅ 通过: {len(promoted)}  ❌ 淘汰: {len(rejected)}")
    if promoted:
        print(f"  推荐: {', '.join(e['factor_name'] for e in promoted)}")
    print(f"{'='*60}\n")
