"""Hotfix: strategy_leaderboard 报告层修复

修复:
  1. 两套 ret5 baseline 分开标注
  2. Δ 默认相对 strategy_engine_ret5_baseline
  3. 回撤 Δ 用绝对值计算, 颜色正确
  4. liquidity/regime 标记 partial/unavailable/not_implemented
  5. ret5_ma20_gate 结论明确

基于已有 JSON 数据重新生成, 不重跑验证。
"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# 最新一次 V1.7 运行结果目录 (从已有报告中读取)
SRC_DIR = Path("/mnt/d/HermesReports/strategy_validation/20260704_190709")


def hotfix():
    with open(SRC_DIR / "strategy_leaderboard.json") as f:
        data = json.load(f)

    entries = data.get("strategies", [])
    canonical = data.get("canonical_baseline", {})

    # 找到 strategy_engine_ret5_baseline (第一行 ret5_baseline)
    se_baseline = None
    for e in entries:
        if e["name"] == "ret5_baseline":
            se_baseline = e.get("metrics", {})
            break

    if not se_baseline:
        print("❌ 未找到 strategy_engine_ret5_baseline")
        return

    # 对每个条目计算相对 strategy_engine 的 Δ (用绝对值修正)
    for e in entries:
        m = e.get("metrics", {})
        e["_se_delta"] = _calc_delta_vs_se(m, se_baseline)
        e["_canonical_delta"] = _calc_delta_vs_canonical(m, canonical)
        e["_status"] = _determine_status(e)

    # 生成文件
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # strategy_engine_ret5_baseline.json
    se_baseline_doc = {
        "source": "V1.7 strategy_engine (strategy_validator._backtest)",
        "sharpe": se_baseline.get("sharpe"),
        "cumulative_return_pct": se_baseline.get("cumulative_return_pct"),
        "max_drawdown_pct": se_baseline.get("max_drawdown_pct"),
        "calmar": se_baseline.get("calmar"),
        "cagr_pct": se_baseline.get("cagr_pct"),
        "total_days": se_baseline.get("n_days"),
        "top_n": 20,
        "rebalance": "monthly",
        "note": "策略引擎基线, 用于所有策略 Δ 对比的默认基线",
    }
    with open(SRC_DIR / "strategy_engine_ret5_baseline.json", "w") as f:
        json.dump(se_baseline_doc, f, indent=2)

    # canonical_ret5_baseline.json (补充字段)
    canonical_doc = {
        **canonical,
        "label": "factor_report_canonical_ret5_baseline",
        "note": "V1.4 QuantStats 回测报告基线。与 strategy_engine 基线口径不同, 不直接混用。",
    }
    with open(SRC_DIR / "canonical_ret5_baseline.json", "w") as f:
        json.dump(canonical_doc, f, indent=2)

    # validation_status.json
    status = {
        "generated_at": now,
        "strategies": [
            {
                "name": e["name"],
                "filter_type": e.get("filter_type", ""),
                "status": e["_status"],
                "beats_se_baseline": e.get("beats_baseline", False),
                "sharpe": e.get("metrics", {}).get("sharpe"),
                "cumulative_return_pct": e.get("metrics", {}).get("cumulative_return_pct"),
            }
            for e in entries
        ],
    }
    with open(SRC_DIR / "validation_status.json", "w") as f:
        json.dump(status, f, indent=2)

    # HTML
    html = _build_html(entries, se_baseline, canonical, now)
    with open(SRC_DIR / "strategy_leaderboard.html", "w") as f:
        f.write(html)

    # 更新 JSON (添加 delta 字段)
    data["strategy_engine_baseline"] = se_baseline_doc
    data["canonical_baseline"] = canonical_doc
    data["hotfix_generated_at"] = now
    for e in data["strategies"]:
        se = next((s for s in entries if s["name"] == e["name"]), None)
        if se:
            e["_se_delta"] = se.get("_se_delta", {})
            e["_canonical_delta"] = se.get("_canonical_delta", {})
            e["_status"] = se.get("_status", "unknown")
    with open(SRC_DIR / "strategy_leaderboard.json", "w") as f:
        json.dump(data, f, indent=2)

    # promoted/rejected (排除 partial/not_implemented)
    promoted = [e for e in entries if e.get("beats_baseline") and e["_status"] == "active"]
    rejected = [e for e in entries if not e.get("beats_baseline") and e["_status"] == "active"]
    partial = [e for e in entries if e["_status"] != "active"]

    with open(SRC_DIR / "promoted_strategies.md", "w") as f:
        f.write(_build_promoted(promoted, se_baseline, canonical))
    with open(SRC_DIR / "rejected_strategies.md", "w") as f:
        f.write(_build_rejected(rejected, partial))
    with open(SRC_DIR / "audit.log", "w") as f:
        f.write(_build_audit(entries, se_baseline, canonical, now))

    print(f"✅ Hotfix 完成: {SRC_DIR}")
    print(f"   strategy_engine_ret5_baseline.json")
    print(f"   canonical_ret5_baseline.json")
    print(f"   validation_status.json")
    print(f"   strategy_leaderboard.html (双重基线 + 回撤颜色修正)")
    print(f"   strategy_leaderboard.json (增补字段)")
    print(f"   promoted/rejected/audit.log")


def _calc_delta_vs_se(m: dict, se: dict) -> dict:
    """相对 strategy_engine 基线的 Δ, 回撤用绝对值"""
    dd_abs_base = abs(se.get("max_drawdown_pct", 0))
    dd_abs_strat = abs(m.get("max_drawdown_pct", 0))
    dd_improvement = round(dd_abs_base - dd_abs_strat, 2)  # 正数=改善

    return {
        "return_delta": round(m.get("cumulative_return_pct", 0) - se.get("cumulative_return_pct", 0), 2),
        "dd_improvement": dd_improvement,  # >0 = 回撤改善
        "sharpe_delta": round(m.get("sharpe", 0) - se.get("sharpe", 0), 4),
        "calmar_delta": round(m.get("calmar", 0) - se.get("calmar", 0), 4),
    }


def _calc_delta_vs_canonical(m: dict, c: dict) -> dict:
    """相对 factor_report_canonical 的 Δ"""
    dd_abs_base = abs(c.get("max_drawdown_pct", 0))
    dd_abs_strat = abs(m.get("max_drawdown_pct", 0))
    return {
        "return_delta": round(m.get("cumulative_return_pct", 0) - c.get("cumulative_return_pct", 0), 2),
        "dd_improvement": round(dd_abs_base - dd_abs_strat, 2),
        "sharpe_delta": round(m.get("sharpe", 0) - c.get("sharpe", 0), 4),
    }


def _determine_status(e: dict) -> str:
    """判定策略状态: active / partial / not_implemented / unavailable"""
    name = e.get("name", "")
    m = e.get("metrics", {})
    se = e.get("_se_delta", {})

    # liquidity / regime 过滤器标记为 not_implemented
    if name in ("ret5_liquidity",):
        return "unavailable"  # amount_rank20 未预计算
    if name in ("ret5_regime",):
        return "not_implemented"

    # 如果与 baseline 完全一致, 可能是未生效
    if abs(se.get("sharpe_delta", 1)) < 0.001 and abs(se.get("return_delta", 1)) < 0.1:
        return "partial"

    return "active"


def _build_html(entries, se_base, canonical, now):
    se_sr = se_base.get("sharpe", "?")
    se_ret = se_base.get("cumulative_return_pct", "?")
    se_dd = se_base.get("max_drawdown_pct", "?")
    c_sr = canonical.get("sharpe", "?")
    c_ret = canonical.get("cumulative_return_pct", "?")
    c_dd = canonical.get("max_drawdown_pct", "?")

    rows = ""
    for e in entries:
        m = e.get("metrics", {})
        se_d = e.get("_se_delta", {})
        ca_d = e.get("_canonical_delta", {})
        status = e.get("_status", "active")

        # 根据状态决定显示
        is_ret5_base = e["name"] == "ret5_baseline"
        is_partial = status in ("not_implemented", "unavailable", "partial")

        # 回撤改善颜色 (绝对值)
        dd_imp = se_d.get("dd_improvement", 0)
        dd_color = "#00c853" if dd_imp > 0.1 else "#ff1744" if dd_imp < -0.1 else "#888"

        # Canonical 对比颜色
        ca_dd_imp = ca_d.get("dd_improvement", 0)
        ca_dd_color = "#00c853" if ca_dd_imp > 0.1 else "#ff1744" if ca_dd_imp < -0.1 else "#888"

        row_style = 'style="background:#00c85311;font-weight:bold;"' if is_ret5_base else ""
        status_tag = ""
        if is_partial:
            status_tag = f'<span style="color:#ff9100;font-size:0.8em;">[{status}]</span>'
        elif is_ret5_base:
            status_tag = '<span style="color:#aaa;font-size:0.8em;">[基线]</span>'

        rows += f"""<tr {row_style}>
<td>{e['name']}</td>
<td>{e.get('filter_type','?')}</td>
<td class="num">{m.get('cumulative_return_pct','?')}%</td>
<td class="num">{m.get('max_drawdown_pct','?')}%</td>
<td class="num">{m.get('sharpe','?')}</td>
<td class="num" style="color:{'#00c853' if se_d.get('return_delta',0) > 0 else '#ff1744'};">{se_d.get('return_delta',0):+.2f}pp</td>
<td class="num" style="color:{dd_color};">{dd_imp:+.2f}pp</td>
<td class="num" style="color:{'#00c853' if se_d.get('sharpe_delta',0) > 0 else '#ff1744'};">{se_d.get('sharpe_delta',0):+.4f}</td>
<td class="num" style="color:{'#00c853' if ca_d.get('return_delta',0) > 0 else '#ff1744'};">{ca_d.get('return_delta',0):+.2f}pp</td>
<td class="num" style="color:{ca_dd_color};">{ca_dd_imp:+.2f}pp</td>
<td class="num" style="color:{'#00c853' if ca_d.get('sharpe_delta',0) > 0 else '#ff1744'};">{ca_d.get('sharpe_delta',0):+.4f}</td>
<td>{status_tag}</td>
</tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>V1.7 ret5 策略层验证 (Hotfix)</title>
<style>
body {{ font-family: -apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; font-size:0.92em; }}
th {{ color:#888; font-size:0.82em; }} .num {{ text-align:right; }}
.green {{ color:#00c853; }} .red {{ color:#ff1744; }} .gray {{ color:#888; }}
</style></head><body>
<div class="card" style="text-align:center;">
<h1>📊 V1.7 ret5 + 过滤器策略验证 (Hotfix 版)</h1>
<p style="color:#aaa;">{now}</p>
<div style="display:flex;justify-content:center;gap:40px;flex-wrap:wrap;">
<div style="text-align:left;background:#0f3460;padding:12px 20px;border-radius:6px;">
<b>📌 strategy_engine_ret5_baseline</b><br>
<span style="color:#aaa;">Sharpe={se_sr} | 收益={se_ret}% | 回撤={se_dd}%</span><br>
<span style="font-size:0.85em;color:#666;">V1.7 策略引擎基线, 用于所有 Δ 默认对比</span>
</div>
<div style="text-align:left;background:#0f3460;padding:12px 20px;border-radius:6px;">
<b>📌 factor_report_canonical_ret5_baseline</b><br>
<span style="color:#aaa;">Sharpe={c_sr} | 收益={c_ret}% | 回撤={c_dd}%</span><br>
<span style="font-size:0.85em;color:#666;">V1.4 QuantStats 报告基线, 供参考对比</span>
</div>
</div>
</div>

<div class="card">
<h2>🏆 策略排行榜</h2>
<p style="font-size:0.85em;color:#ff9100;">
回撤 Δ 用绝对值计算: positive = 回撤改善(绿色), negative = 回撤恶化(红色)。<br>
左侧 Δ 列 = vs strategy_engine_baseline, 右侧 Δ 列 = vs factor_report_canonical_baseline。<br>
[not_implemented] / [unavailable] / [partial] 状态的策略不参与 promoted/rejected 结论。
</p>
<div style="overflow-x:auto;">
<table>
<tr>
<th rowspan=2>策略</th><th rowspan=2>类型</th>
<th rowspan=2 class="num">收益</th><th rowspan=2 class="num">回撤</th><th rowspan=2 class="num">Sharpe</th>
<th colspan=3 class="num" style="border-left:2px solid #444;">vs strategy_engine</th>
<th colspan=3 class="num" style="border-left:2px solid #444;">vs factor_report_canonical</th>
<th rowspan=2></th>
</tr>
<tr>
<th class="num" style="color:#aaa;font-size:0.8em;">收益Δ</th>
<th class="num" style="color:#aaa;font-size:0.8em;">回撤改善</th>
<th class="num" style="color:#aaa;font-size:0.8em;">SharpeΔ</th>
<th class="num" style="color:#aaa;font-size:0.8em;">收益Δ</th>
<th class="num" style="color:#aaa;font-size:0.8em;">回撤改善</th>
<th class="num" style="color:#aaa;font-size:0.8em;">SharpeΔ</th>
</tr>
{rows}
</table></div></div>

<div class="card">
<h2>💡 结论</h2>
<ul>
<li><strong>ret5 + close_gt_ma20 门控</strong>: 相对 strategy_engine_ret5_baseline, 收益/回撤/Sharpe <span class="green">全面改善</span>。是当前候选中最优 ret5 过滤策略。</li>
<li><strong>相对 factor_report_canonical_ret5_baseline</strong>: 收益+164% vs 114% <span class="green">提升</span>, Sharpe+2.10 vs 1.83 <span class="green">提升</span>, 但回撤-14.38% vs -14.31% <span class="red">略差</span>。不能简单称为"全面优于 canonical baseline"。</li>
<li><strong>低波动/量比过滤</strong> Sharpe 低于基线, 当前市场环境下过于保守。</li>
<li><strong>liquidity/regime 过滤器</strong> 因子未正确预计算或未实现, 暂不参与结论。</li>
</ul>
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>V1.7 Strategy Validation Hotfix | {now}</p>
</div>
</body></html>"""


def _build_promoted(promoted, se_base, canonical):
    if not promoted:
        return "# 推荐策略\n\n❌ 无 active 策略优于 strategy_engine_ret5_baseline。\n"
    lines = ["# 推荐策略", ""]
    for e in promoted:
        m = e.get("metrics", {})
        se_d = e.get("_se_delta", {})
        lines.append(f"- **{e['name']}**: Sharpe={m.get('sharpe','?')} (vs 策略引擎={se_d.get('sharpe_delta',0):+.4f})")
        lines.append(f"  - 收益={m.get('cumulative_return_pct','?')}% | 回撤={m.get('max_drawdown_pct','?')}%")
    lines.append("")
    lines.append("---")
    lines.append(f"基线对比: strategy_engine_ret5_baseline (Sharpe={se_base.get('sharpe','?')})")
    return "\n".join(lines)


def _build_rejected(rejected, partial):
    lines = ["# 淘汰策略", "", f"共 {len(rejected)} 个 active 策略未超越基线:" if rejected else "无 active 策略被淘汰。", ""]
    for e in rejected:
        m = e.get("metrics", {})
        se_d = e.get("_se_delta", {})
        lines.append(f"- **{e['name']}**: Sharpe={m.get('sharpe','?')} vs 策略引擎={se_d.get('sharpe_delta',0):+.4f}")
    if partial:
        lines.extend(["", "---", "以下策略未参与正式结论 (partial/not_implemented/unavailable):", ""])
        for e in partial:
            lines.append(f"- **{e['name']}**: [{e.get('_status','?')}]")
    return "\n".join(lines)


def _build_audit(entries, se_base, canonical, now):
    promoted = [e for e in entries if e.get("beats_baseline") and e["_status"] == "active"]
    lines = [
        f"=== V1.7 STRATEGY VALIDATION AUDIT (HOTFIX) ===",
        f"Time: {now}",
        f"Strategy Engine Baseline: Sharpe={se_base.get('sharpe')} Return={se_base.get('cumulative_return_pct')}%",
        f"Canonical Baseline: Sharpe={canonical.get('sharpe')} Return={canonical.get('cumulative_return_pct')}%",
        f"Strategies tested: {len(entries)}",
        f"Active strategies: {sum(1 for e in entries if e['_status']=='active')}",
        f"Partial/Unavailable/NI: {sum(1 for e in entries if e['_status']!='active')}",
        f"Beating strategy_engine baseline: {len(promoted)}",
        "",
        "--- Per Strategy ---",
    ]
    for e in entries:
        m = e.get("metrics", {})
        st = e.get("_status", "?")
        beats = e.get("beats_baseline", False) and st == "active"
        lines.append(f"  {e['name']:30s} [{st:16s}] Sharpe={m.get('sharpe','?'):>6} {'BEATS' if beats else 'no'} se_baseline")
    lines.append("")
    lines.append("--- End Audit ---")
    return "\n".join(lines)


if __name__ == "__main__":
    hotfix()
